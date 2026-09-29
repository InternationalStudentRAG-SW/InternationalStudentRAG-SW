"""
③ 근거 검색 확인 스크립트.

기본 동작(--live 없이)은 API·DB 호출이 전혀 없다. search_exec_scenarios.py의 시나리오를
가짜 검색 함수(FakeSearch)·가짜 청크 저장소(FakeStore)와 함께 execute_search()에 넣어
풀 누적·새 근거 판정·예산 갱신·오류 처리·앞뒤 청크 확장이 기대대로 동작하는지 확인한다.

--live "질문"을 주면 실제 OpenAI(①)와 실제 retriever/ChromaDB(③)로 한 바퀴를 끝까지 돌려서
어떤 청크가 나오는지 눈으로 볼 수 있다. ①→②→③ 순서이고, 첫 바퀴의 ②는 ①의 first_search를
그대로 쓰므로 LLM을 더 부르지 않는다. 기본으로 1순위 청크를 앵커 삼아 원문 확장도 한 번 해 본다.
(Backend/.env의 OPENAI_API_KEY와 ChromaDB가 필요하다. 질문 1개당 LLM 1~2회, reranker 모델 로드 포함)

사용법 (Backend 폴더에서)
  python -m evaluate.check_search_execution                       # 전체 시나리오 (API·DB 없음)
  python -m evaluate.check_search_execution --only E01,X02         # 일부만
  python -m evaluate.check_search_execution --live "GKS 장학생은 아르바이트할 수 있어?"
  python -m evaluate.check_search_execution --live "..." --no-expand   # 원문 확장 생략
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from app.core.single_agent.evidence_schema import EvidenceChunk, EvidencePool, RetrievalTag, parse_evidence_id
from app.core.single_agent.search_schema import SearchBudget, SearchPlan
from app.core.single_agent.searcher import execute_search
from evaluate.search_exec_scenarios import SCENARIOS


class FakeSearch:
    """검색 함수 흉내. 정해 둔 결과를 돌려주고, 부른 기록을 남긴다."""

    def __init__(self, results: Optional[List[Dict]] = None, fail_times: Any = 0):
        self.results = list(results or [])
        self.fail_times = fail_times
        self.calls: List[tuple] = []

    def __call__(self, query: str, k: int):
        self.calls.append((query, k))
        if self.fail_times == "always" or (isinstance(self.fail_times, int) and len(self.calls) <= self.fail_times):
            raise RuntimeError("검색기 오류(가짜)")
        docs = []
        for r in self.results:
            meta = {key: r[key] for key in ("source", "page", "chunk_index", "lang") if key in r}
            if "score" in r:
                meta["similarity_score"] = r["score"]
            docs.append(SimpleNamespace(page_content=r.get("text", ""), metadata=meta))
        return docs


class FakeStore:
    """청크 저장소 흉내. pages = {source: {page: [청크 본문, ...]}} (리스트 순서가 chunk_index)."""

    def __init__(self, pages: Optional[Dict[str, Dict[int, List[str]]]] = None, error: bool = False):
        self.pages = pages or {}
        self.error = error

    def get_chunk(self, source: str, page: int, chunk_index: int) -> Optional[EvidenceChunk]:
        if self.error:
            raise RuntimeError("저장소 오류(가짜)")
        texts = self.pages.get(source, {}).get(page)
        if not texts or not (0 <= chunk_index < len(texts)):
            return None
        return EvidenceChunk(
            evidence_id=f"{source}#p{page}#c{chunk_index}", source=source, page=page,
            chunk_index=chunk_index, text=texts[chunk_index],
        )

    def last_chunk_index(self, source: str, page: int) -> Optional[int]:
        if self.error:
            raise RuntimeError("저장소 오류(가짜)")
        texts = self.pages.get(source, {}).get(page)
        return len(texts) - 1 if texts else None


def build_pool(scenario: Dict) -> EvidencePool:
    pool = EvidencePool()
    for item in scenario.get("pool", []):
        source, page, idx = parse_evidence_id(item["id"])
        chunk = EvidenceChunk(
            evidence_id=item["id"], source=source, page=page, chunk_index=idx,
            text=item.get("text", "(사전 청크)"), score=item.get("score"),
        )
        for slot in item.get("slots") or ["_seed"]:
            pool.add(chunk, RetrievalTag(target_slot_id=slot, search_type="new", query_ko="(사전)", round_no=1))
    return pool


def run_scenario(scenario: Dict) -> Dict:
    pool = build_pool(scenario)
    plan = SearchPlan(**{"action": "search", **scenario["plan"]})
    budget = SearchBudget(**scenario.get("budget", {}))
    fake_search = FakeSearch(scenario.get("search_results"), scenario.get("search_fail_times", 0))
    fake_store = FakeStore(scenario.get("store_pages"), scenario.get("store_error", False))

    run = execute_search(
        plan, pool, budget,
        anchor_evidence_ids=scenario.get("anchors"),
        search_fn=fake_search, store=fake_store,
    )
    got = {
        "ok": run.ok,
        "error_type": run.error_type,
        "chunk_ids": run.chunk_ids,
        "new_chunk_ids": run.new_chunk_ids,
        "anchor_ids": run.anchor_ids,
        "tool_attempts": run.tool_attempts,
        "found_new_evidence": run.attempt.found_new_evidence if run.attempt else None,
        "pool_size": len(pool),
        "search_calls": len(fake_search.calls),
        "search_k": fake_search.calls[0][1] if fake_search.calls else None,
    }
    budget_now = run.budget.model_dump() if run.budget else {}
    pool_scores = {i: c.score for i, c in pool.chunks.items()}
    warnings_text = "\n".join(run.warnings)

    checks = []
    for key, want in scenario["expect"].items():
        if key == "budget":
            actual = {k: budget_now.get(k) for k in want}
            checks.append({"ok": actual == want, "message": f"budget {want!r} (실제 {actual!r})"})
        elif key == "pool_scores":
            actual = {k: pool_scores.get(k) for k in want}
            checks.append({"ok": actual == want, "message": f"pool_scores {want!r} (실제 {actual!r})"})
        elif key == "warnings_contain":
            phrases = [want] if isinstance(want, str) else list(want)
            missing = [p for p in phrases if p not in warnings_text]
            checks.append({"ok": not missing, "message": f"경고에 {phrases!r} 포함 (없는 것 {missing!r}, 실제 {run.warnings!r})"})
        else:
            checks.append({"ok": got.get(key) == want, "message": f"{key} {want!r} (실제 {got.get(key)!r})"})

    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "passed": all(c["ok"] for c in checks),
        "checks": checks,
        "got": got,
        "warnings": run.warnings,
        "error": run.error,
    }


def print_result(r: Dict) -> None:
    mark = "PASS" if r["passed"] else "FAIL"
    print(f"[{mark}] {r['id']}  {r['title']}")
    if not r["passed"]:
        for c in r["checks"]:
            if not c["ok"]:
                print(f"       ✗ {c['message']}")
        if r["error"]:
            print(f"       (error: {r['error']})")


# ── 실제 데이터로 한 바퀴 (--live) ────────────────────────────────────────────

def _show_chunks(title: str, chunk_ids: List[str], pool: EvidencePool, new_ids: List[str]) -> None:
    print(f"\n{title} ({len(chunk_ids)}개, 새 근거 {len(new_ids)}개)")
    for i, cid in enumerate(chunk_ids, 1):
        ch = pool.get(cid)
        score = f"{ch.score:.3f}" if ch and ch.score is not None else "  -  "
        flag = "NEW" if cid in new_ids else "   "
        preview = (ch.text if ch else "").replace("\n", " ")[:110]
        print(f"  {i:>2}. [{flag}] {cid}  score={score}\n        {preview}")


def collect_round1(
    question: str, expand: bool = True, verbose: bool = True,
    client=None, search_fn=None, store=None, model: Optional[str] = None,
) -> Dict:
    """
    ①→②→③ 첫 바퀴(신규 검색 1회 + 1순위 청크 앞뒤 확장 1회)를 실제로 돌려 기록(dict)을 만든다.
    ①이 검색하지 않는 질문이거나 도중에 실패하면 stopped에 이유를 담고, 그때까지의 기록을 돌려준다.
    기록 형식은 check_verification --live가 그대로 읽는다(question, analysis, plan, runs, pool).
    client/search_fn/store는 테스트용 가짜를 끼울 때만 쓴다.
    """
    from app.core.single_agent.analyzer import analyze_question
    from app.core.single_agent.search_planner import plan_search

    say = print if verbose else (lambda *a, **k: None)
    record: Dict = {"question": question, "analysis": None, "plan": None, "runs": [], "pool": EvidencePool().model_dump(),
                    "stopped": None}
    say(f"질문: {question}\n")
    a_run = analyze_question(question, model=model, client=client)
    if a_run.error or a_run.analysis is None:
        say(f"① 질문 분석 실패: {a_run.error}")
        record["stopped"] = f"analysis_error: {a_run.error}"
        return record
    a = a_run.analysis
    record["analysis"] = a.model_dump()
    say(f"① 질문 분석: 유형 {a.primary_type} {a.additional_types}, 다음 행동 {a.next_action}, 범위 {a.answer_scope}")
    if a.next_action != "search":
        say(f"   → 검색하지 않는 질문이야 (다음 행동: {a.next_action}). {a.clarification_question or ''}")
        record["stopped"] = f"no_search: {a.next_action}"
        return record

    budget, pool, history = SearchBudget(), EvidencePool(), []
    p_run = plan_search(a, budget=budget, history=history, model=model, client=client)
    plan = p_run.plan
    if p_run.error or plan is None or plan.action != "search":
        say(f"② 검색 계획 실패/종료: {p_run.error or (plan.action if plan else None)}")
        record["stopped"] = f"plan: {p_run.error or (plan.action if plan else None)}"
        return record
    record["plan"] = plan.model_dump()
    say(f"② 검색 계획: 칸 {plan.target_slot_id}, {plan.search_type}, 검색어 '{plan.query_ko}' (첫 바퀴 재사용={plan.from_first_search})")

    e1 = execute_search(plan, pool, budget, search_fn=search_fn, store=store)
    runs = [e1]
    if not e1.ok:
        say(f"③ 검색 실행 실패 [{e1.error_type}]: {e1.error}")
        record["stopped"] = f"search: {e1.error_type}"
    else:
        say(f"③ 검색 실행: {e1.latency_ms}ms, 도구 호출 {e1.tool_attempts}회, 예산 {e1.budget.model_dump()}")
        if verbose:
            _show_chunks("신규 검색 결과", e1.chunk_ids, pool, e1.new_chunk_ids)
        if expand and e1.chunk_ids:
            anchor = e1.chunk_ids[0]
            plan2 = SearchPlan(action="search", target_slot_id=plan.target_slot_id, search_type="expand_context",
                               query_ko=plan.query_ko, reason="live 확인: 1순위 청크를 앵커로 앞뒤 확장")
            e2 = execute_search(plan2, pool, e1.budget, anchor_evidence_ids=[anchor], search_fn=search_fn, store=store)
            say(f"\n원문 확장 (앵커 {anchor})")
            if e2.ok and verbose:
                _show_chunks("확장으로 가져온 청크", e2.chunk_ids, pool, e2.new_chunk_ids)
            elif not e2.ok:
                say(f"   실패 [{e2.error_type}]: {e2.error}")
            runs.append(e2)
    for r in runs:
        for w in r.warnings:
            say(f"   경고: {w}")
    record["runs"] = [r.model_dump() for r in runs]
    record["pool"] = pool.model_dump()
    return record


def run_live(question: str, expand: bool = True) -> None:
    record = collect_round1(question, expand=expand)
    if record["analysis"] is None:
        return
    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"search_execution_live_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {out}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔에서 한글이 깨지지 않게
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="③ 근거 검색 확인")
    ap.add_argument("--only", help="쉼표로 구분한 시나리오 ID (예: E01,X02)")
    ap.add_argument("--live", metavar="QUESTION", help="실제 OpenAI·retriever로 ①→②→③ 한 바퀴 실행")
    ap.add_argument("--no-expand", action="store_true", help="--live에서 원문 확장 생략")
    args = ap.parse_args()

    if args.live:
        run_live(args.live, expand=not args.no_expand)
        return 0

    wanted = {s.strip() for s in args.only.split(",")} if args.only else None
    results = [run_scenario(s) for s in SCENARIOS if wanted is None or s["id"] in wanted]
    for r in results:
        print_result(r)
    passed = sum(1 for r in results if r["passed"])
    print(f"\n{passed}/{len(results)} 시나리오 통과")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
