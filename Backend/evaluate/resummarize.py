"""
이미 저장된 비교 실험 결과를 다시 합산한다. API 호출 없이 계산만 한다.

쓰임새
  1) 여러 번 나눠 돌린 결과 파일을 합쳐 n회 평균을 낸다.
  2) 채점 지표를 추가한 뒤, 지난 실험도 같은 지표로 다시 본다.

답변과 채점 결과는 파일에 있는 그대로 쓴다. 다시 묻거나 다시 채점하지 않으므로
held-out 세트의 결과가 이 스크립트 때문에 바뀌지 않는다.

사용법 (Backend 폴더에서)
  python -m evaluate.resummarize evaluate/results/service_compare_20261009_*.json
  python -m evaluate.resummarize evaluate/results/service_compare_20261004_003211.json
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Dict, List

from evaluate.compare_service import _pct, summarize


def load_rows(paths: List[str]) -> tuple[List[Dict], List[Dict]]:
    rows: List[Dict] = []
    metas: List[Dict] = []
    for pattern in paths:
        for fn in sorted(glob.glob(pattern)):
            d = json.loads(Path(fn).read_text(encoding="utf-8"))
            meta = d.get("meta") or {}
            meta["_file"] = Path(fn).name
            metas.append(meta)
            rows.extend(d.get("rows") or [])
    return rows, metas


def print_report(rows: List[Dict], metas: List[Dict]) -> None:
    s = summarize(rows)
    b, a = s["baseline"], s["service"]

    print(f"\n파일 {len(metas)}개 · 답변 {len(rows)}쌍")
    for m in metas:
        print(f"  {m['_file']}  세트={m.get('question_set', '?')}  {m.get('label') or ''}")

    sets = {m.get("question_set") for m in metas}
    if len(sets) > 1:
        print(f"\n  주의: 서로 다른 질문 세트({', '.join(sorted(str(x) for x in sets))})를 합쳤다.")

    print("\n                     기존 검색    현재 서비스")
    print(f"핵심 사실 포함률     {_pct(b['coverage']):>8s}    {_pct(a['coverage']):>8s}")
    print(f"완전 정답 답변 수    {b['full_correct']:>5d}/{b['n']:<2d}    {a['full_correct']:>5d}/{a['n']:<2d}")
    print(f"0점 답변 수          {b.get('zero', 0):>5d}/{b['n']:<2d}    {a.get('zero', 0):>5d}/{a['n']:<2d}")
    print(f"최저 포함률          {_pct(b.get('min_coverage')):>8s}    {_pct(a.get('min_coverage')):>8s}")
    print(f"틀린 내용 수(합계)   {b['wrong']:>8d}    {a['wrong']:>8d}")
    print(f"평균 응답 시간       {b['latency_s'] or 0:>7.1f}s    {a['latency_s'] or 0:>7.1f}s")

    # 질문별: 평균과 함께 회차별 점수를 늘어놓아 변동 폭이 보이게 한다.
    runs: Dict[str, Dict[str, List[float]]] = {}
    for r in rows:
        d = runs.setdefault(r["id"], {"baseline": [], "service": []})
        for m in ("baseline", "service"):
            sc = r[m].get("score")
            if sc:
                d[m].append(sc["coverage"])

    print("\n질문별 포함률 (평균, 회차별)")
    for qid, v in runs.items():
        bb = " / ".join(_pct(x) for x in v["baseline"])
        aa = " / ".join(_pct(x) for x in v["service"])
        print(f"  {qid:7s} 기존 {_pct(s['per_question'][qid]['baseline']):>5s} [{bb}]")
        print(f"  {'':7s} 서비스 {_pct(s['per_question'][qid]['service']):>5s} [{aa}]")


def main() -> int:
    p = argparse.ArgumentParser(description="저장된 비교 실험 결과를 다시 합산 (API 호출 없음)")
    p.add_argument("paths", nargs="+", help="결과 JSON 경로 (와일드카드 가능)")
    a = p.parse_args()
    rows, metas = load_rows(a.paths)
    if not rows:
        print("결과 파일을 찾지 못했다.")
        return 1
    print_report(rows, metas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
