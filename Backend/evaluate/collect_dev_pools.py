"""
개발용 질문(dev_questions.py)마다 ①→②→③ 첫 바퀴를 실제로 돌려 근거 풀을 저장한다.
이후 ④를 고칠 때는 검색을 다시 하지 않고 저장된 풀로 반복한다:
  python -m evaluate.check_verification --dev

실제 OpenAI(① 1~2회)와 retriever·ChromaDB를 쓴다. ④는 부르지 않는다.
이미 저장된 질문은 건너뛴다(--force로 다시 수집). 저장 위치: evaluate/results/dev_pools/D1.json ...

사용법 (Backend 폴더에서)
  python -m evaluate.collect_dev_pools              # 없는 것만 수집
  python -m evaluate.collect_dev_pools --only D1,D5
  python -m evaluate.collect_dev_pools --force      # 전부 다시
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from evaluate.check_search_execution import collect_round1
from evaluate.dev_questions import DEV_QUESTIONS

POOL_DIR = Path(__file__).resolve().parent / "results" / "dev_pools"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="개발용 질문의 근거 풀 수집 (①②③ 첫 바퀴)")
    ap.add_argument("--only", help="쉼표로 구분한 질문 ID (예: D1,D5)")
    ap.add_argument("--force", action="store_true", help="이미 저장된 것도 다시 수집")
    ap.add_argument("--no-expand", action="store_true", help="원문 확장 생략")
    args = ap.parse_args()

    wanted = {x.strip() for x in args.only.split(",")} if args.only else None
    POOL_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for q in DEV_QUESTIONS:
        if wanted and q["id"] not in wanted:
            continue
        out = POOL_DIR / f"{q['id']}.json"
        if out.exists() and not args.force:
            print(f"[건너뜀] {q['id']} 이미 있음 ({out.name})")
            continue
        print(f"\n########## {q['id']} ({q['type']}) ##########")
        started = time.perf_counter()
        record = collect_round1(q["question"], expand=not args.no_expand, verbose=True)
        record.update({"dev_id": q["id"], "dev_type": q["type"], "dev_check": q["check"],
                       "collected_at": datetime.now().isoformat(timespec="seconds")})
        out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        a = record.get("analysis") or {}
        n_pool = len((record.get("pool") or {}).get("chunks", {}))
        rows.append((q["id"], a.get("primary_type"), a.get("next_action"), n_pool, record.get("stopped"),
                     int((time.perf_counter() - started) * 1000)))
        print(f"→ 저장: {out}")

    if rows:
        print("\n===== 수집 요약 =====")
        print("ID  | ① 유형 | ① 다음 행동    | 풀 | 중단 이유 | 걸린 시간")
        for r in rows:
            print(f"{r[0]:<3} | {str(r[1]):<6} | {str(r[2]):<14} | {r[3]:>2} | {r[4] or '-'} | {r[5]}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
