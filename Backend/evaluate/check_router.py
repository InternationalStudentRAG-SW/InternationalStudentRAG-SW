"""
⓪ 라우터 결과를 확인하는 스크립트.

실제 OpenAI API를 호출한다 (Backend/.env의 OPENAI_API_KEY). 질문 1개당 LLM 1~2회 (gpt-4o-mini, 짧은 프롬프트).
CI(pytest tests/)에는 포함되지 않는다.

사용법 (Backend 폴더에서)
  # 질문 하나
  python -m evaluate.check_router "저 GKS 장학생인데 아르바이트 해도 돼요? 된다면 어떤 서류를 내요?"

  # 정답 세트 전체 / 일부 + 채점 (결과는 evaluate/results/router_gold_*.json에 저장)
  python -m evaluate.check_router --gold
  python -m evaluate.check_router --gold --only D6 D8 R10

  # 보류 세트(프롬프트를 고칠 때 보지 않은 질문)로 채점 → evaluate/results/router_heldout_*.json
  python -m evaluate.check_router --heldout

옵션
  --model gpt-4o      다른 모델로 비교
  --json              전체 결과를 JSON으로도 출력
  --show-prompt       시스템 프롬프트 출력

채점 지표 (경계 사례 boundary=True는 정확도에서 빼고 따로 표시)
  route_acc   : 경로 일치율
  miss_rate   : 정답 agent인데 simple로 보낸 비율  ← 가장 중요 (놓치면 틀린 답이 나감)
  over_rate   : 정답 simple인데 agent로 보낸 비율   (비용만 늘어남)
  action_acc / asks_acc / depends_acc, 평균 토큰·지연, 라우터 실패(fallback) 수
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.core.single_agent import checklist_config as cfg  # noqa: E402
from app.core.single_agent.router import build_system_prompt, route_question  # noqa: E402
from app.core.single_agent.router_schema import RouteRun  # noqa: E402
from evaluate.router_questions import HARD_QUESTIONS, HELDOUT_QUESTIONS, ROUTER_QUESTIONS  # noqa: E402

RESULTS_DIR = os.path.join(_BACKEND_DIR, "evaluate", "results")


def print_run(run: RouteRun) -> None:
    r = run.result
    print(f"\n질문: {run.question}")
    if run.history:
        print(f"  (이전 대화 {len(run.history)}개)")
    print(f"  경로: {r.route}  | action={r.action}" + ("  [라우터 실패 → fallback]" if run.fallback_used else ""))
    for reason in r.route_reasons:
        print(f"    - {reason}")
    for a in r.asks:
        dep = f"  ← {a.depends_on} ({a.only_if})" if a.depends_on else ""
        print(f"  [{a.ask_id}] {a.kind or '-'} {a.text} | 인용 '{a.quote}' | 검색어 '{a.query_ko}'{dep}")
    for c in r.user_conditions:
        print(f"  조건: {c.field_id}={c.value} ({c.subject}, {c.source_message_id} '{c.quote}')")
    for w in run.warnings:
        print(f"  {w}")
    if run.error:
        print(f"  오류: {run.error}")
    print(f"  토큰 {run.prompt_tokens}+{run.completion_tokens} | {run.latency_ms}ms | 시도 {run.attempts}회")


def score_row(q: Dict, run: RouteRun) -> Dict:
    r = run.result
    has_dep = any(a.depends_on for a in r.asks)
    return {
        "id": q["id"], "question": q["question"], "boundary": bool(q.get("boundary")),
        "label_src": q.get("label_src"),
        "gold": {"route": q["route"], "action": q["action"], "n_asks": q["n_asks"], "depends": q["depends"]},
        "pred": {"route": r.route, "action": r.action, "n_asks": len(r.asks), "depends": has_dep},
        # 정답 라벨이 None이면 채점하지 않는다 (보류 세트의 요구 개수·의존 관계)
        "ok": {k: (None if q[k] is None else pred == q[k]) for k, pred in
               (("route", r.route), ("action", r.action), ("n_asks", len(r.asks)), ("depends", has_dep))},
        "fallback": run.fallback_used,
        "run": run.model_dump(),
    }


def _rate(n: int, d: int) -> Optional[float]:
    return round(n / d, 3) if d else None


def summarize(rows: List[Dict]) -> Dict:
    main = [r for r in rows if not r["boundary"]]
    gold_agent = [r for r in main if r["gold"]["route"] == "agent"]
    gold_simple = [r for r in main if r["gold"]["route"] == "simple"]
    search = [r for r in main if r["gold"]["action"] == "search"]
    runs = [r["run"] for r in rows]
    return {
        "n": len(rows), "n_scored": len(main), "n_boundary": len(rows) - len(main),
        "route_acc": _rate(sum(r["ok"]["route"] for r in main), len(main)),
        "miss_rate": _rate(sum(r["pred"]["route"] == "simple" for r in gold_agent), len(gold_agent)),
        "over_rate": _rate(sum(r["pred"]["route"] == "agent" for r in gold_simple), len(gold_simple)),
        "action_acc": _rate(sum(r["ok"]["action"] for r in main), len(main)),
        "asks_acc": _rate(sum(bool(r["ok"]["n_asks"]) for r in search if r["ok"]["n_asks"] is not None),
                          sum(r["ok"]["n_asks"] is not None for r in search)),
        "depends_acc": _rate(sum(bool(r["ok"]["depends"]) for r in search if r["ok"]["depends"] is not None),
                             sum(r["ok"]["depends"] is not None for r in search)),
        "fallbacks": sum(r["fallback"] for r in rows),
        "avg_prompt_tokens": _rate(sum(x["prompt_tokens"] for x in runs), len(runs)),
        "avg_completion_tokens": _rate(sum(x["completion_tokens"] for x in runs), len(runs)),
        "avg_latency_ms": _rate(sum(x["latency_ms"] for x in runs), len(runs)),
        "boundary": [{"id": r["id"], "gold": r["gold"]["route"], "pred": r["pred"]["route"]}
                     for r in rows if r["boundary"]],
    }


def print_summary(rows: List[Dict], s: Dict) -> None:
    print("\n" + "=" * 70)
    print(f"{'ID':5s} {'정답':7s} {'예측':7s} {'action':14s} {'asks':6s} {'dep':6s}")
    for r in rows:
        mark = "" if r["ok"]["route"] else "  ✗" + (" (놓침)" if r["gold"]["route"] == "agent" else " (과잉)")
        if r["boundary"]:
            mark += "  [경계]"
        print(f"{r['id']:5s} {r['gold']['route']:7s} {r['pred']['route']:7s} "
              f"{r['pred']['action']:14s} {r['pred']['n_asks']}/{str(r['gold']['n_asks'] if r['gold']['n_asks'] is not None else '-'):<4s} "
              f"{str(r['pred']['depends'])[0]}/{str(r['gold']['depends'])[0] if r['gold']['depends'] is not None else '-'}{mark}")
    print("-" * 70)
    for k in ("route_acc", "miss_rate", "over_rate", "action_acc", "asks_acc", "depends_acc", "fallbacks",
              "avg_prompt_tokens", "avg_completion_tokens", "avg_latency_ms"):
        print(f"{k:22s} {s[k]}")
    print(f"(정확도는 경계 사례 {s['n_boundary']}개를 뺀 {s['n_scored']}개 기준)")


def run_gold(only: Optional[List[str]], model: Optional[str], as_json: bool, heldout: bool = False, hard: bool = False) -> str:
    pool = HARD_QUESTIONS if hard else (HELDOUT_QUESTIONS if heldout else ROUTER_QUESTIONS)
    qs = [q for q in pool if not only or q["id"] in only]
    rows = []
    for q in qs:
        run = route_question(q["question"], q.get("history"), model=model)
        print_run(run)
        rows.append(score_row(q, run))
    s = summarize(rows)
    print_summary(rows, s)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"router_{'hard' if hard else ('heldout' if heldout else 'gold')}_{datetime.now():%Y%m%d_%H%M%S}.json")
    meta = {"model": rows[0]["run"]["model"] if rows else model, "checklist_version": cfg.CHECKLIST_VERSION,
            "prompt_chars": len(build_system_prompt()), "agent_kinds": sorted(cfg.ROUTER_AGENT_KINDS),
            "only": only, "set": "hard" if hard else ("heldout" if heldout else "gold")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "summary": s, "rows": rows}, f, ensure_ascii=False, indent=2)
    if as_json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
    print(f"\n저장: {path}")
    return path


def main() -> int:
    p = argparse.ArgumentParser(description="⓪ 라우터 확인")
    p.add_argument("question", nargs="?")
    p.add_argument("--history", help="이전 대화 JSON 파일")
    p.add_argument("--gold", action="store_true")
    p.add_argument("--heldout", action="store_true", help="보류 세트(노션 복합 질문)로 채점")
    p.add_argument("--hard", action="store_true", help="어려운 세트(경계·후속·범위 밖 등)")
    p.add_argument("--only", nargs="*")
    p.add_argument("--model")
    p.add_argument("--json", action="store_true")
    p.add_argument("--show-prompt", action="store_true")
    a = p.parse_args()

    if a.show_prompt:
        print(build_system_prompt())
    if a.gold or a.heldout or a.hard:
        run_gold(a.only, a.model, a.json, heldout=a.heldout, hard=a.hard)
        return 0
    if not a.question:
        p.print_help()
        return 1
    history = None
    if a.history:
        with open(a.history, encoding="utf-8") as f:
            history = json.load(f)
    run = route_question(a.question, history, model=a.model)
    print_run(run)
    if a.json:
        print(json.dumps(run.model_dump(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
