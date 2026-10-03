"""⓪ 라우터·안전장치·기본 RAG 스트리밍 규칙 테스트 (API·DB 호출 없음)."""
import asyncio
import importlib
import json
import sys
import types
from types import SimpleNamespace

import pytest

from app.core.single_agent import checklist_config as cfg
from app.core.single_agent.analyzer import number_messages
from app.core.single_agent.escalation import check_escalation
from app.core.single_agent.router import RouteFormatError, decide_route, route_question, validate_route
from app.core.single_agent.router_schema import Ask, RouteCondition, RouteResult

D8 = "저 GKS 장학생인데 아르바이트 해도 돼요? 된다면 어떤 서류를 어디에 내야 해요?"
KO_TRACK = "2026 모집요강_한국어트랙.pdf"
EN_TRACK = "2026 Admission Guide English+Track.pdf"


class FakeClient:
    """정해 둔 출력을 차례로 돌려주는 OpenAI 클라이언트 흉내."""

    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        out = self._outputs.pop(0) if self._outputs else "{}"
        content = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20, prompt_tokens_details=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content),
                                                        finish_reason="stop")], usage=usage)


def _ask(i, quote, kind="T5", deps=(), query="검색어", only_if=""):
    return Ask(ask_id=f"A{i}", text=f"요구{i}", quote=quote, kind=kind, query_ko=query,
               depends_on=list(deps), only_if=only_if)


def _validated(result, question, history=None):
    r, w = validate_route(result, number_messages(question, history or []))
    return decide_route(r), w


D8_OUTPUT = {
    "action": "search",
    "asks": [
        {"ask_id": "A1", "text": "허용 여부", "quote": "아르바이트 해도 돼요", "kind": "T5",
         "query_ko": "GKS 장학생 시간제 취업 허용 기준", "depends_on": [], "only_if": ""},
        {"ask_id": "A2", "text": "서류와 제출처", "quote": "어떤 서류를 어디에 내야 해요", "kind": "T3",
         "query_ko": "#A1 GKS 시간제 취업 신청 서류", "depends_on": ["A1"], "only_if": "A1이 허용일 때"},
    ],
    "user_conditions": [{"field_id": "gks_status", "value": "예", "subject": "user_self",
                         "source_message_id": "m1", "quote": "저 GKS 장학생인데"}],
}


# ── 경로 규칙 ────────────────────────────────────────────────────────────

def test_d8_goes_to_agent_with_all_reasons():
    r, w = _validated(RouteResult.model_validate(D8_OUTPUT), D8)
    assert r.route == "agent"
    joined = " ".join(r.route_reasons)
    assert "요구 2개" in joined and "의존" in joined
    assert r.asks[1].depends_on == ["A1"] and not w


def test_single_ask_without_condition_goes_simple():
    q = "GKS 장학생은 아르바이트할 수 있어?"
    r, _ = _validated(RouteResult(action="search", asks=[_ask(1, "아르바이트할 수 있어")]), q)
    assert r.route == "simple"


def test_agent_kinds_rule_is_configurable(monkeypatch):
    q = "GKS 장학생은 아르바이트할 수 있어?"
    monkeypatch.setattr(cfg, "ROUTER_AGENT_KINDS", {"T5"})
    r, _ = _validated(RouteResult(action="search", asks=[_ask(1, "아르바이트할 수 있어", kind="T5")]), q)
    assert r.route == "agent" and "T5" in r.route_reasons[0]


def test_non_search_actions():
    for action, route in (("no_retrieval", "simple"), ("out_of_scope", "simple"), ("clarify_scope", "agent")):
        r, w = _validated(RouteResult(action=action, asks=[_ask(1, "안녕")]), "안녕하세요")
        assert r.route == route and r.asks == []


# ── 서버 검증 ────────────────────────────────────────────────────────────

def test_made_up_quote_is_dropped():
    q = "기숙사비는 얼마고 신청은 어떻게 해요?"
    res = RouteResult(action="search", asks=[_ask(1, "기숙사비는 얼마고", kind="T1"),
                                              _ask(2, "환불 규정도 알려줘", kind="T4")])
    r, w = _validated(res, q)
    assert [a.ask_id for a in r.asks] == ["A1"] and r.route == "simple"
    assert any("지어낸 요구" in x for x in w)


def test_no_valid_ask_raises_for_retry():
    with pytest.raises(RouteFormatError):
        validate_route(RouteResult(action="search", asks=[_ask(1, "없는 구절")]),
                       number_messages("기숙사 신청 기간이 언제예요?", []))


def test_dependency_must_point_to_earlier_ask():
    q = "휴학할 수 있어요? 가능하면 신청 절차도 알려주세요."
    res = RouteResult(action="search", asks=[_ask(1, "휴학할 수 있어요", deps=["A2"]),
                                              _ask(2, "신청 절차도 알려주세요", kind="T4", deps=["A9"])])
    r, w = _validated(res, q)
    assert r.asks[0].depends_on == [] and r.asks[1].depends_on == []
    assert sum("의존" in x for x in w) == 2


def test_hash_reference_adds_dependency_and_unknown_reference_is_removed():
    q = "휴학할 수 있어요? 가능하면 신청 절차도 알려주세요."
    res = RouteResult(action="search", asks=[_ask(1, "휴학할 수 있어요", query="#A2 휴학 허용"),
                                              _ask(2, "신청 절차도 알려주세요", kind="T4", query="#A1 휴학 신청 절차")])
    r, _ = _validated(res, q)
    assert r.asks[1].depends_on == ["A1"]
    assert "#A2" not in r.asks[0].query_ko


def test_only_if_without_dependency_is_cleared():
    q = "기숙사비는 얼마고 신청은 어떻게 해요?"
    r, _ = _validated(RouteResult(action="search", asks=[_ask(1, "기숙사비는 얼마고", only_if="A0이면")]), q)
    assert r.asks[0].only_if == ""


def test_asks_over_limit_are_cut():
    q = "수업료, 지원 기간, 기숙사비, 보험료 알려줘"
    asks = [_ask(i, t, kind="T1") for i, t in enumerate(["수업료", "지원 기간", "기숙사비", "보험료"], 1)]
    r, w = _validated(RouteResult(action="search", asks=asks), q)
    assert len(r.asks) == cfg.ROUTER_MAX_ASKS


def test_invalid_kind_is_cleared_and_empty_query_filled():
    q = "기숙사 신청 기간이 언제예요?"
    r, w = _validated(RouteResult(action="search", asks=[_ask(1, "기숙사 신청 기간", kind="T9", query="")]), q)
    assert r.asks[0].kind is None and r.asks[0].query_ko == "요구1"


def test_question_target_is_not_a_user_condition():
    q = "GKS 장학생은 아르바이트할 수 있어?"
    res = RouteResult(action="search", asks=[_ask(1, "아르바이트할 수 있어")],
                      user_conditions=[RouteCondition(field_id="gks_status", value="예", subject="question_target",
                                                      source_message_id="m1", quote="GKS 장학생은")])
    r, _ = _validated(res, q)
    assert r.user_conditions == [] and r.route == "simple"


def test_condition_from_earlier_user_message_counts_but_not_from_assistant():
    history = [{"role": "user", "content": "저 GKS 장학생이에요."},
               {"role": "assistant", "content": "영어트랙이시군요."}]
    q = "아르바이트 해도 돼요?"
    res = RouteResult(action="search", asks=[_ask(1, "아르바이트 해도 돼요")], user_conditions=[
        RouteCondition(field_id="gks_status", value="예", subject="user_self", source_message_id="m1",
                       quote="저 GKS 장학생이에요"),
        RouteCondition(field_id="track", value="영어", subject="user_self", source_message_id="m2",
                       quote="영어트랙이시군요"),
    ])
    r, w = _validated(res, q, history)
    assert [c.field_id for c in r.user_conditions] == ["gks_status"]
    assert r.route == "agent"


def test_two_conditions_route_to_agent():
    q = "나 TOEFL 70점이고 이미 한국에 살고 있는데 지원 가능해?"
    res = RouteResult(action="search", asks=[_ask(1, "지원 가능해")], user_conditions=[
        RouteCondition(field_id="language_score", value="TOEFL 70", subject="user_self", source_message_id="m1",
                       quote="TOEFL 70점이고"),
        RouteCondition(field_id="residence", value="국내", subject="user_self", source_message_id="m1",
                       quote="이미 한국에 살고 있는데")])
    r, _ = _validated(res, q)
    assert r.route == "agent" and any("사용자 조건 2개" in x for x in r.route_reasons)


# ── LLM 호출 ─────────────────────────────────────────────────────────────

def test_route_question_with_fake_client():
    client = FakeClient([D8_OUTPUT])
    run = route_question(D8, model="fake", client=client)
    assert run.result.route == "agent" and not run.fallback_used
    assert client.calls == 1 and run.prompt_tokens == 100


def test_route_question_retries_then_falls_back_to_agent():
    client = FakeClient(["not json", {"action": "search", "asks": []}])
    run = route_question("기숙사 신청 기간이 언제예요?", model="fake", client=client)
    assert client.calls == 2
    assert run.fallback_used and run.result.route == cfg.ROUTER_FAIL_ROUTE
    assert "라우터 실패" in run.result.route_reasons[0]


def test_route_question_retry_recovers():
    good = {"action": "search", "asks": [{"ask_id": "A1", "text": "기숙사 신청 기간", "quote": "기숙사 신청 기간",
                                          "kind": "T1", "query_ko": "기숙사 신청 기간"}]}
    run = route_question("기숙사 신청 기간이 언제예요?", model="fake", client=FakeClient(["{bad", good]))
    assert run.result.route == "simple" and not run.fallback_used and run.attempts == 2


def test_route_question_survives_client_error():
    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("no client")
    run = route_question("기숙사 신청 기간이 언제예요?", model="fake", client=Boom())
    assert run.fallback_used and run.result.route == "agent"


# ── 안전장치 ─────────────────────────────────────────────────────────────

def _simple_route():
    return decide_route(RouteResult(action="search", asks=[_ask(1, "등록금", kind="T1")]))


def test_low_relevance_escalates():
    c = check_escalation("등록금이 얼마예요?", [{"source": "a.pdf", "similarity_score": 0.4}], _simple_route())
    assert c.escalate and c.reasons[0].startswith("low_relevance")


def test_track_split_escalates_unless_track_mentioned():
    sources = [{"source": KO_TRACK, "similarity_score": 0.9}, {"source": EN_TRACK, "similarity_score": 0.8}]
    c = check_escalation("등록금이 얼마예요?", sources, _simple_route())
    assert c.escalate and "scope_split" in c.reasons[0] and set(c.scope_values["track"]) == {"한국어트랙", "영어트랙"}
    c2 = check_escalation("영어트랙 등록금이 얼마예요?", sources, _simple_route())
    assert not c2.escalate
    c3 = check_escalation("등록금이 얼마예요?", sources, _simple_route(),
                          history=[{"role": "user", "content": "저는 한국어 트랙이에요"}])
    assert not c3.escalate


def test_low_score_source_does_not_count_for_split():
    sources = [{"source": KO_TRACK, "similarity_score": 0.9}, {"source": EN_TRACK, "similarity_score": 0.3}]
    assert not check_escalation("등록금이 얼마예요?", sources, _simple_route()).escalate


def test_no_escalation_for_agent_route_or_non_search():
    sources = [{"source": "a.pdf", "similarity_score": 0.1}]
    agent = decide_route(RouteResult.model_validate(D8_OUTPUT))
    assert not check_escalation(D8, sources, agent).escalate
    oos = decide_route(RouteResult(action="out_of_scope"))
    assert not check_escalation("맛집 추천", sources, oos).escalate


# ── 기본 RAG 스트리밍 (하이브리드+리랭커) ─────────────────────────────────

def _load_rag_stream(monkeypatch, sources, answer_tokens):
    calls = {}

    class FakeRetriever:
        def retrieve_with_sources(self, query, ko_query=None, **kw):
            calls["retrieve"] = (query, ko_query)
            return "본문", sources

    async def stream_answer(**kw):
        calls["answer"] = kw
        for t in answer_tokens:
            yield t

    async def generate_suggestions_async(**kw):
        return ["후속 질문"]

    def max_score(srcs):
        return max((s.get("similarity_score", 0.0) for s in srcs), default=0.0)

    async def fake_create(**kw):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="in_scope"))])

    fake_openai = types.ModuleType("openai")
    fake_openai.AsyncOpenAI = lambda **kw: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    fake_config = types.ModuleType("app.config")
    fake_config.settings = SimpleNamespace(openai_api_key="x")
    fake_retriever = types.ModuleType("app.core.retriever")
    fake_retriever.retriever = FakeRetriever()
    fake_llm = types.ModuleType("app.core.llm")
    fake_llm._get_max_relevance_score = max_score
    fake_llm._RELEVANCE_THRESHOLD = 0.7
    fake_llm.stream_answer = stream_answer
    fake_llm.generate_suggestions_async = generate_suggestions_async
    for name, mod in (("openai", fake_openai), ("app.config", fake_config),
                      ("app.core.retriever", fake_retriever), ("app.core.llm", fake_llm)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.delitem(sys.modules, "app.core.rag_stream", raising=False)
    mod = importlib.import_module("app.core.rag_stream")
    monkeypatch.delitem(sys.modules, "app.core.rag_stream", raising=False)
    return mod, calls


def _collect(gen):
    async def go():
        return [json.loads(x[6:]) async for x in gen]
    return asyncio.run(go())


def test_rag_stream_uses_hybrid_rerank_and_streams_answer(monkeypatch):
    mod, calls = _load_rag_stream(monkeypatch, [{"source": "a.pdf", "chunk_index": 3, "similarity_score": 0.9},
                                                {"source": "b.pdf", "chunk_index": 1, "similarity_score": 0.6}],
                                  ["등록금은 ", "얼마입니다."])
    events = _collect(mod.run_rag_stream("등록금 얼마?", "ko", ko_query="등록금 얼마"))
    assert calls["retrieve"] == ("등록금 얼마?", "등록금 얼마")
    assert "".join(e["content"] for e in events if e["type"] == "token") == "등록금은 얼마입니다."
    done = events[-1]
    assert done["type"] == "done" and [s["source"] for s in done["sources"]] == ["a.pdf"]
    assert done["suggestions"] == ["후속 질문"]


def test_rag_stream_low_relevance_returns_guidance_without_llm_answer(monkeypatch):
    mod, calls = _load_rag_stream(monkeypatch, [{"source": "a.pdf", "similarity_score": 0.3}], ["x"])
    events = _collect(mod.run_rag_stream("등록금 얼마?", "ko"))
    assert "answer" not in calls
    assert events[-1] == {"type": "done", "sources": [], "suggestions": []}
    assert any(e["type"] == "token" and "찾지 못했습니다" in e["content"] for e in events)


def test_condition_outside_checklist_still_routes_to_agent():
    q = "제 친구가 D-4 비자인데 아르바이트 할 수 있어요?"
    res = RouteResult(action="search", asks=[_ask(1, "아르바이트 할 수 있어요")], user_conditions=[
        RouteCondition(field_id="visa_status", value="D-4", subject="other_person", source_message_id="m1",
                       quote="제 친구가 D-4 비자인데")])
    r, w = _validated(res, q)
    assert r.route == "agent" and any("체크리스트에 없는 칸" in x for x in w)


# ── 에이전트 SSE 어댑터 (app/core/agent_stream.py) ─────────────────────────────

def _load_agent_stream(monkeypatch):
    rag, _ = _load_rag_stream(monkeypatch, [], [])
    monkeypatch.setitem(sys.modules, "app.core.rag_stream", rag)
    monkeypatch.delitem(sys.modules, "app.core.agent_stream", raising=False)
    mod = importlib.import_module("app.core.agent_stream")
    monkeypatch.delitem(sys.modules, "app.core.agent_stream", raising=False)
    return mod


def _fake_run(mode, answer, sources=()):
    from app.core.single_agent.answer_schema import AnswerRun, AnswerSource, PipelineRun
    from app.core.single_agent.evidence_schema import EvidenceChunk, RetrievalTag
    run = PipelineRun(question="q")
    run.answer_run = AnswerRun(mode=mode, answer=answer, sources=[
        AnswerSource(number=i + 1, evidence_id=f"{s}#p1#c{i}", source=s, page=1) for i, s in enumerate(sources)])
    for i, s in enumerate(sources):
        run.pool.add(EvidenceChunk(evidence_id=f"{s}#p1#c{i}", source=s, page=1, chunk_index=i, text="본문",
                                   score=0.8), RetrievalTag(target_slot_id="D1", search_type="new", query_ko="q"))
    return run


def test_agent_stream_emits_status_tokens_and_sources(monkeypatch):
    mod = _load_agent_stream(monkeypatch)
    seen = {}

    def pipeline(question, history, on_event=None):
        seen["q"], seen["h"] = question, history
        for stage in ("analysis", "plan", "search", "verify_start", "verify", "answer_start", "answer"):
            on_event(stage, {})
        return _fake_run("answer", "GKS 장학생은 휴학을 1년까지 할 수 있습니다. [1]", ["E.pdf"])

    async def suggest(q, a, lang):
        return ["다음 질문"]

    events = _collect(mod.run_agent_stream("휴학?", "ko", ko_query="휴학?", history=[{"role": "user", "content": "x"}],
                                           pipeline_fn=pipeline, suggest_fn=suggest))
    types_ = [e["type"] for e in events]
    assert types_[0] == "status" and types_.count("status") >= 3 and types_[-1] == "done"
    assert "".join(e["content"] for e in events if e["type"] == "token").startswith("GKS 장학생은")
    assert events[-1]["sources"] == [{"source": "E.pdf", "chunk_index": 0, "similarity_score": 0.8}]
    assert events[-1]["suggestions"] == ["다음 질문"] and seen["h"][0]["content"] == "x"


def test_agent_stream_clarify_and_translation(monkeypatch):
    mod = _load_agent_stream(monkeypatch)
    pipeline = lambda q, h, on_event=None: _fake_run("ask_clarification", "어느 트랙이에요?")
    events = _collect(mod.run_agent_stream("Tuition?", "en", ko_query="등록금?", pipeline_fn=pipeline,
                                           translate_fn=lambda t, lang: f"[{lang}] {t}"))
    assert events[-2] == {"type": "clarify", "content": "[en] 어느 트랙이에요?"}
    assert events[-1] == {"type": "done", "sources": [], "suggestions": []}


def test_agent_stream_no_evidence_has_no_sources_and_pipeline_crash_is_safe(monkeypatch):
    mod = _load_agent_stream(monkeypatch)
    events = _collect(mod.run_agent_stream("q", "ko", pipeline_fn=lambda q, h, on_event=None:
                                           _fake_run("no_evidence", "찾지 못했습니다", ["A.pdf"])))
    assert events[-1]["sources"] == []

    def boom(q, h, on_event=None):
        raise RuntimeError("x")
    events = _collect(mod.run_agent_stream("q", "ko", pipeline_fn=boom))
    assert events[-1] == {"type": "done", "sources": [], "suggestions": []}
    assert any(e["type"] == "token" and "문제가 생겼습니다" in e["content"] for e in events)


def test_agent_stream_sends_heartbeat_while_pipeline_is_slow(monkeypatch):
    import time as _t
    mod = _load_agent_stream(monkeypatch)
    monkeypatch.setattr(mod, "HEARTBEAT_S", 0.05)

    def slow(q, h, on_event=None):
        _t.sleep(0.3)
        return _fake_run("no_evidence", "찾지 못했습니다")

    async def go():
        return [x async for x in mod.run_agent_stream("q", "ko", pipeline_fn=slow)]
    raw = asyncio.run(go())
    assert raw.count(mod.HEARTBEAT) >= 2
    assert json.loads(raw[-1][6:]) == {"type": "done", "sources": [], "suggestions": []}


def test_agent_stream_saves_run_log_and_viewer_reads_it(monkeypatch, tmp_path, capsys):
    mod = _load_agent_stream(monkeypatch)
    from app.core.single_agent import run_log
    monkeypatch.setattr(run_log, "enabled", lambda: True)
    monkeypatch.setattr(run_log, "log_dir", lambda: str(tmp_path))
    pipeline = lambda q, h, on_event=None: _fake_run("answer", "1년까지 가능합니다. [1]", ["E.pdf"])

    async def suggest(q, a, lang):
        return []
    _collect(mod.run_agent_stream("휴학?", "ko", ko_query="휴학?", pipeline_fn=pipeline, suggest_fn=suggest,
                                  log_meta={"routing_mode": "auto", "router": {"result": {"route": "agent"}}}))
    files = list((tmp_path / "agent_runs").glob("*.json"))
    assert len(files) == 1
    rec = json.loads(files[0].read_text(encoding="utf-8"))
    assert rec["question"] == "휴학?" and rec["routing_mode"] == "auto"
    assert rec["final"]["sources_sent"][0]["source"] == "E.pdf" and rec["run"]["answer_run"]["mode"] == "answer"

    from evaluate.show_agent_run import show_record
    show_record(rec, full=True)
    out = capsys.readouterr().out
    assert "⓪ 라우터: agent" in out and "⑤ 답변 (answer" in out and "E.pdf" in out


def test_agent_stream_without_log_meta_saves_nothing(monkeypatch, tmp_path):
    mod = _load_agent_stream(monkeypatch)
    from app.core.single_agent import run_log
    monkeypatch.setattr(run_log, "enabled", lambda: True)
    monkeypatch.setattr(run_log, "log_dir", lambda: str(tmp_path))
    _collect(mod.run_agent_stream("q", "ko", pipeline_fn=lambda q, h, on_event=None: _fake_run("no_evidence", "x")))
    assert not (tmp_path / "agent_runs").exists()


def test_route_log_appends_jsonl(tmp_path):
    from app.core.single_agent import run_log
    run_log.append_route({"question": "a", "route": "simple"}, base_dir=str(tmp_path))
    run_log.append_route({"question": "b", "route": "agent"}, base_dir=str(tmp_path))
    lines = (tmp_path / "routes.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["route"] for x in lines] == ["simple", "agent"]


# ── 라우터 요구 → ① 전달, '학부' 별칭 (2026-10-02 실서비스 기록 20261002_224716 대응) ──────────

def test_route_asks_reach_analysis_prompt_and_missing_kind_is_added():
    from app.core.single_agent import analyzer
    from app.core.single_agent.analysis_schema import QuestionAnalysis
    q = "GKS 장학생으로 학부 신입학했는데 첫 학기에 휴학할 수 있어? 휴학하면 장학금은?"
    asks = [{"ask_id": "A1", "text": "첫 학기 휴학 가능 여부", "kind": "T5"},
            {"ask_id": "A2", "text": "휴학 시 장학금", "kind": "T6", "depends_on": ["A1"]}]
    numbered = analyzer.number_messages(q, None)
    prompt = analyzer.build_user_prompt(numbered, asks)
    assert "접수 단계에서 나눈 요구" in prompt and "[T6] 휴학 시 장학금" in prompt and "← A1" in prompt
    assert "접수 단계" not in analyzer.build_user_prompt(numbered)  # 요구가 없으면 기존 프롬프트 그대로

    a = QuestionAnalysis(intent_summary="x", answer_scope="general", primary_type="T5", additional_types=[],
                         next_action="search", first_search={"query_ko": "GKS 첫 학기 휴학", "target_slot_ids": []})
    a, w = analyzer.validate_analysis(a, numbered, ask_kinds=["T5", "T6"])
    assert a.additional_types == ["T6"] and any("T6" in x for x in w)
    assert set(cfg.slots_for_types(["T6"])) <= {s.slot_id for s in a.document_slots}


def test_undergraduate_word_names_gks_stage():
    from app.core.single_agent.branching import fields_named_in_question
    named = fields_named_in_question("GKS 장학생으로 학부 신입학했는데 첫 학기에 휴학할 수 있어?")
    assert {"gks_status", "gks_stage"} <= named
    assert "gks_stage" not in fields_named_in_question("GKS 장학생은 휴학할 수 있어?")


def test_agent_stream_passes_router_asks_to_pipeline(monkeypatch):
    mod = _load_agent_stream(monkeypatch)
    got = {}

    def pipeline(q, h, on_event=None, route_asks=None):
        got["asks"] = route_asks
        return _fake_run("no_evidence", "x")
    asks = [{"ask_id": "A1", "text": "a", "kind": "T5"}]
    _collect(mod.run_agent_stream("q", "ko", pipeline_fn=pipeline,
                                  log_meta={"router": {"result": {"asks": asks}}}))
    assert got["asks"] == asks


# ── PDF 띄어쓰기 복원 (app/core/spacing.py) ─────────────────────────────────

def test_spacing_inserts_only_and_keeps_existing_spaces():
    from app.core.spacing import insert_spaces_only, needs_spacing
    assert insert_spaces_only("제출하여야 한다. 입학후첫학기", "제출하여야한다. 입학 후 첫 학기") == "제출하여야 한다. 입학 후 첫 학기"
    assert insert_spaces_only("학·석사통합", "학· 석사 통합") == "학·석사 통합"
    assert insert_spaces_only("휴학불가", "휴학 금지") == "휴학불가"  # 글자가 바뀌면 원문 유지
    assert needs_spacing("입학후첫학기에는휴학불가합니다")
    assert not needs_spacing("휴학은 학기 단위로 신청하여야 하며, 총 휴학 기간은 1년을 초과할 수 없다.")
    assert needs_spacing("Passport with at least 6 months <br> 여권유효기간이최소6개월이상남아있는여권")


def test_restore_spacing_touches_only_glued_segments(monkeypatch):
    from app.core import spacing

    class FakeKiwi:
        def space(self, text, reset_whitespace=False):
            return {"입학후첫학기에는휴학불가합니다.": "입학 후 첫 학기에는 휴학 불가합니다."}.get(text, text.replace(" ", ""))
    monkeypatch.setattr(spacing, "_kiwi", FakeKiwi())
    text = "- 카. **입학후첫학기에는휴학불가합니다.**\n|**구분**|휴학은 학기 단위로 신청하여야 한다.|"
    new, n = spacing.restore_spacing(text)
    assert n == 1
    assert "**입학 후 첫 학기에는 휴학 불가합니다.**" in new
    assert "|**구분**|휴학은 학기 단위로 신청하여야 한다.|" in new  # 정상 문장·표 기호는 그대로


# ── 2026-10-02 23:40 기록 대응: 근거 ID 괄호 누락, 요구 칸 비활성, 일반 규정 검색 ───────────────

def test_evidence_id_with_missing_paren_is_resolved():
    from app.core.single_agent.verifier import resolve_evidence_id
    shown = {"(KO)정부초청+지침.pdf#p4#c1", "(EN)정부초청+지침.pdf#p4#c1"}
    w = []
    assert resolve_evidence_id("KO)정부초청+지침.pdf#p4#c1", shown, w, "rule") == "(KO)정부초청+지침.pdf#p4#c1"
    assert resolve_evidence_id("KO)정부초청+지침.pdf#p5#c3", shown, w, "rule") is None  # 없는 청크는 그대로 거부


def test_required_slot_of_route_ask_kind_stays_active():
    from app.core.single_agent import analyzer
    from app.core.single_agent.analysis_schema import QuestionAnalysis
    numbered = analyzer.number_messages("휴학할 수 있어? 휴학하면 장학금은?", None)
    t6_required = [sid for sid, req in cfg.slots_for_types(["T6"]).items() if req == "required"]
    slot = t6_required[0]
    a = QuestionAnalysis(intent_summary="x", answer_scope="general", primary_type="T5", additional_types=["T6"],
                         next_action="search", first_search={"query_ko": "휴학", "target_slot_ids": []},
                         document_slots=[{"slot_id": slot, "active": False, "requirement": "required",
                                          "activation_reason": "앞 요구 확인 후 필요"}])
    a, w = analyzer.validate_analysis(a, numbered, ask_kinds=["T5", "T6"])
    assert next(s for s in a.document_slots if s.slot_id == slot).active
    a2 = QuestionAnalysis(intent_summary="x", answer_scope="general", primary_type="T5", additional_types=["T6"],
                          next_action="search", first_search={"query_ko": "휴학", "target_slot_ids": []},
                          document_slots=[{"slot_id": slot, "active": False, "requirement": "required",
                                           "activation_reason": "이유"}])
    a2, _ = analyzer.validate_analysis(a2, numbered)  # 라우터 요구가 없으면 기존 규칙(이유 있으면 비활성 허용)
    assert not next(s for s in a2.document_slots if s.slot_id == slot).active


def test_pipeline_runs_general_query_in_first_round():
    from types import SimpleNamespace as NS
    from app.core.single_agent.pipeline import run_pipeline
    from app.core.single_agent import pipeline as pl
    from app.core.single_agent.analysis_schema import AnalysisRun, QuestionAnalysis
    from app.core.single_agent.answer_schema import AnswerRun
    from app.core.single_agent.verify_schema import VerificationRun, VerifyDecision
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    queries = []
    try:
        analysis = QuestionAnalysis(intent_summary="x", answer_scope="personal", primary_type="T5", next_action="search",
                                    conditions=[{"field_id": "gks_status", "value": "예", "subject": "user_self",
                                                 "source_message_id": "m1", "quote": "GKS"}],
                                    first_search={"query_ko": "GKS 장학생 첫 학기 휴학",
                                                  "general_query_ko": "입학 후 첫 학기 휴학",
                                                  "target_slot_ids": ["rule"]},
                                    document_slots=[{"slot_id": "rule", "active": True, "requirement": "required"}])
        mp.setattr(pl, "analyze_question", lambda *a, **k: AnalysisRun(question="q", analysis=analysis))

        def search_fn(q, k, metrics=None):
            queries.append(q)
            return [NS(page_content=f"본문 {q}", metadata={"source": f"{len(queries)}.pdf", "page": 1,
                                                          "chunk_index": 0, "similarity_score": 0.9})]
        mp.setattr(pl, "verify_evidence", lambda an, *a, **k: VerificationRun(
            analysis=an, decision=VerifyDecision(next_action="no_evidence")))
        mp.setattr(pl, "write_answer", lambda *a, **k: AnswerRun(mode="no_evidence"))
        run_pipeline("q", search_fn=search_fn, store=NS(get=lambda **k: {"documents": [], "metadatas": []}))
    finally:
        mp.undo()
    assert queries[0] == "GKS 장학생 첫 학기 휴학" and "첫 학기 휴학" in queries


def test_general_query_is_derived_when_llm_leaves_it_empty():
    from app.core.single_agent.pipeline import general_query_for
    from app.core.single_agent.analysis_schema import QuestionAnalysis
    a = QuestionAnalysis(intent_summary="x", answer_scope="personal", primary_type="T5", next_action="search",
                         conditions=[{"field_id": "gks_status", "value": "예", "subject": "user_self",
                                      "source_message_id": "m1", "quote": "GKS 장학생으로"}],
                         first_search={"query_ko": "GKS 장학생 첫 학기 휴학 가능 여부", "target_slot_ids": []})
    assert general_query_for(a, "GKS 장학생으로 학부 신입학했는데 첫 학기에 휴학할 수 있어?") == "첫 학기 휴학 가능 여부"
    a.first_search.general_query_ko = "GKS 장학생 휴학 규정"
    assert general_query_for(a) == "첫 학기 휴학 가능 여부"   # 첫 검색어 기반이 우선 (구체적인 내용 유지)
    a.first_search.query_ko = "GKS 장학생"
    assert general_query_for(a) == "휴학 규정"   # 첫 검색어로 못 만들면 ①의 것을 다듬어 씀
    b = QuestionAnalysis(intent_summary="x", answer_scope="general", primary_type="T1", next_action="search",
                         first_search={"query_ko": "기숙사 비용", "target_slot_ids": []})
    assert general_query_for(b, "기숙사 비용 얼마야?") == ""   # 조건이 없으면 일반 검색 안 함


def test_verifier_shows_short_aliases_and_maps_them_back():
    from app.core.single_agent import verifier as v
    from app.core.single_agent.evidence_schema import EvidenceChunk, EvidencePool, RetrievalTag
    pool = EvidencePool()
    ids = ["(KO)지침.pdf#p5#c2", "(EN)지침.pdf#p5#c2"]
    for i, eid in enumerate(ids):
        src = eid.split("#")[0]
        pool.add(EvidenceChunk(evidence_id=eid, source=src, page=5, chunk_index=2, text=f"본문{i}", score=0.5),
                 RetrievalTag(target_slot_id="rule", search_type="new", query_ko="q"))
    token = v._ALIAS_KEYS.set(list(pool.chunks.keys()))
    try:
        assert v.alias_of(ids[1]) == "E2"
        assert "청크 ID: E2\n(출처: (EN)지침.pdf p.5)" in v._chunk_header(ids[1], pool)
        w = []
        assert v.resolve_evidence_id("E2", set(ids), w, "rule") == ids[1]
        assert v.resolve_evidence_id("[E1]", set(ids), w, "rule") == ids[0]
        assert v.resolve_evidence_id("E9", set(ids), w, "rule") is None
        assert v.resolve_evidence_id("E2", {ids[0]}, w, "rule") is None   # 이번에 안 보여준 청크는 거부
    finally:
        v._ALIAS_KEYS.reset(token)
    assert v.alias_of(ids[0]) == ids[0]   # 별칭 범위 밖에서는 실제 ID 그대로


# ── 인용 낱말 대조 (2026-10-03 LANG: 맞는 요구가 지워짐) ─────────────────────────

LANG_Q = "동아대 학부 신입학에 지원하려는데, 한국어 트랙과 영어 트랙의 어학 기준이 각각 뭐야? 영어 트랙에서 어학 성적을 안 내도 되는 경우도 있어?"


def test_shared_phrase_ask_is_kept_by_word_match():
    asks = [_ask(1, "한국어 트랙의 어학 기준이"), _ask(2, "영어 트랙의 어학 기준이"), _ask(3, "어학 성적을 안 내도 되는 경우")]
    r, w = _validated(RouteResult(action="search", asks=asks), LANG_Q)
    assert [a.ask_id for a in r.asks] == ["A1", "A2", "A3"]
    assert any("[확인] 요구 A1" in x for x in w) and not any("[제거]" in x for x in w)


def test_made_up_ask_is_still_removed():
    r, w = _validated(RouteResult(action="search", asks=[_ask(1, "어학 기준이"), _ask(2, "기숙사 신청 방법")]), LANG_Q)
    assert [a.ask_id for a in r.asks] == ["A1"] and any("[제거] 요구 A2" in x for x in w)


def test_single_word_quote_needs_exact_match():
    from app.core.single_agent.router import quote_words_in_text
    assert not quote_words_in_text("기숙사", LANG_Q)
    assert not quote_words_in_text("트랙의", LANG_Q)          # 낱말 1개는 낱말 대조로 인정하지 않음
    assert quote_words_in_text("한국어 트랙의 어학 기준이", LANG_Q)
    assert not quote_words_in_text("한국어 트랙의 기숙사 기준이", LANG_Q)


def test_router_prompt_and_answer_rule_for_shared_phrase():
    from app.core.single_agent import router, answerer
    assert "그 구절 전체를 각 요구의 quote로" in router.SYSTEM_PROMPT_TEMPLATE
    assert "목록에 빠진 부분이 있어도" in answerer.SYSTEM_PROMPT
