"""evaluate/compare_service.py 규칙 테스트 (API·DB·서버 호출 없음)."""
import asyncio
import json
from types import SimpleNamespace

from evaluate import compare_service as cs


def _sse(d):
    return f"data: {json.dumps(d, ensure_ascii=False)}\n\n"


async def _agen(items):
    for x in items:
        yield x


class FakeClient:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls += 1
        out = self._outputs.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(out)))])


def test_collect_sse_joins_tokens_and_ignores_heartbeat():
    stream = _agen([_sse({"type": "status", "content": "검색 중"}), ": ping\n\n",
                    _sse({"type": "token", "content": "첫 학기 "}), _sse({"type": "token", "content": "휴학 불가[1]"}),
                    _sse({"type": "done", "sources": [{"source": "a.pdf"}]})])
    answer, sources = asyncio.run(cs.collect_sse(stream))
    assert answer == "첫 학기 휴학 불가[1]" and sources == [{"source": "a.pdf"}]


def test_collect_sse_keeps_clarify_text():
    answer, _ = asyncio.run(cs.collect_sse(_agen([_sse({"type": "clarify", "content": "어느 트랙이에요?"}),
                                                   _sse({"type": "done", "sources": []})])))
    assert answer == "어느 트랙이에요?"


def test_score_judgement_points_and_missing_facts():
    q = {"facts": ["a", "b", "c", "d"]}
    s = cs.score_judgement(q, {"facts": [{"no": 1, "status": "included"}, {"no": 2, "status": "partial"},
                                         {"no": 3, "status": "wrong"}], "contradictions": ["경고 2회면 자격 상실"]})
    assert s["coverage"] == (1 + 0.5 + 0 + 0) / 4
    assert s["wrong"] == 1 and s["per_fact"][3]["status"] == "missing"


def test_service_uses_baseline_answer_when_router_says_simple():
    base = {"route": "simple", "answer": "기존 답", "sources": [], "latency_s": 1.0}
    rrun = SimpleNamespace(result=SimpleNamespace(route="simple", route_reasons=["요구 1개"]))
    called = []
    out = asyncio.run(cs.run_service("q", base, route_fn=lambda q, h: rrun,
                                     agent_stream_fn=lambda *a, **k: called.append(1)))
    assert out["answer"] == "기존 답" and out["route"] == "simple" and called == []


def test_service_runs_agent_with_router_meta():
    rrun = SimpleNamespace(result=SimpleNamespace(route="agent", route_reasons=["요구 2개"]),
                           model_dump=lambda: {"result": {"asks": [{"text": "A1"}]}})
    seen = {}

    def agent(question, language, ko_query=None, history=None, log_meta=None):
        seen.update(log_meta)
        return _agen([_sse({"type": "token", "content": "에이전트 답"}), _sse({"type": "done", "sources": []})])

    out = asyncio.run(cs.run_service("q", {}, route_fn=lambda q, h: rrun, agent_stream_fn=agent))
    assert out["route"] == "agent" and out["answer"] == "에이전트 답"
    assert seen["routing_mode"] == "auto" and seen["router"]["result"]["asks"][0]["text"] == "A1"


def test_compare_end_to_end_with_fakes():
    rag = lambda q, lang, ko_query=None, history=None: _agen([_sse({"type": "token", "content": "모름"}),
                                                               _sse({"type": "done", "sources": []})])
    rrun = SimpleNamespace(result=SimpleNamespace(route="agent", route_reasons=[]), model_dump=lambda: {})
    agent = lambda *a, **k: _agen([_sse({"type": "token", "content": "70점, 80%, 지각 2번=결석 1번"}),
                                   _sse({"type": "done", "sources": []})])
    bad = {"facts": [{"no": i, "status": "missing"} for i in (1, 2, 3)], "contradictions": []}
    good = {"facts": [{"no": i, "status": "included"} for i in (1, 2, 3)], "contradictions": []}
    client = FakeClient([bad, good])
    rows = asyncio.run(cs.compare({"E3"}, 1, client=client, log=lambda *a: None,
                                  rag_stream_fn=rag, route_fn=lambda q, h: rrun, agent_stream_fn=agent))
    s = cs.summarize(rows)
    assert s["baseline"]["coverage"] == 0 and s["service"]["coverage"] == 1 and s["service"]["full_correct"] == 1
    md = cs.to_markdown(rows, s, {"started_at": "t", "repeat": 1, "judge_model": "gpt-4o",
                                  "models": {"openai_model": "m", "verify_model": "", "answer_model": "gpt-4o"}})
    assert "| 핵심 사실 포함률 | 0% | 100% |" in md and "지각 2번=결석 1번" in md


def test_questions_have_ids_and_facts():
    ids = [q["id"] for q in cs.QUESTIONS]
    assert ids == ["Q7", "LANG", "GKSW", "E2", "E3"] and all(q["facts"] for q in cs.QUESTIONS)
