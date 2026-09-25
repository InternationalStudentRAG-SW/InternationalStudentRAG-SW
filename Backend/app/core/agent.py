"""
RAG 에이전트 (스트리밍 전용).

흐름:
  router → graph_search | hybrid_search | clarify
         → (graph 후) hybrid_search
         → run_agent_stream (llm.py에서 답변·후속질문 생성)
"""
import os
import json
import asyncio
from typing import TypedDict, Optional, List, Dict, Any, AsyncGenerator

from openai import OpenAI, AsyncOpenAI

from app.config import settings
from app.core.knowledge_graph import knowledge_graph
from app.core.retriever import retriever
from app.core.llm import (
    _get_max_relevance_score,
    _RELEVANCE_THRESHOLD,
    stream_answer,
    generate_suggestions_async,
)

_client = OpenAI(api_key=settings.openai_api_key)
_async_client = AsyncOpenAI(api_key=settings.openai_api_key)

# ── 언어별 지시문 (llm.py와 동일) ─────────────────────────────────────────
_LANG_INSTRUCTIONS = {
    "ko": "반드시 한국어로만 답변하십시오.",
    "en": "You MUST respond in English only. This is NOT a translation task — answer the user's question directly in English based on the provided context.",
    "zh": "您必须只用中文回答。这不是翻译任务，请直接用中文根据参考上下文回答用户的问题。",
    "vi": "Bạn PHẢI chỉ trả lời bằng tiếng Việt. Đây không phải là nhiệm vụ dịch thuật — hãy trả lời câu hỏi của người dùng bằng tiếng Việt dựa trên ngữ cảnh được cung cấp.",
    "es": "DEBE responder únicamente en español. Esta NO es una tarea de traducción — responda directamente la pregunta del usuario en español basándose en el contexto proporcionado.",
}

MAX_TOOL_CALLS = 3  # 무한 루프 방지


# ── 공유 상태 ──────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    question: str
    language: str
    ko_query: Optional[str]
    history: List[Dict]
    graph_result: Optional[Dict]       # tool_graph 결과
    search_context: Optional[str]      # tool_search 결과 (포맷된 텍스트)
    search_sources: Optional[List[Dict]]
    answer: Optional[str]
    sources: List[Dict]
    suggestions: List[str]
    tool_calls: int                    # 호출 횟수 (루프 방지)
    clarify_question: Optional[str]    # 재질문 (모호한 질문일 때)


# ── 노드 1: 라우터 ────────────────────────────────────────────────────────

def router_node(state: AgentState) -> AgentState:
    """현재 상태를 보고 다음 행동을 결정한다."""
    return state


def route_decision(state: AgentState) -> str:
    """라우터 조건 엣지: 다음 노드 이름을 반환."""
    # 무한 루프 방지
    if state["tool_calls"] >= MAX_TOOL_CALLS:
        return "generate"

    # 이미 검색 결과가 있으면 답변 생성
    if state["search_context"]:
        return "generate"

    # 그래프 탐색을 이미 수행했으면 하이브리드 검색으로 진행 (엔티티 없어도)
    if state["graph_result"] is not None:
        return "hybrid_search"

    question = state["question"].strip()
    # 번역된 한국어 쿼리 사용 — 라우터 프롬프트가 한국어이므로 ko_query로 분류
    routing_question = (state.get("ko_query") or question).strip()
    history = state.get("history") or []

    # 히스토리가 없을 때만 길이 체크 — 대화 중이면 짧은 질문도 맥락으로 이해 가능
    if not history and len(routing_question) < 5:
        return "clarify"

    # GPT로 질문 유형 분류 (히스토리 있으면 최근 4턴 포함)
    history_messages = [
        {"role": h["role"], "content": h["content"]}
        for h in history[-4:]
    ]
    # 히스토리가 있으면 clarify 불필요 — 맥락으로 충분히 이해 가능
    valid_decisions = ("graph", "hybrid_search") if history else ("graph", "hybrid_search", "clarify")
    system_prompt = (
        "유학생 Q&A 시스템의 라우터입니다. "
        "이전 대화 맥락을 함께 고려하여 현재 질문을 분석하고 아래 중 하나만 반환하세요.\n"
        "- graph: 절차, 관계, 순서, 조건, 목록, 종류, 항목을 묻는 질문\n"
        "- hybrid_search: 세부 내용, 날짜, 금액, 구체적 정보를 묻는 질문\n"
        + ("" if history else "- clarify: 이전 대화 맥락이 없고 너무 모호해서 파악이 필요한 질문\n")
        + f"반드시 {', '.join(valid_decisions)} 중 하나만 반환하세요."
    )
    try:
        resp = _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                *history_messages,
                {"role": "user", "content": routing_question},
            ],
            temperature=0,
            max_tokens=10,
        )
        decision = resp.choices[0].message.content.strip().lower()
        if decision in valid_decisions:
            return decision
    except Exception:
        pass

    return "hybrid_search"


# ── 노드 2: 그래프 탐색 ───────────────────────────────────────────────────

def _extract_graph_keywords(query: str) -> List[str]:
    """GPT로 쿼리에서 Neo4j 검색용 핵심 명사 키워드를 추출한다."""
    try:
        resp = _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "질문에서 지식 그래프 검색에 쓸 핵심 명사 키워드를 추출하세요. "
                        "조사·어미를 제거한 순수 명사만 추출하고, 쉼표로 구분해서 반환하세요. "
                        "예) '영어트랙 지원 서류, 졸업증명서, 아포스티유'"
                    ),
                },
                {"role": "user", "content": query},
            ],
            max_tokens=60,
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        keywords = [k.strip() for k in raw.split(",") if k.strip()]
        return keywords[:5]
    except Exception:
        return [query]


def graph_search_node(state: AgentState) -> AgentState:
    """Neo4j 그래프 탐색으로 엔티티/관계 파악."""
    query = state["ko_query"] or state["question"]

    keywords = _extract_graph_keywords(query)
    print(f"[graph] keywords={keywords}")

    merged = {"entities": {}, "relations": [], "chunks": {}}
    for kw in keywords:
        result = knowledge_graph.search_by_embedding(kw)
        for e in result.get("entities", []):
            merged["entities"][e["name"]] = e
        merged["relations"].extend(result.get("relations", []))
        for c in result.get("chunks", []):
            key = (c["source"], c["page"], c["chunk_index"])
            merged["chunks"][key] = c

    final_result = {
        "entities": list(merged["entities"].values()),
        "relations": merged["relations"],
        "chunks": list(merged["chunks"].values()),
    }
    entities = [e["name"] for e in final_result["entities"]]
    print(f"[graph] entities={entities} | relations={len(final_result['relations'])}개 | chunks={len(final_result['chunks'])}개")

    return {
        **state,
        "graph_result": final_result,
        "tool_calls": state["tool_calls"] + 1,
    }


# ── 노드 3: 하이브리드 검색 ───────────────────────────────────────────────

def hybrid_search_node(state: AgentState) -> AgentState:
    """
    벡터+BM25 하이브리드 검색.
    그래프 결과가 있으면 엔티티를 쿼리에 추가해서 검색 정확도 향상.
    """
    base_query = state["question"]
    ko_query = state["ko_query"] or base_query

    # 그래프 결과로 쿼리 보강
    enriched_query = ko_query
    if state.get("graph_result"):
        entity_names = [e["name"] for e in state["graph_result"].get("entities", [])]
        if entity_names:
            enriched_query = f"{ko_query} {' '.join(entity_names[:5])}"

    context, sources = retriever.retrieve_with_sources(
        query=base_query,
        ko_query=enriched_query,
    )

    return {
        **state,
        "search_context": context,
        "search_sources": sources,
        "tool_calls": state["tool_calls"] + 1,
    }


# ── 노드 4: 재질문 생성 ───────────────────────────────────────────────────

def clarify_node(state: AgentState) -> AgentState:
    """질문이 모호할 때 사용자에게 되묻는 질문 생성."""
    lang = state["language"]
    lang_inst = _LANG_INSTRUCTIONS.get(lang, _LANG_INSTRUCTIONS["ko"])

    try:
        resp = _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    f"{lang_inst}\n"
                    "유학생 Q&A 어시스턴트입니다. "
                    "질문이 모호해서 더 구체적인 정보가 필요합니다. "
                    "어떤 상황인지 파악하기 위한 간결한 질문을 하나만 생성하세요."
                )},
                {"role": "user", "content": state["question"]},
            ],
            temperature=0.3,
            max_tokens=100,
        )
        clarify_q = resp.choices[0].message.content.strip()
    except Exception:
        clarify_q = "더 구체적으로 어떤 상황인지 알려주시겠어요?"

    return {
        **state,
        "clarify_question": clarify_q,
        "answer": clarify_q,
        "sources": [],
        "suggestions": [],
    }






async def _run_search_pipeline(
    question: str,
    language: str,
    ko_query: Optional[str],
    history: Optional[List[Dict]],
) -> AgentState:
    """라우팅 + 검색까지만 실행하고 상태를 반환 (generate 제외)."""
    state: AgentState = {
        "question": question,
        "language": language,
        "ko_query": ko_query,
        "history": history or [],
        "graph_result": None,
        "search_context": None,
        "search_sources": None,
        "answer": None,
        "sources": [],
        "suggestions": [],
        "tool_calls": 0,
        "clarify_question": None,
    }

    print(f"[pipeline] route_decision 시작 | history={len(history or [])}턴")
    decision = await asyncio.to_thread(route_decision, state)
    print(f"[pipeline] route_decision 결과: {decision}")

    if decision == "clarify":
        return await asyncio.to_thread(clarify_node, state)

    if decision == "graph":
        print("[pipeline] graph_search_node 시작")
        state = await asyncio.to_thread(graph_search_node, state)
        print("[pipeline] graph_search_node 완료")

    print("[pipeline] hybrid_search_node 시작")
    state = await asyncio.to_thread(hybrid_search_node, state)
    print("[pipeline] hybrid_search_node 완료")
    return state


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
        "meta":             "출처와 추천 질문을 정리하는 중",
    },
    "en": {
        "analyzing":        "Understanding your question",
        "searching":        "Searching through documents",
        "searching_done":   "Document search complete",
        "search_one":       "[{name}] found",
        "search_many":      "[{name}] and {n} more found",
        "generating":       "Writing your answer",
        "meta":             "Preparing sources and suggestions",
    },
    "zh": {
        "analyzing":        "正在理解您的问题",
        "searching":        "正在搜索文档",
        "searching_done":   "文档搜索完成",
        "search_one":       "已找到 [{name}]",
        "search_many":      "已找到 [{name}] 等 {n} 份文档",
        "generating":       "正在撰写答案",
        "meta":             "正在整理来源和推荐问题",
    },
    "es": {
        "analyzing":        "Entendiendo tu pregunta",
        "searching":        "Buscando en documentos",
        "searching_done":   "Búsqueda completada",
        "search_one":       "[{name}] encontrado",
        "search_many":      "[{name}] y {n} más encontrados",
        "generating":       "Escribiendo tu respuesta",
        "meta":             "Preparando fuentes y sugerencias",
    },
    "vi": {
        "analyzing":        "Đang phân tích câu hỏi",
        "searching":        "Đang tìm kiếm tài liệu",
        "searching_done":   "Tìm kiếm tài liệu hoàn tất",
        "search_one":       "Đã tìm thấy [{name}]",
        "search_many":      "Đã tìm thấy [{name}] và {n} tài liệu khác",
        "generating":       "Đang soạn câu trả lời",
        "meta":             "Đang chuẩn bị nguồn và gợi ý",
    },
}


async def run_agent_stream(
    question: str,
    language: str = "ko",
    ko_query: Optional[str] = None,
    history: Optional[List[Dict]] = None,
) -> AsyncGenerator[str, None]:
    """에이전트 스트리밍 진입점. SSE 형식의 JSON 문자열을 yield."""
    labels = _STATUS_LABELS.get(language, _STATUS_LABELS["ko"])

    yield f"data: {json.dumps({'type': 'status', 'content': labels['analyzing']}, ensure_ascii=False)}\n\n"
    await asyncio.sleep(0)
    yield f"data: {json.dumps({'type': 'status', 'content': labels['searching']}, ensure_ascii=False)}\n\n"
    await asyncio.sleep(0)

    state = await _run_search_pipeline(question, language, ko_query, history)

    # clarify 경로: 재질문 바로 반환
    if state.get("clarify_question"):
        yield f"data: {json.dumps({'type': 'clarify', 'content': state['clarify_question']})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'sources': [], 'suggestions': []})}\n\n"
        return

    lang_inst = _LANG_INSTRUCTIONS.get(language, _LANG_INSTRUCTIONS["ko"])
    sources = state.get("search_sources") or []

    # pipeline 완료 후 실제 문서명 포함한 검색 결과 status
    if sources:
        top_name = os.path.basename(sources[0].get("source", "문서"))
        n = len(sources)
        search_msg = labels["search_many"].format(name=top_name, n=n-1) if n > 1 else labels["search_one"].format(name=top_name)
    else:
        search_msg = labels["searching_done"]
    yield f"data: {json.dumps({'type': 'status', 'content': search_msg}, ensure_ascii=False)}\n\n"
    await asyncio.sleep(0.35)

    # 관련성 임계값 미달 — 질문 범위 분류 후 적절한 안내 메시지 반환
    max_score = _get_max_relevance_score(sources)
    if not state.get("graph_result") and max_score < _RELEVANCE_THRESHOLD:
        fallback_msg = await _classify_and_get_fallback(question, language)
        yield f"data: {json.dumps({'type': 'token', 'content': fallback_msg}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'sources': [], 'suggestions': []}, ensure_ascii=False)}\n\n"
        return

    # 컨텍스트 구성
    context_parts = []
    if state.get("graph_result") and state["graph_result"].get("relations"):
        relations = state["graph_result"]["relations"]
        graph_text = "\n".join(f"- {r['from']} → [{r['relation']}] → {r['to']}" for r in relations)
        context_parts.append(f"[지식그래프 관계 정보]\n{graph_text}")
    if state.get("search_context"):
        context_parts.append(f"[문서 검색 결과]\n{state['search_context']}")
    context = "\n\n".join(context_parts) if context_parts else "관련 문서를 찾을 수 없습니다."

    history_text = "\n".join(
        f"{'사용자' if h['role'] == 'user' else '어시스턴트'}: {h['content']}"
        for h in (history or [])[-10:]
    ) or "(이전 대화 없음)"

    yield f"data: {json.dumps({'type': 'status', 'content': labels['generating']}, ensure_ascii=False)}\n\n"
    await asyncio.sleep(0)

    # ── 1. 후속질문 생성을 백그라운드에서 미리 시작 (답변 스트리밍과 동시 실행) ──
    suggestion_task = asyncio.create_task(
        generate_suggestions_async(
            question=question,
            suggestion_context=state.get("search_context") or context,
            lang_instruction=lang_inst,
            lang=language,
        )
    )

    # ── 2. 답변 스트리밍 (llm.py stream_answer) ───────────────────────────────
    full_answer = ""
    async for token in stream_answer(
        question=question,
        context=context,
        lang_instruction=lang_inst,
        session_history=history_text,
    ):
        full_answer += token
        yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"

    print(f"[agent] 답변 완료 | len={len(full_answer)} | no_result={_is_no_result_answer(full_answer)}")

    # 답변이 "관련 내용 없음" 유형이면 출처/후속질문 없이 종료
    if _is_no_result_answer(full_answer):
        print("[agent] → no_result 경로, task cancel")
        suggestion_task.cancel()
        yield f"data: {json.dumps({'type': 'done', 'sources': [], 'suggestions': []}, ensure_ascii=False)}\n\n"
        return

    # ── 3. 소스 포맷 변환 (70% 이상만) ──────────────────────────────────────
    formatted_sources = [
        {"source": s.get("source", ""), "chunk_index": s.get("chunk_index", 0), "similarity_score": s.get("similarity_score", 0.0)}
        for s in sources
        if s.get("similarity_score", 0.0) >= 0.7
    ]
    print(f"[agent] formatted_sources: {len(formatted_sources)}개 | scores={[round(s.get('similarity_score',0),2) for s in sources]}")

    # 출처가 없으면 메타 이벤트 없이 바로 종료
    if not formatted_sources:
        print("[agent] → formatted_sources 없음, task cancel")
        suggestion_task.cancel()
        yield f"data: {json.dumps({'type': 'done', 'sources': [], 'suggestions': []}, ensure_ascii=False)}\n\n"
        return

    # 출처 있을 때만 meta 이벤트 전송
    yield f"data: {json.dumps({'type': 'meta', 'content': labels['meta']}, ensure_ascii=False)}\n\n"
    await asyncio.sleep(0)

    # ── 4. 후속질문 결과 수집 (이미 백그라운드에서 실행 중이므로 대기 시간 최소화) ─
    print(f"[agent] suggestion_task 상태: done={suggestion_task.done()}")
    try:
        suggestions = await asyncio.wait_for(suggestion_task, timeout=30.0)
        print(f"[agent] suggestions 수집 완료: {len(suggestions)}개")
    except asyncio.TimeoutError:
        print("[agent] suggestion_task 타임아웃")
        suggestions = []
    except Exception as e:
        print(f"[agent] suggestion_task 예외: {e}")
        suggestions = []

    yield f"data: {json.dumps({'type': 'done', 'sources': formatted_sources, 'suggestions': suggestions}, ensure_ascii=False)}\n\n"


