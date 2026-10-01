"""Replay expansion planning on saved baseline states, without API/DB access.

This isolates planner overhead; it is NOT an end-to-end speed/accuracy benchmark.
Run: python -m evaluate.replay_expansion_plans results-file.json --output report.json
"""
import argparse
import json
from pathlib import Path

from app.core.single_agent.analysis_schema import QuestionAnalysis
from app.core.single_agent.search_schema import SearchAttempt, SearchBudget
from app.core.single_agent.search_planner import check_budget, count_attempts, plan_search, rank_candidates, slot_attempt_limit


class NoLLM:
    calls = 0

    @property
    def chat(self):
        self.calls += 1
        raise AssertionError("Unexpected LLM call in expansion replay")


def replay(data):
    rows = []
    for item in data["items"]:
        run = item["run"]
        cursor = 0
        for i, old in enumerate(run["plan_runs"]):
            plan = old.get("plan")
            if not plan or plan["action"] != "search":
                continue
            pos = next((j for j in range(cursor, len(run["search_runs"]))
                        if run["search_runs"][j]["plan"] == plan), None)
            if pos is None:
                continue
            cursor = pos + 1
            if plan["search_type"] != "expand_context":
                continue
            before = [s for s in run["search_runs"][:pos] if s["ok"]]
            budget = SearchBudget.model_validate(before[-1]["budget"]) if before else SearchBudget()
            history = [SearchAttempt.model_validate(s["attempt"]) for s in before]
            state = run["analysis_run"]["analysis"] if i == 0 else run["verify_runs"][i - 1]["analysis"]
            analysis = QuestionAnalysis.model_validate(state)
            eligible = [(s, kind) for s, kind in rank_candidates(analysis.document_slots)
                        if not check_budget(budget, kind) and count_attempts(history, s.slot_id, kind) < slot_attempt_limit(kind)]
            # A preceding new-search query/duplicate response cannot be replayed without its raw output.
            if not eligible or (eligible[0][0].slot_id, eligible[0][1]) != (plan["target_slot_id"], "expand_context"):
                rows.append({"id": item["label"], "round": i + 1, "skipped": "preceding query-dependent candidate"})
                continue
            client = NoLLM()
            new = plan_search(analysis, budget, history, model="offline", client=client)
            assert client.calls == 0 and new.attempts == 0
            assert new.plan.target_slot_id == plan["target_slot_id"] and new.plan.search_type == "expand_context"
            rows.append({"id": item["label"], "round": i + 1, "target": plan["target_slot_id"],
                         "same_target_and_operation": True, "after_sdk_calls": 0,
                         "before_sdk_calls": len(old.get("calls", [])),
                         "before_recorded_tokens": old.get("prompt_tokens", 0) + old.get("completion_tokens", 0),
                         "before_planning_ms": old["latency_ms"]})
    checked = [r for r in rows if "skipped" not in r]
    return {"scope": "fixed-state expansion planning only; retrieval equivalence covered by offline tests",
            "rows": rows, "replayed": len(checked), "skipped": len(rows) - len(checked),
            "removed_sdk_calls": sum(r["before_sdk_calls"] for r in checked),
            "removed_recorded_tokens": sum(r["before_recorded_tokens"] for r in checked),
            "baseline_planning_ms": sum(r["before_planning_ms"] for r in checked)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = replay(json.loads(args.baseline.read_text(encoding="utf-8")))
    result["baseline"] = args.baseline.name
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
