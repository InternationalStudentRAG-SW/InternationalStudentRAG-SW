import re
import json
import asyncio
import logging
from typing import Optional, List, Dict, Tuple
from langdetect import detect, DetectorFactory, LangDetectException
DetectorFactory.seed = 0
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from app.models.schemas import ChatRequest, ChatResponse
from app.config import settings
from app.core.rag_stream import _STATUS_LABELS, run_rag_stream  # 기본 경로: 하이브리드+리랭커 (팀원 agent.py는 쓰지 않음)
from app.core.agent_stream import run_agent_stream  # 복합 질문 경로: 단일 에이전트
from app.core.translation import translator
from app.core.cache import semantic_cache
from app.db.database import supabase

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)

ROUTING_MODES = ("off", "auto", "always")


async def _choose_route(question: str, history: List[Dict]) -> Tuple[str, Dict]:
    """
    AGENT_ROUTING 설정에 따라 'simple'(기본 RAG) 또는 'agent'(단일 에이전트)를 고른다. 실패해도 예외 없음.
    돌려주는 dict는 실행 기록용 (설정 모드, 라우터 판단 전체).
    """
    mode = (settings.agent_routing or "off").strip().lower()
    if mode not in ROUTING_MODES:
        logger.warning("알 수 없는 AGENT_ROUTING=%r → off로 처리", mode)
        mode = "off"
    if mode == "off":
        return "simple", {"routing_mode": mode}
    if mode == "always":
        return "agent", {"routing_mode": mode}
    try:
        from app.core.single_agent import run_log
        from app.core.single_agent.router import route_question
        run = await asyncio.to_thread(route_question, question, history)
        route = run.result.route or "agent"
        logger.info("route=%s reasons=%s fallback=%s latency=%dms", route,
                    run.result.route_reasons, run.fallback_used, run.latency_ms)
        if run_log.enabled():
            await asyncio.to_thread(run_log.append_route, {
                "question": question, "route": route, "reasons": run.result.route_reasons,
                "action": run.result.action, "asks": [a.text for a in run.result.asks],
                "user_conditions": [f"{c.field_id}={c.value}" for c in run.result.user_conditions],
                "fallback": run.fallback_used, "latency_ms": run.latency_ms})
        return route, {"routing_mode": mode, "router": run.model_dump()}
    except Exception as e:  # route_question은 예외를 던지지 않지만 import 실패 등 대비
        logger.exception("router failed: %s → simple", e)
        return "simple", {"routing_mode": mode, "router_error": str(e)}


def _detect_language(question: str, explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    if re.search(r'[가-힣]', question):
        return "ko"
    if re.search(r'[぀-ヿ]', question):
        return "ja"
    if re.search(r'[一-鿿㐀-䶿]', question):
        return "zh"
    if re.search(r'[؀-ۿ]', question):
        return "ar"
    try:
        detected = detect(question)
        return detected if detected in {"en", "vi", "es", "ko", "zh"} else "auto"
    except LangDetectException:
        return "auto"


def _insert_chat_log(query: str, answer: str, sources: list, language: str):
    try:
        supabase.table("chat_logs").insert({
            "query": query,
            "answer": answer,
            "sources": sources,
            "language": language,
        }).execute()
    except Exception:
        pass


async def _get_cached_response(
    ko_query: str,
    language: str,
    question: str,
    background_tasks: BackgroundTasks,
) -> Optional[ChatResponse]:
    """캐시 조회. HIT이면 ChatResponse 반환, MISS면 None 반환."""
    cached = await asyncio.to_thread(semantic_cache.get, ko_query, language)
    if not cached:
        return None

    # 해당 언어 캐시가 없어서 한국어 답변을 실시간 번역해야 하는 경우
    if cached.get("_needs_translation"):
        translated_answer = await asyncio.to_thread(
            translator.translate_from_ko, cached["answer"], language
        )
        translated_suggestions = [
            await asyncio.to_thread(translator.translate_from_ko, s, language)
            for s in cached["suggestions"]
        ]
        background_tasks.add_task(
            semantic_cache.add_language,
            cached["_cache_key"], language, translated_answer, translated_suggestions,
        )
        return ChatResponse(
            answer=translated_answer,
            sources=cached["sources"],
            suggestions=translated_suggestions,
            language=language,
            question=question,
        )

    return ChatResponse(
        answer=cached["answer"],
        sources=cached["sources"],
        suggestions=cached["suggestions"],
        language=language,
        question=question,
    )


async def _save_streaming_results(
    ko_query: str,
    language: str,
    question: str,
    full_answer: str,
    sources: list,
    suggestions: list,
    is_first_message: bool,
    is_clarify: bool,
):
    if is_first_message and full_answer and not is_clarify:
        if language == "ko":
            await asyncio.to_thread(
                semantic_cache.set,
                ko_query, "ko",
                {"answer": full_answer, "sources": sources, "suggestions": suggestions or []},
            )
        else:
            # 비-한국어 답변: 한국어로 번역해 캐시 기준값(answer_ko)으로 저장
            # → 이후 한국어 질문이 캐시 히트할 때 answer_ko를 바로 반환 가능
            ko_answer = await asyncio.to_thread(translator.translate_to_ko, full_answer)
            ko_suggestions = [
                await asyncio.to_thread(translator.translate_to_ko, s)
                for s in (suggestions or [])
            ]
            cache_key = await asyncio.to_thread(
                semantic_cache.set,
                ko_query, "ko",
                {"answer": ko_answer, "sources": sources, "suggestions": ko_suggestions},
            )
            if cache_key:
                await asyncio.to_thread(
                    semantic_cache.add_language,
                    cache_key, language, full_answer, suggestions or [],
                )
    await asyncio.to_thread(
        _insert_chat_log,
        query=question,
        answer=full_answer,
        sources=sources,
        language=language,
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest, background_tasks: BackgroundTasks):
    """SSE 스트리밍 엔드포인트."""
    try:
        language = _detect_language(request.question, request.language)
        ko_query = await asyncio.to_thread(translator.translate_to_ko, request.question)
        history = [{"role": m.role, "content": m.content} for m in (request.history or [])]
        is_first_message = len(history) == 0

        # ── 캐시 조회 (첫 질문만) ─────────────────────────────────────────
        if is_first_message:
            cached = await _get_cached_response(ko_query, language, request.question, background_tasks)
            if cached:
                async def cached_generator():
                    chunk_size = 15
                    answer = cached.answer
                    for i in range(0, len(answer), chunk_size):
                        yield f"data: {json.dumps({'type': 'token', 'content': answer[i:i+chunk_size]}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0)
                    sources = [s.model_dump() for s in cached.sources]
                    yield f"data: {json.dumps({'type': 'done', 'sources': sources, 'suggestions': cached.suggestions}, ensure_ascii=False)}\n\n"
                return StreamingResponse(
                    cached_generator(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )

        # ── 경로 선택: 기본 RAG(하이브리드+리랭커) / 단일 에이전트 ─────────────────────
        async def event_generator():
            full_answer = ""
            final_sources: list = []
            final_suggestions: list = []
            is_clarify = False

            # 라우터(LLM 1회, 약 3초) 동안 화면이 멈춰 보이지 않게 먼저 상태를 보낸다
            if (settings.agent_routing or "off").strip().lower() == "auto":
                labels = _STATUS_LABELS.get(language, _STATUS_LABELS["en"])
                yield f"data: {json.dumps({'type': 'status', 'content': labels['analyzing']}, ensure_ascii=False)}\n\n"
            route, route_meta = await _choose_route(request.question, history)
            if route == "agent":
                stream = run_agent_stream(question=request.question, language=language,
                                          ko_query=ko_query, history=history, log_meta=route_meta)
            else:
                stream = run_rag_stream(question=request.question, language=language,
                                        ko_query=ko_query, history=history)

            async for chunk in stream:
                if chunk.startswith("data: "):
                    try:
                        payload = json.loads(chunk[6:].strip())
                        ptype = payload.get("type")
                        if ptype == "token":
                            full_answer += payload.get("content", "")
                        elif ptype == "done":
                            final_sources = payload.get("sources", [])
                            final_suggestions = payload.get("suggestions", [])
                        elif ptype == "clarify":
                            full_answer = payload.get("content", "")
                            is_clarify = True
                    except Exception:
                        pass
                yield chunk

            asyncio.create_task(_save_streaming_results(
                ko_query=ko_query,
                language=language,
                question=request.question,
                full_answer=full_answer,
                sources=final_sources,
                suggestions=final_suggestions,
                is_first_message=is_first_message,
                is_clarify=is_clarify,
            ))

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
