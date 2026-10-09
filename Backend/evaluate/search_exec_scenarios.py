"""
③ 근거 검색 확인용 시나리오.

실제 retriever·ChromaDB 없이, 가짜 검색 함수(FakeSearch)와 가짜 청크 저장소(FakeStore)로
execute_search()를 끝까지 돌려 규칙(풀 누적·새 근거 판정·예산 갱신·오류 처리·앞뒤 청크 확장)을
확인한다. 실제 검색 품질은 여기서 채점하지 않는다(check_search_execution.py --live로 눈으로 확인).

시나리오 키
  plan            : SearchPlan 필드 (기본: action=search, target_slot_id=rule, search_type=new)
  budget          : SearchBudget 필드 (없으면 0부터)
  store_pages     : 가짜 저장소 {source: {page: [청크 본문, ...]}}  (리스트 순서가 chunk_index)
  pool            : 미리 풀에 넣어 둘 청크 [{"id", "score"(선택), "slots"(선택, 이 청크를 찾았던 칸들)}]
  anchors         : anchor_evidence_ids (원문 확장)
  search_results  : 가짜 검색 함수가 돌려줄 결과 [{"source","page","chunk_index","text","score"}]
  search_fail_times : 가짜 검색 함수가 처음 몇 번 예외를 던질지 (숫자 또는 "always")
  store_error     : True면 가짜 저장소가 항상 예외를 던짐
expect 키 (적은 것만 검사)
  ok, error_type, chunk_ids, new_chunk_ids, anchor_ids, tool_attempts
  found_new_evidence : run.attempt.found_new_evidence (실패하면 None)
  budget             : 갱신된 예산 (적은 필드만)
  pool_size          : 실행 후 풀 크기
  pool_scores        : {청크 ID: 점수} (적은 것만)
  search_calls       : 가짜 검색 함수가 불린 횟수
  search_k           : 가짜 검색 함수에 넘어온 k
  warnings_contain   : 경고 메시지에 들어 있어야 할 문구 (문자열 또는 목록)
"""
from app.core.single_agent import checklist_config as cfg

DOC = "d.pdf"


def c(page, idx, score=None, text=None, source=DOC):
    """가짜 검색 결과 1건."""
    d = {"source": source, "page": page, "chunk_index": idx, "text": text or f"{source} p{page} c{idx} 본문"}
    if score is not None:
        d["score"] = score
    return d


def eid(page, idx, source=DOC):
    return f"{source}#p{page}#c{idx}"


NEW_PLAN = {"target_slot_id": "rule", "search_type": "new", "query_ko": "GKS 시간제 취업 허용 기준"}
EXPAND_PLAN = {"target_slot_id": "rule", "search_type": "expand_context", "query_ko": "GKS 시간제 취업 관련 조항"}

# 원문 확장용 저장소: 3페이지 청크 4개(c0~c3), 4페이지 청크 2개(c0~c1). 2·5페이지는 없음.
PAGES = {DOC: {3: ["t0", "t1", "t2", "t3"], 4: ["u0", "u1"]}}

SCENARIOS = [
    # ── 신규 검색 ────────────────────────────────────────────────────────
    {
        "id": "E01",
        "title": "신규 검색: 결과를 풀에 쌓고 예산(subqueries·total) 증가, SEARCH_TOP_K로 호출",
        "plan": NEW_PLAN,
        "search_results": [c(3, 1, 0.91), c(3, 2, 0.80), c(5, 0, 0.42)],
        "expect": {
            "ok": True,
            "chunk_ids": [eid(3, 1), eid(3, 2), eid(5, 0)],
            "new_chunk_ids": [eid(3, 1), eid(3, 2), eid(5, 0)],
            "found_new_evidence": True,
            "budget": {"total_calls": 1, "subqueries": 1, "expand_calls": 0},
            "pool_size": 3,
            "search_calls": 1,
            "search_k": cfg.SEARCH_TOP_K,
        },
    },
    {
        "id": "E02",
        "title": "이미 풀에 있는 청크만 나오면 found_new_evidence=False (검색은 실행됐으므로 예산은 차감)",
        "plan": NEW_PLAN,
        "pool": [{"id": eid(3, 1), "score": 0.9, "slots": ["rule"]}, {"id": eid(3, 2), "score": 0.8, "slots": ["rule"]}],
        "search_results": [c(3, 1, 0.90), c(3, 2, 0.80)],
        "expect": {
            "ok": True,
            "chunk_ids": [eid(3, 1), eid(3, 2)],
            "new_chunk_ids": [],
            "found_new_evidence": False,
            "budget": {"total_calls": 1, "subqueries": 1},
            "pool_size": 2,
        },
    },
    {
        "id": "E03",
        "title": "일부만 새 청크: 새 것만 new_chunk_ids, 점수는 더 높은 쪽으로만 갱신",
        "plan": NEW_PLAN,
        "pool": [{"id": eid(3, 1), "score": 0.30, "slots": ["rule"]}, {"id": eid(3, 2), "score": 0.95, "slots": ["rule"]}],
        "search_results": [c(3, 1, 0.90), c(3, 2, 0.10), c(4, 0, 0.50)],
        "expect": {
            "ok": True,
            "new_chunk_ids": [eid(4, 0)],
            "found_new_evidence": True,
            "pool_size": 3,
            "pool_scores": {eid(3, 1): 0.90, eid(3, 2): 0.95, eid(4, 0): 0.50},
        },
    },
    {
        "id": "E04",
        "title": "결과 0건: 검색은 실행됐으니 예산 차감, 새 근거 없음, 경고(자료 부재 확정 아님)",
        "plan": NEW_PLAN,
        "search_results": [],
        "expect": {
            "ok": True,
            "chunk_ids": [],
            "found_new_evidence": False,
            "budget": {"total_calls": 1, "subqueries": 1},
            "pool_size": 0,
            "warnings_contain": "결과 없음",
        },
    },
    {
        "id": "E05",
        "title": "도구 오류 1번 뒤 재시도 성공: 예산은 한 번만 차감, 도구 호출 2회",
        "plan": NEW_PLAN,
        "search_results": [c(3, 1, 0.9)],
        "search_fail_times": 1,
        "expect": {
            "ok": True,
            "new_chunk_ids": [eid(3, 1)],
            "tool_attempts": 2,
            "search_calls": 2,
            "budget": {"total_calls": 1, "subqueries": 1},
            "warnings_contain": "도구 오류",
        },
    },
    {
        "id": "E06",
        "title": "도구 오류가 계속되면 tool_error: 예산·풀·검색 기록을 바꾸지 않음 ('문서에 없음'으로 취급 금지)",
        "plan": NEW_PLAN,
        "pool": [{"id": eid(3, 1), "score": 0.9, "slots": ["rule"]}],
        "budget": {"total_calls": 1, "subqueries": 1},
        "search_results": [c(4, 0, 0.5)],
        "search_fail_times": "always",
        "expect": {
            "ok": False,
            "error_type": "tool_error",
            "tool_attempts": 1 + cfg.TOOL_MAX_RETRIES,
            "chunk_ids": [],
            "found_new_evidence": None,
            "budget": {"total_calls": 1, "subqueries": 1},
            "pool_size": 1,
        },
    },
    {
        "id": "E07",
        "title": "page·chunk_index·본문이 없는 결과는 걸러냄 (근거 ID를 만들 수 없으므로)",
        "plan": NEW_PLAN,
        "search_results": [
            c(3, 1, 0.9),
            {"source": DOC, "page": 3, "text": "chunk_index 없음"},
            c(4, 0, 0.5, text="   "),
        ],
        "expect": {
            "ok": True,
            "chunk_ids": [eid(3, 1)],
            "pool_size": 1,
            "warnings_contain": "제거",
        },
    },
    {
        "id": "E08",
        "title": "한 결과 안에서 같은 청크가 두 번 나오면 하나만",
        "plan": NEW_PLAN,
        "search_results": [c(3, 1, 0.9), c(3, 1, 0.8)],
        "expect": {"ok": True, "chunk_ids": [eid(3, 1)], "pool_size": 1, "warnings_contain": "중복"},
    },
    {
        "id": "E09",
        "title": "하위 질문 예산이 이미 소진 → budget_exhausted, 검색 도구를 부르지 않음",
        "plan": NEW_PLAN,
        "budget": {"total_calls": 3, "subqueries": 3},
        "search_results": [c(3, 1, 0.9)],
        "expect": {"ok": False, "error_type": "budget_exhausted", "search_calls": 0, "pool_size": 0,
                   "budget": {"total_calls": 3, "subqueries": 3}},
    },
    {
        "id": "E10",
        "title": "검색이 아닌 계획(action=budget_exhausted)을 받으면 invalid_plan, 아무것도 실행하지 않음",
        "plan": {"action": "budget_exhausted", "reason": "검색 호출 총 한도 소진"},
        "search_results": [c(3, 1, 0.9)],
        "expect": {"ok": False, "error_type": "invalid_plan", "search_calls": 0},
    },
    {
        "id": "E11",
        "title": "검색어가 비어 있는 계획은 invalid_plan",
        "plan": {"target_slot_id": "rule", "search_type": "new", "query_ko": "  "},
        "search_results": [c(3, 1, 0.9)],
        "expect": {"ok": False, "error_type": "invalid_plan", "search_calls": 0},
    },

    # ── 원문 확장 (앞뒤 청크) ─────────────────────────────────────────────
    {
        "id": "X01",
        "title": "페이지 중간 앵커: 같은 페이지 앞·뒤 청크. expand_calls·total 증가, 검색기는 부르지 않음",
        "plan": EXPAND_PLAN,
        "store_pages": PAGES,
        "pool": [{"id": eid(3, 1), "score": 0.9, "slots": ["rule"]}],
        "anchors": [eid(3, 1)],
        "budget": {"total_calls": 1, "subqueries": 1},
        "expect": {
            "ok": True,
            "chunk_ids": [eid(3, 0), eid(3, 2)],
            "new_chunk_ids": [eid(3, 0), eid(3, 2)],
            "anchor_ids": [eid(3, 1)],
            "found_new_evidence": True,
            "budget": {"total_calls": 2, "expand_calls": 1, "subqueries": 1},
            "pool_size": 3,
            "search_calls": 0,
        },
    },
    {
        "id": "X02",
        "title": "앵커가 페이지의 마지막 청크: 앞 청크 + 다음 페이지 첫 청크",
        "plan": EXPAND_PLAN,
        "store_pages": PAGES,
        "pool": [{"id": eid(3, 3), "score": 0.9, "slots": ["rule"]}],
        "anchors": [eid(3, 3)],
        "expect": {"ok": True, "chunk_ids": [eid(3, 2), eid(4, 0)]},
    },
    {
        "id": "X03",
        "title": "앵커가 페이지의 첫 청크: 이전 페이지 마지막 청크 + 다음 청크",
        "plan": EXPAND_PLAN,
        "store_pages": PAGES,
        "pool": [{"id": eid(4, 0), "score": 0.9, "slots": ["rule"]}],
        "anchors": [eid(4, 0)],
        "expect": {"ok": True, "chunk_ids": [eid(3, 3), eid(4, 1)]},
    },
    {
        "id": "X04",
        "title": "문서의 마지막 청크: 뒤가 없으면 앞 청크만",
        "plan": EXPAND_PLAN,
        "store_pages": PAGES,
        "pool": [{"id": eid(4, 1), "score": 0.9, "slots": ["rule"]}],
        "anchors": [eid(4, 1)],
        "expect": {"ok": True, "chunk_ids": [eid(4, 0)]},
    },
    {
        "id": "X05",
        "title": "문서의 첫 청크(이전 페이지 없음): 뒤 청크만",
        "plan": EXPAND_PLAN,
        "store_pages": PAGES,
        "pool": [{"id": eid(3, 0), "score": 0.9, "slots": ["rule"]}],
        "anchors": [eid(3, 0)],
        "expect": {"ok": True, "chunk_ids": [eid(3, 1)]},
    },
    {
        "id": "X06",
        "title": "이웃이 이미 풀에 있으면 청크는 돌려주되 새 근거는 아님 (found_new_evidence=False)",
        "plan": EXPAND_PLAN,
        "store_pages": PAGES,
        "pool": [{"id": eid(3, 0)}, {"id": eid(3, 1), "score": 0.9, "slots": ["rule"]}, {"id": eid(3, 2)}],
        "anchors": [eid(3, 1)],
        "expect": {"ok": True, "chunk_ids": [eid(3, 0), eid(3, 2)], "new_chunk_ids": [],
                   "found_new_evidence": False, "pool_size": 3},
    },
    {
        "id": "X07",
        "title": "앵커를 안 주면 그 칸의 최고 점수 청크를 앵커로 사용 (보완 경고)",
        "plan": EXPAND_PLAN,
        "store_pages": PAGES,
        "pool": [{"id": eid(3, 1), "score": 0.40, "slots": ["rule"]},
                 {"id": eid(4, 0), "score": 0.90, "slots": ["rule"]},
                 {"id": eid(3, 2), "score": 0.99, "slots": ["other_slot"]}],
        "expect": {"ok": True, "anchor_ids": [eid(4, 0)], "chunk_ids": [eid(3, 3), eid(4, 1)],
                   "warnings_contain": "앵커가 없어"},
    },
    {
        "id": "X08",
        "title": "앵커가 여러 개: 이웃을 합치되 앵커끼리·중복은 제외하고 문서 순으로",
        "plan": EXPAND_PLAN,
        "store_pages": PAGES,
        "pool": [{"id": eid(3, 1), "score": 0.9, "slots": ["rule"]}, {"id": eid(3, 2), "score": 0.8, "slots": ["rule"]}],
        "anchors": [eid(3, 1), eid(3, 2)],
        "expect": {"ok": True, "chunk_ids": [eid(3, 0), eid(3, 3)]},
    },
    {
        "id": "X09",
        "title": "앵커 ID가 형식에 안 맞고 풀에도 그 칸의 청크가 없으면 no_anchor (예산 차감 없음)",
        "plan": EXPAND_PLAN,
        "store_pages": PAGES,
        "anchors": ["엉뚱한 문자열"],
        "budget": {"total_calls": 1, "subqueries": 1},
        "expect": {"ok": False, "error_type": "no_anchor", "budget": {"total_calls": 1, "expand_calls": 0},
                   "warnings_contain": "형식이 아님"},
    },
    {
        "id": "X10",
        "title": "원문 확장 예산이 이미 소진 → budget_exhausted",
        "plan": EXPAND_PLAN,
        "store_pages": PAGES,
        "pool": [{"id": eid(3, 1), "score": 0.9, "slots": ["rule"]}],
        "anchors": [eid(3, 1)],
        "budget": {"total_calls": 3, "expand_calls": 3},
        "expect": {"ok": False, "error_type": "budget_exhausted"},
    },
    {
        "id": "X11",
        "title": "저장소 오류: tool_error, 예산·풀 그대로",
        "plan": EXPAND_PLAN,
        "store_pages": PAGES,
        "store_error": True,
        "pool": [{"id": eid(3, 1), "score": 0.9, "slots": ["rule"]}],
        "anchors": [eid(3, 1)],
        "expect": {"ok": False, "error_type": "tool_error", "tool_attempts": 1 + cfg.TOOL_MAX_RETRIES,
                   "budget": {"total_calls": 0, "expand_calls": 0}, "pool_size": 1},
    },
    {
        "id": "X12",
        "title": "풀에 없어도 형식이 맞는 앵커 ID는 그대로 사용",
        "plan": EXPAND_PLAN,
        "store_pages": PAGES,
        "anchors": [eid(3, 1)],
        "expect": {"ok": True, "chunk_ids": [eid(3, 0), eid(3, 2)], "new_chunk_ids": [eid(3, 0), eid(3, 2)]},
    },
]
