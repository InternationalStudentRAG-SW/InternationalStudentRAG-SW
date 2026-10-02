"""
② 검색 계획 확인 스크립트.

기본 동작(--live 없이)은 API 호출이 전혀 없다. search_plan_scenarios.py의
가짜(mock) 체크리스트 상태를 가짜 LLM(FakeClient)과 함께 plan_search()에 넣어
슬롯 선택·예산·칸별 상한·첫 검색 재사용·중복 차단이 기대대로 동작하는지 확인한다.

--live를 주면 시나리오 중 하나를 골라 실제 OpenAI로 plan_search()를 끝까지
돌려서 LLM이 만든 검색어 문구도 눈으로 볼 수 있다.

사용법 (Backend 폴더에서)
  python -m evaluate.check_search_plan                 # 전체 시나리오 (API 호출 없음)
  python -m evaluate.check_search_plan --only P02,B04   # 일부만
  python -m evaluate.check_search_plan --live P01       # P01을 실제 LLM으로 끝까지
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional

from app.core.single_agent.analysis_schema import Condition, DocSlot, FirstSearch, QuestionAnalysis
from app.core.single_agent.search_planner import plan_search
from app.core.single_agent.search_schema import SearchAttempt, SearchBudget
from evaluate.search_plan_scenarios import SCENARIOS


class FakeClient:
    """OpenAI 클라이언트 흉내. 정해 둔 검색어를 차례로 JSON으로 돌려준다."""

    def __init__(self, queries: Optional[List[str]] = None):
        self._queries = list(queries or [])
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        q = self._queries.pop(0) if self._queries else f"가짜 검색어 {self.calls}"
        content = json.dumps({"query_ko": q, "reason": "가짜 LLM"}, ensure_ascii=False)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None)


def build_inputs(scenario: Dict):
    fs = scenario.get("first_search")
    analysis = QuestionAnalysis(
        intent_summary="GKS 장학생의 아르바이트 허용 여부 확인 (검색 계획 테스트용 가상 질문)",
        answer_scope="general",
        primary_type="T5",
        conditions=[Condition(
            field_id="gks_status", value="예", subject="question_target",
            source_message_id="m1", quote="GKS 장학생은",
        )],
        document_slots=[DocSlot(**s) for s in scenario["document_slots"]],
        first_search=FirstSearch(**fs) if fs else None,
        next_action="search",
    )
    budget = SearchBudget(**scenario.get("budget", {}))
    history = [SearchAttempt(**h) for h in scenario.get("history", [])]
    return analysis, budget, history


def run_scenario(scenario: Dict) -> Dict:
    analysis, budget, history = build_inputs(scenario)
    fake = FakeClient(scenario.get("fake_queries"))
    run = plan_search(analysis, budget=budget, history=history, model="fake", client=fake)
    p = run.plan
    got = {
        "action": p.action if p else None,
        "target_slot_id": p.target_slot_id if p else None,
        "search_type": p.search_type if p else None,
        "query_ko": p.query_ko if p else None,
        "from_first_search": p.from_first_search if p else None,
        "exhausted_slot_ids": p.exhausted_slot_ids if p else None,
        "llm_calls": fake.calls,
    }

    checks = []
    for key, want in scenario["expect"].items():
        if key == "slot_statuses":  # 적은 칸만 검사. 상한에 걸려도 status가 그대로인지 확인
            actual = {s.slot_id: s.status for s in analysis.document_slots}
            ok = all(actual.get(k) == v for k, v in want.items())
            checks.append({"ok": ok, "message": f"slot_statuses {want!r} (실제 {actual!r})"})
            continue
        checks.append({"ok": got.get(key) == want, "message": f"{key} {want!r} (실제 {got.get(key)!r})"})
    if run.error:
        checks.append({"ok": False, "message": f"오류 없음 (실제 {run.error})"})

    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "passed": all(c["ok"] for c in checks),
        "checks": checks,
        "got": got,
        "skipped": p.skipped if p else [],
        "warnings": run.warnings,
    }


def print_result(r: Dict, verbose: bool = False) -> None:
    mark = "✅" if r["passed"] else "❌"
    print(f"{mark} [{r['id']}] {r['title']}")
    for c in r["checks"]:
        cm = "  ✓" if c["ok"] else "  ✗"
        print(f"{cm} {c['message']}")
    if verbose or not r["passed"]:
        for s in r["skipped"]:
            print(f"    · 건너뜀: {s}")
        for w in r["warnings"]:
            print(f"    · 경고: {w}")
    print()


def run_live(scenario_id: str, model: Optional[str]) -> None:
    scenario = next((s for s in SCENARIOS if s["id"] == scenario_id), None)
    if scenario is None:
        print(f"시나리오 {scenario_id}를 찾을 수 없음")
        return

    analysis, budget, history = build_inputs(scenario)
    run = plan_search(analysis, budget=budget, history=history, model=model)

    print(f"=== [{scenario['id']}] {scenario['title']} (실제 LLM 호출) ===")
    print(f"모델: {run.model} | 지연: {run.latency_ms}ms | LLM 호출: {run.attempts}회")
    if run.error:
        print(f"오류: {run.error}")
    if run.plan:
        print(json.dumps(run.plan.model_dump(), ensure_ascii=False, indent=2))
    if run.warnings:
        print("경고:")
        for w in run.warnings:
            print(f"  - {w}")


def main() -> None:
    ap = argparse.ArgumentParser(description="② 검색 계획 확인 스크립트")
    ap.add_argument("--only", help="쉼표로 구분한 시나리오 ID만 실행 (예: P02,B04)")
    ap.add_argument("--live", metavar="SCENARIO_ID", help="해당 시나리오를 실제 LLM으로 끝까지 실행")
    ap.add_argument("--model", default=None, help="--live일 때 쓸 모델 (기본: settings.openai_model)")
    ap.add_argument("-v", "--verbose", action="store_true", help="통과한 시나리오도 건너뜀·경고 출력")
    ap.add_argument("--save", action="store_true", help="결과를 evaluate/results/에 JSON으로 저장")
    args = ap.parse_args()

    if args.live:
        run_live(args.live, args.model)
        return

    scenarios = SCENARIOS
    if args.only:
        ids = {s.strip() for s in args.only.split(",")}
        scenarios = [s for s in scenarios if s["id"] in ids]

    results = [run_scenario(s) for s in scenarios]
    for r in results:
        print_result(r, args.verbose)

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"--- {passed}/{total} 통과 (가짜 LLM, API 호출 없음) ---")

    if args.save:
        out_dir = Path(__file__).parent / "results"
        out_dir.mkdir(exist_ok=True)
        fname = out_dir / f"search_plan_scenarios_{datetime.now():%Y%m%d_%H%M%S}.json"
        fname.write_text(
            json.dumps({"passed": passed, "total": total, "results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"저장: {fname}")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
