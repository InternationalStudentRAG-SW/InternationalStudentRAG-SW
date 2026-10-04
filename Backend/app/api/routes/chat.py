import re
import json
import asyncio
from typing import Optional, List
from langdetect import detect, DetectorFactory, LangDetectException
DetectorFactory.seed = 0
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from app.models.schemas import ChatRequest, ChatResponse
from app.core.single_agent.pipeline import run_pipeline
from app.core.translation import translator
from app.core.cache import semantic_cache
from app.core.llm import generate_suggestions_async
from app.db.database import supabase
from app.core.agent import _STATUS_LABELS, _LANG_INSTRUCTIONS

router = APIRouter(prefix="/chat", tags=["chat"])

# pipeline stage → _STATUS_LABELS 키 매핑 (agent.py의 _STATUS_LABELS 재사용)
_STAGE_TO_LABEL = {
    "analysis":     "analysis",
    "kg_search":    "kg_search",
    "plan":         "plan",
    "search":       "search_ev",
    "verify_start": "verify",
    "answer_start": "answer_start",
}


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
            # 원본 언어 답변도 추가 저장 → 같은 언어 재질문 시 번역 불필요
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


def _convert_sources(answer_run, pool=None) -> List[dict]:
    """AnswerSource 목록 → SSE done 페이로드용 dict 목록.
    pool이 있으면 실제 청크 score를 가져오고, LLM이 [번호] 마커를 안 쓴 경우 shown_evidence_ids 폴백."""
    if not answer_run:
        return []

    def _score(eid: str) -> float:
        if pool is None:
            return 0.0
        chunk = pool.get(eid)
        return float(chunk.score) if chunk and chunk.score is not None else 0.0

    if answer_run.sources:
        seen: set = set()
        result = []
        for s in answer_run.sources:
            if s.source not in seen:
                seen.add(s.source)
                result.append({
                    "source": s.source,
                    "chunk_index": s.page,
                    "similarity_score": _score(s.evidence_id),
                })
        return result

    # 폴백: LLM이 인용 마커를 안 썼어도 증거로 쓴 청크의 출처는 표시
    if pool is not None and answer_run.shown_evidence_ids:
        seen2: set = set()
        fallback = []
        for eid in answer_run.shown_evidence_ids[:5]:
            chunk = pool.get(eid)
            if chunk and chunk.source not in seen2:
                seen2.add(chunk.source)
                fallback.append({
                    "source": chunk.source,
                    "chunk_index": chunk.page,
                    "similarity_score": float(chunk.score) if chunk.score is not None else 0.0,
                })
        return fallback
    return []


@router.post("/stream")
async def chat_stream(request: ChatRequest, background_tasks: BackgroundTasks):
    """SSE 스트리밍 엔드포인트."""
    try:
        language = _detect_language(request.question, request.language)
        # ko_query: 캐시 키 용도로만 사용. run_pipeline은 원본 질문을 직접 받는다.
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

        # ── single_agent 스트리밍 ────────────────────────────────────────
        async def event_generator():
            full_answer = ""
            final_sources: list = []
            final_suggestions: list = []
            is_clarify = False

            loop = asyncio.get_event_loop()
            queue: asyncio.Queue = asyncio.Queue()
            pipeline_result = None

            # 반복되는 단계(plan/search/verify)는 라운드 번호를 붙여 구분한다.
            _stage_round: dict = {}
            _REPEATABLE = {"plan", "search", "verify_start"}

            def on_event(stage: str, info: dict):
                # run_pipeline은 스레드풀에서 실행되므로 call_soon_threadsafe로 큐에 넣는다.
                loop.call_soon_threadsafe(queue.put_nowait, ("event", stage, info))

            lang_labels = _STATUS_LABELS.get(language, _STATUS_LABELS["ko"])
            lang_instruction = _LANG_INSTRUCTIONS.get(language, _LANG_INSTRUCTIONS["ko"])

            async def run_pipeline_task():
                nonlocal pipeline_result
                try:
                    pipeline_result = await asyncio.to_thread(
                        run_pipeline,
                        question=request.question,
                        history=history,
                        lang_instruction=lang_instruction,
                        on_event=on_event,
                    )
                except Exception:
                    pipeline_result = None
                finally:
                    # 스레드가 끝난 뒤 이벤트 루프에서 실행되므로 put_nowait 사용 가능
                    await queue.put(("done", None))

            task = asyncio.create_task(run_pipeline_task())

            # 단계별 진행 이벤트를 SSE로 흘려보내고, done 센티넬을 받으면 종료
            while True:
                item = await queue.get()
                if item[0] == "event":
                    _, stage, _ = item
                    label_key = _STAGE_TO_LABEL.get(stage)
                    base_msg = lang_labels.get(label_key) if label_key else None
                    if base_msg:
                        if stage in _REPEATABLE:
                            cnt = _stage_round.get(stage, 0) + 1
                            _stage_round[stage] = cnt
                            msg = base_msg if cnt == 1 else f"{base_msg} ({cnt})"
                        else:
                            msg = base_msg
                        yield f"data: {json.dumps({'type': 'status', 'content': msg}, ensure_ascii=False)}\n\n"
                elif item[0] == "done":
                    break

            await task  # 태스크 예외가 있으면 여기서 전파

            # ── 디버그 로그 ──────────────────────────────────────────────
            if pipeline_result:
                print(f"\n[pipeline] stopped={pipeline_result.stopped}")
                print(f"[pipeline] rounds={pipeline_result.rounds}")
                print(f"[pipeline] warnings={pipeline_result.warnings}")
                if pipeline_result.analysis:
                    a = pipeline_result.analysis
                    print(f"[pipeline] type={a.primary_type} next_action={a.next_action}")
                    if a.first_search:
                        print(f"[pipeline] first_search.query_ko={a.first_search.query_ko}")
                    for s in a.document_slots:
                        if s.active:
                            print(f"[pipeline]   slot={s.slot_id} status={s.status} refs={len(s.evidence_refs)}")
                for i, sr in enumerate(pipeline_result.search_runs):
                    print(f"[pipeline] search[{i}] ok={sr.ok} chunks={len(sr.chunk_ids)} new={len(sr.new_chunk_ids)} error={sr.error}")
                for i, vr in enumerate(pipeline_result.verify_runs):
                    if vr.decision:
                        print(f"[pipeline] verify[{i}] next_action={vr.decision.next_action} reason={vr.decision.reason[:120]}")
                if pipeline_result.answer_run:
                    ar = pipeline_result.answer_run
                    print(f"[pipeline] answer_mode={ar.mode}")
                    print(f"[pipeline] answer={ar.answer[:150] if ar.answer else None}")
                print()
            # ─────────────────────────────────────────────────────────────

            # pipeline이 완료된 뒤 답변을 청크로 나눠 전송
            if pipeline_result and pipeline_result.answer_run:
                answer_run = pipeline_result.answer_run
                full_answer = answer_run.answer or ""
                mode = answer_run.mode
                is_clarify = mode in ("ask_clarification", "clarify_scope")
                final_sources = _convert_sources(answer_run, pool=pipeline_result.pool)

                chunk_size = 15
                for i in range(0, len(full_answer), chunk_size):
                    yield f"data: {json.dumps({'type': 'token', 'content': full_answer[i:i+chunk_size]}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0)

            # 출처·후속질문 수집 중 안내 (프론트의 metaStatus 트리거, 언어별)
            if full_answer:
                meta_msg = lang_labels.get("meta", "출처와 추천 질문을 정리하는 중")
                yield f"data: {json.dumps({'type': 'meta', 'content': meta_msg}, ensure_ascii=False)}\n\n"

            # 후속 질문 생성 (clarify 모드가 아닌 경우에만)
            if full_answer and not is_clarify:
                lang_instruction = _LANG_INSTRUCTIONS.get(language, _LANG_INSTRUCTIONS["ko"])
                try:
                    final_suggestions = await generate_suggestions_async(
                        question=request.question,
                        suggestion_context=full_answer,
                        lang_instruction=lang_instruction,
                        lang=language,
                    )
                except Exception:
                    final_suggestions = []

            yield f"data: {json.dumps({'type': 'done', 'sources': final_sources, 'suggestions': final_suggestions}, ensure_ascii=False)}\n\n"

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
