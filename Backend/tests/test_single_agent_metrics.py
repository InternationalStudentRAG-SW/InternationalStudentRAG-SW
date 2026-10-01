"""Offline telemetry checks: no model downloads or live API calls."""
from types import SimpleNamespace as NS

from app.core.single_agent.answer_schema import PipelineRun
from app.core.single_agent.llm import run_json_loop
from app.core.single_agent.search_schema import SearchPlanRun
from app.core.single_agent.verify_schema import VerificationRun
from evaluate.check_pipeline import summarize
from evaluate.benchmark_rerank_candidates import _new_searches, summarize as summarize_rerank


def test_plan_usage_counts_repair_and_api_retry(monkeypatch):
    from app.core.single_agent import llm
    monkeypatch.setattr(llm, "API_RETRY_WAIT_S", 0)
    responses = iter([TimeoutError("offline timeout"), "broken", "valid"])

    def create(**kwargs):
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return NS(choices=[NS(message=NS(content=value), finish_reason="stop")],
                  usage=NS(prompt_tokens=100, completion_tokens=10, prompt_tokens_details=NS(cached_tokens=20)))

    def parse(text):
        if text != "valid":
            raise ValueError("repair needed")
        return text

    run = SearchPlanRun()
    value, ok = run_json_loop(run, NS(chat=NS(completions=NS(create=create))), "fake", [], parse,
                              0, 100, "JSON")
    assert ok and value == "valid"
    assert run.attempts == 2 and len(run.calls) == 3  # API retry != format retry
    assert run.prompt_tokens == 200 and run.completion_tokens == 20
    assert run.calls[0].error_type == "TimeoutError" and run.calls[0].prompt_tokens is None
    summary = summarize(PipelineRun(question="q", plan_runs=[run]))
    assert summary["tokens"] == 220 and summary["sdk_calls"] == 3
    assert summary["stage_usage"]["plan"]["cached_prompt_tokens"] == 40
    assert not summary["usage_complete"]  # failed request usage is unknown, not a measured zero


def test_recheck_metrics_are_separate_and_not_double_counted():
    from app.core.single_agent.metrics import LLMCallMetric
    verify = VerificationRun(prompt_tokens=300, completion_tokens=30, attempts=2, calls=[
        LLMCallMetric(prompt_tokens=100, completion_tokens=10, latency_ms=5),
        LLMCallMetric(purpose="recheck", prompt_tokens=200, completion_tokens=20, latency_ms=7)])
    summary = summarize(PipelineRun(question="q", verify_runs=[verify]))
    assert summary["tokens"] == 330
    assert summary["recheck"] == {"sdk_calls": 1, "latency_ms": 7, "tokens": 220}
    assert summary["usage_complete"]


def test_legacy_logs_do_not_claim_complete_usage():
    summary = summarize(PipelineRun(question="q", plan_runs=[SearchPlanRun(attempts=1)]))
    assert not summary["usage_complete"]


def test_default_search_telemetry_flows_to_execution(monkeypatch):
    import sys
    from app.core.single_agent.evidence_schema import EvidencePool
    from app.core.single_agent.search_schema import SearchPlan
    from app.core.single_agent.searcher import execute_search

    def retrieve(query, k, metrics):
        metrics.update(rerank_ms=12.5, rerank_pairs=50)
        return [NS(page_content="evidence", metadata={"source": "d", "page": 1, "chunk_index": 0})]

    monkeypatch.setitem(sys.modules, "app.core.retriever", NS(retriever=NS(retrieve=retrieve)))
    run = execute_search(SearchPlan(action="search", target_slot_id="rule", search_type="new", query_ko="q"),
                         EvidencePool())
    assert run.ok and len(run.retrieval_calls) == 1
    assert run.retrieval_calls[0]["rerank_pairs"] == 50
    assert run.retrieval_calls[0]["import_init_ms"] >= 0
    assert len(run.new_chunk_ids) == 1


def test_retriever_metrics_do_not_change_ranking_or_candidate_count():
    # Load only the real retrieve method, avoiding module-level model/DB initialization.
    import ast
    import time
    from pathlib import Path
    from typing import Any, Dict, List, Optional

    path = Path(__file__).resolve().parents[1] / "app/core/retriever.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RAGRetriever")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "retrieve")
    namespace = dict(time=time, Any=Any, Dict=Dict, List=List, Optional=Optional, Document=NS)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    docs = [NS(page_content=str(i), metadata={}) for i in range(50)]
    batches = []

    def predict(pairs, batch_size):
        batches.append((len(pairs), batch_size))
        return list(range(len(pairs)))

    retriever = NS(mode="hybrid_rerank", top_k=10,
                   keyword_retriever=NS(invoke=lambda q: docs[:25]),
                   vector_retriever=NS(invoke=lambda q: docs[25:]),
                   _rrf=NS(weighted_reciprocal_rank=lambda groups: sum(groups, [])),
                   reranker=NS(predict=predict, device="fake-cpu"))
    stats = {}
    result = namespace["retrieve"](retriever, "q", k=7, metrics=stats)
    assert [d.page_content for d in result] == [str(i) for i in range(49, 42, -1)]
    assert batches == [(50, 8)]  # telemetry does not silently cap pre-rerank candidates
    assert stats["merged_candidates"] == stats["rerank_pairs"] == 50
    assert stats["returned_chunks"] == 7 and stats["reranker_device"] == "fake-cpu"
    assert all(stats[k] >= 0 for k in ("bm25_ms", "vector_with_embedding_ms", "rrf_ms", "rerank_ms"))
    reused = {}
    namespace["retrieve"](retriever, "q", k=7, prefetched_vector_docs=docs[25:], metrics=reused)
    assert reused["vector_prefetched"] and "vector_with_embedding_ms" not in reused


def test_reranker_candidate_limit_caps_rrf_input_without_reducing_final_k():
    # 실제 모델/DB를 초기화하지 않고 retrieve 메서드만 로드한다.
    import ast
    import time
    from pathlib import Path
    from typing import Any, Dict, List, Optional

    path = Path(__file__).resolve().parents[1] / "app/core/retriever.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RAGRetriever")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "retrieve")
    namespace = dict(time=time, Any=Any, Dict=Dict, List=List, Optional=Optional, Document=NS)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    docs = [NS(page_content=str(i), metadata={}) for i in range(50)]
    batches = []

    def predict(pairs, batch_size):
        batches.append((len(pairs), batch_size))
        return list(range(len(pairs)))

    retriever = NS(mode="hybrid_rerank", top_k=10, rerank_candidate_limit=12,
                   keyword_retriever=NS(invoke=lambda q: docs[:25]),
                   vector_retriever=NS(invoke=lambda q: docs[25:]),
                   _rrf=NS(weighted_reciprocal_rank=lambda groups: sum(groups, [])),
                   reranker=NS(predict=predict, device="fake-cpu"))
    stats = {}
    result = namespace["retrieve"](retriever, "q", k=7, metrics=stats)
    assert batches == [(12, 8)]
    assert [d.page_content for d in result] == [str(i) for i in range(11, 4, -1)]
    assert stats["merged_candidates"] == 50
    assert stats["rerank_pairs"] == stats["rerank_effective_limit"] == 12
    assert stats["rerank_candidate_limit"] == 12
    assert stats["rerank_dropped_candidates"] == 38

    # 잘못 작은 설정이어도 요청한 최종 결과 수보다 적게 BGE에 보내지는 않는다.
    retriever.rerank_candidate_limit = 3
    floor_stats = {}
    floor_result = namespace["retrieve"](retriever, "q", k=7, metrics=floor_stats)
    assert batches[-1] == (7, 8)
    assert len(floor_result) == 7 and floor_stats["rerank_effective_limit"] == 7


def test_rerank_benchmark_extracts_new_searches_and_summarizes_recall():
    payload = {"items": [{"label": "D1", "run": {"search_runs": [
        {"plan": {"search_type": "new", "query_ko": "등록금"}, "chunk_ids": ["a", "b"]},
        {"plan": {"search_type": "expand_context", "query_ko": "등록금"}, "chunk_ids": ["c"]},
    ]}}]}
    searches = _new_searches(payload)
    assert searches == [{"label": "D1", "query": "등록금", "baseline_chunk_ids": ["a", "b"],
                         "adopted_baseline_ids": []}]
    rows = [{"limit": 12, "rerank_ms": 100.0, "rerank_pairs": 12,
             "baseline_hits": 1, "baseline_count": 2,
             "adopted_hits": 0, "adopted_count": 0,
             "result_chunk_ids": ["a", "x"], "baseline_chunk_ids": ["a", "b"]}]
    result = summarize_rerank(rows, [12])[0]
    assert result["baseline_recall"] == 0.5
    assert result["adopted_recall"] == 0
    assert result["mean_rerank_pairs"] == 12 and result["exact_topk_matches"] == 0
