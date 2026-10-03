"""
단일 에이전트(app/core/single_agent) 결과를 프론트의 SSE 형식으로 바꾸는 어댑터.

프론트가 받는 이벤트 (rag_stream.py와 같은 형식)
  status  : 진행 단계 문구 (분석 → 검색 → 근거 확인 → 답변 작성)
  token   : 답변 조각 (에이전트는 답을 한 번에 만들므로 완성 후 잘라서 보낸다)
  clarify : 되묻기 (⑤가 ask_clarification일 때)
  meta    : 출처·추천 질문 정리 중
  done    : sources, suggestions

run_pipeline은 동기 함수라 스레드에서 돌리고, 단계 이벤트(on_event)는 큐로 받아 status로 내보낸다.
에이전트 답은 한국어로 만들어지므로 사용자 언어가 한국어가 아니면 번역한다.
실패해도 예외를 밖으로 던지지 않고 안내 문구로 끝낸다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Dict, List, Optional

from app.core.rag_stream import _STATUS_LABELS, _FALLBACK_MESSAGES

logger = logging.getLogger(__name__)

TOKEN_CHUNK = 15          # 완성된 답을 이 글자 수씩 잘라 token 이벤트로 보낸다
SUGGESTION_TIMEOUT = 20.0
# 에이전트는 한 단계(LLM 호출)에 수십 초가 걸릴 수 있다. 그동안 연결이 끊긴 것으로 보이지 않게
# 이 간격마다 SSE 주석(": ping")을 보낸다. 프론트는 'data: '로 시작하지 않는 줄을 무시하지만,
# 데이터가 들어온 것이므로 '응답 없음' 타이머는 다시 시작된다.
HEARTBEAT_S = 10.0
HEARTBEAT = ": ping\n\n"

# 단계 이벤트 → 상태 문구 키 (rag_stream의 다국어 문구를 재사용)
_STAGE_LABEL = {
    "analysis": "searching",
    "search": "searching_done",
    "verify_start": "verifying",
    "answer_start": "generating",
}

_VERIFYING = {
    "ko": "찾은 근거가 충분한지 확인하는 중",
    "en": "Checking whether the evidence is enough",
    "zh": "正在确认依据是否充分",
    "es": "Verificando si la información es suficiente",
    "vi": "Đang kiểm tra bằng chứng đã đủ chưa",
}

_ERROR_MESSAGES = {
    "ko": "죄송합니다. 답변을 만드는 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.",
    "en": "Sorry, something went wrong while preparing the answer. Please try again shortly.",
}


def _sse(payload: Dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def format_sources(run) -> List[Dict]:
    """
    ⑤가 본문에 실제로 쓴 근거만 프론트 출처 형식(source, chunk_index, similarity_score)으로 바꾼다.
    화면은 문서 이름과 관련도만 보여주므로, 기존 검색 경로(retriever.retrieve_with_sources, 커밋 52ec76d)와 같이
    **문서 하나당 한 줄**만 남긴다. 같은 문서가 여러 번이면 관련도가 가장 높은 조각을 대표로 쓴다.
    (2026-10-03: 같은 문서의 다른 조각이 이름만 같은 여러 줄로 보여 중복처럼 보였음)
    """
    best: Dict[str, Dict] = {}
    order: List[str] = []
    answer_run = getattr(run, "answer_run", None)
    for s in (answer_run.sources if answer_run else []):
        chunk = run.pool.get(s.evidence_id) if getattr(run, "pool", None) else None
        score = chunk.score if chunk and chunk.score is not None else 1.0  # 확장으로만 얻은 청크는 점수 없음
        item = {"source": s.source, "chunk_index": chunk.chunk_index if chunk else 0,
                "similarity_score": float(score)}
        if s.source not in best:
            order.append(s.source)
            best[s.source] = item
        elif item["similarity_score"] > best[s.source]["similarity_score"]:
            best[s.source] = item
    return [best[src] for src in order]


async def run_agent_stream(
    question: str,
    language: str,
    ko_query: Optional[str] = None,
    history: Optional[List[Dict]] = None,
    log_meta: Optional[Dict] = None,
    pipeline_fn=None,
    translate_fn=None,
    suggest_fn=None,
) -> AsyncGenerator[str, None]:
    """에이전트 경로 SSE 생성기. pipeline_fn/translate_fn/suggest_fn은 테스트용 가짜를 끼울 때만 쓴다."""
    labels = {**_STATUS_LABELS.get(language, _STATUS_LABELS["en"])}
    labels.setdefault("verifying", _VERIFYING.get(language, _VERIFYING["en"]))
    yield _sse({"type": "status", "content": labels["analyzing"]})

    if pipeline_fn is None:
        from app.core.single_agent.pipeline import run_pipeline as pipeline_fn
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def on_event(stage: str, info: Dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (stage, info))

    # ⓪ 라우터가 나눈 요구를 ①에 넘긴다 (요구가 빠지지 않게)
    route_asks = (((log_meta or {}).get("router") or {}).get("result") or {}).get("asks") or []
    kwargs = {"on_event": on_event}
    if route_asks:
        kwargs["route_asks"] = route_asks
    task = asyncio.create_task(asyncio.to_thread(pipeline_fn, ko_query or question, history, **kwargs))

    last_label = labels["analyzing"]
    while True:
        getter = asyncio.create_task(queue.get())
        done, _ = await asyncio.wait({task, getter}, timeout=HEARTBEAT_S, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            getter.cancel()
            yield HEARTBEAT
            continue
        if getter in done:
            stage, _info = getter.result()
            key = _STAGE_LABEL.get(stage)
            if key and labels.get(key) and labels[key] != last_label:
                last_label = labels[key]
                yield _sse({"type": "status", "content": last_label})
            continue
        getter.cancel()
        break

    try:
        run = task.result()
    except Exception as e:  # run_pipeline은 예외를 던지지 않지만 혹시 모를 경우
        logger.exception("agent pipeline failed: %s", e)
        yield _sse({"type": "token", "content": _ERROR_MESSAGES.get(language, _ERROR_MESSAGES["en"])})
        yield _sse({"type": "done", "sources": [], "suggestions": []})
        return

    answer_run = run.answer_run
    mode = answer_run.mode if answer_run else "error"
    answer = (answer_run.answer if answer_run else "") or ""
    if not answer:
        fb = _FALLBACK_MESSAGES["in_scope"]
        answer = fb.get(language, fb["en"])
    if language not in ("ko", "auto"):
        try:
            if translate_fn is None:
                from app.core.translation import translator
                translate_fn = translator.translate_from_ko
            answer = await asyncio.to_thread(translate_fn, answer, language)
        except Exception as e:
            logger.warning("agent answer translation failed: %s", e)

    async def save_log(sent_sources: List[Dict], suggestions: List[str]) -> None:
        if log_meta is None:
            return
        from app.core.single_agent import run_log
        if not run_log.enabled():
            return
        record = {"question": question, "language": language, "ko_query": ko_query, "history": history or [],
                  **log_meta, "final": {"mode": mode, "answer_sent": answer, "sources_sent": sent_sources,
                                        "suggestions": suggestions},
                  "run": run.model_dump()}
        await asyncio.to_thread(run_log.save_agent_run, record)

    if mode in ("ask_clarification", "clarify_scope"):
        yield _sse({"type": "clarify", "content": answer})
        yield _sse({"type": "done", "sources": [], "suggestions": []})
        await save_log([], [])
        return

    for i in range(0, len(answer), TOKEN_CHUNK):
        yield _sse({"type": "token", "content": answer[i:i + TOKEN_CHUNK]})
        await asyncio.sleep(0)

    sources = format_sources(run) if mode not in ("no_evidence", "error", "out_of_scope", "no_retrieval") else []
    suggestions: List[str] = []
    if sources:
        yield _sse({"type": "meta", "content": labels["meta"]})
        suggestions = await _suggest(question, answer, language, suggest_fn)
    yield _sse({"type": "done", "sources": sources, "suggestions": suggestions})
    await save_log(sources, suggestions)


async def _suggest(question: str, answer: str, language: str, suggest_fn) -> List[str]:
    """기본 경로와 같은 추천 질문 생성기를 쓴다 (실패하면 빈 목록)."""
    try:
        if suggest_fn is None:
            from app.core.llm import generate_suggestions_async as suggest_fn
            from app.core.rag_stream import _LANG_INSTRUCTIONS
            lang_inst = _LANG_INSTRUCTIONS.get(language, _LANG_INSTRUCTIONS.get("en", ""))
            coro = suggest_fn(question=question, suggestion_context=answer, lang_instruction=lang_inst,
                              lang=language)
        else:
            coro = suggest_fn(question, answer, language)
        return await asyncio.wait_for(coro, timeout=SUGGESTION_TIMEOUT) or []
    except Exception:
        return []
