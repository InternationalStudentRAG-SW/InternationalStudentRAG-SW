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
    tokens = sum(x.prompt_tokens + x.completion_tokens for x in
                 [r for r in [run.analysis_run, a] if r] + run.verify_runs)
    return {"mode": a.mode if a else None, "rounds": run.rounds, "stopped": run.stopped,
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
    args = ap.parse_args()

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
        out.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n결과 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
