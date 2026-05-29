import json
from typing import Optional, Tuple, List, Dict

from langchain_openai import ChatOpenAI

from app.core.retriever import retriever
from app.config import settings


_SYSTEM_PROMPT = """귀하는 대한민국 대학교에 재학 중인 외국인 유학생들의 정착과 행정 절차를 돕는 전문가 어시스턴트입니다.

[1] 제공된 대화 히스토리와 RAG 컨텍스트를 바탕으로 사용자의 현재 질문에 성실하게 답변하십시오.
[2] 답변 후 유용한 후속 질문(Useful Follow-up Questions) 3개를 생성하십시오.

{lang_instruction}

컨텍스트에 관련 정보가 없으면 "이 질문에 답변할 충분한 정보가 없습니다"라고 말하세요.

---
[대화 히스토리 (최근 내역 우선)]
{session_history}

[참고 컨텍스트 (RAG 문서 추출 내용)]
{context}

[사용자의 현재 질문]
{question}
---

[후속 질문 생성 가이드라인]
1. 중복 제거: 현재 질문 또는 히스토리와 의미상 중복되는 질문은 배제하십시오.
2. 전제조건 스킵: 사용자가 이미 알고 있을 기초 단계는 건너뛰고 다음 액션 단계를 제안하십시오.
3. 다음 여정 유도: 유학생 행정 주기(모집요강 → 원서접수 → 서류제출 → 비자신청 → 정착)에 맞는 실무적 질문을 제안하십시오.

[출력 형식] 아래 JSON만 반환하고 마크다운 코드 블록은 제외하십시오.
{{
    "answer": "사용자 질문에 대한 답변",
    "suggestions": [
        "후속 질문 1",
        "후속 질문 2",
        "후속 질문 3"
    ]
}}"""


_LANGUAGE_INSTRUCTIONS: Dict[str, str] = {
    "ko":   "한국어로 답변하고, 후속 질문도 한국어로 생성하십시오.",
    "en":   "Please answer in English, and generate follow-up questions in English as well.",
    "zh":   "请用中文回答，并同样用中文生成后续推荐问题。",
    "es":   "Por favor, responda en español y genere también las preguntas de seguimiento en español.",
    "vi":   "Vui lòng trả lời bằng tiếng Việt và tạo các câu hỏi tiếp theo bằng tiếng Việt.",
    "auto": "사용자가 질문한 언어를 파악하여 반드시 답변과 후속 질문 모두 그 언어로 작성하십시오.",
}


class RAGLLM:
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=0.4,
            max_tokens=2048,
        )

    def generate_answer_with_suggestions(
        self,
        question: str,
        context: str,
        lang_instruction: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Tuple[str, List[str]]:
        history_str = (
            "".join(
                f"- {'유저' if t.get('role') == 'user' else '봇'}: {t.get('content')}\n"
                for t in history[-5:]
            )
            if history
            else "(이전 대화 내역 없음 - 첫 질문)"
        )

        prompt = _SYSTEM_PROMPT.format(
            lang_instruction=lang_instruction,
            session_history=history_str,
            context=context,
            question=question,
        )

        try:
            raw = self.llm.invoke(prompt).content
            clean = raw.replace("```json", "").replace("```", "").strip()
            try:
                parsed = json.loads(clean)
                return parsed.get("answer", raw), parsed.get("suggestions", [])
            except (json.JSONDecodeError, KeyError):
                return raw, []
        except Exception:
            return "죄송합니다. 답변을 생성하는 도중 에러가 발생했습니다.", []

    def generate_answer_with_language(
        self,
        question: str,
        language: str = "en",
        top_k: int = 3,
        ko_query: Optional[str] = None,
    ) -> Tuple[str, list, List[str]]:
        search_query = ko_query or question
        context_str, sources = retriever.retrieve_with_sources(search_query, k=top_k)

        lang_instruction = _LANGUAGE_INSTRUCTIONS.get(
            language, "질문과 같은 언어로 명확하고 유용한 답변을 제공하십시오."
        )

        answer, suggestions = self.generate_answer_with_suggestions(
            question=question,
            context=context_str,
            lang_instruction=lang_instruction,
            history=[],
        )

        return answer, sources, suggestions


rag_chain = RAGLLM()
