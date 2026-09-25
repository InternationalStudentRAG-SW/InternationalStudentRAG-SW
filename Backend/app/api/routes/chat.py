import re
import json
import asyncio
from typing import Optional, List, Dict
from langdetect import detect, DetectorFactory, LangDetectException
DetectorFactory.seed = 0
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from app.models.schemas import ChatRequest, ChatResponse
from app.core.agent import run_agent_stream
from app.core.translation import translator
from app.core.cache import semantic_cache
from app.db.database import supabase

router = APIRouter(prefix="/chat", tags=["chat"])


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
        await asyncio.to_thread(
            semantic_cache.set,
            ko_query, language,
            {"answer": full_answer, "sources": sources, "suggestions": suggestions or []},
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

        # ── 에이전트 스트리밍 ──────────────────────────────────────────────
        async def event_generator():
            full_answer = ""
            final_sources: list = []
            final_suggestions: list = []
            is_clarify = False

            async for chunk in run_agent_stream(
                question=request.question,
                language=language,
                ko_query=ko_query,
                history=history,
            ):
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
