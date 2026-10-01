"""Incremental verification and narrow recheck regressions (no live services)."""
from app.core.single_agent.analysis_schema import DocSlot, EvidenceRef, QuestionAnalysis
from app.core.single_agent.evidence_schema import EvidenceChunk, EvidencePool, RetrievalTag
from app.core.single_agent.search_schema import SearchAttempt, SearchBudget
from app.core.single_agent.verifier import RECHECK_SYSTEM_PROMPT, build_recheck_prompt, select_chunks, verify_evidence
from app.core.single_agent.verify_schema import SlotVerdict, VerificationRun, VerifyDecision
from evaluate.check_verification import FakeClient


def _analysis(slots):
    return QuestionAnalysis(intent_summary="GKS 시간제 취업", answer_scope="general", primary_type="T5",
                            next_action="search", document_slots=slots)


def _pool(*items):
    pool = EvidencePool()
    for eid, text in items:
        source, rest = eid.split("#p", 1)
        page, idx = rest.split("#c", 1)
        pool.add(EvidenceChunk(evidence_id=eid, source=source, page=int(page), chunk_index=int(idx), text=text),
                 RetrievalTag(target_slot_id="rule", search_type="new", query_ko="q"))
    return pool


def test_delta_chunk_selection_keeps_only_new_and_target_refs():
    old = "d.pdf#p1#c0"
    new = "d.pdf#p1#c1"
    unrelated = "d.pdf#p1#c2"
    rest = "d.pdf#p1#c3"
    slots = [
        DocSlot(slot_id="rule", active=True, requirement="required", status="partial",
                evidence_refs=[EvidenceRef(evidence_id=old, quote="old rule")]),
        DocSlot(slot_id="applicable_scope", active=True, requirement="required", status="partial",
                evidence_refs=[EvidenceRef(evidence_id=unrelated, quote="other scope")]),
    ]
    pool = _pool((old, "old rule"), (new, "new rule"), (unrelated, "other scope"), (rest, "rest"))
    shown = select_chunks(_analysis(slots), pool, [new, rest], target_slot_ids={"rule"},
                          new_chunk_ids=[new], previously_shown={rest})
    assert shown == [new, old]


def test_slot_verdict_treats_null_optional_text_as_empty():
    verdict = SlotVerdict(slot_id="rule", status="supported", value=None,
                          missing_detail=None, reason=None)
    assert verdict.value == verdict.missing_detail == verdict.reason == ""


def test_same_slot_state_and_uncited_chunk_is_not_rechecked_twice():
    cited = "d.pdf#p1#c0"
    omitted = "d.pdf#p1#c1"
    pool = _pool((cited, "Existing condition text"), (omitted, "Additional related text"))
    a = _analysis([DocSlot(slot_id="rule", active=True, requirement="required")])
    history = [SearchAttempt(target_slot_id="rule", search_type="new", query_ko="q", found_new_evidence=True)]
    main = {
        "chunk_notes": [
            {"evidence_id": cited, "relevant_slots": ["rule"]},
            {"evidence_id": omitted, "relevant_slots": ["rule"]},
        ],
        "slot_verdicts": [{"slot_id": "rule", "status": "partial", "missing_kind": "different_section",
                            "missing_detail": "추가 조건 필요",
                            "evidence_refs": [{"evidence_id": cited, "quote": "Existing condition text"}]}],
    }
    recheck = {"slot_verdicts": [{"slot_id": "rule", "status": "partial",
                                   "missing_kind": "different_section", "missing_detail": "추가 조건 필요",
                                   "evidence_refs": [{"evidence_id": cited, "quote": "Existing condition text"}]}]}
    first_client = FakeClient([main, recheck])
    first = verify_evidence(a, pool, SearchBudget(), history, model="fake", client=first_client)
    assert first_client.calls == 2 and first.recheck_keys

    second_client = FakeClient(main)
    second = verify_evidence(first.analysis, pool, SearchBudget(), history, prior_runs=[first],
                             model="fake", client=second_client)
    assert second_client.calls == 1
    assert not second.recheck_slot_ids
    assert any("재확인 생략" in w for w in second.warnings)


def test_recheck_prompt_contains_only_current_refs_and_flagged_chunks():
    current = "d.pdf#p1#c0"
    flagged = "d.pdf#p1#c1"
    unrelated = "d.pdf#p1#c2"
    pool = _pool((current, "CURRENT TEXT"), (flagged, "FLAGGED TEXT"), (unrelated, "UNRELATED TEXT"))
    slot = DocSlot(slot_id="rule", active=True, requirement="required", status="partial", value="current",
                   evidence_refs=[EvidenceRef(evidence_id=current, quote="CURRENT TEXT")])
    a = _analysis([slot])
    prompt = build_recheck_prompt({"rule": [flagged]}, {"rule": slot}, pool, a, "질문")
    assert "CURRENT TEXT" in prompt and "FLAGGED TEXT" in prompt
    assert "UNRELATED TEXT" not in prompt
    assert '"evidence_id"' in RECHECK_SYSTEM_PROMPT and '"status"' in RECHECK_SYSTEM_PROMPT
    assert "reference, source, page" in RECHECK_SYSTEM_PROMPT


def test_new_conflict_signal_reopens_supported_slot_only():
    old = "d.pdf#p1#c0"
    new = "d.pdf#p1#c1"
    pool = _pool((old, "Allowed up to 20 hours"), (new, "Allowed up to 10 hours"))
    rule = DocSlot(slot_id="rule", active=True, requirement="required", status="supported", value="주 20시간",
                   evidence_refs=[EvidenceRef(evidence_id=old, quote="Allowed up to 20 hours")])
    scope = DocSlot(slot_id="applicable_scope", active=True, requirement="required", status="unchecked")
    a = _analysis([rule, scope])
    prior = VerificationRun(decision=VerifyDecision(next_action="continue_search"), shown_chunk_ids=[old])
    main = {
        "chunk_notes": [{"evidence_id": new, "relevant_slots": [],
                         "conflicting_slots": ["rule"]}],
        "slot_verdicts": [{"slot_id": "applicable_scope", "status": "missing", "missing_kind": "scope_gap"}],
    }
    recheck = {
        "slot_verdicts": [{"slot_id": "rule", "status": "conflicting", "missing_kind": "conflict",
                            "missing_detail": "시간 한도가 서로 다름",
                            "evidence_refs": [{"evidence_id": new, "quote": "Allowed up to 10 hours"}]}]
    }
    client = FakeClient([main, recheck])
    run = verify_evidence(
        a, pool, SearchBudget(),
        [SearchAttempt(target_slot_id="applicable_scope", search_type="new", query_ko="q",
                       found_new_evidence=True)],
        round_chunk_ids=[new], round_new_chunk_ids=[new], prior_runs=[prior],
        model="fake", client=client,
    )
    updated = {s.slot_id: s for s in run.analysis.document_slots}
    assert client.calls == 2 and run.recheck_slot_ids == ["rule"]
    assert updated["rule"].status == "conflicting"
    assert updated["rule"].missing_kind == "conflict"
    assert {r.evidence_id for r in updated["rule"].evidence_refs} == {old, new}
