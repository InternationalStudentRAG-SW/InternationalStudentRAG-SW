"""Offline audit reproductions; no API, model loading, or database access.

Run from Backend: .venv/Scripts/python.exe -m evaluate.audit_single_agent_offline
Historical findings are retained; repaired findings now assert the corrected behavior.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.core.single_agent.analysis_schema import DocSlot, EvidenceRef, QuestionAnalysis
from app.core.single_agent.answerer import _clean_markers
from app.core.single_agent.evidence_schema import EvidenceChunk, EvidencePool
from app.core.single_agent.search_planner import _build_query_user_prompt, rank_candidates
from app.core.single_agent.search_schema import SearchBudget, SearchPlanRun
from app.core.single_agent.searcher import _collect_neighbors
from app.core.single_agent.verifier import apply_verdicts, decide, find_uncited_relevant, judge_targets
from app.core.single_agent.verify_schema import ChunkNote, SlotVerdict
from evaluate.check_search_execution import FakeStore


def main():
    findings = {}
    # Missing detail is the verifier's feedback, but the query builder never reads it.
    slot = DocSlot(slot_id="conditions_limits", active=True, requirement="required", status="partial",
                   missing_detail="Missing the approval authority")
    def prompt(s):
        return _build_query_user_prompt("Part-time work", [], s, "new", [], [])
    changed = slot.model_copy(update={"missing_detail": "Missing the maximum weekly hours"})
    assert prompt(slot) == prompt(changed)
    findings["missing_detail_does_not_change_query_prompt"] = True
    assert rank_candidates([slot])[0][1] == "expand_context"
    findings["partial_always_selects_expansion"] = True

    # Same anchor + fixed window repeats exactly the same neighbors.
    store = FakeStore({"d.pdf": {1: ["before", "anchor", "after", "unreached"]}})
    first = _collect_neighbors(store, [("d.pdf", 1, 1)])
    second = _collect_neighbors(store, [("d.pdf", 1, 1)])
    assert [c.evidence_id for c in first] == [c.evidence_id for c in second]
    findings["repeated_expansion_ids"] = [c.evidence_id for c in second]

    eid = "d.pdf#p1#c0"
    pool = EvidencePool(chunks={eid: EvidenceChunk(evidence_id=eid, source="d.pdf", page=1,
                                                 chunk_index=0, text="Tuition is 100 units.")})
    core = [DocSlot(slot_id=s, active=True, requirement="required", status="supported",
                    evidence_refs=[EvidenceRef(evidence_id=eid, quote="Tuition is 100 units.")])
            for s in ("requested_value", "applicable_scope")]
    analysis = QuestionAnalysis(intent_summary="Amount AND effective year", answer_scope="general",
                                primary_type="T1", next_action="search", document_slots=core + [
                                    DocSlot(slot_id="reference_time", active=True, requirement="required",
                                            status="missing", activation_reason="User explicitly asks year")])
    decision = decide(analysis, SearchBudget(), [])
    assert decision.next_action == "continue_search" and "reference_time" in decision.unresolved_slot_ids
    findings["fixed_explicit_required_year_preserved"] = decision.model_dump()
    assert "requested_value" not in [s.slot_id for s in judge_targets(analysis)]
    findings["supported_slot_not_rejudged_when_new_evidence_arrives"] = True

    # Exact quotation validation is not entailment validation.
    target = DocSlot(slot_id="requested_value", active=True, requirement="required")
    verdict = SlotVerdict(slot_id="requested_value", status="supported", value="Tuition is 999 units.",
                          evidence_refs=[EvidenceRef(evidence_id=eid, quote="Tuition is 100 units.")])
    apply_verdicts({target.slot_id: target}, [verdict], {eid}, pool, {target.slot_id}, [])
    assert target.status == "supported" and target.value == "Tuition is 999 units."
    findings["quote_exists_but_contradictory_value_accepted"] = target.model_dump()
    text, sources = _clean_markers("Tuition is 999 units [1]. Invented fact [99].", [eid], pool, [])
    assert "999" in text and "Invented fact" in text and "[99]" not in text and sources
    findings["citation_cleanup_keeps_unsupported_claims"] = text

    # Merely duplicated evidence creates a recheck request.
    notes = {eid: ChunkNote(evidence_id=eid, relevant_slots=[target.slot_id]),
             "copy.pdf#p1#c0": ChunkNote(evidence_id="copy.pdf#p1#c0", relevant_slots=[target.slot_id])}
    assert find_uncited_relevant({target.slot_id: target}, notes)
    findings["uncited_duplicate_triggers_recheck"] = True
    assert "prompt_tokens" in SearchPlanRun.model_fields
    findings["fixed_plan_tokens_recorded"] = True

    results = Path(__file__).parent / "results"
    latest = json.loads((results / "pipeline_20260930_210415.json").read_text(encoding="utf-8"))["items"][0]
    findings["latest_saved_pipeline"] = latest["summary"]
    findings["latest_stage_tokens"] = {
        stage: {k: latest["run"][name][k] for k in ("prompt_tokens", "completion_tokens")}
        for stage, name in (("analyze", "analysis_run"), ("answer", "answer_run"))}
    findings["latest_stage_tokens"]["verify"] = {
        k: sum(v[k] for v in latest["run"]["verify_runs"])
        for k in ("prompt_tokens", "completion_tokens")}
    verification = json.loads((results / "verification_dev_20260930_211340.json").read_text(encoding="utf-8"))["rows"]
    findings["saved_verification_rechecks"] = {
        "cases": len(verification), "rechecked_cases": sum(bool(r["run"]["recheck_slot_ids"]) for r in verification),
        "calls": sum(r["run"]["attempts"] for r in verification),
        "tokens": sum(r["tokens"] for r in verification)}
    comparison = json.loads((results / "compare_20260930_212934.json").read_text(encoding="utf-8"))
    findings["comparison_baseline_missing_search_ms"] = all(
        "search_ms" not in r["results"]["baseline"] for r in comparison["rows"])
    # An earlier saved trace demonstrates wasted verification even with no new chunks.
    old = json.loads((results / "pipeline_20260929_220240.json").read_text(encoding="utf-8"))["items"]
    d6 = next(x["run"] for x in old if x["label"] == "D6")
    findings["saved_d6_last_expansion"] = {
        "new_chunks": len(d6["search_runs"][-1]["new_chunk_ids"]),
        "subsequent_verify_ms": d6["verify_runs"][-1]["latency_ms"],
        "subsequent_verify_tokens": sum(d6["verify_runs"][-1][k] for k in ("prompt_tokens", "completion_tokens")),
        "search_budget": d6["budget"]}
    print(json.dumps(findings, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
