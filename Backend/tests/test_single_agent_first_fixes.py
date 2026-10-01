"""Regression cases for the first two behavior changes, with no live services."""
import pytest

from app.core.single_agent.analysis_schema import Condition, DocSlot, EvidenceRef, QuestionAnalysis
from app.core.single_agent.evidence_schema import EvidenceChunk, EvidencePool
from app.core.single_agent.search_schema import SearchAttempt, SearchBudget, SearchPlan
from app.core.single_agent.search_planner import _build_query_user_prompt, plan_search, rank_candidates
from app.core.single_agent.searcher import execute_search
from app.core.single_agent.verifier import decide
from evaluate.check_search_execution import FakeStore


def analysis(slots):
    return QuestionAnalysis(intent_summary="허용 조건", answer_scope="general", primary_type="T1",
                            next_action="search", document_slots=slots)


class NoLLM:
    @property
    def chat(self):
        raise AssertionError("Expansion must not call an LLM")


def test_expansion_plan_uses_no_llm_and_preserves_neighbors_and_budget():
    slot = DocSlot(slot_id="rule", active=True, requirement="required", status="partial")
    history = [SearchAttempt(target_slot_id="rule", search_type="new", query_ko="허용 조건")]
    budget = SearchBudget(total_calls=1, subqueries=1)
    plan_run = plan_search(analysis([slot]), budget, history, model="fake", client=NoLLM())
    assert plan_run.attempts == 0 and not plan_run.calls
    assert plan_run.plan.query_ko == "허용 조건"  # existing query may be reused for logging
    assert plan_run.plan.search_type == "expand_context"
    eid = "d.pdf#p1#c1"
    def pool():
        return EvidencePool(chunks={eid: EvidenceChunk(evidence_id=eid, source="d.pdf", page=1,
                                                       chunk_index=1, text="anchor")})
    store = FakeStore({"d.pdf": {1: ["before", "anchor", "after"]}})
    old = SearchPlan(action="search", target_slot_id="rule", search_type="expand_context",
                     query_ko="LLM-generated alternative wording")
    before = execute_search(old, pool(), budget, [eid], store=store)
    after = execute_search(plan_run.plan, pool(), budget, [eid], store=store)
    assert before.chunk_ids == after.chunk_ids == ["d.pdf#p1#c0", "d.pdf#p1#c2"]
    assert before.budget == after.budget == SearchBudget(total_calls=2, subqueries=1, expand_calls=1)


@pytest.mark.parametrize("sid", ["reference_time", "variation_notes", "extra_info"])
@pytest.mark.parametrize("status", ["unchecked", "missing", "partial"])
def test_required_auxiliary_slot_cannot_be_ignored_by_early_stop(sid, status):
    refs = [EvidenceRef(evidence_id="d.pdf#p1#c0", quote="supported value")]
    slots = [DocSlot(slot_id=s, active=True, requirement="required", status="supported", evidence_refs=refs)
             for s in ("requested_value", "applicable_scope")]
    slots.append(DocSlot(slot_id=sid, active=True, requirement="required", status=status,
                         activation_reason="사용자가 명시적으로 요구함",
                         evidence_refs=refs if status == "partial" else []))
    decision = decide(analysis(slots), SearchBudget(), [])
    assert decision.next_action == "continue_search"
    assert sid in decision.unresolved_slot_ids
    exhausted = decide(analysis(slots), SearchBudget(total_calls=6), [])
    assert exhausted.next_action == "partial_answer" and sid in exhausted.unresolved_slot_ids


def test_non_required_auxiliary_slot_still_allows_early_stop():
    refs = [EvidenceRef(evidence_id="d.pdf#p1#c0", quote="supported value")]
    slots = [DocSlot(slot_id=s, active=True, requirement="required", status="supported", evidence_refs=refs)
             for s in ("requested_value", "applicable_scope")]
    slots.append(DocSlot(slot_id="reference_time", active=True, requirement="conditional",
                         activation_state="unresolved", status="missing"))
    assert decide(analysis(slots), SearchBudget(), []).next_action == "answer"


@pytest.mark.parametrize("missing_kind", ["different_section", "scope_gap", "conflict"])
def test_partial_needing_another_section_switches_to_new_search(missing_kind):
    slot = DocSlot(slot_id="rule", active=True, requirement="required", status="partial",
                   missing_kind=missing_kind, missing_detail="다른 조항의 승인 주체가 필요")
    assert rank_candidates([slot])[0][1] == "new"


def test_partial_continuation_still_expands_context():
    slot = DocSlot(slot_id="rule", active=True, requirement="required", status="partial",
                   missing_kind="continuation", missing_detail="표가 다음 청크로 이어짐")
    assert rank_candidates([slot])[0][1] == "expand_context"


def test_new_search_prompt_includes_current_value_and_missing_detail():
    slot = DocSlot(slot_id="conditions_limits", active=True, requirement="required", status="partial",
                   value="방학 중 허용", missing_detail="법무부 승인 주체가 빠짐",
                   missing_kind="different_section")
    prompt = _build_query_user_prompt(
        "GKS 시간제 취업 조건", [Condition(field_id="gks_status", value="예",
        subject="question_target", source_message_id="m1", quote="GKS")],
        slot, "new", [], [],
    )
    assert "방학 중 허용" in prompt
    assert "법무부 승인 주체가 빠짐" in prompt
    assert "different_section" in prompt


def test_completed_expansion_is_skipped_for_another_candidate():
    first = DocSlot(slot_id="rule", active=True, requirement="required", status="partial",
                    missing_kind="continuation")
    second = DocSlot(slot_id="applicable_scope", active=True, requirement="required", status="partial",
                     missing_kind="continuation")
    history = [SearchAttempt(target_slot_id="rule", search_type="new", query_ko="허용 조건")]
    anchors = {"rule": ["d.pdf#p1#c1"], "applicable_scope": ["d.pdf#p3#c1"]}
    completed = {(("d.pdf#p1#c1",), 1)}
    run = plan_search(analysis([first, second]), SearchBudget(total_calls=1, subqueries=1), history,
                      model="fake", client=NoLLM(), anchors_by_slot=anchors,
                      completed_expansions=completed)
    assert run.plan.target_slot_id == "applicable_scope"
    assert run.plan.search_type == "expand_context"
    assert any("동일 앵커" in w for w in run.warnings)
