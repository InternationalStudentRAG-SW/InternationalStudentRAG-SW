# app/core/llm.py
# 고도화 버전: Dynamic Few-Shot + 세션 히스토리 라우터 연결 + Usefulness 가이드라인

import re
import json
import asyncio
from typing import Optional, List, Dict, AsyncGenerator

from openai import AsyncOpenAI

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
    try:
        embeddings = [_embed(ex["question"]) for ex in FEW_SHOT_QAS_TRIPLETS]
        print(f"[llm.py] Few-shot 예시 임베딩 완료 ({len(embeddings)}개)")
        return embeddings
    except Exception as e:
        print(f"[llm.py] Few-shot 임베딩 건너뜀: {e}")
        return []


_FEW_SHOT_EMBEDDINGS: List[List[float]] = _build_few_shot_embeddings()


def _ensure_embeddings() -> None:
    pass  # 서버 시작 시 이미 로딩 완료


def _get_max_relevance_score(sources: List[dict]) -> float:
    if not sources:
        return 0.0
    scores = []
    for s in sources:
        score = s.get("similarity_score")  # ← retriever.py에서 저장하는 키와 일치
        if score is not None:
            scores.append(float(score))
    return max(scores) if scores else 0.0


# 관련성 임계값 — 이 값 미만이면 PDF 범위 밖 질문으로 판단하여 답변 차단
_RELEVANCE_THRESHOLD = 0.7

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

    _ensure_embeddings()

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
# [4] 스트리밍 전용 비동기 함수 (agent.py run_agent_stream 에서 호출)
# ===========================================================================

_async_client = AsyncOpenAI(api_key=settings.openai_api_key)

_STREAM_ANSWER_TEMPLATE = """귀하는 대한민국 대학교에 재학 중인 외국인 유학생들의 정착과 행정 절차를 돕는 전문가 어시스턴트입니다.

{lang_instruction}

---
[절대 규칙 — 반드시 준수]
1. 답변은 반드시 아래 [참고 컨텍스트]에 명시된 내용만을 근거로 작성하십시오.
2. 컨텍스트에 없는 내용은 LLM의 일반 지식으로 절대 보완하지 마십시오.
3. 앱 추천, 일반 생활 팁, 심리 상담 등 문서 범위 밖의 질문은 아래와 같이 답변하십시오:
   "업로드된 문서에서 해당 질문에 대한 정보를 찾을 수 없습니다."
4. 완전 열거: 질문에 해당하는 모든 항목·케이스·예외 규정을 빠짐없이 열거하십시오.
   컨텍스트에 '~의 경우', '단, 중국은', '특정 국가는' 등 예외절이 보이면 반드시 포함하십시오.
5. 대상 선별: 질문의 전형(신입학/편입학)·대상에 해당하지 않는 항목은 답변에서 제외하십시오.
6. 자기 점검: 답변 작성 후 "컨텍스트에 등장한 항목 중 빠진 것이 없는지" 확인하고, 누락이 있으면 추가하십시오.

---
[대화 세션 히스토리 (최근 내역 우선)]
{session_history}

[참고 컨텍스트 (RAG 문서 추출 내용)]
{context}

[사용자의 현재 질문]
{question}

답변을 plain text로 작성하십시오. JSON 형식 없이 답변 내용만 출력하십시오.
"""

_STREAM_SUGGESTIONS_TEMPLATE = """귀하는 대한민국 대학교 유학생 Q&A 어시스턴트입니다.
아래 컨텍스트를 바탕으로 유학생이 다음에 관심 가질 후속 질문 3개를 생성하십시오.

{lang_instruction}

---
[Dynamic Few-Shot 예시 — 후속 질문 스타일 참고]
아래 예시들을 참고하여 후속 질문의 스타일, 구체성, 행동 지향성을 학습하십시오.
단, 예시의 내용을 그대로 복사하지 말고, 현재 질문과 컨텍스트에 맞게 새롭게 생성하십시오.

{few_shot_examples}

---
[후속 질문 생성 전용 컨텍스트 (RAG 문서 추출 내용)]
아래는 현재 질문과 관련하여 RAG로 추가 검색한 문서 내용입니다.
후속 질문은 반드시 이 컨텍스트 안에서 답변 가능한 내용을 소재로 생성하십시오.
이 컨텍스트에 근거가 없는 후속 질문은 절대 생성하지 마십시오.

{suggestion_context}

---
[방금 한 질문]
{question}

---
[후속 질문 생성 시 필수 준수 가이드라인 (Usefulness Guidelines)]
1. 중복 제거 (No Redundancy): 방금 한 질문과 의미상 중복되거나 단순히 유사한 질문은 절대 배제하십시오.
2. 전제조건 스킵 (Skip Prerequisites): 이미 수행했거나 알고 있을 기초 단계는 건너뛰고, 실질적인 다음 액션 단계의 질문을 생성하십시오.
3. 다음 유저 여정 유도 (Lead Next Journey): 유학생 행정 주기(모집요강 확인 → 원서접수 → 서류제출 및 공증 → 합격확인 → 비자신청 → 정착 및 학사운영)에 따라 다음 단계를 유도하십시오.
4. 답변 가능성 보장 (Answerability): 반드시 위 [컨텍스트]에서 답변 가능한 범위 내의 질문만 생성하십시오. 컨텍스트 범위를 벗어나는 질문은 배제하십시오.
5. 직접 근거 (Direct Groundedness): 반드시 위 [컨텍스트]에 등장하는 구체적인 단어, 수치, 절차, 조건 중 하나를 직접 소재로 하십시오. 컨텍스트에서 직접 파생되지 않은 질문은 절대 생성하지 마십시오.
6. 구체적 키워드 포함 (Specific Keywords): 컨텍스트에 등장하는 고유명사, 수치, 기한, 서류명 중 하나 이상을 질문 문장 안에 명시적으로 포함하십시오.
   나쁜 예: "장학금 신청 방법은?" → 좋은 예: "GKS 장학금 신청 시 제출 기한과 필수 서류 목록은?"
7. 독립 완결성 (Self-contained): 앞선 대화 맥락 없이 단독으로 검색되어도 완전히 의미가 통하는 독립적인 완전한 문장으로 작성하십시오. "그", "이", "해당", "위의" 등 지시대명사 대신 구체적인 명사를 사용하십시오.

반드시 JSON 배열만 반환: ["질문1", "질문2", "질문3"]
"""


def _parse_suggestions(raw: str) -> List[str]:
    """GPT 응답에서 JSON 배열 추출."""
    raw = raw.strip()
    raw = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        result = json.loads(match.group())
        if isinstance(result, list):
            return result
    return []


async def stream_answer(
    question: str,
    context: str,
    lang_instruction: str,
    session_history: str,
) -> AsyncGenerator[str, None]:
    """답변만 스트리밍으로 생성. 토큰 단위로 yield."""
    prompt = _STREAM_ANSWER_TEMPLATE.format(
        lang_instruction=lang_instruction,
        session_history=session_history,
        context=context,
        question=question,
    )
    try:
        stream = await _async_client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            stream=True,
        )
        async for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if token:
                yield token
    except Exception:
        yield "답변 생성 중 오류가 발생했습니다."


async def _verify_suggestions_async(
    suggestions: List[str],
    min_score: float = 0.5,
) -> List[str]:
    """후속질문별 재검색으로 문서 근거 확인 — 점수 미달 시 탈락. 병렬 실행."""
    if not suggestions:
        return []

    async def _check(suggestion: str) -> tuple[str, float]:
        try:
            _, sources = await asyncio.to_thread(
                retriever.retrieve_with_sources, suggestion, 1
            )
            score = sources[0].get("similarity_score", 0.0) if sources else 0.0
            return suggestion, score
        except Exception:
            return suggestion, 0.0

    results = await asyncio.gather(*[_check(s) for s in suggestions])
    for s, score in results:
        print(f"[verify] {score:.3f} | {s}")
    verified = [s for s, score in results if score >= min_score]
    print(f"[verify] {len(verified)}/{len(results)} 통과 (min_score={min_score})")
    return verified


async def generate_suggestions_async(
    question: str,
    suggestion_context: str,
    lang_instruction: str,
    lang: str = "ko",
) -> List[str]:
    """후속질문 비동기 생성. Dynamic Few-Shot + 문서 근거 검증 포함."""
    print(f"[suggestions] 시작 | lang={lang} | question={question[:30]}")
    try:
        few_shot_examples = await asyncio.to_thread(
            _select_dynamic_few_shot_examples, question, 3, lang
        )
        few_shot_block = _format_few_shot_block(few_shot_examples)
    except Exception:
        few_shot_block = "(예시 없음)"

    prompt = _STREAM_SUGGESTIONS_TEMPLATE.format(
        lang_instruction=lang_instruction,
        suggestion_context=suggestion_context,
        question=question,
        few_shot_examples=few_shot_block,
    )
    try:
        resp = await _async_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        )
        suggestions = _parse_suggestions(resp.choices[0].message.content)
        print(f"[suggestions] GPT 생성 {len(suggestions)}개: {suggestions}")
    except Exception as e:
        print(f"[suggestions] GPT 호출 실패: {e}")
        return []

    return await _verify_suggestions_async(suggestions)
