"""
개발용 질문의 정답 초안을 팀 검토용 마크다운으로 내보낸다.
정답에 적힌 청크마다 저장된 풀(results/dev_pools)의 본문 앞부분을 붙여서, PDF를 열지 않고도 대조할 수 있게 한다.
풀 밖 청크(final.outside_pool)는 본문이 없으므로 PDF 원문으로 확인해야 한다.

사용법 (Backend 폴더에서)
  python -m evaluate.export_dev_gold            # ../docs/single_agent/dev_gold_draft.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from evaluate.dev_questions import DEV_QUESTIONS

POOL_DIR = Path(__file__).resolve().parent / "results" / "dev_pools"
OUT = Path(__file__).resolve().parents[2] / "docs" / "single_agent" / "dev_gold_draft.md"


def _short(eid: str) -> str:
    src, rest = eid.split("#", 1)
    name = src.replace(".pdf", "")
    for key, label in [("(EN)정부초청", "GKS지침(EN)"), ("(KO)정부초청", "GKS지침(KO)"), ("한국어트랙", "모집요강(한국어트랙)"),
                       ("English+Track", "모집요강(영어트랙)"), ("Korean+Language+Course", "어학당 안내"),
                       ("Study in KOREA", "Study in KOREA(KVAC 헤이그)")]:
        if key in name:
            name = label
            break
    return f"{name} {rest}"


def build() -> str:
    lines = ["# 개발용 질문 정답 초안 (검토용)", "",
             "- 자동 생성: `python -m evaluate.export_dev_gold` (원본은 `Backend/evaluate/dev_questions.py`)",
             "- 상태: **초안**. 체크리스트 9절대로 원문 근거 승인은 팀이 한다. 틀린 곳은 dev_questions.py를 고치고 다시 생성.",
             "- 기준 풀: 2026-09-29 수집한 첫 바퀴(검색 1회 + 1순위 청크 앞뒤 확장)", ""]
    for q in DEV_QUESTIONS:
        g = q.get("gold") or {}
        r1 = g.get("round1") or {}
        pool_file = POOL_DIR / f"{q['id']}.json"
        chunks = json.loads(pool_file.read_text(encoding="utf-8"))["pool"]["chunks"] if pool_file.exists() else {}

        def excerpt(eid: str) -> str:
            ch = chunks.get(eid)
            if not ch:
                return "(풀 밖: PDF 원문 확인)"
            return ch["text"].replace("\n", " ").replace("|", "¦")[:160]

        lines += [f"## {q['id']} ({q['type']}) {q['question']}", "", f"- 확인할 점: {q['check']}",
                  f"- 첫 바퀴 기대 다음 행동: {' / '.join(r1.get('next_action', []))}", ""]
        lines += ["| 칸 | 허용 상태 | 꼭 인용 (묶음 중 하나) | 인용 금지 |", "|---|---|---|---|"]
        slots = list(dict.fromkeys(list(r1.get("slots", {})) + list(r1.get("must_cite", {})) + list(r1.get("must_not_cite", {}))))
        for s in slots:
            allowed = "/".join(r1.get("slots", {}).get(s, [])) or "-"
            cites = "<br>".join(" 또는 ".join(_short(i) for i in grp) for grp in r1.get("must_cite", {}).get(s, [])) or "-"
            nots = "<br>".join(_short(i) for i in r1.get("must_not_cite", {}).get(s, [])) or "-"
            lines.append(f"| {s} | {allowed} | {cites} | {nots} |")
        if r1.get("user_fields"):
            lines += ["", f"- 활성화돼야 할 사용자 칸: {', '.join(r1['user_fields'])}"]
        ids = []
        for grps in r1.get("must_cite", {}).values():
            for grp in grps:
                ids += grp
        for bad in r1.get("must_not_cite", {}).values():
            ids += bad
        if ids:
            lines += ["", "<details><summary>근거 청크 본문 (앞부분)</summary>", ""]
            for i in dict.fromkeys(ids):
                lines.append(f"- **{_short(i)}**: {excerpt(i)}")
            lines += ["", "</details>"]
        fin = g.get("final") or {}
        lines += ["", f"**최종 기대**: {fin.get('mode', '-')}"]
        for k in fin.get("key_facts", []):
            lines.append(f"- {k}")
        if fin.get("outside_pool"):
            lines.append("- 첫 풀 밖에 있는 필요한 청크: " + ", ".join(_short(i) for i in fin["outside_pool"]))
        if g.get("notes"):
            lines += ["", "**메모**"] + [f"- {n}" for n in g["notes"]]
        lines += ["", "---", ""]
    return "\n".join(lines)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"저장: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
