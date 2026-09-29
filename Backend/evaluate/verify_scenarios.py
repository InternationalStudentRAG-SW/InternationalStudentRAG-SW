"""
④ 충분성 검증 확인용 시나리오.

가짜 LLM(FakeClient)이 정해 둔 판정 JSON을 돌려주게 하고, verify_evidence()의 서버 규칙
(근거 ID·인용 대조, 상태 강등, missing/unchecked 구분, not_applicable 제한, 사용자 칸 활성화,
다음 행동 결정)이 기대대로 동작하는지 확인한다. LLM 판정의 품질은 여기서 채점하지 않는다
(check_verification.py --live로 실제 판정을 눈으로 확인).

시나리오 키
  slots          : DocSlot 필드 목록 (없으면 T5 기본 5칸, 모두 unchecked)
  answer_scope   : 기본 general
  conditions     : Condition 필드 목록
  user_slots     : UserSlot 필드 목록
  pool           : [{"id", "text", "slots"(이 청크를 찾은 칸, 기본 ["rule"]), "score"}]
  round_chunk_ids: 이번 라운드에 ③이 돌려준 청크 (없으면 None = 풀 순서대로)
  history, budget: SearchAttempt 목록 / SearchBudget 필드
  llm            : 가짜 LLM이 돌려줄 판정 (dict) 또는 원문 문자열 목록(차례로 반환)
expect 키 (적은 것만 검사)
  next_action, llm_called, llm_calls, shown_chunk_ids, judged_slot_ids, clarify_field_ids, condition_field_ids
  slot_statuses   : {slot_id: status}
  slot_ref_ids    : {slot_id: [evidence_id]}
  activation      : {slot_id: activation_state}
  user_active     : {field_id: required_by_evidence 목록}   (활성 + 근거)
  user_inactive   : [field_id]  (활성화되면 안 됨)
  expand_anchors  : {slot_id: [evidence_id]}
  warnings_contain: 문구 (문자열 또는 목록)
  error_contains  : 오류 문구
  input_unchanged : True면 입력 analysis가 바뀌지 않았는지 확인
"""

G = "GKS지침(EN).pdf"


def gid(page, idx, source=G):
    return f"{source}#p{page}#c{idx}"


# 실제 live 결과에서 가져온 문장 (EN GKS 지침 p10~11)
T_DEGREE = ("3. A GKS recipient in a degree program may engage in part-time employment only where the president "
            "of the university grants approval upon determining that such employment does not significantly "
            "interfere with academic studies.")
T_LANG = ("2. A GKS recipient in the Korean language program shall not engage in part-time employment until "
          "completing at least six (6) months of the program.  Part-time employment shall be permitted only during "
          "vacation periods.")
T_LIMIT = ("Such employment shall require prior approval from the president of the Korean language institution and "
           "prior authorization from the Ministry of Justice.  In such case, part-time employment shall not exceed "
           "twenty (20) hours per week.")
T_EXCEPT = ("4. Activities under Subparagraph 3(E) shall, in principle, not be permitted for GKS recipients who have "
            "received an academic warning under Article 18(2).  However, an exception may be granted if all of the "
            "following conditions are met:")
T_NOISE = "교육원장은 정부초청 외국인 장학생(GKS) 사업의 성과 분석 및 동문 네트워크 구축을 위하여 현황을 조사할 수 있다."
T_OTHER = "The president of the institution must manage part-time employment of GKS recipients."

BASE_POOL = [
    {"id": gid(11, 0), "text": T_DEGREE, "score": 0.99},
    {"id": gid(10, 3), "text": T_LANG, "score": 0.97},
    {"id": gid(10, 4), "text": T_LIMIT},
    {"id": gid(11, 2), "text": T_EXCEPT, "score": 0.84},
    {"id": gid(10, 9), "text": T_NOISE, "score": 0.50},
]
FIRST = [{"target_slot_id": "rule", "search_type": "new", "query_ko": "GKS 장학생 아르바이트 가능 여부",
          "found_new_evidence": True}]
B1 = {"total_calls": 1, "subqueries": 1}


def ref(page, idx, quote):
    return {"evidence_id": gid(page, idx), "quote": quote}


def v(slot_id, status, refs=(), **kw):
    return {"slot_id": slot_id, "status": status, "evidence_refs": list(refs), "value": kw.pop("value", "요약"), **kw}


ALL_GOOD = [
    v("rule", "supported", [ref(11, 0, "may engage in part-time employment only where the president of the university grants approval")]),
    v("applicable_scope", "supported", [ref(11, 0, "A GKS recipient in a degree program"), ref(10, 3, "A GKS recipient in the Korean language program")]),
    v("conditions_limits", "supported", [ref(10, 4, "part-time employment shall not exceed twenty (20) hours per week")], activation_state="triggered"),
    v("exceptions_related", "supported", [ref(11, 2, "However, an exception may be granted if all of the following conditions are met:")]),
    v("approval_reporting", "supported", [ref(10, 4, "prior authorization from the Ministry of Justice")], activation_state="triggered"),
]
STAGE_NEED = {"field_id": "gks_stage", "evidence_ids": [gid(11, 0), gid(10, 3)],
              "branches": ["학위과정: 총장 승인 시 가능", "한국어연수: 6개월 이후 방학 중"], "reason": "단계별로 규정이 다름"}

SCENARIOS = [
    # ── 다음 행동 ───────────────────────────────────────────────────────
    {
        "id": "V01",
        "title": "live GKS 질문: 모든 칸 근거 확보 + GKS 단계별로 갈림, 일반 질문 → 조건별 일반 안내",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": ALL_GOOD, "user_field_needs": [STAGE_NEED]},
        "expect": {
            "next_action": "answer_by_condition",
            "condition_field_ids": ["gks_stage"],
            "slot_statuses": {"rule": "supported", "applicable_scope": "supported", "conditions_limits": "supported",
                              "exceptions_related": "supported", "approval_reporting": "supported"},
            "activation": {"conditions_limits": "triggered", "approval_reporting": "triggered"},
            "user_active": {"gks_stage": [gid(11, 0), gid(10, 3)]},
            "llm_calls": 1, "input_unchanged": True,
        },
    },
    {
        "id": "V02",
        "title": "같은 상황인데 본인 사례(personal) → 갈리는 조건만 되묻기",
        "answer_scope": "personal",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": ALL_GOOD, "user_field_needs": [STAGE_NEED]},
        "expect": {"next_action": "ask_clarification", "clarify_field_ids": ["gks_stage"]},
    },
    {
        "id": "V03",
        "title": "본인 사례지만 그 조건이 이미 확인됨 → 완결 답변",
        "answer_scope": "personal",
        "conditions": [{"field_id": "gks_stage", "value": "학위과정", "subject": "user_self",
                        "source_message_id": "m1", "quote": "학위과정"}],
        "user_slots": [{"field_id": "gks_stage", "status": "confirmed"}],
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": ALL_GOOD, "user_field_needs": [STAGE_NEED]},
        "expect": {"next_action": "answer", "user_active": {"gks_stage": [gid(11, 0), gid(10, 3)]}},
    },
    {
        "id": "V04",
        "title": "문서상 갈림이 없고 모든 칸 확보 → 완결 답변",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": ALL_GOOD, "user_field_needs": []},
        "expect": {"next_action": "answer"},
    },
    {
        "id": "V05",
        "title": "partial 칸이 남고 예산 있음 → continue_search, partial 칸의 근거가 원문 확장 앵커",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": ALL_GOOD[:3] + [
            v("exceptions_related", "partial", [ref(11, 2, "However, an exception may be granted")],
              missing_detail="예외 요건 목록(A~C)이 다음 청크로 이어짐"),
            ALL_GOOD[4]]},
        "expect": {"next_action": "continue_search", "slot_statuses": {"exceptions_related": "partial"},
                   "expand_anchors": {"exceptions_related": [gid(11, 2)]}},
    },
    {
        "id": "V06",
        "title": "미해결 칸이 남았는데 총 예산 소진 → partial_answer",
        "pool": BASE_POOL, "history": FIRST, "budget": {"total_calls": 6, "subqueries": 3, "expand_calls": 3},
        "llm": {"slot_verdicts": ALL_GOOD[:3] + [v("exceptions_related", "missing", missing_detail="관련 조항 못 찾음"),
                                                 ALL_GOOD[4]]},
        "expect": {"next_action": "partial_answer", "slot_statuses": {"exceptions_related": "unchecked"}},
    },
    {
        "id": "V07",
        "title": "최근 2회 연속 새 근거 없음 → 예산이 남아도 partial_answer",
        "pool": BASE_POOL,
        "history": FIRST + [
            {"target_slot_id": "exceptions_related", "search_type": "new", "query_ko": "예외 1", "found_new_evidence": False},
            {"target_slot_id": "exceptions_related", "search_type": "expand_context", "query_ko": "예외 2", "found_new_evidence": False}],
        "budget": {"total_calls": 3, "subqueries": 2, "expand_calls": 1},
        "llm": {"slot_verdicts": ALL_GOOD[:3] + [v("exceptions_related", "missing"), ALL_GOOD[4]]},
        "expect": {"next_action": "partial_answer"},
    },
    {
        "id": "V08",
        "title": "근거가 하나도 없고 더 검색할 수 없음 → no_evidence",
        "pool": [{"id": gid(10, 9), "text": T_NOISE}],
        "history": FIRST, "budget": {"total_calls": 6, "subqueries": 3, "expand_calls": 3},
        "llm": {"slot_verdicts": [v(s, "missing") for s in
                                  ("rule", "applicable_scope", "conditions_limits", "exceptions_related", "approval_reporting")]},
        "expect": {"next_action": "no_evidence", "slot_statuses": {"rule": "missing", "applicable_scope": "unchecked"}},
    },
    {
        "id": "V09",
        "title": "근거가 없지만 예산 남음 → continue_search (검색 안 한 칸은 unchecked라 ②가 검색 가능)",
        "pool": [{"id": gid(10, 9), "text": T_NOISE}], "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": [v(s, "missing") for s in
                                  ("rule", "applicable_scope", "conditions_limits", "exceptions_related", "approval_reporting")]},
        "expect": {"next_action": "continue_search",
                   "slot_statuses": {"rule": "missing", "applicable_scope": "unchecked", "exceptions_related": "unchecked"},
                   "warnings_contain": "검색한 적 없는 칸"},
    },
    # ── 근거 검증 ───────────────────────────────────────────────────────
    {
        "id": "C01",
        "title": "인용이 청크 본문에 없음(요약·위조) → 근거 제거, supported → missing 강등",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": [v("rule", "supported", [ref(11, 0, "GKS students can work part-time with approval")])] + ALL_GOOD[1:]},
        "expect": {"slot_statuses": {"rule": "missing"}, "slot_ref_ids": {"rule": []},
                   "warnings_contain": ["청크 본문에 없음", "유효한 근거가 없음"], "next_action": "continue_search"},
    },
    {
        "id": "C02",
        "title": "보여주지 않은 청크 ID를 근거로 댐 → 제거",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": [v("rule", "supported", [
            {"evidence_id": "없는문서.pdf#p1#c0", "quote": "anything"},
            ref(11, 0, "grants approval")])] + ALL_GOOD[1:]},
        "expect": {"slot_statuses": {"rule": "supported"}, "slot_ref_ids": {"rule": [gid(11, 0)]},
                   "warnings_contain": "보여준 청크가 아님"},
    },
    {
        "id": "C03",
        "title": "공백·줄바꿈·** 차이는 인용 일치로 인정",
        "pool": [{"id": gid(11, 0), "text": "- **Article 3** A GKS recipient  \n in a degree program may engage"}],
        "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": [v("rule", "supported", [ref(11, 0, "Article 3 A GKS recipient in a degree program")])]},
        "expect": {"slot_statuses": {"rule": "supported"}, "slot_ref_ids": {"rule": [gid(11, 0)]}},
    },
    {
        "id": "C04",
        "title": "필수 칸을 not_applicable로 판정 → 거부 (검색한 칸이면 missing)",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": [v("rule", "not_applicable", [ref(11, 0, "grants approval")])] + ALL_GOOD[1:]},
        "expect": {"slot_statuses": {"rule": "missing"}, "warnings_contain": "필수 칸은 not_applicable"},
    },
    {
        "id": "C05",
        "title": "조건부 칸을 근거와 함께 not_applicable → 허용, 발동 안 함, 답변에 불필요",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": ALL_GOOD[:4] + [
            v("approval_reporting", "not_applicable", [ref(10, 3, "Part-time employment shall be permitted only during vacation periods.")],
              activation_state="not_triggered")]},
        "expect": {"slot_statuses": {"approval_reporting": "not_applicable"},
                   "activation": {"approval_reporting": "not_triggered"}, "next_action": "answer"},
    },
    {
        "id": "C06",
        "title": "조건부 칸을 근거 없이 not_applicable → 거부, 발동 미확인 유지",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": ALL_GOOD[:4] + [v("approval_reporting", "not_applicable", activation_state="not_triggered")]},
        "expect": {"slot_statuses": {"approval_reporting": "unchecked"}, "activation": {"approval_reporting": "unresolved"},
                   "next_action": "continue_search", "warnings_contain": "근거 없이 조건부 칸"},
    },
    {
        "id": "C07",
        "title": "LLM이 unavailable_in_corpus를 씀 → 금지, missing으로",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": [v("rule", "unavailable_in_corpus")] + ALL_GOOD[1:]},
        "expect": {"slot_statuses": {"rule": "missing"}, "warnings_contain": "자료 범위표로만"},
    },
    {
        "id": "C08",
        "title": "충돌인데 근거가 1개뿐 → partial",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": [v("rule", "conflicting", [ref(11, 0, "grants approval")])] + ALL_GOOD[1:]},
        "expect": {"slot_statuses": {"rule": "partial"}, "warnings_contain": "근거 2개 이상"},
    },
    {
        "id": "C09",
        "title": "판정 대상이 아닌 칸·중복 판정은 제거, 빠진 칸은 상태 유지(검색한 칸은 missing)",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": [ALL_GOOD[1], ALL_GOOD[1], v("deadline", "supported", [ref(11, 0, "grants approval")])]},
        "expect": {"slot_statuses": {"rule": "missing", "applicable_scope": "supported", "exceptions_related": "unchecked"},
                   "warnings_contain": ["판정 대상 칸이 아님", "중복", "판정하지 않음"]},
    },
    {
        "id": "C10",
        "title": "조건부 칸이 근거로 supported → 발동(triggered)으로",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": ALL_GOOD[:2] + [
            v("conditions_limits", "supported", [ref(10, 4, "shall not exceed twenty (20) hours per week")])] + ALL_GOOD[3:]},
        "expect": {"activation": {"conditions_limits": "triggered"}},
    },
    # ── 사용자 칸 ───────────────────────────────────────────────────────
    {
        "id": "U01",
        "title": "문서 근거 없는 되묻기 후보(nationality) → 활성화하지 않음",
        "answer_scope": "personal",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": ALL_GOOD, "user_field_needs": [
            {"field_id": "nationality", "evidence_ids": [], "reason": "국적 확인 필요할 듯"},
            {"field_id": "made_up_field", "evidence_ids": [gid(11, 0)]}]},
        "expect": {"next_action": "answer", "user_inactive": ["nationality", "made_up_field"],
                   "warnings_contain": ["문서 근거 없이 되묻기 금지", "정의되지 않은 칸"]},
    },
    {
        "id": "U02",
        "title": "되묻기는 최대 2개",
        "answer_scope": "personal",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": ALL_GOOD, "user_field_needs": [
            STAGE_NEED,
            {"field_id": "degree_level", "evidence_ids": [gid(11, 0)]},
            {"field_id": "activity_timing", "evidence_ids": [gid(10, 3)]}]},
        "expect": {"next_action": "ask_clarification", "clarify_field_ids": ["gks_stage", "degree_level"]},
    },
    # ── 청크 선택·LLM 호출 ───────────────────────────────────────────────
    {
        "id": "S01",
        "title": "보여줄 청크: 칸에 연결된 청크 → 이번 라운드 청크 → 나머지 풀 순",
        "slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "supported",
             "evidence_refs": [{"evidence_id": gid(11, 0), "quote": "grants approval"}]},
            {"slot_id": "exceptions_related", "active": True, "requirement": "required", "status": "partial",
             "evidence_refs": [{"evidence_id": gid(11, 2), "quote": "However, an exception may be granted"}]},
        ],
        "pool": BASE_POOL, "round_chunk_ids": [gid(10, 4)],
        "history": FIRST + [{"target_slot_id": "exceptions_related", "search_type": "expand_context",
                             "query_ko": "예외", "found_new_evidence": True}],
        "budget": {"total_calls": 2, "subqueries": 1, "expand_calls": 1},
        "llm": {"slot_verdicts": [v("exceptions_related", "supported", [ref(11, 2, "However, an exception may be granted")])]},
        "expect": {"shown_chunk_ids": [gid(11, 0), gid(11, 2), gid(10, 4), gid(10, 3), gid(10, 9)],
                   "judged_slot_ids": ["exceptions_related"],
                   "next_action": "answer"},
    },
    {
        "id": "S02",
        "title": "판정할 칸이 없으면 LLM을 부르지 않고 바로 결정",
        "slots": [{"slot_id": "rule", "active": True, "requirement": "required", "status": "supported",
                   "evidence_refs": [{"evidence_id": gid(11, 0), "quote": "grants approval"}]}],
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": []},
        "expect": {"llm_called": False, "llm_calls": 0, "next_action": "answer"},
    },
    {
        "id": "S03",
        "title": "풀이 비었으면 LLM을 부르지 않음, 검색한 칸만 missing",
        "pool": [], "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": []},
        "expect": {"llm_called": False, "next_action": "continue_search",
                   "slot_statuses": {"rule": "missing", "applicable_scope": "unchecked"}},
    },
    {
        "id": "S04",
        "title": "형식 오류 1번 뒤 재시도 성공",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": ["이건 JSON이 아님", {"slot_verdicts": ALL_GOOD}],
        "expect": {"llm_calls": 2, "next_action": "answer"},
    },
    {
        "id": "S05",
        "title": "형식 오류가 계속되면 error, 칸 상태는 바꾸지 않고 결정 없음",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": ["{\"slot_verdicts\": \"틀림\"}", "여전히 틀림"],
        "expect": {"llm_calls": 2, "next_action": None, "error_contains": "형식 오류",
                   "slot_statuses": {"rule": "unchecked"}},
    },

    # ── live 결과에서 찾은 문제 재현 ─────────────────────────────────────
    {
        "id": "S06",
        "title": "[버그 재현] 예전에 놓친 청크가 이번 라운드에 다시 검색되면 (새 청크가 아니어도) 상한 안에 보여줌",
        "slots": [
            {"slot_id": "rule", "active": True, "requirement": "required", "status": "supported",
             "evidence_refs": [{"evidence_id": gid(11, 0), "quote": "grants approval"}]},
            {"slot_id": "exceptions_related", "active": True, "requirement": "required", "status": "missing"},
        ],
        # 풀: 연결된 청크 + 잡음 25개 + 맨 뒤에 예전에 놓친 예외 청크 → 들어온 순서로는 상한(20) 밖
        "pool": [{"id": gid(11, 0), "text": T_DEGREE}] + [{"id": gid(50, i, "잡음.pdf"), "text": f"관련 없는 청크 {i}"} for i in range(25)] + [{"id": gid(11, 2), "text": T_EXCEPT}],
        "round_chunk_ids": [gid(11, 2)],
        "history": FIRST + [{"target_slot_id": "exceptions_related", "search_type": "new", "query_ko": "GKS 아르바이트 예외",
                             "found_new_evidence": False}],
        "budget": {"total_calls": 2, "subqueries": 2},
        "llm": {"slot_verdicts": [v("exceptions_related", "supported",
                                   [ref(11, 2, "However, an exception may be granted if all of the following conditions are met:")])]},
        "expect": {"slot_statuses": {"exceptions_related": "supported"}, "next_action": "answer"},
    },
    {
        "id": "S07",
        "title": "청크 상한: 연결된 청크·이번 라운드 청크가 먼저 들어가고 총 VERIFY_MAX_CHUNKS개로 자름",
        "slots": [{"slot_id": "rule", "active": True, "requirement": "required", "status": "partial",
                   "evidence_refs": [{"evidence_id": gid(11, 0), "quote": "grants approval"}]}],
        "pool": [{"id": gid(50, i, "잡음.pdf"), "text": f"관련 없는 청크 {i}"} for i in range(25)] + [{"id": gid(11, 0), "text": T_DEGREE}, {"id": gid(10, 4), "text": T_LIMIT}],
        "round_chunk_ids": [gid(10, 4)],
        "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": [v("rule", "supported", [ref(11, 0, "grants approval")])]},
        "expect": {"shown_first": [gid(11, 0), gid(10, 4), gid(50, 0, "잡음.pdf")], "shown_count": 20},
    },
    {
        "id": "SC1",
        "title": "[live 재현] 일반 질문, 갈래(gks_stage)는 적었는데 적용 범위가 한 갈래만 인용 → partial로 낮추고 재검색",
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": [ALL_GOOD[0],
                                  v("applicable_scope", "supported", [ref(11, 0, "A GKS recipient in a degree program")])]
                                 + ALL_GOOD[2:],
                "user_field_needs": [STAGE_NEED]},
        "expect": {"slot_statuses": {"applicable_scope": "partial"}, "next_action": "continue_search",
                   "expand_anchors": {"applicable_scope": [gid(11, 0)]}, "warnings_contain": "갈래 근거"},
    },
    {
        "id": "SC2",
        "title": "그 사용자 조건이 이미 확인됐으면 한 갈래만 인용해도 적용 범위 supported 유지",
        "answer_scope": "personal",
        "conditions": [{"field_id": "gks_stage", "value": "학위과정", "subject": "user_self",
                        "source_message_id": "m1", "quote": "학위과정"}],
        "user_slots": [{"field_id": "gks_stage", "status": "confirmed"}],
        "pool": BASE_POOL, "history": FIRST, "budget": B1,
        "llm": {"slot_verdicts": [ALL_GOOD[0],
                                  v("applicable_scope", "supported", [ref(11, 0, "A GKS recipient in a degree program")])]
                                 + ALL_GOOD[2:],
                "user_field_needs": [STAGE_NEED]},
        "expect": {"slot_statuses": {"applicable_scope": "supported"}, "next_action": "answer"},
    },
]
