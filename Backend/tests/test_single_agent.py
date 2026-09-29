"""단일 에이전트 ①②③④ 규칙 테스트 (API·DB 호출 없음)."""
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


# ── ③ 근거 검색 ────────────────────────────────────────────────────────────

def test_search_exec_scenarios():
    """③ 시나리오 전체: 풀 누적·새 근거 판정·예산 갱신·오류 처리·앞뒤 청크 확장."""
    from evaluate.check_search_execution import run_scenario as run_exec_scenario
    from evaluate.search_exec_scenarios import SCENARIOS as EXEC_SCENARIOS
    failed = [r for r in (run_exec_scenario(s) for s in EXEC_SCENARIOS) if not r["passed"]]
    assert not failed, [(r["id"], [c["message"] for c in r["checks"] if not c["ok"]]) for r in failed]


def test_evidence_id_roundtrip():
    from app.core.single_agent.evidence_schema import make_evidence_id, parse_evidence_id
    eid = make_evidence_id("Study in KOREA! 한국 유학 가이드.pdf", 3, 4)
    assert eid == "Study in KOREA! 한국 유학 가이드.pdf#p3#c4"
    assert parse_evidence_id(eid) == ("Study in KOREA! 한국 유학 가이드.pdf", 3, 4)
    assert parse_evidence_id("엉뚱한 문자열") is None


def test_evidence_pool_add_reports_new_and_keeps_best_score():
    from app.core.single_agent.evidence_schema import EvidenceChunk, EvidencePool, RetrievalTag
    pool = EvidencePool()
    chunk = EvidenceChunk(evidence_id="d.pdf#p1#c0", source="d.pdf", page=1, chunk_index=0, text="본문", score=0.5)
    tag1 = RetrievalTag(target_slot_id="rule", search_type="new", query_ko="검색어 1", round_no=1)
    tag2 = RetrievalTag(target_slot_id="applicable_scope", search_type="new", query_ko="검색어 2", round_no=2)
    assert pool.add(chunk, tag1) is True
    lower = chunk.model_copy(update={"score": 0.1})
    assert pool.add(lower, tag2) is False
    stored = pool.get("d.pdf#p1#c0")
    assert stored.score == 0.5 and [t.target_slot_id for t in stored.tags] == ["rule", "applicable_scope"]


def test_searcher_import_does_not_load_heavy_retriever():
    """searcher를 import만 해서는 retriever(BM25 색인·reranker 로드)가 import되지 않아야 한다."""
    import subprocess
    import sys
    from pathlib import Path
    backend_dir = Path(__file__).resolve().parents[1]
    code = "import sys; import app.core.single_agent.searcher; sys.exit(1 if 'app.core.retriever' in sys.modules else 0)"
    result = subprocess.run([sys.executable, "-c", code], cwd=backend_dir, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# ── ④ 충분성 검증 ──────────────────────────────────────────────────────────

def test_verify_scenarios():
    """④ 시나리오 전체: 인용 대조·상태 강등·missing/unchecked 구분·사용자 칸·다음 행동."""
    from evaluate.check_verification import run_scenario as run_verify_scenario
    from evaluate.verify_scenarios import SCENARIOS as VERIFY_SCENARIOS
    failed = [r for r in (run_verify_scenario(s) for s in VERIFY_SCENARIOS) if not r["passed"]]
    assert not failed, [(r["id"], [c["message"] for c in r["checks"] if not c["ok"]]) for r in failed]


def test_verify_decision_actions_are_defined():
    """decide()가 돌려줄 수 있는 행동은 모두 설정에 정의돼 있어야 한다."""
    import re
    from pathlib import Path
    from app.core.single_agent import checklist_config as cfg
    src = (Path(__file__).resolve().parents[1] / "app/core/single_agent/verifier.py").read_text(encoding="utf-8")
    used = set(re.findall(r'next_action="([a-z_]+)"', src))
    assert used and used <= set(cfg.VERIFY_ACTIONS), used - set(cfg.VERIFY_ACTIONS)


def test_docslot_evidence_fields_default_empty():
    """① 단계 출력에는 근거 필드가 비어 있어야 한다 (기존 분석 JSON과 호환)."""
    from app.core.single_agent.analysis_schema import DocSlot
    s = DocSlot(slot_id="rule", active=True, requirement="required")
    assert s.evidence_refs == [] and s.value == "" and s.missing_detail == ""


def test_verify_replay_real_mini_output_on_live_pool(capsys):
    """
    2026-09-29 실제 gpt-4o-mini 출력(판정이 청크 하나에 몰림)을 --live 경로로 재생한다.
    적용 범위가 한 갈래만 인용했으므로 서버가 partial로 낮추고, 검색 안 한 예외 칸은 unchecked로 둔다.
    """
    import json
    from pathlib import Path
    from evaluate.check_verification import FakeClient, run_live
    fx = Path(__file__).resolve().parent / "fixtures"
    raw = json.loads((fx / "verify_llm_output_gks_mini.json").read_text(encoding="utf-8"))["raw_output"]
    [s] = run_live(str(fx / "search_execution_live_gks.json"), models=["fake"], client=FakeClient([raw]), save=False)
    assert s["error"] is None and s["removed_refs"] == 0
    assert s["statuses"]["applicable_scope"] == "partial"
    assert s["statuses"]["exceptions_related"] == "unchecked"
    assert s["next_action"] == "continue_search"


def test_verify_live_path_all_chunks_shown_for_small_pool():
    """풀이 상한(20)보다 작으면 --live는 풀 전체를 보여준다 (놓친 청크가 없도록)."""
    from pathlib import Path
    from evaluate.check_verification import load_live
    from app.core.single_agent.verifier import select_chunks
    fx = Path(__file__).resolve().parent / "fixtures" / "search_execution_live_gks.json"
    _, analysis, pool, _, _ = load_live(fx)
    assert set(select_chunks(analysis, pool, None)) == set(pool.chunks)


def test_dev_pipeline_collect_then_verify(tmp_path, monkeypatch):
    """
    개발용 흐름 전체를 가짜 LLM·가짜 검색으로 돌린다:
    collect_round1(①②③ 첫 바퀴) → 파일 저장 → run_dev(④) → 비교표 행.
    ①이 검색하지 않는 질문(clarify)도 파일은 남고 ④에서 건너뛰는지 확인한다.
    """
    import json
    from evaluate import check_verification as cv
    from evaluate.check_search_execution import FakeSearch, FakeStore, collect_round1

    analysis = {
        "intent_summary": "GKS 아르바이트 가능 여부", "answer_scope": "general", "primary_type": "T5",
        "additional_types": [], "conditions": [], "user_slots": [],
        "document_slots": [{"slot_id": "rule", "active": True, "requirement": "required", "status": "unchecked"}],
        "first_search": {"query_ko": "GKS 아르바이트", "target_slot_ids": ["rule"]},
        "next_action": "search",
    }
    clarify = {"intent_summary": "목적 불명확", "answer_scope": "general", "primary_type": None,
               "next_action": "clarify_scope", "clarification_question": "어떤 서류요?"}
    search = FakeSearch([{"source": "d.pdf", "page": 1, "chunk_index": 0, "text": "Part-time work requires approval.", "score": 0.9}])
    store = FakeStore({"d.pdf": {1: ["Part-time work requires approval.", "Limited to 20 hours per week."]}})

    rec = collect_round1("GKS 장학생은 아르바이트할 수 있어?", verbose=False, model="fake",
                         client=cv.FakeClient(analysis), search_fn=search, store=store)
    assert rec["stopped"] is None and len(rec["runs"]) == 2
    assert set(rec["pool"]["chunks"]) == {"d.pdf#p1#c0", "d.pdf#p1#c1"}   # 검색 1 + 확장 1
    rec2 = collect_round1("서류 알려줘", verbose=False, model="fake", client=cv.FakeClient(clarify))
    assert rec2["stopped"] == "no_search: clarify_scope" and rec2["runs"] == []

    monkeypatch.setattr(cv, "DEV_POOL_DIR", tmp_path)
    (tmp_path / "D1.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "D2.json").write_text(json.dumps(rec2, ensure_ascii=False), encoding="utf-8")
    verdict = {"slot_verdicts": [{"slot_id": "rule", "status": "supported",
                                  "evidence_refs": [{"evidence_id": "d.pdf#p1#c0", "quote": "requires approval"}]}]}
    rows = cv.run_dev(models=["fake"], repeat=1, client=cv.FakeClient(verdict), save=False)
    assert [r["label"] for r in rows] == ["D1", "D2"]
    # ①의 서버 검증이 T5의 나머지 칸을 기본값으로 채우므로, rule만 확인되고 나머지 필수 칸은 남는다
    assert rows[0]["statuses"]["rule"] == "supported" and rows[0]["statuses"]["exceptions_related"] == "unchecked"
    assert rows[0]["next_action"] == "continue_search"
    assert rows[1]["skipped"] == "no_search: clarify_scope"
    # --dev 결과에 LLM 원문·서버 경고·실행 기록 전체가 남아야 원인 분석이 가능하다 (0-3)
    assert rows[0]["raw_outputs"] and '"requires approval"' in rows[0]["raw_outputs"][0]
    assert isinstance(rows[0]["warnings"], list)
    assert rows[0]["run"]["analysis"]["document_slots"][0]["evidence_refs"][0]["quote"] == "requires approval"


def test_dev_gold_is_well_formed():
    """정답 초안의 칸·사용자 칸·다음 행동·청크 ID가 설정과 형식에 맞는지 (오타 방지)."""
    from app.core.single_agent import checklist_config as cfg
    from app.core.single_agent.evidence_schema import parse_evidence_id
    from evaluate.dev_questions import DEV_QUESTIONS
    assert [q["id"] for q in DEV_QUESTIONS] == [f"D{i}" for i in range(1, 10)]
    for q in DEV_QUESTIONS:
        r1 = q["gold"]["round1"]
        for slot, allowed in r1["slots"].items():
            assert slot in cfg.DOC_SLOTS, (q["id"], slot)
            assert set(allowed) <= set(cfg.DOC_SLOT_STATUSES), (q["id"], allowed)
        for slot in list(r1["must_cite"]) + [s for s in r1["must_not_cite"] if s != "*"]:
            assert slot in cfg.DOC_SLOTS, (q["id"], slot)
        ids = [i for grps in r1["must_cite"].values() for g in grps for i in g]
        ids += [i for v in r1["must_not_cite"].values() for i in v] + q["gold"]["final"]["outside_pool"]
        assert all(parse_evidence_id(i) for i in ids), q["id"]
        assert set(r1["user_fields"]) <= set(cfg.USER_FIELDS), q["id"]
        assert set(r1["next_action"]) <= set(cfg.VERIFY_ACTIONS), q["id"]


def test_dev_scoring_counts_misses():
    from evaluate.dev_scoring import score_row
    gold = {"slots": {"rule": ["supported"], "applicable_scope": ["supported"]},
            "must_cite": {"rule": [["a#p1#c0"], ["a#p2#c0", "b#p2#c0"]]},
            "must_not_cite": {"*": ["x#p9#c9"]},
            "user_fields": ["gks_stage"], "next_action": ["answer_by_condition"]}
    perfect = {"statuses": {"rule": "supported", "applicable_scope": "supported"},
               "refs": {"rule": ["a#p1#c0", "b#p2#c0"], "applicable_scope": ["a#p1#c0"]},
               "user_active": ["gks_stage"], "next_action": "answer_by_condition"}
    s = score_row(perfect, gold)
    assert s["misses"] == [] and s["cite"] == {"pass": 2, "total": 2} and s["not_cite"]["pass"] == 2
    bad = {"statuses": {"rule": "supported", "applicable_scope": "partial"},
           "refs": {"rule": ["a#p1#c0"], "applicable_scope": ["x#p9#c9"]},
           "user_active": [], "next_action": "answer"}
    s = score_row(bad, gold)
    assert s["slots"]["pass"] == 1 and s["cite"]["pass"] == 1 and s["users"]["pass"] == 0 and s["action"]["pass"] == 0
    assert any("엉뚱한 근거" in m for m in s["misses"])


def test_quote_match_ignores_table_markup():
    """표 기호·<br>·마크다운·공백 차이는 무시하고 비교한다 (0-2)."""
    from app.core.single_agent.text_match import quote_in_text
    chunk = " |**Tuition Fee**<br>1,300,000 KRW per semester<br>(excluding fee)|"
    assert quote_in_text("Tuition Fee 1,300,000 KRW per semester", chunk)
    assert quote_in_text("tuition fee: 1,300,000 KRW", chunk)
    assert not quote_in_text("Tuition Fee 1,500,000 KRW", chunk)


def test_quote_match_rejects_empty_and_keeps_other_languages():
    """기호만 있는 인용은 빈 문자열이 되므로 거부하고, 한·영 외 언어 인용은 그대로 비교한다."""
    from app.core.single_agent.text_match import normalize, quote_in_text
    assert not quote_in_text("", "아무 본문")
    assert not quote_in_text("|<br>**", "아무 본문 | <br>")
    assert normalize("我是GKS奖学生") == "我是gks奖学生"
    assert quote_in_text("GKS奖学生", "你好, 我是 GKS 奖学生。")
    assert not quote_in_text("研究生", "你好, 我是 GKS 奖学生。")
    assert quote_in_text("Tôi là sinh viên", "Xin chào, tôi là sinh viên GKS")
    assert not quote_in_text("GKS", "GKS 장학생", min_chars=4)


def test_analyzer_condition_quote_ignores_punctuation():
    """① 조건 인용도 같은 정규화를 쓴다 (문장부호 차이로 조건을 버리지 않음)."""
    q = "저, GKS 장학생인데요! 아르바이트 돼요?"
    out, w = validate_analysis(_search_analysis([_cond("user_self", "저 GKS 장학생인데요")]), number_messages(q, []))
    assert [c.field_id for c in out.conditions] == ["gks_status"]


# ── 2단계 기반: llm.py 통합·VERIFY_MODEL·①조건부 칸·④ 프롬프트 ─────────────────

def test_analyzer_keeps_conditional_slot_open_instead_of_not_triggered():
    """① 단계는 문서 근거가 없으므로 조건부 칸을 not_triggered로 끄지 못한다 (1-6)."""
    a = _search_analysis([])
    a.document_slots = [DocSlot(slot_id="approval_reporting", active=False, requirement="conditional",
                                activation_state="not_triggered")]
    out, w = validate_analysis(a, number_messages("GKS 장학생 아르바이트 돼?", []))
    slot = next(s for s in out.document_slots if s.slot_id == "approval_reporting")
    assert slot.active is True and slot.activation_state == "unresolved"
    assert any("not_triggered 불가" in x for x in w)


def _verify_inputs():
    from evaluate.check_verification import build_inputs
    from evaluate.verify_scenarios import B1, BASE_POOL, FIRST
    return build_inputs({"pool": BASE_POOL, "history": FIRST, "budget": B1})


class _FlakyClient:
    """처음 fail_times번은 API 오류, 그다음은 정해 둔 응답(finish_reason 지정 가능)을 차례로 돌려준다."""

    def __init__(self, responses, fail_times=0):
        import json
        from types import SimpleNamespace
        self._ns, self._json = SimpleNamespace, json
        self.responses, self.fail_times, self.calls, self.max_tokens = responses, fail_times, 0, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls += 1
        self.max_tokens.append(kw.get("max_tokens"))
        if self.calls <= self.fail_times:
            raise TimeoutError("가짜 타임아웃")
        content, finish = self.responses[min(self.calls - self.fail_times - 1, len(self.responses) - 1)]
        if isinstance(content, dict):
            content = self._json.dumps(content, ensure_ascii=False)
        ns = self._ns
        return ns(choices=[ns(message=ns(content=content), finish_reason=finish)],
                  usage=ns(prompt_tokens=1, completion_tokens=1))


def test_llm_api_error_is_retried_once(monkeypatch):
    from app.core.single_agent import llm
    from app.core.single_agent.verifier import verify_evidence
    from evaluate.verify_scenarios import ALL_GOOD
    monkeypatch.setattr(llm, "API_RETRY_WAIT_S", 0)
    analysis, pool, history, budget = _verify_inputs()
    fake = _FlakyClient([({"slot_verdicts": ALL_GOOD}, "stop")], fail_times=1)
    run = verify_evidence(analysis, pool, budget, history, model="fake", client=fake)
    assert run.error is None and run.decision.next_action == "answer"
    assert fake.calls == 2 and run.attempts == 1
    assert any(w.startswith("[API 재시도]") for w in run.warnings)


def test_llm_api_error_gives_up_after_retries(monkeypatch):
    from app.core.single_agent import llm
    from app.core.single_agent.verifier import verify_evidence
    monkeypatch.setattr(llm, "API_RETRY_WAIT_S", 0)
    analysis, pool, history, budget = _verify_inputs()
    fake = _FlakyClient([("{}", "stop")], fail_times=99)
    run = verify_evidence(analysis, pool, budget, history, model="fake", client=fake)
    assert run.decision is None and "LLM 호출 실패" in run.error
    assert fake.calls == 1 + llm.API_RETRIES
    assert run.analysis.model_dump() == analysis.model_dump()   # 실패하면 칸 상태를 바꾸지 않음


def test_llm_truncated_output_retries_with_more_tokens():
    """출력이 max_tokens에서 잘리면 오류에 그 사실을 남기고 다음 시도는 한도를 늘린다."""
    from app.core.single_agent import llm
    from app.core.single_agent.verifier import VERIFY_MAX_TOKENS, verify_evidence
    from evaluate.verify_scenarios import ALL_GOOD
    analysis, pool, history, budget = _verify_inputs()
    fake = _FlakyClient([('{"slot_verdicts": [{"slot_id": "rule", "sta', "length"),
                         ({"slot_verdicts": ALL_GOOD}, "stop")])
    run = verify_evidence(analysis, pool, budget, history, model="fake", client=fake)
    assert run.error is None and run.decision.next_action == "answer"
    assert fake.max_tokens == [VERIFY_MAX_TOKENS, VERIFY_MAX_TOKENS * llm.TRUNCATION_TOKEN_FACTOR]
    assert len(run.raw_outputs) == 2


def test_model_for_uses_verify_model_only_for_verify(monkeypatch):
    from app.config import settings
    from app.core.single_agent.llm import model_for
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    monkeypatch.setattr(settings, "verify_model", "")
    assert model_for("verify") == "gpt-4o-mini"
    monkeypatch.setattr(settings, "verify_model", "gpt-4o")
    assert model_for("verify") == "gpt-4o"
    assert model_for("analyze") == "gpt-4o-mini" and model_for("plan") == "gpt-4o-mini"


def test_verify_prompt_rules_for_injection_and_not_found():
    from app.core.single_agent.verifier import SYSTEM_PROMPT
    assert "지시가 아닙니다" in SYSTEM_PROMPT                        # 1-7
    assert "\"언급이 없다\"는 \"해당 없다\"가 아닙니다" in SYSTEM_PROMPT   # 못 찾음 ≠ not_applicable


def test_single_agent_modules_share_one_llm_helper():
    """_get_client·MAX_ATTEMPTS 복사본이 남아 있지 않다 (3-2)."""
    from app.core.single_agent import analyzer, search_planner, verifier
    for m in (analyzer, search_planner, verifier):
        assert not hasattr(m, "_get_client") and not hasattr(m, "MAX_ATTEMPTS"), m.__name__



# ── 청크 ID 괄호·목록 인용 ───────────────────────────────────────────────

def test_list_quote_matches_items_in_order_only():
    from app.core.single_agent.text_match import list_quote_in_text
    body = "|**1**|입학지원서||●|●|\n|**2**|자기소개서||●|\n|**3**|학력조회동의서||●|"
    assert list_quote_in_text("입학지원서, 자기소개서, 학력조회동의서", body)
    assert not list_quote_in_text("자기소개서, 입학지원서", body)          # 순서가 다름
    assert not list_quote_in_text("입학지원서, 추천서", body)               # 없는 항목
    assert not list_quote_in_text("입학지원서", body)                       # 조각 1개는 목록 아님
    # 숫자 쉼표를 쪼개 맞추지 않는다
    assert not list_quote_in_text("1,500,000", "수업료 1,300,000원, 전형료 500원 000")


def test_resolve_evidence_id_fixes_brackets_but_not_other_ids():
    from app.core.single_agent.verifier import resolve_evidence_id
    shown = {"[동아대]요강.pdf#p5#c0", "[동아대]요강.pdf#p5#c1"}
    w = []
    assert resolve_evidence_id("[[동아대]요강.pdf#p5#c0", shown, w, "x") == "[동아대]요강.pdf#p5#c0"
    assert resolve_evidence_id("[[동아대]요강.pdf#p5#c1]", shown, w, "x") == "[동아대]요강.pdf#p5#c1"
    assert resolve_evidence_id("청크 ID: [동아대]요강.pdf#p5#c0", shown, w, "x") == "[동아대]요강.pdf#p5#c0"
    assert resolve_evidence_id("[동아대]요강.pdf#p5#c9", shown, w, "x") is None
    assert len(w) == 3


def test_verify_prompt_chunk_header_has_no_brackets():
    from app.core.single_agent.verifier import build_user_prompt, judge_targets
    analysis, pool, _, _ = _verify_inputs()
    cid = next(iter(pool.chunks))
    prompt = build_user_prompt(analysis, judge_targets(analysis), [cid], pool, "질문")
    assert f"### 청크 ID: {cid}\n" in prompt and f"[{cid}]" not in prompt


# ── 청크 메모: 대상 한정(1-1)·갈래 감지(1-3)·갈래 저장(1-5) ─────────────────

def _run_verify(llm_output, conditions=None, analysis=None):
    from evaluate.check_verification import FakeClient, build_inputs
    from evaluate.verify_scenarios import B1, BASE_POOL, FIRST
    from app.core.single_agent.verifier import verify_evidence
    a0, pool, history, budget = build_inputs(
        {"pool": BASE_POOL, "history": FIRST, "budget": B1, "conditions": conditions or []})
    return verify_evidence(analysis or a0, pool, budget, history, model="fake", client=FakeClient(llm_output))


def _note(page, idx, applies=(), rel=("rule",)):
    from evaluate.verify_scenarios import gid
    return {"evidence_id": gid(page, idx), "applies_to": [{"field_id": f, "value": v} for f, v in applies],
            "relevant_slots": list(rel)}


def _verdicts(scope_pages):
    from evaluate.verify_scenarios import ALL_GOOD, ref, v
    quotes = {(11, 0): "A GKS recipient in a degree program", (10, 3): "A GKS recipient in the Korean language program"}
    scope = v("applicable_scope", "supported", [ref(p, i, quotes[(p, i)]) for p, i in scope_pages])
    return [ALL_GOOD[0], scope] + ALL_GOOD[2:]


STAGE_NOTES = [_note(11, 0, [("gks_stage", "학위과정")], ("rule", "applicable_scope")),
               _note(10, 3, [("gks_stage", "어학연수")], ("rule", "applicable_scope"))]


def test_notes_detect_branches_and_lower_scope_citing_one_branch():
    """1-3: 청크 메모의 적용 대상 값이 둘이면 갈래. 적용 범위가 한 갈래만 인용하면 partial."""
    run = _run_verify({"chunk_notes": STAGE_NOTES, "slot_verdicts": _verdicts([(11, 0)])})
    a = run.analysis
    scope = next(s for s in a.document_slots if s.slot_id == "applicable_scope")
    u = next(u for u in a.user_slots if u.field_id == "gks_stage")
    assert scope.status == "partial" and "어학연수" in scope.missing_detail
    assert u.active and [b.value for b in u.branches] == ["학위과정", "어학연수"]
    assert all(b.source == "notes" for b in u.branches)
    assert run.decision.next_action == "continue_search"
    assert any(w.startswith("[갈래] gks_stage") for w in run.warnings)


def test_notes_branches_with_full_scope_give_answer_by_condition():
    run = _run_verify({"chunk_notes": STAGE_NOTES, "slot_verdicts": _verdicts([(11, 0), (10, 3)])})
    d = run.decision
    assert d.next_action == "answer_by_condition" and d.condition_field_ids == ["gks_stage"]
    assert d.condition_branches["gks_stage"] == ["학위과정", "어학연수"]


def test_notes_single_target_marks_scope_partial():
    """1-1: 인용된 근거가 전부 한 대상(GKS 장학생) 규정이면 적용 범위 partial + 그 조건을 연다."""
    gks = [("gks_status", "GKS 장학생")]
    notes = [_note(11, 0, gks), _note(10, 3, gks), _note(10, 4, gks), _note(11, 2, gks)]
    run = _run_verify({"chunk_notes": notes, "slot_verdicts": _verdicts([(11, 0), (10, 3)])})
    a = run.analysis
    scope = next(s for s in a.document_slots if s.slot_id == "applicable_scope")
    u = next(u for u in a.user_slots if u.field_id == "gks_status")
    assert scope.status == "partial" and "gks_status=GKS 장학생" in scope.missing_detail
    assert u.active and u.branches[0].value == "GKS 장학생"
    assert any("[대상 한정]" in w for w in run.warnings)


def test_notes_ignore_confirmed_condition_and_unrelated_chunks():
    """질문이 이미 대상을 밝혔으면(조건 확인됨) 대상 한정이 아니다. 관련 없는 청크의 값은 갈래로 치지 않는다."""
    gks = [("gks_status", "GKS 장학생")]
    cond = [{"field_id": "gks_status", "value": "GKS 장학생", "subject": "question_target", "status": "confirmed",
             "source_message_id": "m1", "quote": "GKS 장학생"}]
    notes = [_note(11, 0, gks), _note(10, 3, gks), _note(10, 4, gks), _note(11, 2, gks),
             _note(10, 9, [("gks_stage", "졸업생")], rel=()),              # 인용·관련 없음
             _note(11, 0, [("없는칸", "x")])]                              # 중복·정의 안 된 칸
    run = _run_verify({"chunk_notes": notes, "slot_verdicts": _verdicts([(11, 0), (10, 3)])}, conditions=cond)
    a = run.analysis
    assert next(s for s in a.document_slots if s.slot_id == "applicable_scope").status == "supported"
    assert not any(u.active for u in a.user_slots)
    assert run.decision.next_action == "answer"


def test_branches_persist_to_next_round():
    """1-5: 다음 라운드 LLM이 갈래를 다시 적지 않아도 저장된 갈래로 조건별 안내를 한다."""
    from evaluate.verify_scenarios import ALL_GOOD, v
    r1 = _verdicts([(11, 0), (10, 3)])
    r1[2] = v("conditions_limits", "partial", [r1[2]["evidence_refs"][0]], activation_state="triggered")
    run1 = _run_verify({"chunk_notes": STAGE_NOTES, "slot_verdicts": r1})
    assert run1.decision.next_action == "continue_search"
    run2 = _run_verify({"slot_verdicts": [ALL_GOOD[2]]}, analysis=run1.analysis)   # 메모·갈래 없이 한 칸만 판정
    d = run2.decision
    assert d.next_action == "answer_by_condition"
    assert d.condition_branches["gks_stage"] == ["학위과정", "어학연수"]


def test_llm_user_field_needs_are_stored_as_branches():
    from evaluate.verify_scenarios import ALL_GOOD, STAGE_NEED
    run = _run_verify({"slot_verdicts": ALL_GOOD, "user_field_needs": [STAGE_NEED]})
    u = next(u for u in run.analysis.user_slots if u.field_id == "gks_stage")
    assert [(b.value, b.summary, b.source) for b in u.branches] == [
        ("학위과정", "총장 승인 시 가능", "llm"), ("한국어연수", "6개월 이후 방학 중", "llm")]
    assert "갈래:" not in u.reason     # 예전처럼 reason에 누적하지 않음


# ── 문서별 기본 대상(DOC_SCOPES)·질문이 가리킨 대상 ─────────────────────────

KOT_SRC = "[동아대]2026학년도+후기+학부+외국인+신(편)입학+특별전형+모집요강_한국어트랙.pdf"
ENT_SRC = "[Dong-A+univ]2026+FALL+Admission+Guidelines_English+track+for+the+Undergraduates_English+Track.pdf"
KLC_SRC = "English_2026-2027+Korean+Language+Course.pdf"


def _run_docs(pool_items, verdicts, notes=None, question=""):
    from evaluate.check_verification import FakeClient, build_inputs
    from evaluate.verify_scenarios import B1, FIRST
    from app.core.single_agent.verifier import verify_evidence
    a, pool, history, budget = build_inputs({"pool": pool_items, "history": FIRST, "budget": B1})
    out = {"slot_verdicts": verdicts, "chunk_notes": notes or []}
    return verify_evidence(a, pool, budget, history, question=question, model="fake", client=FakeClient(out))


def _scope_verdicts(ids_quotes):
    from evaluate.verify_scenarios import v
    refs = [{"evidence_id": i, "quote": q} for i, q in ids_quotes]
    return [v("rule", "supported", refs[:1]), v("applicable_scope", "supported", refs)]


def test_doc_scopes_find_track_branch_even_without_llm_notes():
    """D2 재현: LLM이 청크 메모에 트랙을 안 적어도 문서 이름으로 track 갈래를 찾는다."""
    k, e = f"{KOT_SRC}#p5#c0", f"{ENT_SRC}#p5#c0"
    pool = [{"id": k, "text": "모집기간 2026.4.1.(수) ~ 4.14.(화)"}, {"id": e, "text": "Application period April 1 ~ April 14"}]
    run = _run_docs(pool, _scope_verdicts([(k, "2026.4.1.(수) ~ 4.14.(화)"), (e, "Application period April 1")]),
                    question="동아대학교 2026년 가을학기 지원 기간이 언제예요?")
    u = next(u for u in run.analysis.user_slots if u.field_id == "track")
    assert u.active and sorted(b.value for b in u.branches) == ["영어트랙", "한국어트랙"]


def test_doc_scopes_unify_llm_value_and_question_alias_skips_target_rule():
    """LLM 표기('Korean Language Course')는 문서 값으로 통일, 질문이 '어학당'을 가리키면 대상 한정을 적용하지 않는다."""
    c = f"{KLC_SRC}#p2#c1"
    pool = [{"id": c, "text": "Tuition Fee 1,300,000 KRW per semester"}]
    notes = [{"evidence_id": c, "applies_to": [{"field_id": "program", "value": "Korean Language Course"}],
              "relevant_slots": ["rule"]}]
    verdicts = _scope_verdicts([(c, "Tuition Fee 1,300,000 KRW per semester")])
    run = _run_docs(pool, verdicts, notes, question="한국어학당 수업료가 얼마예요?")
    assert [a.value for a in run.chunk_notes[0].applies_to] == ["어학연수"]
    assert next(s for s in run.analysis.document_slots if s.slot_id == "applicable_scope").status == "supported"
    assert not any(u.active for u in run.analysis.user_slots)
    # 질문이 대상을 가리키지 않으면(비자 서류) 어학당 자료만으로 답한 것 → 대상 한정
    run2 = _run_docs(pool, verdicts, notes, question="What documents do I need to apply for a student visa?")
    assert next(s for s in run2.analysis.document_slots if s.slot_id == "applicable_scope").status == "partial"
    assert next(u for u in run2.analysis.user_slots if u.field_id == "program").active


# ── 1-2 근거 빠뜨림: 관련 있다고 적고 인용 안 한 청크 → 1회 재판정 ─────────────

def _recheck_inputs():
    from evaluate.verify_scenarios import ALL_GOOD, ref, v
    first = {"chunk_notes": [_note(11, 0, rel=("rule",)), _note(10, 4, rel=("rule", "conditions_limits"))],
             "slot_verdicts": ALL_GOOD}    # rule은 11,0만 인용 → 10,4 빠뜨림
    fixed = v("rule", "supported", [ref(10, 4, "part-time employment shall not exceed twenty (20) hours per week")])
    return first, fixed


def test_recheck_adds_missed_evidence_and_keeps_old_refs():
    from evaluate.check_verification import FakeClient, build_inputs
    from evaluate.verify_scenarios import B1, BASE_POOL, FIRST, gid
    from app.core.single_agent.verifier import verify_evidence
    first, fixed = _recheck_inputs()
    a, pool, history, budget = build_inputs({"pool": BASE_POOL, "history": FIRST, "budget": B1})
    fake = FakeClient([first, {"slot_verdicts": [fixed]}])
    run = verify_evidence(a, pool, budget, history, model="fake", client=fake)
    rule = next(s for s in run.analysis.document_slots if s.slot_id == "rule")
    assert fake.calls == 2 and run.recheck_slot_ids == ["rule"]
    assert [r.evidence_id for r in rule.evidence_refs] == [gid(11, 0), gid(10, 4)]   # 기존 근거 유지 + 추가
    assert rule.status == "supported" and any(w.startswith("[재확인] rule") for w in run.warnings)
    assert run.error is None and run.decision.next_action == "answer"


def test_recheck_failure_marks_supported_slot_partial():
    from evaluate.check_verification import FakeClient, build_inputs
    from evaluate.verify_scenarios import B1, BASE_POOL, FIRST
    from app.core.single_agent.verifier import verify_evidence
    first, _ = _recheck_inputs()
    a, pool, history, budget = build_inputs({"pool": BASE_POOL, "history": FIRST, "budget": B1})
    run = verify_evidence(a, pool, budget, history, model="fake", client=FakeClient([first, "JSON 아님", "또 아님"]))
    rule = next(s for s in run.analysis.document_slots if s.slot_id == "rule")
    assert rule.status == "partial" and "재확인 실패" in rule.missing_detail
    assert run.error is None and run.decision.next_action == "continue_search"


def test_no_recheck_when_all_relevant_chunks_cited():
    from evaluate.check_verification import FakeClient, build_inputs
    from evaluate.verify_scenarios import ALL_GOOD, B1, BASE_POOL, FIRST
    from app.core.single_agent.verifier import verify_evidence
    a, pool, history, budget = build_inputs({"pool": BASE_POOL, "history": FIRST, "budget": B1})
    fake = FakeClient([{"chunk_notes": [_note(11, 0, rel=("rule",))], "slot_verdicts": ALL_GOOD}])
    run = verify_evidence(a, pool, budget, history, model="fake", client=fake)
    assert fake.calls == 1 and run.recheck_slot_ids == []
