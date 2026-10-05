"""
기본 RAG 경로 (스트리밍): 하이브리드(BM25+벡터) + BGE 리랭커 검색 → 답변·후속 질문 생성.

chat.py의 기본 경로다. 팀원의 app/core/agent.py(그래프/하이브리드 라우터)는 쓰지 않는다.
SSE 이벤트 형식(status / token / meta / done)은 프론트가 쓰던 형식과 같다.

흐름
  1. retriever.retrieve_with_sources (mode=hybrid_rerank)
  2. 관련도 최고 점수 < 0.7 → 질문 범위를 분류해 안내 문구로 끝냄
     (다음 단계에서 라우터를 붙이면 이 경우는 단일 에이전트로 넘긴다: single_agent/escalation.py)
  3. llm.stream_answer로 답변 스트리밍 + 후속 질문을 동시에 생성
  4. 점수 0.7 이상 출처만 done 이벤트로 보냄
"""
import os
import json
import asyncio
import logging
from typing import AsyncGenerator, Dict, List, Optional

from openai import AsyncOpenAI

from app.config import settings
from app.core.retriever import retriever
from app.core.llm import (
    _get_max_relevance_score,
    _RELEVANCE_THRESHOLD,
    stream_answer,
    generate_suggestions_async,
)

_async_client = AsyncOpenAI(api_key=settings.openai_api_key)
logger = logging.getLogger(__name__)

SOURCE_MIN_SCORE = 0.7  # done 이벤트에 보낼 출처의 최소 점수


async def _no_suggestions() -> List[str]:
    return []


def _sse(payload: Dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


_LANG_INSTRUCTIONS = {
    "ko": "반드시 한국어로만 답변하십시오.",
    "en": "You MUST respond in English only. This is NOT a translation task — answer the user's question directly in English based on the provided context.",
    "zh": "您必须只用中文回答。这不是翻译任务，请直接用中文根据参考上下文回答用户的问题。",
    "vi": "Bạn PHẢI chỉ trả lời bằng tiếng Việt. Đây không phải là nhiệm vụ dịch thuật — hãy trả lời câu hỏi của người dùng bằng tiếng Việt dựa trên ngữ cảnh được cung cấp.",
    "es": "DEBE responder únicamente en español. Esta NO es una tarea de traducción — responda directamente la pregunta del usuario en español basándose en el contexto proporcionado.",
}


_FALLBACK_MESSAGES = {
    "in_scope": {
        "ko": "해당 내용을 문서에서 찾지 못했습니다. 질문을 더 구체적으로 해주시거나, 담당 부서에 직접 문의해보시는 걸 권장합니다.",
        "en": "I couldn't find that information in our documents. Please try asking more specifically, or contact the relevant office directly.",
        "zh": "在文件中找不到相关内容。请尝试更具体地提问，或直接联系相关部门。",
        "es": "No encontré esa información en nuestros documentos. Intente preguntar con más detalle o contacte directamente con la oficina correspondiente.",
        "vi": "Tôi không tìm thấy thông tin đó trong tài liệu. Vui lòng hỏi cụ thể hơn hoặc liên hệ trực tiếp với bộ phận liên quan.",
    },
    "out_of_scope": {
        "ko": "저는 동아대학교 유학생 관련 정보(입학, 비자, 장학금, 기숙사 등)를 안내해드리는 챗봇이에요. 해당 주제로 궁금한 점이 있으시면 질문해주세요!",
        "en": "I'm a chatbot specialized in information for international students at Dong-A University (admissions, visas, scholarships, dormitories, etc.). Feel free to ask about those topics!",
        "zh": "我是专门为东亚大学留学生提供信息的聊天机器人（入学、签证、奖学金、宿舍等）。如有相关问题，请随时提问！",
        "es": "Soy un chatbot especializado en información para estudiantes internacionales de la Universidad Dong-A (admisiones, visas, becas, residencias, etc.). ¡No dudes en preguntar sobre esos temas!",
        "vi": "Tôi là chatbot chuyên cung cấp thông tin cho du học sinh tại Đại học Đông-A (nhập học, visa, học bổng, ký túc xá, v.v.). Hãy hỏi về những chủ đề đó nhé!",
    },
}


async def _classify_and_get_fallback(question: str, language: str) -> str:
    """관련 문서가 없을 때 질문 범위를 분류해서 적절한 안내 메시지 반환."""
    try:
        resp = await _async_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "다음 질문이 동아대학교 유학생 관련 주제에 해당하는지 판단하세요.\n"
                    "in_scope 주제 예시: 입학, 비자, 장학금, GKS, 한국어학당, 기숙사, 생활정보, 학사행정, "
                    "외국인 등록, 건강보험, 문의 방법, 연락처, 담당 부서, 오피스 운영 시간, "
                    "카카오톡 문의, 이메일 문의, 전화 문의, 행정 절차, 서류 제출, 등록금 납부 방법 등 "
                    "유학생의 학교 생활 및 행정과 관련된 모든 질문.\n"
                    "out_of_scope 주제 예시: 일반 여행 정보, 음식 추천, 연예인, 스포츠, 날씨, "
                    "타 대학교 정보 등 동아대학교 유학생 생활과 무관한 질문.\n"
                    "반드시 'in_scope' 또는 'out_of_scope' 중 하나만 반환하세요."
                )},
                {"role": "user", "content": question},
            ],
            temperature=0,
            max_tokens=10,
        )
        result = resp.choices[0].message.content.strip().lower()
        scope = "in_scope" if "in_scope" in result else "out_of_scope"
    except Exception:
        scope = "in_scope"

    lang_key = language if language in ("ko", "en", "zh", "es", "vi") else "ko"
    return _FALLBACK_MESSAGES[scope][lang_key]


_NO_RESULT_PHRASES = (
    "업로드된 문서에서 해당 질문에 대한 정보를 찾을 수 없습니다",
    "관련 정보를 찾을 수 없습니다",
    "관련 내용을 찾을 수 없습니다",
    "정보를 찾을 수 없습니다",
    "해당 내용을 찾을 수 없습니다",
    "cannot find",
    "no relevant information",
    "information not found",
    "找不到相关",
    "no se encontró información",
)


def _is_no_result_answer(answer: str) -> bool:
    lower = answer.lower()
    return any(phrase.lower() in lower for phrase in _NO_RESULT_PHRASES)


_STATUS_LABELS = {
    "ko": {
        "analyzing":        "질문 의도를 파악하는 중",
        "searching":        "문서를 탐색하는 중",
        "searching_done":   "관련 문서 검색 완료",
        "search_one":       "[{name}] 검색 완료",
        "search_many":      "[{name}] 외 {n}건 검색 완료",
        "generating":       "답변을 작성하는 중",
        "meta":             "출처를 정리하는 중",
    },
    "en": {
        "analyzing":        "Understanding your question",
        "searching":        "Searching through documents",
        "searching_done":   "Document search complete",
        "search_one":       "[{name}] found",
        "search_many":      "[{name}] and {n} more found",
        "generating":       "Writing your answer",
        "meta":             "Preparing sources",
    },
    "zh": {
        "analyzing":        "正在理解您的问题",
        "searching":        "正在搜索文档",
        "searching_done":   "文档搜索完成",
        "search_one":       "已找到 [{name}]",
        "search_many":      "已找到 [{name}] 等 {n} 份文档",
        "generating":       "正在撰写答案",
        "meta":             "正在整理来源",
    },
    "es": {
        "analyzing":        "Entendiendo tu pregunta",
        "searching":        "Buscando en documentos",
        "searching_done":   "Búsqueda completada",
        "search_one":       "[{name}] encontrado",
        "search_many":      "[{name}] y {n} más encontrados",
        "generating":       "Escribiendo tu respuesta",
        "meta":             "Preparando fuentes",
    },
    "vi": {
        "analyzing":        "Đang phân tích câu hỏi",
        "searching":        "Đang tìm kiếm tài liệu",
        "searching_done":   "Tìm kiếm tài liệu hoàn tất",
        "search_one":       "Đã tìm thấy [{name}]",
        "search_many":      "Đã tìm thấy [{name}] và {n} tài liệu khác",
        "generating":       "Đang soạn câu trả lời",
        "meta":             "Đang chuẩn bị nguồn",
    },
}



async def run_rag_stream(
    question: str,
    language: str = "ko",
    ko_query: Optional[str] = None,
    history: Optional[List[Dict]] = None,
) -> AsyncGenerator[str, None]:
    """기본 RAG 스트리밍 진입점. SSE 형식의 JSON 문자열을 yield."""
    labels = _STATUS_LABELS.get(language, _STATUS_LABELS["ko"])
    lang_inst = _LANG_INSTRUCTIONS.get(language, _LANG_INSTRUCTIONS["ko"])

    yield _sse({"type": "status", "content": labels["searching"]})
    await asyncio.sleep(0)

    # 1. 하이브리드 + 리랭커 검색
    logger.info("[RAG] 검색 시작 query='%s'", (ko_query or question)[:60])
    context, sources = await asyncio.to_thread(
        retriever.retrieve_with_sources, query=question, ko_query=ko_query or question,
    )
    sources = sources or []
    max_score = _get_max_relevance_score(sources)
    logger.info("[RAG] 검색 완료 chunks=%d max_score=%.3f", len(sources), max_score)

    if sources:
        top_name = os.path.basename(sources[0].get("source", "문서"))
        n = len(sources)
        search_msg = (labels["search_many"].format(name=top_name, n=n - 1) if n > 1
                      else labels["search_one"].format(name=top_name))
    else:
        search_msg = labels["searching_done"]
    yield _sse({"type": "status", "content": search_msg})
    await asyncio.sleep(0)

    # 2. 관련 문서가 없으면 안내 문구로 끝냄
    if max_score < _RELEVANCE_THRESHOLD:
        logger.info("[RAG] 관련 문서 없음(max_score=%.3f < %.1f) → fallback", max_score, _RELEVANCE_THRESHOLD)
        fallback_msg = await _classify_and_get_fallback(question, language)
        yield _sse({"type": "token", "content": fallback_msg})
        yield _sse({"type": "done", "sources": [], "suggestions": []})
        return

    history_text = "\n".join(
        f"{'사용자' if h['role'] == 'user' else '어시스턴트'}: {h['content']}"
        for h in (history or [])[-10:]
    ) or "(이전 대화 없음)"
    context = f"[문서 검색 결과]\n{context}" if context else "관련 문서를 찾을 수 없습니다."

    yield _sse({"type": "status", "content": labels["generating"]})
    await asyncio.sleep(0)

    # 3. 후속 질문을 미리 시작하고 답변을 스트리밍 (SUGGESTIONS_ENABLED가 꺼져 있으면 만들지 않음)
    if getattr(settings, "suggestions_enabled", False):
        suggestion_task = asyncio.create_task(generate_suggestions_async(
            question=question, suggestion_context=context, lang_instruction=lang_inst, lang=language,
        ))
    else:
        suggestion_task = asyncio.create_task(_no_suggestions())
    full_answer = ""
    logger.info("[RAG] 답변 생성 시작")
    try:
        async for token in stream_answer(
            question=question, context=context, lang_instruction=lang_inst, session_history=history_text,
        ):
            full_answer += token
            yield _sse({"type": "token", "content": token})
    except Exception:
        suggestion_task.cancel()
        raise

    formatted_sources = [
        {"source": s.get("source", ""), "chunk_index": s.get("chunk_index", 0),
         "similarity_score": s.get("similarity_score", 0.0)}
        for s in sources if s.get("similarity_score", 0.0) >= SOURCE_MIN_SCORE
    ]
    logger.info("[RAG] 답변 완료 len=%d sources=%d", len(full_answer), len(formatted_sources))
    if _is_no_result_answer(full_answer) or not formatted_sources:
        logger.info("[RAG] 답변 내용 없음 또는 출처 없음 → done(빈 출처)")
        suggestion_task.cancel()
        yield _sse({"type": "done", "sources": [], "suggestions": []})
        return

    # 4. 출처·후속 질문
    yield _sse({"type": "meta", "content": labels["meta"]})
    await asyncio.sleep(0)
    try:
        suggestions = await asyncio.wait_for(suggestion_task, timeout=30.0)
    except Exception:
        suggestions = []
    logger.info("[RAG] done suggestions=%d", len(suggestions))
    yield _sse({"type": "done", "sources": formatted_sources, "suggestions": suggestions})
