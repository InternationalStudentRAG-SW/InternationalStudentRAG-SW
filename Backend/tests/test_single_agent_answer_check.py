"""⑤ 답변 검사·영어 검색어 함께 검색 테스트 (2026-10-03 안정성 확인 후 추가, API·DB 호출 없음)."""
import json
from types import SimpleNamespace

from app.core.single_agent import answerer
from app.core.single_agent import checklist_config as cfg
from app.core.single_agent.analysis_schema import QuestionAnalysis
from app.core.single_agent.answer_check import check_answer, drop_units, split_units, join_units
from app.core.single_agent.evidence_schema import EvidenceChunk, EvidencePool, RetrievalTag
from app.core.single_agent.search_schema import SearchPlan
from app.core.single_agent.searcher import execute_search, merge_results

VISA_KO = "1. 사증발급신청서(제17호 서식) 2. 여권 3. 사진 4. 표준입학허가서 5. 사업자등록증명원 6. 송금내역서"
GKS_EN = "9. When the recipient receives three (3) or more warnings. Two (2) academic warnings. 80% attendance"


class FakeClient:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        out = self._outputs.pop(0) if self._outputs else {"answer": "?"}
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20, prompt_tokens_details=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(out, ensure_ascii=False)),
                                                        finish_reason="stop")], usage=usage)


# ── answer_check ─────────────────────────────────────────────────────────

def test_made_up_document_names_are_flagged():
    """2026-10-03 비자 답변: 근거에 없는 '건강보험 가입 증명서'·'재정 증명서'를 [1]과 함께 씀."""
    answer = "비자 서류:\n- 사증발급신청서 [1]\n- 재정 증명서 [1]\n- 건강보험 가입 증명서 [1]\n- 표준 입학 허가서 [1]"
    _, issues = check_answer(answer, {1: VISA_KO})
    assert sorted(i.item for i in issues) == ["건강보험 가입 증명서", "재정 증명서"]
    assert all(i.kind == "document" for i in issues)


def test_numbers_must_appear_in_cited_evidence():
    answer = "경고를 3회 이상 받으면 자격을 잃습니다[1]. 출석률은 90% 이상이어야 합니다[1]."
    _, issues = check_answer(answer, {1: GKS_EN})
    assert [(i.kind, i.item) for i in issues] == [("number", "90")]


def test_known_limit_number_from_other_clause_passes():
    """'경고 2번'은 근거에 'Two (2) academic warnings'가 있어 숫자 검사만으로는 못 잡는다 (프롬프트 규칙으로 줄임)."""
    _, issues = check_answer("경고는 2번 받으면 자격을 잃습니다[1].", {1: GKS_EN})
    assert issues == []


def test_unconfirmed_and_contact_sentences_are_not_checked():
    answer = "사증발급신청서가 필요합니다[1]. 건강보험 가입 증명서는 확인하지 못했습니다. 학교에 문의하세요."
    _, issues = check_answer(answer, {1: VISA_KO})
    assert issues == []


def test_document_check_skipped_for_english_only_evidence():
    _, issues = check_answer("면제 확인서가 필요합니다[1].", {1: "Applicants who completed high school are exempt."})
    assert issues == []


def test_drop_units_keeps_other_sentences_and_moves_trailing_markers():
    answer = "경고를 3회 이상 받으면 자격을 잃습니다. [1] 출석률은 90% 이상이어야 합니다[1]. 나머지는 학교에 문의하세요."
    units, issues = check_answer(answer, {1: GKS_EN})
    kept, dropped = drop_units(units, issues)
    assert kept == "경고를 3회 이상 받으면 자격을 잃습니다[1]. 나머지는 학교에 문의하세요."
    assert dropped == ["출석률은 90% 이상이어야 합니다[1]."]


def test_split_and_join_round_trip_for_bullets():
    text = "서류:\n- 여권 [1]\n- 사진 [1]\n\n문의하세요."
    assert join_units(split_units(text)) == text


# ── ⑤ write_answer: 검사 → 다시 쓰기 → 문장 제거 ─────────────────────────

def _setup(monkeypatch, text=VISA_KO):
    pool = EvidencePool()
    pool.add(EvidenceChunk(evidence_id="s.pdf#p7#c5", source="s.pdf", page=7, chunk_index=5, text=text),
             RetrievalTag(target_slot_id="requested_documents", search_type="new", query_ko="비자 서류"))
    monkeypatch.setattr(answerer, "_evidence_order", lambda a, d, p: ["s.pdf#p7#c5"])
    analysis = QuestionAnalysis(intent_summary="비자 서류", answer_scope="general", next_action="search")
    return analysis, pool


def test_write_answer_rewrites_once_when_check_fails(monkeypatch):
    analysis, pool = _setup(monkeypatch)
    client = FakeClient([{"answer": "- 사증발급신청서 [1]\n- 건강보험 가입 증명서 [1]"},
                         {"answer": "- 사증발급신청서 [1]\n- 송금내역서 [1]"}])
    run = answerer.write_answer("비자 서류?", "answer", analysis=analysis, pool=pool, client=client, model="fake")
    assert client.calls == 2 and run.rewrites == 1
    assert run.answer == "- 사증발급신청서 [1]\n- 송금내역서 [1]"
    assert run.check_issues and "건강보험 가입 증명서" in run.check_issues[0]
    assert run.dropped_sentences == [] and run.prompt_tokens == 200


def test_write_answer_drops_sentence_when_rewrite_still_fails(monkeypatch):
    analysis, pool = _setup(monkeypatch)
    bad = {"answer": "- 사증발급신청서 [1]\n- 건강보험 가입 증명서 [1]"}
    client = FakeClient([bad, bad])
    run = answerer.write_answer("비자 서류?", "answer", analysis=analysis, pool=pool, client=client, model="fake")
    assert client.calls == 2
    assert run.answer == "- 사증발급신청서 [1]"
    assert run.dropped_sentences == ["- 건강보험 가입 증명서 [1]"]


def test_write_answer_no_extra_call_when_clean(monkeypatch):
    analysis, pool = _setup(monkeypatch)
    client = FakeClient([{"answer": "사증발급신청서와 여권이 필요합니다[1]."}])
    run = answerer.write_answer("비자 서류?", "answer", analysis=analysis, pool=pool, client=client, model="fake")
    assert client.calls == 1 and run.rewrites == 0 and run.check_issues == []


def test_write_answer_check_can_be_disabled(monkeypatch):
    analysis, pool = _setup(monkeypatch)
    monkeypatch.setattr(cfg, "ANSWER_CHECK_ENABLED", False)
    client = FakeClient([{"answer": "건강보험 가입 증명서가 필요합니다[1]."}])
    run = answerer.write_answer("비자 서류?", "answer", analysis=analysis, pool=pool, client=client, model="fake")
    assert client.calls == 1 and "건강보험" in run.answer


def test_answer_prompt_has_new_rules():
    p = answerer.SYSTEM_PROMPT
    assert "근거에 적힌 이름 그대로" in p and "서로 다른 조항" in p and "연속 3일 이상 또는 월 누계 5일 이상" in p


# ── 영어 검색어 함께 검색 ─────────────────────────────────────────────────

def _chunk(eid, score):
    src, page, idx = eid.split("#")
    return EvidenceChunk(evidence_id=eid, source=src, page=int(page[1:]), chunk_index=int(idx[1:]),
                         text=eid, score=score)


def test_merge_keeps_top_of_each_language_then_by_score():
    ko = [_chunk(f"k.pdf#p1#c{i}", s) for i, s in enumerate([0.9, 0.8, 0.7, 0.6, 0.5])]
    en = [_chunk(f"e.pdf#p1#c{i}", s) for i, s in enumerate([0.3, 0.2, 0.75, 0.1])]
    out = [c.evidence_id for c in merge_results(ko, en, 5)]
    assert out == ["k.pdf#p1#c0", "k.pdf#p1#c1", "e.pdf#p1#c0", "e.pdf#p1#c1", "e.pdf#p1#c2"]


class _Doc:
    def __init__(self, source, idx, score):
        self.page_content = f"{source} {idx}"
        self.metadata = {"source": source, "page": 6, "chunk_index": idx, "similarity_score": score}


def test_execute_search_runs_english_query_and_caps_top_k():
    calls = []

    def search(q, k):
        calls.append(q)
        if q.startswith("English"):
            return [_Doc("en_track.pdf", 4, 0.95)]
        return [_Doc("ko_track.pdf", i, 0.5 - i * 0.01) for i in range(k)]

    plan = SearchPlan(action="search", target_slot_id="exceptions_related", search_type="new",
                      query_ko="영어 트랙 어학 성적 면제 조건", query_en="English track language requirement exemption")
    pool = EvidencePool()
    run = execute_search(plan, pool, search_fn=search)
    assert run.ok and calls == [plan.query_ko, plan.query_en]
    assert "en_track.pdf#p6#c4" in run.chunk_ids and len(run.chunk_ids) == cfg.SEARCH_TOP_K
    assert any("[영어 검색]" in w for w in run.warnings)


def test_execute_search_english_failure_keeps_korean_results():
    def search(q, k):
        if q.startswith("English"):
            raise RuntimeError("boom")
        return [_Doc("ko_track.pdf", 0, 0.5)]

    plan = SearchPlan(action="search", target_slot_id="rule", search_type="new",
                      query_ko="어학 기준", query_en="English language requirement")
    run = execute_search(plan, EvidencePool(), search_fn=search)
    assert run.ok and run.chunk_ids == ["ko_track.pdf#p6#c0"]
    assert any("[영어 검색 실패]" in w for w in run.warnings)


def test_no_english_query_means_single_search():
    calls = []
    plan = SearchPlan(action="search", target_slot_id="rule", search_type="new", query_ko="어학 기준")
    execute_search(plan, EvidencePool(), search_fn=lambda q, k: calls.append(q) or [])
    assert calls == ["어학 기준"]


def test_planner_passes_query_en(monkeypatch):
    from app.core.single_agent import search_planner as sp
    from app.core.single_agent.analysis_schema import DocSlot, FirstSearch
    analysis = QuestionAnalysis(
        intent_summary="어학 기준", answer_scope="general", primary_type="T1", next_action="search",
        document_slots=[DocSlot(slot_id="rule", requirement="required", active=True, status="unchecked")],
        first_search=FirstSearch(query_ko="어학 기준", query_en="language requirement", target_slot_ids=["rule"]),
    )
    run = sp.plan_search(analysis)
    assert run.plan.query_en == "language requirement"

    client = FakeClient([{"query_ko": "어학 성적 면제", "query_en": "language score exemption", "reason": "r"}])
    from app.core.single_agent.search_schema import SearchAttempt, SearchBudget
    hist = [SearchAttempt(target_slot_id="rule", search_type="new", query_ko="어학 기준", found_new_evidence=False)]
    run2 = sp.plan_search(analysis, budget=SearchBudget(total_calls=1, subqueries=1), history=hist,
                          client=client, model="fake")
    assert run2.plan.query_ko == "어학 성적 면제" and run2.plan.query_en == "language score exemption"


def test_verifier_prompt_requires_original_language_quotes():
    from app.core.single_agent import verifier
    src = open(verifier.__file__, encoding="utf-8").read()
    assert "영어 원문 그대로 인용" in src


# ── ⑤에 사용자 요구 넘기기·근거 없는 칸 숨기기 (쉬운 복합 질문 E1~E3 후 추가) ──────

def _e3_analysis():
    from app.core.single_agent.analysis_schema import DocSlot, EvidenceRef
    return QuestionAnalysis(
        intent_summary="한국어과정 진급 기준", answer_scope="general", primary_type="T5", next_action="search",
        document_slots=[
            DocSlot(slot_id="rule", requirement="required", active=True, status="supported", value="70점·80%",
                    evidence_refs=[EvidenceRef(evidence_id="c.pdf#p2#c11", quote="Grade of 70 points or higher")]),
            DocSlot(slot_id="applicable_scope", requirement="required", active=True, status="partial",
                    value="한국어과정", missing_detail="적용 범위 구체 내용",
                    evidence_refs=[EvidenceRef(evidence_id="c.pdf#p2#c11", quote="Criteria for Passing")]),
            DocSlot(slot_id="full_reason_list", requirement="conditional", active=True, status="unchecked",
                    missing_detail="지각 계산 방법"),
        ])


E3_TEXT = "Attendance 100% (Two tardies = 1 absence) Grade of 70 points or higher and at least an 80% attendance rate. Criteria for Passing"
E3_ASKS = [{"ask_id": "A1", "text": "다음 급 진급 성적·출석 기준", "quote": "성적이랑 출석률이 각각 얼마"},
           {"ask_id": "A2", "text": "지각 계산 방법", "quote": "지각은 어떻게 계산돼"}]


def _e3_pool():
    pool = EvidencePool()
    pool.add(EvidenceChunk(evidence_id="c.pdf#p2#c11", source="c.pdf", page=2, chunk_index=11, text=E3_TEXT),
             RetrievalTag(target_slot_id="rule", search_type="new", query_ko="진급 기준"))
    return pool


def test_answer_prompt_lists_router_asks_and_hides_empty_slots():
    a = _e3_analysis()
    p = answerer.build_user_prompt("질문", "partial_answer", a, None, _e3_pool(), ["c.pdf#p2#c11"], asks=E3_ASKS)
    assert "## 사용자가 물은 것" in p and "- 지각 계산 방법 (질문 속 표현: \"지각은 어떻게 계산돼\")" in p
    label = cfg.DOC_SLOTS["full_reason_list"]["label"]
    assert label not in p                      # 근거 없는 칸은 숨김
    assert "확인 필요: 적용 범위 구체 내용" not in p   # 요구가 있으면 칸 메모도 숨김
    assert "Two tardies = 1 absence" in p      # 원문은 그대로 보여줌


def test_answer_prompt_without_asks_keeps_missing_detail():
    p = answerer.build_user_prompt("질문", "partial_answer", _e3_analysis(), None, _e3_pool(), ["c.pdf#p2#c11"])
    assert "## 사용자가 물은 것" not in p and "확인 필요: 적용 범위 구체 내용" in p


def test_hide_empty_slots_can_be_disabled(monkeypatch):
    monkeypatch.setattr(cfg, "ANSWER_HIDE_EMPTY_SLOTS", False)
    p = answerer.build_user_prompt("질문", "partial_answer", _e3_analysis(), None, _e3_pool(), ["c.pdf#p2#c11"], asks=E3_ASKS)
    assert cfg.DOC_SLOTS["full_reason_list"]["label"] in p and "확인 필요: 적용 범위 구체 내용" in p


def test_partial_mode_guide_limits_unconfirmed_to_user_asks():
    g = answerer.MODE_GUIDE["partial_answer"]
    assert "사용자가 물은 것" in g and "묻지 않은 내부 확인 항목" in g
    assert "원문(영어 원문 포함)" in answerer.SYSTEM_PROMPT


def test_pipeline_passes_route_asks_to_answerer(monkeypatch):
    from app.core.single_agent import pipeline as pl
    from app.core.single_agent.answer_schema import AnswerRun
    from app.core.single_agent.analysis_schema import AnalysisRun
    seen = {}
    monkeypatch.setattr(pl, "analyze_question", lambda *a, **k: AnalysisRun(
        question="q", analysis=QuestionAnalysis(intent_summary="x", answer_scope="general", next_action="out_of_scope")))

    def fake_write(*a, **k):
        seen.update(k)
        return AnswerRun(mode="out_of_scope", answer="안내")

    monkeypatch.setattr(pl, "write_answer", fake_write)
    pl.run_pipeline("q", route_asks=E3_ASKS, client=FakeClient([]))
    assert seen.get("asks") == E3_ASKS


# ── 인용 먼저 쓰기 (facts) ──────────────────────────────────────────────

def test_quote_first_guide_in_prompt_only_with_evidence():
    p = answerer.build_user_prompt("질문", "partial_answer", _e3_analysis(), None, _e3_pool(), ["c.pdf#p2#c11"], asks=E3_ASKS)
    assert "## 출력 방법 (인용 먼저)" in p and '"facts"' in p
    p2 = answerer.build_user_prompt("안녕", "no_retrieval", None, None, None, [])
    assert "인용 먼저" not in p2


def test_facts_are_validated_against_source(monkeypatch):
    monkeypatch.setattr(answerer, "_evidence_order", lambda a, d, p: ["c.pdf#p2#c11"])
    out = {"facts": [{"ask": "지각 계산", "evidence": 1, "quote": "Two tardies = 1 absence"},
                     {"ask": "지각 계산", "evidence": 1, "quote": "지각 2번은 결석 1번"},     # 번역 → 버림
                     {"ask": "x", "evidence": 5, "quote": "Grade of 70 points"}],         # 없는 번호 → 버림
           "answer": "성적 70점 이상, 출석률 80% 이상이 필요하고[1], 지각 2번은 결석 1번으로 계산됩니다[1]."}
    client = FakeClient([out])
    run = answerer.write_answer("질문", "partial_answer", analysis=_e3_analysis(), pool=_e3_pool(),
                                client=client, model="fake", asks=E3_ASKS)
    assert client.calls == 1
    assert [(f["quote"], f["verified"]) for f in run.facts] == [("Two tardies = 1 absence", True),
                                                               ("지각 2번은 결석 1번", False)]
    assert run.facts[0]["evidence_id"] == "c.pdf#p2#c11"
    assert sum("[답변 인용 제거]" in w for w in run.warnings) == 1      # 없는 번호
    assert sum("[답변 인용 불일치]" in w for w in run.warnings) == 1    # 번역 인용
    assert "지각 2번은 결석 1번" in run.answer


def test_answer_without_facts_still_works_and_is_flagged(monkeypatch):
    monkeypatch.setattr(answerer, "_evidence_order", lambda a, d, p: ["c.pdf#p2#c11"])
    client = FakeClient([{"answer": "성적 70점 이상이 필요합니다[1]."}])
    run = answerer.write_answer("질문", "answer", analysis=_e3_analysis(), pool=_e3_pool(), client=client, model="fake")
    assert run.answer == "성적 70점 이상이 필요합니다[1]." and run.facts == []
    assert any("facts" in w for w in run.warnings)


def test_number_words_in_evidence_count_as_numbers():
    _, issues = check_answer("지각 2번은 결석 1번으로 계산됩니다[1]. 경고는 세 번이면[2] 안 됩니다.",
                             {1: "Two tardies = 1 absence", 2: "경고를 세 번 받으면"})
    assert issues == []


def test_sources_come_from_facts_when_answer_has_no_markers(monkeypatch):
    """2026-10-03 E1~E3: ⑤가 번호를 facts에만 적고 answer에 [번호]를 안 붙여 출처가 비어 보였다."""
    monkeypatch.setattr(answerer, "_evidence_order", lambda a, d, p: ["c.pdf#p2#c11"])
    out = {"facts": [{"ask": "지각", "evidence": 1, "quote": "Two tardies = 1 absence"}],
           "answer": "지각 2번은 결석 1번으로 계산됩니다."}
    run = answerer.write_answer("질문", "partial_answer", analysis=_e3_analysis(), pool=_e3_pool(),
                                client=FakeClient([out]), model="fake", asks=E3_ASKS)
    assert [(s.number, s.evidence_id) for s in run.sources] == [(1, "c.pdf#p2#c11")]
    assert any("[보완]" in w for w in run.warnings)


def test_sources_fall_back_to_unverified_fact_numbers(monkeypatch):
    monkeypatch.setattr(answerer, "_evidence_order", lambda a, d, p: ["c.pdf#p2#c11"])
    out = {"facts": [{"ask": "기준", "evidence": 1, "quote": "성적 70점 이상과 출석률 80% 이상"}],
           "answer": "성적 70점 이상, 출석률 80% 이상이 필요합니다."}
    run = answerer.write_answer("질문", "partial_answer", analysis=_e3_analysis(), pool=_e3_pool(),
                                client=FakeClient([out]), model="fake", asks=E3_ASKS)
    assert [s.number for s in run.sources] == [1]
    assert any("원문 대조 안 된" in w for w in run.warnings)


def test_quote_first_guide_requires_markers_in_answer():
    assert "[번호]가 없으면 출처가 표시되지 않습니다" in answerer.QUOTE_FIRST_GUIDE


def test_model_for_answer_uses_answer_model(monkeypatch):
    from app.config import settings
    from app.core.single_agent.llm import model_for
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    monkeypatch.setattr(settings, "answer_model", "")
    assert model_for("answer") == "gpt-4o-mini"
    monkeypatch.setattr(settings, "answer_model", "gpt-4o")
    assert model_for("answer") == "gpt-4o"
    assert model_for("verify") != "gpt-4o" or settings.verify_model == "gpt-4o"
    assert model_for("analyze") == "gpt-4o-mini"


def test_format_sources_keeps_same_chunk_index_on_different_pages(monkeypatch):
    from tests.test_single_agent_router import _load_agent_stream
    format_sources = _load_agent_stream(monkeypatch).format_sources
    from app.core.single_agent.answer_schema import AnswerRun, AnswerSource
    pool = EvidencePool()
    for page in (5, 9):
        pool.add(EvidenceChunk(evidence_id=f"g.pdf#p{page}#c3", source="g.pdf", page=page, chunk_index=3, text="t", score=0.9),
                 RetrievalTag(target_slot_id="rule", search_type="new", query_ko="q"))
    ar = AnswerRun(mode="answer", sources=[AnswerSource(number=1, evidence_id="g.pdf#p5#c3", source="g.pdf", page=5),
                                           AnswerSource(number=4, evidence_id="g.pdf#p9#c3", source="g.pdf", page=9)])
    out = format_sources(SimpleNamespace(answer_run=ar, pool=pool))
    assert len(out) == 2 and [o["chunk_index"] for o in out] == [3, 3]


def test_answer_prompt_keeps_prohibition_across_documents():
    assert "그 금지가 풀린다고 쓰지 않습니다" in answerer.SYSTEM_PROMPT
