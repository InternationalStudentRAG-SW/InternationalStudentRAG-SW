"""단일 에이전트 ①② 규칙 테스트 (API 호출 없음)."""
from app.core.single_agent.analysis_schema import DocSlot, FirstSearch, QuestionAnalysis
from app.core.single_agent.analyzer import number_messages, validate_analysis
from evaluate.check_search_plan import run_scenario
from evaluate.search_plan_scenarios import SCENARIOS


def test_clarify_scope_passes_validation_with_null_type():
    """[수정 1] clarify_scope + primary_type=null이 형식 오류로 막히지 않는다."""
    a = QuestionAnalysis(
        intent_summary="목적 불명확한 서류 요청",
        answer_scope="general",
        primary_type=None,
        next_action="clarify_scope",
        clarification_question="어떤 것에 필요한 서류인가요?",
    )
    out, warnings = validate_analysis(a, number_messages("서류 알려줘", []))
    assert out.next_action == "clarify_scope"
    assert out.primary_type is None and out.document_slots == [] and out.first_search is None


def test_clarify_scope_clears_guessed_type():
    """clarify_scope인데 유형·칸·첫 검색을 채워 오면 비운다."""
    a = QuestionAnalysis(
        intent_summary="x",
        answer_scope="general",
        primary_type="T3",
        document_slots=[DocSlot(slot_id="requested_documents", active=True, requirement="required")],
        first_search=FirstSearch(query_ko="입학 지원 서류", target_slot_ids=["requested_documents"]),
        next_action="clarify_scope",
        clarification_question="어떤 서류요?",
    )
    out, warnings = validate_analysis(a, number_messages("서류 알려줘", []))
    assert out.primary_type is None and out.document_slots == [] and out.first_search is None
    assert any("clarify_scope" in w for w in warnings)


def test_search_plan_scenarios():
    failed = [r for r in (run_scenario(s) for s in SCENARIOS) if not r["passed"]]
    assert not failed, [(r["id"], [c["message"] for c in r["checks"] if not c["ok"]]) for r in failed]


def _cond(subject, quote, msg="m1"):
    from app.core.single_agent.analysis_schema import Condition
    return Condition(field_id="gks_status", value="예", subject=subject, source_message_id=msg, quote=quote)


def _search_analysis(conditions):
    return QuestionAnalysis(
        intent_summary="x", answer_scope="general", primary_type="T5", conditions=conditions,
        first_search=FirstSearch(query_ko="GKS 아르바이트", target_slot_ids=["rule"]), next_action="search",
    )


def test_answer_scope_follows_user_self_condition():
    q = "저 GKS 장학생인데 아르바이트 해도 돼요?"
    out, w = validate_analysis(_search_analysis([_cond("user_self", "저 GKS 장학생인데")]), number_messages(q, []))
    assert out.answer_scope == "personal"


def test_answer_scope_follows_other_person_condition():
    q = "친구가 GKS 장학생인데 아르바이트 해도 된대?"
    out, w = validate_analysis(_search_analysis([_cond("other_person", "친구가 GKS 장학생인데")]), number_messages(q, []))
    assert out.answer_scope == "third_party"


def test_answer_scope_question_target_stays_general():
    q = "GKS 장학생은 아르바이트할 수 있어?"
    out, w = validate_analysis(_search_analysis([_cond("question_target", "GKS 장학생은")]), number_messages(q, []))
    assert out.answer_scope == "general"
