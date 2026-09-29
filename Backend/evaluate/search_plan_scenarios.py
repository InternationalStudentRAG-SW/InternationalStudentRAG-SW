"""
② 검색 계획 확인용 시나리오.

③④가 아직 없어서 실제 검색으로 문서 칸 상태가 바뀌는 걸 볼 수 없다.
그래서 상태를 손으로 지정한 가짜(mock) 체크리스트와 가짜 LLM(FakeClient)을 넣어
plan_search()를 끝까지 돌리고, 규칙(슬롯 선택·예산·칸별 상한·첫 검색 재사용·중복 차단)이
맞게 동작하는지 확인한다. 실제 검색어 문구 품질은 여기서 채점하지 않는다(--live로 눈으로 확인).

시나리오 키
  document_slots : analysis_schema.DocSlot 필드 그대로
  budget         : SearchBudget 필드 (없으면 0부터)
  history        : 이미 실행한 검색 [SearchAttempt 필드] (없으면 빈 목록)
  first_search   : ①의 FirstSearch 필드 (없으면 None)
  fake_queries   : 가짜 LLM이 차례로 돌려줄 검색어 (없으면 "가짜 검색어 1", "가짜 검색어 2", ...)
expect 키 (적은 것만 검사)
  action            : "search" / "budget_exhausted" / "no_target_left"
  target_slot_id    : 선택된 칸 (budget_exhausted면 막힌 1순위 칸)
  search_type       : "new" / "expand_context"
  query_ko          : 최종 검색어
  from_first_search : ①의 first_search를 그대로 썼는지
  exhausted_slot_ids: 칸별 시도 상한에 걸려 더 검색하지 않는 칸 목록
  slot_statuses     : 계획 후 칸 status (적은 칸만 검사. 상한에 걸려도 status가 바뀌지 않는지 확인)
  llm_calls         : 가짜 LLM 호출 횟수
"""

# T5(자격·허용·의무) 프로파일 순서 그대로: rule, applicable_scope, conditions_limits,
# exceptions_related, approval_reporting — checklist_config.PROFILES["T5"] 참고.

SCENARIOS = [
    # ── 슬롯 선택 우선순위 ──────────────────────────────────────────────
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
        "expect": {"action": "search", "target_slot_id": "rule", "search_type": "new", "llm_calls": 1},
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
        "expect": {"action": "search", "target_slot_id": "applicable_scope", "search_type": "expand_context"},
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
        "history": [
            {"target_slot_id": "rule", "search_type": "new", "query_ko": "GKS 장학생 아르바이트 허용 기준"},
        ],
        "budget": {"total_calls": 1, "expand_calls": 0, "subqueries": 1},
        "expect": {"action": "search", "target_slot_id": "rule", "search_type": "new"},
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
        "expect": {"action": "no_target_left", "llm_calls": 0},
    },
    {
        "id": "P05",
        "title": "conflicting 상태도 신규 검색 대상 (원칙 필수 칸)",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "conflicting"},
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "supported"},
            {"slot_id": "exceptions_related", "active": True, "requirement": "required", "status": "supported"},
        ],
        "expect": {"action": "search", "target_slot_id": "rule", "search_type": "new"},
    },
    {
        "id": "P06",
        "title": "unavailable_in_corpus는 후보에서 제외",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "unavailable_in_corpus"},
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "unchecked"},
        ],
        "expect": {"action": "search", "target_slot_id": "applicable_scope", "search_type": "new"},
    },
    # ── 예산 ───────────────────────────────────────────────────────────
    {
        "id": "B01",
        "title": "검색 호출 총 한도 소진 → 후보가 있어도 budget_exhausted",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "unchecked"},
        ],
        "budget": {"total_calls": 6, "expand_calls": 0, "subqueries": 2},
        "expect": {"action": "budget_exhausted", "target_slot_id": "rule", "search_type": "new", "llm_calls": 0},
    },
    {
        "id": "B02",
        "title": "원문 확장 한도 소진 + 후보가 expand뿐 → budget_exhausted",
        "document_slots": [
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "partial"},
        ],
        "budget": {"total_calls": 3, "expand_calls": 3, "subqueries": 0},
        "expect": {"action": "budget_exhausted", "target_slot_id": "applicable_scope",
                   "search_type": "expand_context", "llm_calls": 0},
    },
    {
        "id": "B03",
        "title": "하위 질문 한도 소진 + 후보가 new뿐 → budget_exhausted",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "unchecked"},
        ],
        "budget": {"total_calls": 3, "expand_calls": 0, "subqueries": 3},
        "expect": {"action": "budget_exhausted", "target_slot_id": "rule", "search_type": "new", "llm_calls": 0},
    },
    {
        "id": "B04",
        "title": "[수정 2] 1순위(partial)는 확장 한도에 막혀도 다음 후보(new)로 넘어감",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "partial"},
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "unchecked"},
        ],
        "budget": {"total_calls": 4, "expand_calls": 3, "subqueries": 1},
        "expect": {"action": "search", "target_slot_id": "applicable_scope", "search_type": "new"},
    },
    {
        "id": "B05",
        "title": "[수정 2] 1순위(new)는 하위 질문 한도에 막혀도 다음 후보(partial 확장)로 넘어감",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "unchecked"},
            {"slot_id": "conditions_limits", "active": True, "requirement": "conditional",
             "activation_state": "unresolved", "status": "partial"},
        ],
        "budget": {"total_calls": 3, "expand_calls": 0, "subqueries": 3},
        "expect": {"action": "search", "target_slot_id": "conditions_limits", "search_type": "expand_context"},
    },
    # ── 칸별 시도 상한 ─────────────────────────────────────────────────
    {
        "id": "R01",
        "title": "[수정 3] 신규 검색 2번에도 missing → 상한 도달로 건너뜀(status는 missing 유지), 다음 필수 칸 검색",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "missing"},
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "supported"},
            {"slot_id": "exceptions_related", "active": True, "requirement": "required", "status": "unchecked"},
        ],
        "history": [
            {"target_slot_id": "rule", "search_type": "new", "query_ko": "GKS 장학생 아르바이트 허용 기준"},
            {"target_slot_id": "rule", "search_type": "new", "query_ko": "GKS 시간제 취업 금지 조항"},
        ],
        "budget": {"total_calls": 2, "expand_calls": 0, "subqueries": 2},
        "expect": {"action": "search", "target_slot_id": "exceptions_related", "search_type": "new",
                   "exhausted_slot_ids": ["rule"], "slot_statuses": {"rule": "missing"}},
    },
    {
        "id": "R02",
        "title": "[수정 3] 원문 확장 2번에도 partial → 더 확장하지 않고 다음 후보로 (partial 유지)",
        "document_slots": [
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "partial"},
            {"slot_id": "conditions_limits", "active": True, "requirement": "conditional",
             "activation_state": "unresolved", "status": "unchecked"},
        ],
        "history": [
            {"target_slot_id": "applicable_scope", "search_type": "new", "query_ko": "GKS 적용 대상"},
            {"target_slot_id": "applicable_scope", "search_type": "expand_context", "query_ko": "GKS 적용 대상 표 나머지"},
            {"target_slot_id": "applicable_scope", "search_type": "expand_context", "query_ko": "GKS 적용 대상 다음 조항"},
        ],
        "budget": {"total_calls": 3, "expand_calls": 2, "subqueries": 1},
        "expect": {"action": "search", "target_slot_id": "conditions_limits", "search_type": "new",
                   "exhausted_slot_ids": ["applicable_scope"], "slot_statuses": {"applicable_scope": "partial"}},
    },
    {
        "id": "R03",
        "title": "[수정 3] 모든 후보가 상한에 걸림 → no_target_left (예산은 남아 있음, status는 missing 유지 → 부분 답변)",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "missing"},
        ],
        "history": [
            {"target_slot_id": "rule", "search_type": "new", "query_ko": "검색어 1"},
            {"target_slot_id": "rule", "search_type": "new", "query_ko": "검색어 2"},
        ],
        "budget": {"total_calls": 2, "expand_calls": 0, "subqueries": 2},
        "expect": {"action": "no_target_left", "exhausted_slot_ids": ["rule"], "slot_statuses": {"rule": "missing"},
                   "llm_calls": 0},
    },
    # ── ①의 first_search 재사용 ────────────────────────────────────────
    {
        "id": "F01",
        "title": "[수정 4] 첫 바퀴: ①의 first_search를 그대로 사용, LLM 호출 없음 (대상은 우선순위 높은 칸)",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "unchecked"},
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "unchecked"},
            {"slot_id": "exceptions_related", "active": True, "requirement": "required", "status": "unchecked"},
        ],
        "first_search": {"query_ko": "GKS 장학생 시간제 취업 허용 기준",
                         "target_slot_ids": ["applicable_scope", "rule"], "reason": "허용 원칙과 적용 범위부터"},
        "expect": {"action": "search", "target_slot_id": "rule", "search_type": "new",
                   "query_ko": "GKS 장학생 시간제 취업 허용 기준", "from_first_search": True, "llm_calls": 0},
    },
    {
        "id": "F02",
        "title": "[수정 4] 두 번째 바퀴부터는 first_search를 다시 쓰지 않음",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "supported"},
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "unchecked"},
        ],
        "first_search": {"query_ko": "GKS 장학생 시간제 취업 허용 기준",
                         "target_slot_ids": ["rule", "applicable_scope"], "reason": ""},
        "history": [
            {"target_slot_id": "rule", "search_type": "new", "query_ko": "GKS 장학생 시간제 취업 허용 기준"},
        ],
        "budget": {"total_calls": 1, "expand_calls": 0, "subqueries": 1},
        "expect": {"action": "search", "target_slot_id": "applicable_scope", "from_first_search": False,
                   "llm_calls": 1},
    },
    # ── 중복 검색어 ────────────────────────────────────────────────────
    {
        "id": "D01",
        "title": "[수정 5] 다른 칸에서 쓴 검색어와 같으면 1회 다시 생성",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "supported"},
            {"slot_id": "applicable_scope", "active": True, "requirement": "required", "status": "unchecked"},
        ],
        "history": [
            {"target_slot_id": "rule", "search_type": "new", "query_ko": "GKS 장학생 아르바이트 허용 기준"},
        ],
        "budget": {"total_calls": 1, "expand_calls": 0, "subqueries": 1},
        "fake_queries": ["GKS 장학생  아르바이트 허용기준", "GKS 장학생 적용 대상 과정"],
        "expect": {"action": "search", "target_slot_id": "applicable_scope",
                   "query_ko": "GKS 장학생 적용 대상 과정", "llm_calls": 2},
    },
    {
        "id": "D02",
        "title": "[수정 5] 다시 만들어도 중복이면 그 칸은 건너뛰고 다음 후보로",
        "document_slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "missing"},
            {"slot_id": "exceptions_related", "active": True, "requirement": "required", "status": "unchecked"},
        ],
        "history": [
            {"target_slot_id": "rule", "search_type": "new", "query_ko": "GKS 장학생 아르바이트 허용 기준"},
        ],
        "budget": {"total_calls": 1, "expand_calls": 0, "subqueries": 1},
        "fake_queries": ["GKS 장학생 아르바이트 허용 기준", "GKS 장학생 아르바이트 허용 기준",
                         "GKS 장학생 아르바이트 예외 조항"],
        "expect": {"action": "search", "target_slot_id": "exceptions_related",
                   "query_ko": "GKS 장학생 아르바이트 예외 조항", "llm_calls": 3},
    },
]
