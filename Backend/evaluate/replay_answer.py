"""
⑤ 답변만 다시 돌려 보는 확인 도구 (검색·검증은 다시 하지 않음).

저장된 에이전트 실행 기록(logs/agent_runs/*.json)의 근거·판정을 그대로 두고, 지금 코드의 ⑤로 답을 다시 쓴 뒤
compare_service의 핵심 사실 기준으로 이전 답과 새 답을 채점해 비교한다. ⑤를 고친 효과를 본 실험 전에 빠르게 확인하는 용도.

  python -m evaluate.replay_answer --since 20261003_1653 --until 20261003_1718      # 그 시간대 기록 전부
  python -m evaluate.replay_answer logs/agent_runs/20261003_165801_xxxx.json --repeat 3

비용: 기록 1개당 ⑤ 1~3회 + 채점 1~2회 (모델은 .env 설정 그대로)
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

BACKEND = Path(__file__).resolve().parents[1]
LOG_DIR = BACKEND / "logs" / "agent_runs"


def find_logs(since: str = "", until: str = "") -> List[Path]:
    return [p for p in sorted(LOG_DIR.glob("*.json")) if (not since or p.stem >= since) and (not until or p.stem <= until)]


def question_spec(question: str) -> Optional[Dict]:
    from evaluate.compare_service import QUESTIONS
    return next((q for q in QUESTIONS if q["question"].strip() == question.strip()), None)


def replay(log: Dict, write_fn=None):
    """기록 하나의 근거로 ⑤만 다시 실행한다. 돌려주는 값: 새 AnswerRun."""
    from app.core.single_agent.answer_schema import PipelineRun
    from app.core.single_agent.pipeline import ask_extra_evidence
    if write_fn is None:
        from app.core.single_agent.answerer import write_answer as write_fn
    run = PipelineRun.model_validate(log["run"])
    asks = ((log.get("router") or {}).get("result") or {}).get("asks") or None
    mode = run.answer_run.mode if run.answer_run else (run.decision.next_action if run.decision else "partial_answer")
    return write_fn(run.question, mode, run.analysis, run.pool, run.decision, asks=asks,
                    extra_evidence_ids=ask_extra_evidence(run.search_runs))


def main() -> int:
    p = argparse.ArgumentParser(description="⑤ 답변만 다시 돌려 이전 답과 비교")
    p.add_argument("logs", nargs="*", help="실행 기록 파일 (없으면 --since/--until 범위)")
    p.add_argument("--since", default="")
    p.add_argument("--until", default="")
    p.add_argument("--repeat", type=int, default=2, help="기록마다 ⑤를 몇 번 다시 돌릴지 (기본 2)")
    p.add_argument("--no-judge", action="store_true")
    args = p.parse_args()

    from evaluate.compare_service import judge_answer, _pct
    from app.core.single_agent.llm import get_client
    client = get_client()
    paths = [Path(x) for x in args.logs] or find_logs(args.since, args.until)
    if not paths:
        print("실행 기록이 없습니다. --since/--until 또는 파일 경로를 확인하세요.")
        return 1
    rows = []
    for path in paths:
        log = json.loads(path.read_text(encoding="utf-8"))
        spec = question_spec(log["question"])
        old = (log.get("final") or {}).get("answer_sent") or ""
        row = {"log": path.name, "question": log["question"], "id": spec["id"] if spec else None, "old": {"answer": old}, "new": []}
        print(f"\n=== {row['id'] or '?'} {log['question']}")
        if spec and not args.no_judge:
            row["old"]["score"] = judge_answer(spec, old, client)
            print(f"  이전: 포함률 {_pct(row['old']['score']['coverage'])} 틀림 {row['old']['score']['wrong']}")
        for t in range(1, args.repeat + 1):
            ar = replay(log)
            item = {"answer": ar.answer, "shown": len(ar.shown_evidence_ids), "caveats": ar.caveat_sentences,
                    "rewrites": ar.rewrites, "warnings": ar.warnings, "tokens": ar.prompt_tokens + ar.completion_tokens}
            if spec and not args.no_judge:
                item["score"] = judge_answer(spec, ar.answer, client)
                print(f"  새 답 #{t}: 포함률 {_pct(item['score']['coverage'])} 틀림 {item['score']['wrong']} "
                      f"(근거 {item['shown']}개, 단서 다시쓰기 {'O' if ar.caveat_sentences else 'X'}, ⑤ 토큰 {item['tokens']})")
            print("    " + ar.answer.replace("\n", "\n    "))
            row["new"].append(item)
        rows.append(row)
    out = BACKEND / "evaluate" / "results" / f"replay_answer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
