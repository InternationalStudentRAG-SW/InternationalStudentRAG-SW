# app/core/llm.py
# 고도화 버전: Dynamic Few-Shot + 세션 히스토리 라우터 연결 + Usefulness 가이드라인

import json
from typing import Optional, Tuple, List, Dict, Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.callbacks import get_openai_callback

from app.core.retriever import retriever
from app.config import settings

from app.core.few_shot_qas import FEW_SHOT_QAS_TRIPLETS

DEFAULT_TOP_K = settings.top_k_results


def _embed(text: str) -> List[float]:
    """OpenAI API를 호출하여 텍스트를 임베딩 벡터로 변환합니다."""
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-small",
    )
    return response.data[0].embedding


def _build_few_shot_embeddings() -> List[List[float]]:
    """
    서버 시작 시 1회 호출되어 QAS 예시들의 임베딩을 캐싱합니다.
    실패 시 오류 메시지를 출력하고 프로세스를 종료합니다.
    """
    try:
        embeddings = [_embed(ex["question"]) for ex in FEW_SHOT_QAS_TRIPLETS]
        print(f"[llm.py] Few-shot 예시 임베딩 완료 ({len(embeddings)}개)")
        return embeddings
    except Exception as e:
        print(
            f"\n[오류] Few-shot 예시 임베딩 생성에 실패했습니다: {e}\n"
            "OpenAI API 키와 네트워크 연결을 확인한 뒤 서버를 재실행하세요.\n"
        )
        import sys
        sys.exit(1)


# 서버 시작 시 1회 계산 후 메모리에 캐싱
_FEW_SHOT_EMBEDDINGS: List[List[float]] = _build_few_shot_embeddings()


def _get_max_relevance_score(sources: List[dict]) -> float:
    if not sources:
        return 0.0
    scores = []
    for s in sources:
        score = s.get("similarity_score")  # ← retriever.py에서 저장하는 키와 일치
        if score is not None:
            scores.append(float(score))
    return max(scores) if scores else 1.0


# 관련성 임계값 — 이 값 미만이면 PDF 범위 밖 질문으로 판단하여 답변 차단
_RELEVANCE_THRESHOLD = 0.3

# PDF 범위 밖 질문에 대한 고정 응답 메시지
_OUT_OF_SCOPE_ANSWER = (
    "죄송합니다. 업로드된 문서에서 해당 질문에 대한 정보를 찾을 수 없습니다. "
    "동아대학교 입학, 비자, 장학금, GKS 규정, 한국어학당 등에 관한 질문을 해주세요."
)


def _select_dynamic_few_shot_examples(
    question: str,
    top_k: int = 3,
    lang: str = "ko",
) -> List[Dict[str, str]]:
    """
    유저 쿼리와 가장 유사한 QAS 트리플을 선택합니다.
    lang 파라미터로 동일 언어 예시만 후보로 사용합니다.

    논문 §4: "Dynamic few-shot diverges from traditional few-shot prompting
    by dynamically choosing each example based on the user's query,
    rather than relying on a static set of examples."

    OpenAI embeddings + cosine similarity로 유사도를 계산합니다.
    예시 임베딩은 서버 시작 시 _FEW_SHOT_EMBEDDINGS에 캐싱되어 있습니다.
    """
    import numpy as np

    # 동일 언어 예시만 필터링 (lang 필드 없는 예시는 "ko"로 간주)
    candidates = [
        (ex, emb)
        for ex, emb in zip(FEW_SHOT_QAS_TRIPLETS, _FEW_SHOT_EMBEDDINGS)
        if ex.get("lang", "ko") == lang
    ]
    # 해당 언어 예시가 없으면 전체 후보 사용 (fallback)
    if not candidates:
        candidates = list(zip(FEW_SHOT_QAS_TRIPLETS, _FEW_SHOT_EMBEDDINGS))

    q_vec = np.array(_embed(question))
    scored = []
    for ex, ex_vec in candidates:
        e_vec = np.array(ex_vec)
        similarity = np.dot(q_vec, e_vec) / (np.linalg.norm(q_vec) * np.linalg.norm(e_vec))
        scored.append((similarity, ex))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [ex for _, ex in scored[:top_k]]


def _format_few_shot_block(examples: List[Dict[str, str]]) -> str:
    """선택된 QAS 트리플을 프롬프트에 삽입할 텍스트 블록으로 변환합니다."""
    if not examples:
        return "(예시 없음)"
    lines = []
    for i, ex in enumerate(examples, 1):
        sugg_str = "\n".join(f"  - {s}" for s in ex["suggestions"])
        lines.append(
            f"[예시 {i}]\n"
            f"  질문: {ex['question']}\n"
            f"  답변 요약: {ex['answer']}\n"
            f"  후속 질문:\n{sugg_str}"
        )
    return "\n\n".join(lines)


# ===========================================================================
# [2] 통합 프롬프트 템플릿
#     - Dynamic Few-Shot 블록 추가 (논문 핵심)
#     - Usefulness 가이드라인 유지
#     - 세션 히스토리 유지
# ===========================================================================

_CONVERSATIONAL_LEADING_TEMPLATE = """귀하는 대한민국 대학교에 재학 중인 외국인 유학생들의 정착과 행정 절차를 돕는 전문가 어시스턴트입니다.

[1] 제공된 유학생 대화 세션 히스토리와 참고 컨텍스트(RAG)를 바탕으로 사용자의 현재 질문에 성실하게 답변하십시오.
[2] 답변을 마친 후, 사용자가 다음에 수행해야 하거나 관심을 가질 만한 '유용한 후속 질문(Useful Follow-up Questions)' 6개를 생성하십시오.

{lang_instruction}

---
[절대 규칙 — 반드시 준수]
1. 답변은 반드시 아래 [참고 컨텍스트]에 명시된 내용만을 근거로 작성하십시오.
2. 컨텍스트에 없는 내용은 LLM의 일반 지식으로 절대 보완하지 마십시오.
3. 앱 추천, 일반 생활 팁, 심리 상담 등 문서 범위 밖의 질문은 아래와 같이 답변하십시오:
   "업로드된 문서에서 해당 질문에 대한 정보를 찾을 수 없습니다."
4. 후속 질문도 반드시 [후속 질문 생성 전용 컨텍스트] 범위 내에서만 생성하십시오.
5. 컨텍스트에 근거가 없는 후속 질문은 생성하지 말고, 생성 가능한 개수만큼만 반환하십시오.

---
[대화 세션 히스토리 (최근 내역 우선)]
{session_history}

[참고 컨텍스트 (RAG 문서 추출 내용) — 답변 생성용]
{context}

[사용자의 현재 질문]
{question}
---
[Dynamic Few-Shot 예시 — 유사 질문에 대한 후속 질문 생성 레퍼런스]
아래 예시들을 참고하여 후속 질문의 스타일, 구체성, 행동 지향성을 학습하십시오.
단, 예시의 내용을 그대로 복사하지 말고, 현재 질문과 컨텍스트에 맞게 새롭게 생성하십시오.

{few_shot_examples}

---
[후속 질문 생성 전용 컨텍스트 (RAG 문서 추출 내용) — 후속 질문 소재 탐색용]
아래는 현재 질문과 관련하여 RAG로 추가 검색한 문서 내용입니다.
후속 질문은 반드시 이 컨텍스트 안에서 답변 가능한 내용을 소재로 생성하십시오.
이 컨텍스트에 근거가 없는 후속 질문은 절대 생성하지 마십시오.

{suggestion_context}

---
[후속 질문 생성 시 필수 준수 가이드라인 (Usefulness Guidelines)]
1. 중복 제거 (No Redundancy): 사용자의 현재 질문이나 세션 히스토리에 이미 등장했던 내용과 의미상 중복되거나 단순히 유사한 질문은 절대 배제하십시오.
2. 전제조건 스킵 (Skip Prerequisites): 사용자가 이미 수행했거나 알고 있을 것으로 간주되는 기초적인 지식 단계는 건너뛰고, 실질적인 다음 액션 단계의 질문을 생성하십시오.
3. 다음 유저 여정 유도 (Lead Next Journey): 유학생 행정 주기(예: 모집요강 확인 → 원서접수 → 서류제출 및 공증 → 합격확인 → 비자신청 → 정착 및 학사운영)에 따라, 다음 단계에 마주하게 될 실무적이고 구체적인 행동을 유도하는 질문을 제안하십시오.
4. 답변 가능성 보장 (Answerability): 생성된 후속 질문은 반드시 위의 [후속 질문 생성 전용 컨텍스트]에서 답변 가능한 범위 내의 질문이어야 합니다. 컨텍스트 범위를 벗어나는 질문은 배제하십시오.
5. 직접 근거 (Direct Groundedness): 후속 질문은 반드시 위의 [후속 질문 생성 전용 컨텍스트]에 등장하는 구체적인 단어, 수치, 절차, 조건 중 하나를 직접 소재로 해야 합니다. 컨텍스트에서 직접 파생되지 않은 질문은 절대 생성하지 마십시오.

[출력 양식 가이드]
반드시 아래의 엄격한 JSON 형식으로만 결과를 반환해야 하며, 마크다운 코드 블록(```json ```)을 제외한 다른 텍스트는 포함하지 마십시오.

{{
    "answer": "사용자 질문에 대한 최종 답변 내용",
    "suggestions": ["답변 가능한 후속 질문을 6개 생성하십시오"]
}}"""


_LANGUAGE_INSTRUCTIONS = {
    "ko": "한국어로 답변하고, 후속 질문도 한국어로 생성하십시오.",
    "en": "Please answer in English, and generate follow-up questions in English as well.",
    "zh": "请用中文回答，并同样用中文生成后续推荐问题。",
    "es": "Por favor, responda en español y genere también las preguntas de seguimiento en español.",
    "auto": "사용자가 질문한 언어를 파악하여 반드시 답변과 후속 질문 모두 그 언어로 작성하십시오.",
}


# ===========================================================================
# [3] RAGLLM 클래스
# ===========================================================================

class RAGLLM:
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            model="gpt-4o-mini",
            temperature=0.4,
            max_tokens=2048,
        )
        self._total_tokens = 0
        self._total_requests = 0
        self._total_cost = 0.0

    def get_usage(self) -> dict:
        return {
            "total_tokens": self._total_tokens,
            "total_requests": self._total_requests,
            "total_cost_usd": round(self._total_cost, 4),
        }

    def generate_answer_with_suggestions(
        self,
        question: str,
        context: str,
        lang_instruction: str,
        history: Optional[List[Dict[str, str]]] = None,
        use_few_shot: bool = True,          # ← 논문 Dynamic Few-Shot 제어 플래그
        few_shot_top_k: int = 3,            # ← 선택할 예시 개수
        suggestion_context: str = "",       # ← 후속 질문 전용 RAG 컨텍스트 (논문 §4)
        lang: str = "ko",                   # ← few-shot 언어 필터링용
    ) -> Tuple[str, List[str]]:
        """
        Dynamic Few-Shot + 세션 히스토리 + Usefulness 가이드라인을 통합한 코어 파이프라인.
        
        Args:
            question:            현재 유저 질문
            context:             RAG로 검색된 문서 컨텍스트 (답변용)
            lang_instruction:    언어별 응답 지시문
            history:             FastAPI 세션에서 전달받은 대화 히스토리 [{role, content}, ...]
            use_few_shot:        Dynamic Few-Shot 예시 사용 여부 (기본 True)
            few_shot_top_k:      동적으로 선택할 예시 개수 (기본 2)
            suggestion_context:  후속 질문 생성 전용 RAG 컨텍스트 (논문 §4 Dynamic Retrieved Contexts)
                                 비어있으면 답변용 context를 그대로 재사용
        """

        # ── 세션 히스토리 포맷팅 ──────────────────────────────────────────
        history_str = ""
        if history:
            for turn in history[-5:]:   # 최근 5턴만 사용 (토큰 절약)
                role = "유저" if turn.get("role") == "user" else "봇"
                history_str += f"- {role}: {turn.get('content')}\n"
        else:
            history_str = "(이전 대화 내역 없음 - 첫 질문)"

        # ── Dynamic Few-Shot 예시 선택 (논문 핵심) ───────────────────────
        if use_few_shot:
            selected_examples = _select_dynamic_few_shot_examples(
                question=question,
                top_k=few_shot_top_k,
                lang=lang,
            )
            few_shot_block = _format_few_shot_block(selected_examples)
        else:
            few_shot_block = "(Dynamic Few-Shot 비활성화)"

        # ── 후속 질문 전용 컨텍스트 결정 (논문 §4: Dynamic Retrieved Contexts) ──
        # suggestion_context가 전달된 경우 → 후속 질문 전용 컨텍스트 사용
        # 전달되지 않은 경우 → 답변용 context 재사용 (하위 호환)
        suggestion_ctx = suggestion_context if suggestion_context.strip() else context

        # ── 프롬프트 구성 ─────────────────────────────────────────────────
        prompt_text = _CONVERSATIONAL_LEADING_TEMPLATE.format(
            lang_instruction=lang_instruction,
            session_history=history_str,
            context=context,
            suggestion_context=suggestion_ctx,
            question=question,
            few_shot_examples=few_shot_block,
        )

        try:
            with get_openai_callback() as cb:
                response = self.llm.invoke(prompt_text)
            self._total_tokens += cb.total_tokens
            self._total_requests += cb.successful_requests
            self._total_cost += cb.total_cost
            print(f"[API] 이번: {cb.total_tokens}토큰 | 누적: {self._total_tokens:,}토큰 / {self._total_requests}회 / ${self._total_cost:.4f}")

            raw_output = response.content
            clean_output = raw_output.replace("```json", "").replace("```", "").strip()
            parsed_data = json.loads(clean_output)

            answer = parsed_data.get("answer", "답변을 생성하지 못했습니다.")
            suggestions = parsed_data.get("suggestions", [])

        except Exception as e:
            answer = "죄송합니다. 답변을 생성하는 도중 에러가 발생했습니다."
            suggestions = [
                "비자 신청/연장을 위한 필수 서류 목록을 확인해 볼까요?",
                "동아대학교 외국인 전형 장학금 혜택 조건이 궁금하신가요?",
                "학기 중 인턴십이나 아르바이트 신청 절차를 알아볼까요?",
            ]

        return answer, suggestions

    # ── 라우터 연동 메서드 ─────────────────────────────────────────────────
    # [고도화 포인트] history 파라미터를 실제로 받아서 코어 파이프라인에 전달
    # FastAPI 라우터에서: rag_chain.generate_answer_with_language(..., history=session_history)
    # ─────────────────────────────────────────────────────────────────────────

    def generate_answer_with_language(
        self,
        question: str,
        language: str = "en",
        top_k: int = DEFAULT_TOP_K,
        ko_query: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,  # ← 라우터에서 주입
    ) -> Tuple[str, List[dict], List[str]]:
        """
        chat.py 라우터와의 호환성을 유지하면서 세션 히스토리를 실제로 수신하는 메서드.
        
        FastAPI 라우터 연동 예시 (app/api/chat.py):
        
            from app.core.session import get_session_history  # 세션 관리 유틸
            
            @router.post("/chat")
            async def chat(req: ChatRequest, session_id: str = Header(...)):
                history = await get_session_history(session_id)   # ← 세션에서 히스토리 조회
                
                answer, sources, suggestions = rag_chain.generate_answer_with_language(
                    question=req.question,
                    language=req.language,
                    ko_query=req.ko_query,
                    history=history,          # ← 실제 히스토리 전달 (기존: [])
                )
                
                await append_to_session(session_id, "user", req.question)
                await append_to_session(session_id, "assistant", answer)
                
                return {"answer": answer, "sources": sources, "suggestions": suggestions}
        """
        search_query = ko_query if ko_query else question

        # ── 답변용 컨텍스트 검색 ──────────────────────────────────────────
        context_str, sources = retriever.retrieve_with_sources(search_query, k=top_k)

        # ── [코드 레벨 1차 차단] 관련성 점수 임계값 체크 ─────────────────
        # PDF와 무관한 질문(관련성 < 0.3)은 LLM 호출 없이 즉시 차단
        max_score = _get_max_relevance_score(sources)
        if max_score < _RELEVANCE_THRESHOLD:
            return _OUT_OF_SCOPE_ANSWER, sources, []

        # # ── 후속 질문 전용 컨텍스트 별도 검색 (논문 §4: Dynamic Retrieved Contexts) ──
        # # 논문 권장: top 4개 문서를 별도 검색하여 후속 질문 소재로 활용
        # # 답변용(top_k=3)보다 넓게 검색해 다양한 후속 질문 소재 확보
        # suggestion_context_str, _ = retriever.retrieve_with_sources(search_query, k=4)

        lang_instruction = _LANGUAGE_INSTRUCTIONS.get(
            language, "질문과 같은 언어로 명확하고 유용한 답변을 제공하십시오."
        )

        answer, suggestions = self.generate_answer_with_suggestions(
            question=question,
            context=context_str,
            lang_instruction=lang_instruction,
            history=history or [],
            use_few_shot=True,
            few_shot_top_k=2,
            suggestion_context=context_str,
            lang=language,                   # ← 언어별 few-shot 필터링
        )

        # ── 생성 후 검증 (Post-generation Verification) ──────────────────────
        # 각 후속질문으로 Vector DB에 재검색하여 유사도가 임계값 이상인 것만 반환
        SUGGESTION_VERIFY_THRESHOLD = 0.3

        verified = []
        for q in suggestions:
            _, verify_sources = retriever.retrieve_with_sources(q, k=1)
            score = verify_sources[0].get("similarity_score", 0.0) if verify_sources else 0.0
            if score >= SUGGESTION_VERIFY_THRESHOLD:
                verified.append(q)

        # 검증 통과한 게 하나도 없으면 빈 리스트 반환 (프론트에서 버튼 안 보임)
        suggestions = verified[:3]

        return answer, sources, suggestions

    def generate_answer(
        self,
        question: str,
        context: Optional[str] = None,
        top_k: int = 3,
    ) -> Tuple[str, List[dict]]:
        """기본형 메서드 구조 호환 유지 (히스토리 불필요한 단순 질의용)"""
        if context is None:
            context_str, sources = retriever.retrieve_with_sources(question, k=top_k)
        else:
            context_str = context
            sources = []

        lang_instruction = _LANGUAGE_INSTRUCTIONS.get("ko")
        answer, _ = self.generate_answer_with_suggestions(
            question=question,
            context=context_str,
            lang_instruction=lang_instruction,
            history=[],
            use_few_shot=False,   # 단순 질의는 Few-Shot 불필요
        )
        return answer, sources


# chat.py 라우터 인스턴스 이름 바인딩
rag_chain = RAGLLM()
