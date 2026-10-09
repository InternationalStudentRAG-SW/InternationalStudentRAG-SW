"""저장된 파이프라인의 신규 검색어를 재생해 BGE 후보 제한을 비교한다.

OpenAI 생성 LLM은 호출하지 않는다. 현재 문서/색인과 임베딩·BGE 검색기는 사용한다.

예:
  python -m evaluate.benchmark_rerank_candidates \
    evaluate/results/pipeline_20260930_221219.json --limits 12,20,30,0
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any


RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _new_searches(payload: dict[str, Any], labels: set[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in payload.get("items", []):
        label = item.get("label") or "-"
        if labels is not None and label not in labels:
            continue
        adopted_ids = {
            ref.get("evidence_id")
            for slot in (item.get("run", {}).get("analysis", {}).get("document_slots", []))
            for ref in slot.get("evidence_refs", [])
            if ref.get("evidence_id")
        }
        for run in item.get("run", {}).get("search_runs", []):
            plan = run.get("plan") or {}
            if plan.get("search_type") != "new" or not plan.get("query_ko"):
                continue
            key = (label, plan["query_ko"])
            if key in seen:
                continue
            seen.add(key)
            baseline_ids = run.get("chunk_ids", [])
            rows.append({"label": label, "query": plan["query_ko"],
                         "baseline_chunk_ids": baseline_ids,
                         "adopted_baseline_ids": [eid for eid in baseline_ids if eid in adopted_ids]})
    return rows


def _evidence_id(doc: Any) -> str:
    meta = getattr(doc, "metadata", {}) or {}
    return f"{meta.get('source')}#p{int(meta.get('page'))}#c{int(meta.get('chunk_index'))}"


def summarize(rows: list[dict[str, Any]], limits: list[int]) -> list[dict[str, Any]]:
    summaries = []
    for limit in limits:
        selected = [r for r in rows if r["limit"] == limit]
        rerank_ms = [r["rerank_ms"] for r in selected]
        summaries.append({
            "limit": limit,
            "queries": len(selected),
            "mean_rerank_ms": round(statistics.mean(rerank_ms), 1) if rerank_ms else 0,
            "total_rerank_ms": round(sum(rerank_ms), 1),
            "mean_rerank_pairs": round(statistics.mean(r["rerank_pairs"] for r in selected), 1)
            if selected else 0,
            "baseline_recall": round(sum(r["baseline_hits"] for r in selected)
                                     / max(1, sum(r["baseline_count"] for r in selected)), 4),
            "adopted_recall": round(sum(r["adopted_hits"] for r in selected)
                                    / max(1, sum(r["adopted_count"] for r in selected)), 4),
            "exact_topk_matches": sum(r["result_chunk_ids"] == r["baseline_chunk_ids"] for r in selected),
        })
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="기준선 pipeline JSON")
    parser.add_argument("--limits", default="12,20,30,0", help="쉼표 구분 후보 수; 0은 제한 없음")
    parser.add_argument("--dev", help="재생할 질문 ID (예: D1,D6, 미지정 시 전체)")
    parser.add_argument("--output", type=Path, help="결과 JSON 경로")
    args = parser.parse_args()
    limits = [int(value.strip()) for value in args.limits.split(",") if value.strip()]
    if not limits or any(value < 0 for value in limits):
        parser.error("--limits에는 0 이상의 정수가 하나 이상 필요합니다")

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    labels = {value.strip() for value in args.dev.split(",") if value.strip()} if args.dev else None
    searches = _new_searches(payload, labels)
    if not searches:
        parser.error("입력 결과에서 new 검색을 찾지 못했습니다")

    # 지연 import: 인자 검증이 끝난 뒤 DB와 BGE를 한 번만 초기화한다.
    from app.core.retriever import retriever

    rows = []
    for search in searches:
        for limit in limits:
            retriever.rerank_candidate_limit = limit
            metrics: dict[str, Any] = {}
            docs = retriever.retrieve(search["query"], k=len(search["baseline_chunk_ids"]) or 7,
                                      metrics=metrics)
            result_ids = [_evidence_id(doc) for doc in docs]
            baseline_ids = search["baseline_chunk_ids"]
            adopted_ids = search["adopted_baseline_ids"]
            rows.append({
                "label": search["label"], "query": search["query"], "limit": limit,
                "baseline_chunk_ids": baseline_ids, "result_chunk_ids": result_ids,
                "baseline_count": len(baseline_ids),
                "baseline_hits": len(set(baseline_ids) & set(result_ids)),
                "adopted_count": len(adopted_ids),
                "adopted_hits": len(set(adopted_ids) & set(result_ids)),
                "merged_candidates": metrics.get("merged_candidates"),
                "rerank_pairs": metrics.get("rerank_pairs"),
                "rerank_ms": round(float(metrics.get("rerank_ms", 0)), 1),
                "reranker_device": metrics.get("reranker_device"),
            })
            print(f"{search['label']} limit={limit or 'all':>3} "
                  f"pairs={metrics.get('rerank_pairs', 0):>2} "
                  f"BGE={metrics.get('rerank_ms', 0) / 1000:>5.1f}s "
                  f"baseline={rows[-1]['baseline_hits']}/{len(baseline_ids)}")

    summaries = summarize(rows, limits)
    print("\nlimit  queries  mean BGE  total BGE  pairs  baseline recall  adopted recall  exact")
    for row in summaries:
        print(f"{row['limit'] or 'all':>5}  {row['queries']:>7}  "
              f"{row['mean_rerank_ms'] / 1000:>8.2f}s  {row['total_rerank_ms'] / 1000:>9.2f}s  "
              f"{row['mean_rerank_pairs']:>5.1f}  {row['baseline_recall']:>15.1%}  "
              f"{row['adopted_recall']:>14.1%}  "
              f"{row['exact_topk_matches']:>5}")

    output = args.output or RESULTS_DIR / f"rerank_candidates_{datetime.now():%Y%m%d_%H%M%S}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"input": str(args.input), "limits": limits,
                                  "summary": summaries, "rows": rows},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
