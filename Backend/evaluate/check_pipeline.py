"""
단일 에이전트 전체 흐름 확인 스크립트: 질문 → ① → (②③④ 반복) → ⑤ 답변.

실제 OpenAI와 retriever·ChromaDB를 쓴다 (Backend 폴더에서 실행).
  python -m evaluate.check_pipeline "GKS 장학생은 아르바이트 할 수 있어?"
  python -m evaluate.check_pipeline --dev D1,D6           # 개발용 질문을 끝까지
  python -m evaluate.check_pipeline --dev all --verify-model gpt-4o
  python -m evaluate.check_pipeline "질문" --max-rounds 2 --no-save

결과는 evaluate/results/pipeline_<시각>.json에 저장한다 (라운드별 계획·검색·판정·답변 전체 기록).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.core.single_agent.answer_schema import PipelineRun
from app.core.single_agent.pipeline import run_pipeline
from app.core.single_agent.metrics import METRICS_VERSION

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _printer(stage: str, info: Dict) -> None:
    if stage == "analysis":
        if info.get("error"):
            print(f"① 분석 실패: {info['error']}")
        else:
            print(f"① 분석: 유형 {info['type']}, 다음 행동 {info['next_action']}, 칸 {info['slots']}")
    elif stage == "plan":
        if info.get("slot"):
            print(f"\n[라운드 {info['round']}] ② 계획: {info['slot']} / {info['type']} / '{info['query']}'")
        else:
            print(f"\n[라운드 {info['round']}] ② 더 검색하지 않음: {info.get('action')} {info.get('error') or ''}")
    elif stage == "search":
        if info.get("error"):
            print(f"   ③ 검색 실패 [{info['error_type']}]: {info['error']}")
        else:
            print(f"   ③ 검색: 이번 청크 {info['chunks']}개 (새 청크 {info['new']}), 풀 {info['pool']}개")
    elif stage == "verify_start":
        print("   ④ 판정 중...")
    elif stage == "verify":
        if info.get("error"):
            print(f"   ④ 실패: {info['error']}")
        else:
            st = " ".join(f"{k}={v}" for k, v in info["statuses"].items())
            print(f"   ④ {info['next_action']}  ({info['reason']})\n      {st}")
    elif stage == "answer_start":
        print(f"\n⑤ 답변 작성 ({info['mode']})...")


def summarize(run: PipelineRun) -> Dict:
    a = run.answer_run
    stage_ms = {
        "①": run.analysis_run.latency_ms if run.analysis_run else 0,
        "②": sum(p.latency_ms for p in run.plan_runs),
        "③": sum(s.latency_ms for s in run.search_runs),
        "④": sum(v.latency_ms for v in run.verify_runs),
        "⑤": a.latency_ms if a else 0,
    }
    stages = {"analyze": [run.analysis_run] if run.analysis_run else [], "plan": run.plan_runs,
              "verify": run.verify_runs, "answer": [a] if a else []}
    stage_usage = {}
    for name, runs in stages.items():
        calls = [c for r in runs for c in r.calls]
        stage_usage[name] = {
            "prompt_tokens": sum(r.prompt_tokens for r in runs),
            "completion_tokens": sum(r.completion_tokens for r in runs),
            "sdk_calls": len(calls),
            "usage_complete": all(c.prompt_tokens is not None and c.completion_tokens is not None for c in calls)
                              and all(r.attempts == 0 or r.calls for r in runs),
            "cached_prompt_tokens": sum(c.cached_prompt_tokens or 0 for c in calls),
        }
    all_calls = [c for runs in stages.values() for r in runs for c in r.calls]
    rechecks = [c for c in all_calls if c.purpose == "recheck"]
    tokens = sum(s["prompt_tokens"] + s["completion_tokens"] for s in stage_usage.values())
    return {"mode": a.mode if a else None, "rounds": run.rounds, "stopped": run.stopped,
            "verification_skips": run.verification_skips,
            "metrics_version": METRICS_VERSION, "stage_usage": stage_usage,
            "sdk_calls": len(all_calls), "usage_complete": all(s["usage_complete"] for s in stage_usage.values()),
            "recheck": {"sdk_calls": len(rechecks), "latency_ms": sum(c.latency_ms for c in rechecks),
                        "tokens": sum((c.prompt_tokens or 0) + (c.completion_tokens or 0) for c in rechecks)},
            "searches": [{"type": s.plan.search_type if s.plan else None, "ok": s.ok,
                          "returned_chunks": len(s.chunk_ids), "new_chunks": len(s.new_chunk_ids),
                          "latency_ms": s.latency_ms, "retrieval_calls": s.retrieval_calls}
                         for s in run.search_runs],
            "adopted_evidence_count": len({r.evidence_id for slot in run.analysis.document_slots
                                           if slot.active for r in slot.evidence_refs}) if run.analysis else 0,
            "latency_ms": run.latency_ms, "stage_ms": stage_ms, "tokens": tokens,
            "llm_calls": (run.analysis_run.attempts if run.analysis_run else 0)
            + sum(p.attempts for p in run.plan_runs) + sum(v.attempts for v in run.verify_runs)
            + (a.attempts if a else 0),
            "sources": len(a.sources) if a else 0}


def show(run: PipelineRun) -> None:
    a = run.answer_run
    print("\n" + "=" * 70)
    print(a.answer if a else "(답변 없음)")
    if a and a.sources:
        print("\n출처")
        for s in a.sources:
            print(f"  [{s.number}] {s.source} p.{s.page}")
    sm = summarize(run)
    print("=" * 70)
    print(f"방식 {sm['mode']} | 라운드 {sm['rounds']} | 종료 {sm['stopped']} | "
          f"{sm['latency_ms'] / 1000:.1f}초 (" + " ".join(f"{k}{v / 1000:.1f}" for k, v in sm["stage_ms"].items())
          + f") | LLM {sm['llm_calls']}회, 토큰 {sm['tokens']}")
    for w in run.warnings + (a.warnings if a else []):
        print(f"  경고: {w}")


def run_one(question: str, args, label: Optional[str] = None) -> Dict:
    print(f"\n########## {label or ''} {question}")
    run = run_pipeline(question, model=args.model, verify_model=args.verify_model,
                       answer_model=args.answer_model, max_rounds=args.max_rounds, on_event=_printer)
    show(run)
    return {"label": label, "question": question, "summary": summarize(run), "run": run.model_dump()}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="단일 에이전트 전체 흐름 확인 (질문 → 답변)")
    ap.add_argument("question", nargs="?", help="질문")
    ap.add_argument("--dev", help="개발용 질문 ID (예: D1,D6 또는 all)")
    ap.add_argument("--model", help="①② 모델 (기본: OPENAI_MODEL)")
    ap.add_argument("--verify-model", help="④ 모델 (기본: VERIFY_MODEL 또는 OPENAI_MODEL)")
    ap.add_argument("--answer-model", help="⑤ 모델 (기본: OPENAI_MODEL)")
    ap.add_argument("--max-rounds", type=int, help="②③④ 라운드 상한 (기본: MAX_VERIFY_ROUNDS)")
    ap.add_argument("--no-save", action="store_true", help="결과 JSON 저장 안 함")
    ap.add_argument("--label", default="", help="실험 변경 이름")
    ap.add_argument("--corpus-version", default="", help="사용한 문서/색인 버전 (미지정이면 unknown)")
    ap.add_argument("--rerank-candidates", type=int, default=None,
                    help="BGE에 전달할 RRF 상위 후보 수 (0=제한 없음, 권장 실험값: 12/20/30)")
    args = ap.parse_args()

    if args.rerank_candidates is not None:
        if args.rerank_candidates < 0:
            ap.error("--rerank-candidates는 0 이상의 정수여야 합니다")
        # retriever는 첫 검색에서 지연 import되므로 여기서 설정하면 해당 실행 전체에 동일하게 적용된다.
        from app.config import settings
        settings.rerank_candidate_limit = args.rerank_candidates

    from evaluate.experiment_metadata import experiment_metadata
    metadata = experiment_metadata(args.label, args.corpus_version)

    items: List[Dict] = []
    if args.dev:
        from evaluate.dev_questions import DEV_QUESTIONS
        want = None if args.dev == "all" else {x.strip() for x in args.dev.split(",")}
        for q in DEV_QUESTIONS:
            if want is None or q["id"] in want:
                items.append(run_one(q["question"], args, q["id"]))
    elif args.question:
        items.append(run_one(args.question, args))
    else:
        ap.print_help()
        return 1

    if len(items) > 1:
        print("\n===== 요약 =====")
        for it in items:
            s = it["summary"]
            print(f"{it['label'] or '-':<4} {s['mode']:<20} 라운드 {s['rounds']} {s['latency_ms'] / 1000:>5.1f}초 "
                  f"LLM {s['llm_calls']:>2}회 출처 {s['sources']} | {s['stopped']}")
    if not args.no_save:
        RESULTS_DIR.mkdir(exist_ok=True)
        out = RESULTS_DIR / f"pipeline_{datetime.now():%Y%m%d_%H%M%S}.json"
        out.write_text(json.dumps({"meta": metadata, "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n결과 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
