"""
② 검색 계획의 '슬롯 선택' 확인용 시나리오.

③④가 아직 없어서 실제 검색으로 문서 칸 상태가 바뀌는 걸 볼 수 없다.
그래서 상태를 손으로 지정한 가짜(mock) 체크리스트를 넣어서, 규칙 기반
슬롯 선택(select_target_slot)과 예산 강제(check_budget)가 맞게
동작하는지만 확인한다. 검색어 문구 자체(LLM 출력)는 여기서 채점하지 않는다.

document_slots 항목은 analysis_schema.DocSlot 필드를 그대로 쓴다.
expect 키
  target_slot_id : 선택돼야 하는 슬롯 (None이면 no_target_left 기대)
  search_type    : "new" / "expand_context" (target_slot_id가 있을 때만)
  budget_action  : budget을 지정했을 때 기대하는 action ("budget_exhausted" 등)
"""

# T5(자격·허용·의무) 프로파일 순서 그대로: rule, applicable_scope, conditions_limits,
# exceptions_related, approval_reporting — checklist_config.PROFILES["T5"] 참고.

SCENARIOS = [
    {
        "id": "P01",
        "title": "①에서 막 나온 상태: 전부 unchecked → 첫 필수 칸(rule)부터",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "unchecked"},
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "unchecked"},
            {"slot_id": "conditions_limits", "active": True, "requirement": "conditional",
             "activation_state": "unresolved", "status": "unchecked"},
            {"slot_id": "exceptions_related", "active": True, "requirement": "required", "status": "unchecked"},
            {"slot_id": "approval_reporting", "active": True, "requirement": "conditional",
             "activation_state": "unresolved", "status": "unchecked"},
        ],
        "expect": {"target_slot_id": "rule", "search_type": "new"},
    },
    {
        "id": "P02",
        "title": "필수 칸 하나가 partial: 같은 필수도면 원문 확장을 신규 검색보다 먼저",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "supported"},
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "partial"},
            {"slot_id": "conditions_limits", "active": True, "requirement": "conditional",
             "activation_state": "unresolved", "status": "unchecked"},
            {"slot_id": "exceptions_related", "active": True, "requirement": "required", "status": "unchecked"},
            {"slot_id": "approval_reporting", "active": True, "requirement": "conditional",
             "activation_state": "unresolved", "status": "unchecked"},
        ],
        "expect": {"target_slot_id": "applicable_scope", "search_type": "expand_context"},
    },
    {
        "id": "P03",
        "title": "필수 칸이 missing: 조건부 칸이 unchecked여도 필수부터",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "missing"},
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "supported"},
            {"slot_id": "conditions_limits", "active": True, "requirement": "conditional",
             "activation_state": "unresolved", "status": "unchecked"},
            {"slot_id": "exceptions_related", "active": True, "requirement": "required", "status": "supported"},
            {"slot_id": "approval_reporting", "active": True, "requirement": "conditional",
             "activation_state": "unresolved", "status": "unchecked"},
        ],
        "expect": {"target_slot_id": "rule", "search_type": "new"},
    },
    {
        "id": "P04",
        "title": "모두 처리됨(supported/not_applicable) → 검색 대상 없음",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "supported"},
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "supported"},
            {"slot_id": "conditions_limits", "active": True, "requirement": "conditional",
             "activation_state": "not_triggered", "status": "not_applicable"},
            {"slot_id": "exceptions_related", "active": True, "requirement": "required", "status": "supported"},
            {"slot_id": "approval_reporting", "active": False, "requirement": "conditional",
             "activation_state": "not_triggered", "status": "not_applicable"},
        ],
        "expect": {"target_slot_id": None},
    },
    {
        "id": "P05",
        "title": "conflicting 상태도 신규 검색 대상 (원칙 필수 칸)",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "conflicting"},
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "supported"},
            {"slot_id": "exceptions_related", "active": True, "requirement": "required", "status": "supported"},
        ],
        "expect": {"target_slot_id": "rule", "search_type": "new"},
    },
    {
        "id": "P06",
        "title": "unavailable_in_corpus는 후보에서 제외",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "unavailable_in_corpus"},
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "unchecked"},
        ],
        "expect": {"target_slot_id": "applicable_scope", "search_type": "new"},
    },
    {
        "id": "B01",
        "title": "검색 호출 총 한도 소진 → 후보가 있어도 budget_exhausted",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "unchecked"},
        ],
        "budget": {"total_calls": 6, "expand_calls": 0, "subqueries": 2},
        "expect": {"target_slot_id": "rule", "search_type": "new", "budget_action": "budget_exhausted"},
    },
    {
        "id": "B02",
        "title": "원문 확장 한도만 소진 → 신규 검색 대상이면 통과, expand 대상이면 차단",
        "document_slots": [
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "partial"},
        ],
        "budget": {"total_calls": 3, "expand_calls": 3, "subqueries": 1},
        "expect": {"target_slot_id": "applicable_scope", "search_type": "expand_context",
                   "budget_action": "budget_exhausted"},
    },
    {
        "id": "B03",
        "title": "하위 질문(신규 검색) 한도만 소진 → new는 막히고 expand는 안 막힘",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "unchecked"},
        ],
        "budget": {"total_calls": 3, "expand_calls": 0, "subqueries": 3},
        "expect": {"target_slot_id": "rule", "search_type": "new", "budget_action": "budget_exhausted"},
    },
]
