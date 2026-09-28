"""
② 검색 계획 확인 스크립트.

기본 동작(--live 없이)은 API 호출이 전혀 없다. search_plan_scenarios.py의
가짜(mock) 체크리스트 상태를 select_target_slot()·check_budget()에 넣어
규칙 기반 슬롯 선택이 기대대로 동작하는지만 확인한다.

--live를 주면 시나리오 중 하나를 골라 실제 OpenAI로 plan_search()를 끝까지
돌려서 LLM이 만든 검색어 문구도 눈으로 볼 수 있다.

사용법 (Backend 폴더에서)
  python -m evaluate.check_search_plan                 # 전체 규칙 기반 시나리오
  python -m evaluate.check_search_plan --only P02,B02   # 일부만
  python -m evaluate.check_search_plan --live P01       # P01을 실제 LLM으로 끝까지
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.core.single_agent.analysis_schema import Condition, DocSlot, QuestionAnalysis
from app.core.single_agent.search_planner import check_budget, plan_search, select_target_slot
from app.core.single_agent.search_schema import SearchBudget
from evaluate.search_plan_scenarios import SCENARIOS


def _slots(raw: List[Dict]) -> List[DocSlot]:
    return [DocSlot(**s) for s in raw]


def run_rule_based(scenario: Dict) -> Dict:
    slots = _slots(scenario["document_slots"])
    slot, search_type = select_target_slot(slots)
    expect = scenario["expect"]

    checks = []
    got_id = slot.slot_id if slot else None
    ok = got_id == expect["target_slot_id"]
    checks.append({
        "ok": ok,
        "message": f"대상 칸 {expect['target_slot_id']!r} (실제 {got_id!r})",
    })
    if expect.get("target_slot_id") is not None:
        ok2 = search_type == expect.get("search_type")
        checks.append({
            "ok": ok2,
            "message": f"검색 종류 {expect.get('search_type')!r} (실제 {search_type!r})",
        })

    budget_note = None
    if "budget" in scenario and slot is not None:
        budget = SearchBudget(**scenario["budget"])
        msg = check_budget(budget, search_type)
        expect_action = expect.get("budget_action")
        if expect_action == "budget_exhausted":
            ok3 = msg is not None
            checks.append({"ok": ok3, "message": f"예산 한도 초과 감지 (실제: {msg!r})"})
        budget_note = msg

    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "passed": all(c["ok"] for c in checks),
        "checks": checks,
        "selected": {"target_slot_id": got_id, "search_type": search_type},
        "budget_block_reason": budget_note,
    }


def print_result(r: Dict) -> None:
    mark = "✅" if r["passed"] else "❌"
    print(f"{mark} [{r['id']}] {r['title']}")
    for c in r["checks"]:
        cm = "  ✓" if c["ok"] else "  ✗"
        print(f"{cm} {c['message']}")
    print()


def run_live(scenario_id: str, model: Optional[str]) -> None:
    scenario = next((s for s in SCENARIOS if s["id"] == scenario_id), None)
    if scenario is None:
        print(f"시나리오 {scenario_id}를 찾을 수 없음")
        return

    slots = _slots(scenario["document_slots"])
    analysis = QuestionAnalysis(
        intent_summary="GKS 장학생의 아르바이트 허용 여부 확인 (검색 계획 테스트용 가상 질문)",
        answer_scope="general",
        primary_type="T5",
        conditions=[Condition(
            field_id="gks_status", value="예", subject="question_target",
            source_message_id="m1", quote="GKS 장학생은",
        )],
        document_slots=slots,
        next_action="search",
    )
    budget = SearchBudget(**scenario.get("budget", {}))
    run = plan_search(analysis, budget=budget, model=model)

    print(f"=== [{scenario['id']}] {scenario['title']} (실제 LLM 호출) ===")
    print(f"모델: {run.model} | 지연: {run.latency_ms}ms | 시도: {run.attempts}회")
    if run.error:
        print(f"오류: {run.error}")
    if run.plan:
        p = run.plan
        print(f"action: {p.action}")
        print(f"target_slot_id: {p.target_slot_id}")
        print(f"search_type: {p.search_type}")
        print(f"query_ko: {p.query_ko}")
        print(f"reason: {p.reason}")
        print(f"is_duplicate: {p.is_duplicate}")
    if run.warnings:
        print("경고:")
        for w in run.warnings:
            print(f"  - {w}")


def main() -> None:
    ap = argparse.ArgumentParser(description="② 검색 계획 확인 스크립트")
    ap.add_argument("--only", help="쉼표로 구분한 시나리오 ID만 실행 (예: P02,B02)")
    ap.add_argument("--live", metavar="SCENARIO_ID", help="해당 시나리오를 실제 LLM으로 끝까지 실행")
    ap.add_argument("--model", default=None, help="--live일 때 쓸 모델 (기본: settings.openai_model)")
    ap.add_argument("--save", action="store_true", help="결과를 evaluate/results/에 JSON으로 저장")
    args = ap.parse_args()

    if args.live:
        run_live(args.live, args.model)
        return

    scenarios = SCENARIOS
    if args.only:
        ids = {s.strip() for s in args.only.split(",")}
        scenarios = [s for s in scenarios if s["id"] in ids]

    results = [run_rule_based(s) for s in scenarios]
    for r in results:
        print_result(r)

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"--- {passed}/{total} 통과 (규칙 기반, API 호출 없음) ---")

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
