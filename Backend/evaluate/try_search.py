"""
검색어 하나를 에이전트 ③과 같은 방식(하이브리드 + BGE 리랭커)으로 검색해 순위를 본다. LLM은 부르지 않는다.

  python -m evaluate.try_search "학부 신입생 첫 학기 휴학"
  python -m evaluate.try_search "GKS 장학생 첫 학기 휴학 규정" "입학 후 첫 학기 휴학 불가" -k 10
  python -m evaluate.try_search "첫 학기 휴학" --grep "첫 학기"   # 본문에 이 문구가 있는 청크 표시
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="검색어 순위 확인")
    ap.add_argument("queries", nargs="+")
    ap.add_argument("-k", type=int, default=7, help="가져올 청크 수 (에이전트 기본 SEARCH_TOP_K=7)")
    ap.add_argument("--grep", help="본문에 이 문구가 있으면 ★ 표시")
    a = ap.parse_args()

    from app.core.retriever import retriever
    for q in a.queries:
        print(f"\n### '{q}'")
        for i, d in enumerate(retriever.retrieve(q, k=a.k), 1):
            m = d.metadata or {}
            score = m.get("rerank_score", m.get("score", m.get("similarity_score")))
            sc = f"{score:.3f}" if isinstance(score, (int, float)) else "-"
            text = " ".join((d.page_content or "").split())
            star = "★" if a.grep and a.grep.replace(" ", "") in text.replace(" ", "") else " "
            print(f"{i:2d}.{star} {sc} {os.path.basename(str(m.get('source', '?')))} p.{m.get('page', '?')} "
                  f"c{m.get('chunk_index', '?')} | {text[:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
