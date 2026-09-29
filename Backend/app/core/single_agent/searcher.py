"""
③ 근거 검색.

입력: ②가 만든 SearchPlan(검색 액션 1개) + 누적 근거 풀 + 예산
출력: 이번 검색으로 얻은 청크(풀에 누적), 갱신된 예산, 검색 기록(SearchAttempt)

이 단계는 LLM을 부르지 않는다. 칸 상태(supported 등)도 바꾸지 않는다. 그건 ④의 몫이다.

검색 종류
  new             : retriever(BM25 + Vector → RRF → BGE reranker)로 query_ko를 검색한다.
                    돌려받는 청크 수는 checklist_config.SEARCH_TOP_K.
  expand_context  : 앵커 청크의 앞·뒤 청크(EXPAND_WINDOW개)를 저장소에서 직접 가져온다.
                    임베딩·reranker를 쓰지 않는다. 앵커가 페이지의 처음·끝이면 이웃 페이지로 넘어간다.
                    ②가 만든 query_ko는 기록에만 남고 확장에는 쓰지 않는다.

규칙
  - found_new_evidence는 규칙으로 계산한다: 이번 실행에서 풀에 처음 들어온 청크가 하나라도 있으면 True.
  - 검색 도구 오류는 '문서에 없음'이 아니다. TOOL_MAX_RETRIES번 다시 시도하고도 실패하면
    error_type="tool_error"로 돌려주며, 예산·풀·검색 기록은 바꾸지 않는다.
  - 결과가 0건이어도 검색은 실행된 것이므로 예산은 차감하고 found_new_evidence=False로 기록한다.
  - 예산 검사는 ②가 이미 하지만, 서버가 강제한다는 원칙에 따라 여기서도 한 번 더 막는다.

테스트에서는 search_fn과 store를 가짜로 바꿔 끼운다. 기본값은 실제 retriever / ChromaDB를
호출 시점에 import한다(모듈을 import만 해서는 BM25 색인·reranker가 로드되지 않게).
"""
from __future__ import annotations

import time
from typing import Any, Callable, List, Optional, Protocol, Tuple

from app.core.single_agent import checklist_config as cfg
from app.core.single_agent.evidence_schema import (
    EvidenceChunk,
    EvidencePool,
    RetrievalTag,
    SearchExecutionRun,
    make_evidence_id,
    parse_evidence_id,
)
from app.core.single_agent.search_planner import check_budget
from app.core.single_agent.search_schema import SearchAttempt, SearchBudget, SearchPlan

SearchFn = Callable[[str, int], List[Any]]  # (query_ko, k) -> Document 비슷한 객체 목록


# ── 저장소 / 기본 검색 함수 ─────────────────────────────────────────────────

class ChunkStore(Protocol):
    """원문 확장이 이웃 청크를 가져올 때 쓰는 저장소."""

    def get_chunk(self, source: str, page: int, chunk_index: int) -> Optional[EvidenceChunk]: ...

    def last_chunk_index(self, source: str, page: int) -> Optional[int]:
        """해당 페이지의 마지막 chunk_index. 페이지에 청크가 없으면 None."""
        ...


class ChromaChunkStore:
    """ChromaDB(knowledge_base.vector_store)에서 (source, page, chunk_index)로 청크를 읽는다."""

    def __init__(self, vector_store: Any = None):
        self._vs = vector_store

    def _store(self):
        if self._vs is None:
            from app.core.knowledge_base import knowledge_base
            self._vs = knowledge_base.vector_store
        return self._vs

    def get_chunk(self, source: str, page: int, chunk_index: int) -> Optional[EvidenceChunk]:
        res = self._store().get(
            where={"$and": [{"source": source}, {"page": page}, {"chunk_index": chunk_index}]},
            include=["documents", "metadatas"],
        )
        docs = res.get("documents") or []
        if not docs:
            return None
        meta = (res.get("metadatas") or [{}])[0] or {}
        return EvidenceChunk(
            evidence_id=make_evidence_id(source, page, chunk_index),
            source=source,
            page=page,
            chunk_index=chunk_index,
            lang=str(meta.get("lang", "")),
            text=docs[0],
        )

    def last_chunk_index(self, source: str, page: int) -> Optional[int]:
        res = self._store().get(
            where={"$and": [{"source": source}, {"page": page}]},
            include=["metadatas"],
        )
        idxs = [int(m["chunk_index"]) for m in (res.get("metadatas") or []) if m and "chunk_index" in m]
        return max(idxs) if idxs else None


def _default_search_fn(query: str, k: int) -> List[Any]:
    """실제 하이브리드 + rerank 검색. import 시점에 무거운 초기화가 일어나므로 호출 때 import한다."""
    from app.core.retriever import retriever
    return retriever.retrieve(query, k=k)


# ── 변환 ─────────────────────────────────────────────────────────────────

def _docs_to_chunks(docs: List[Any], warnings: List[str]) -> List[EvidenceChunk]:
    """검색 결과(Document 비슷한 객체)를 EvidenceChunk로 바꾼다. 메타데이터가 부족한 것은 걸러낸다."""
    chunks: List[EvidenceChunk] = []
    seen = set()
    for i, doc in enumerate(docs[: cfg.SEARCH_TOP_K], 1):
        meta = getattr(doc, "metadata", None) or {}
        text = str(getattr(doc, "page_content", "") or "")
        source = meta.get("source")
        try:
            page = int(meta.get("page"))
            idx = int(meta.get("chunk_index"))
        except (TypeError, ValueError):
            warnings.append(f"[제거] 결과 {i}번: page/chunk_index 메타데이터가 없어 근거 ID를 만들 수 없음")
            continue
        if not source or not text.strip():
            warnings.append(f"[제거] 결과 {i}번: source 또는 본문이 비어 있음")
            continue
        eid = make_evidence_id(source, page, idx)
        if eid in seen:
            warnings.append(f"[제거] 결과 {i}번: {eid} 결과 안에서 중복")
            continue
        seen.add(eid)
        score = meta.get("similarity_score")
        chunks.append(EvidenceChunk(
            evidence_id=eid, source=source, page=page, chunk_index=idx,
            lang=str(meta.get("lang", "")), text=text,
            score=float(score) if score is not None else None,
        ))
    return chunks


# ── 원문 확장 ─────────────────────────────────────────────────────────────

Position = Tuple[str, int, int]  # (source, page, chunk_index)


def _resolve_anchors(
    anchor_ids: Optional[List[str]], pool: EvidencePool, slot_id: str, warnings: List[str],
) -> List[Position]:
    """앵커 ID를 (source, page, chunk_index)로 바꾼다. 못 바꾸면 그 칸의 최고 점수 청크로 대체한다."""
    positions: List[Position] = []
    for eid in anchor_ids or []:
        chunk = pool.get(eid)
        if chunk is not None:
            pos = (chunk.source, chunk.page, chunk.chunk_index)
        else:
            parsed = parse_evidence_id(eid)
            if parsed is None:
                warnings.append(f"[제거] 앵커 '{eid}': 근거 ID 형식이 아님")
                continue
            pos = parsed
        if pos not in positions:
            positions.append(pos)

    if not positions:
        best = pool.best_for_slot(slot_id)
        if best is not None:
            positions.append((best.source, best.page, best.chunk_index))
            warnings.append(f"[보완] 앵커가 없어 {slot_id} 칸의 최고 점수 청크 {best.evidence_id}를 사용")
    return positions


def _step(store: ChunkStore, source: str, page: int, idx: int, direction: int) -> Optional[Tuple[int, int]]:
    """(page, idx)에서 direction(+1/-1)으로 한 청크 이동한 위치. 문서의 처음·끝이면 None."""
    if direction > 0:
        last = store.last_chunk_index(source, page)
        if last is None:
            return None
        if idx < last:
            return page, idx + 1
        if store.last_chunk_index(source, page + 1) is not None:
            return page + 1, 0
        return None
    if idx > 0:
        return page, idx - 1
    prev_last = store.last_chunk_index(source, page - 1)
    if prev_last is not None:
        return page - 1, prev_last
    return None


def _collect_neighbors(store: ChunkStore, anchors: List[Position]) -> List[EvidenceChunk]:
    """앵커마다 앞·뒤 EXPAND_WINDOW개 청크를 모은다. 앵커 자신은 빼고, 문서 순으로 정렬한다."""
    anchor_set = set(anchors)
    found = {}
    for source, page, idx in anchors:
        for direction in (-1, 1):
            cur = (page, idx)
            for _ in range(cfg.EXPAND_WINDOW):
                nxt = _step(store, source, cur[0], cur[1], direction)
                if nxt is None:
                    break
                cur = nxt
                if (source, cur[0], cur[1]) in anchor_set:
                    continue
                chunk = store.get_chunk(source, cur[0], cur[1])
                if chunk is None:
                    break
                found[chunk.evidence_id] = chunk
    return sorted(found.values(), key=lambda c: (c.source, c.page, c.chunk_index))


# ── 실행 ─────────────────────────────────────────────────────────────────

def _call_with_retries(run: SearchExecutionRun, fn: Callable[[], Any]) -> Tuple[bool, Any]:
    """도구 호출을 TOOL_MAX_RETRIES번까지 다시 시도한다. 끝내 실패하면 run에 오류를 적고 (False, None)."""
    last: Optional[Exception] = None
    total = 1 + cfg.TOOL_MAX_RETRIES
    for n in range(1, total + 1):
        run.tool_attempts += 1
        try:
            return True, fn()
        except Exception as e:  # 검색기·저장소의 모든 오류를 '도구 오류'로 취급
            last = e
            run.warnings.append(f"[도구 오류] {n}/{total}회 시도 실패: {type(e).__name__}: {e}")
    run.error = f"검색 도구 오류 ({total}회 시도 후 실패): {type(last).__name__}: {last}"
    run.error_type = "tool_error"
    return False, None


def _execute(
    run: SearchExecutionRun,
    plan: SearchPlan,
    pool: EvidencePool,
    budget: SearchBudget,
    anchor_evidence_ids: Optional[List[str]],
    search_fn: Optional[SearchFn],
    store: Optional[ChunkStore],
) -> None:
    # 1) 계획 검사
    if plan.action != "search":
        run.error, run.error_type = f"실행할 검색이 아님 (action={plan.action!r})", "invalid_plan"
        return
    if plan.search_type not in ("new", "expand_context") or not plan.target_slot_id \
            or not (plan.query_ko or "").strip():
        run.error, run.error_type = "검색 계획이 불완전함 (target_slot_id / search_type / query_ko)", "invalid_plan"
        return

    # 2) 예산 (②가 이미 확인했지만 서버가 한 번 더 강제)
    msg = check_budget(budget, plan.search_type)
    if msg:
        run.error, run.error_type = msg, "budget_exhausted"
        return

    tag = RetrievalTag(
        target_slot_id=plan.target_slot_id,
        search_type=plan.search_type,
        query_ko=plan.query_ko.strip(),
        round_no=budget.total_calls + 1,
    )

    # 3) 청크 확보 (풀은 도구 호출이 성공한 뒤에만 건드린다)
    if plan.search_type == "new":
        fn = search_fn or _default_search_fn
        ok, docs = _call_with_retries(run, lambda: fn(tag.query_ko, cfg.SEARCH_TOP_K))
        if not ok:
            return
        chunks = _docs_to_chunks(list(docs or []), run.warnings)
        if not chunks:
            run.warnings.append(f"[결과 없음] '{tag.query_ko}' 검색 결과가 없음 (미확보이지 자료 부재 확정은 아님)")
    else:
        anchors = _resolve_anchors(anchor_evidence_ids, pool, plan.target_slot_id, run.warnings)
        if not anchors:
            run.error, run.error_type = "원문 확장의 기준이 될 앵커 청크를 찾지 못함", "no_anchor"
            return
        run.anchor_ids = [make_evidence_id(*a) for a in anchors]
        the_store = store or ChromaChunkStore()
        ok, chunks = _call_with_retries(run, lambda: _collect_neighbors(the_store, anchors))
        if not ok:
            return
        if not chunks:
            run.warnings.append("[이웃 없음] 앵커 앞·뒤에 가져올 청크가 없음 (문서의 처음·끝)")

    # 4) 풀에 누적 + 새 근거 판정
    for chunk in chunks:
        is_new = pool.add(chunk, tag)
        run.chunk_ids.append(chunk.evidence_id)
        if is_new:
            run.new_chunk_ids.append(chunk.evidence_id)

    # 5) 예산 갱신 + 검색 기록
    new_budget = budget.model_copy()
    new_budget.total_calls += 1
    if plan.search_type == "expand_context":
        new_budget.expand_calls += 1
    else:
        new_budget.subqueries += 1
    run.budget = new_budget
    run.attempt = SearchAttempt(
        target_slot_id=plan.target_slot_id,
        search_type=plan.search_type,
        query_ko=tag.query_ko,
        found_new_evidence=bool(run.new_chunk_ids),
    )
    run.ok = True


def execute_search(
    plan: SearchPlan,
    pool: EvidencePool,
    budget: Optional[SearchBudget] = None,
    anchor_evidence_ids: Optional[List[str]] = None,
    search_fn: Optional[SearchFn] = None,
    store: Optional[ChunkStore] = None,
) -> SearchExecutionRun:
    """
    ②의 검색 액션 1개를 실행한다. 실패해도 예외 대신 SearchExecutionRun.error에 이유를 담는다.

    pool은 제자리에서 갱신된다(성공했을 때만). 예산과 검색 기록은 호출자가 반영한다:
      run.budget  → 다음 바퀴의 예산
      run.attempt → 검색 기록(history)에 추가
    anchor_evidence_ids: expand_context일 때 앞·뒤를 넓힐 기준 청크 ID. 없으면 그 칸의 최고 점수 청크.
    """
    budget = budget or SearchBudget()
    run = SearchExecutionRun(plan=plan, budget=budget.model_copy(), checklist_version=cfg.CHECKLIST_VERSION)
    started = time.perf_counter()
    try:
        _execute(run, plan, pool, budget, anchor_evidence_ids, search_fn, store)
    finally:
        run.latency_ms = int((time.perf_counter() - started) * 1000)
    return run
