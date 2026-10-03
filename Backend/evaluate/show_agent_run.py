"""
실서비스 에이전트 실행 기록 보기 (logs/agent_runs/*.json, AGENT_RUN_LOG=true일 때 저장됨).

  python -m evaluate.show_agent_run              # 가장 최근 기록
  python -m evaluate.show_agent_run 3            # 최근 3개
  python -m evaluate.show_agent_run logs/agent_runs/20261002_223501_ab12cd.json --full
  python -m evaluate.show_agent_run --routes 20  # 최근 라우터 판단 20건 (logs/routes.jsonl)

보는 순서: ⓪ 라우터 → ① 분석(유형·칸·첫 검색어) → ② 검색 계획 → ③ 검색 결과(문서·쪽·점수)
          → ④ 판정(다음 행동·칸 상태) → 최종 칸 근거 → ⑤ 답변·출처.
--full이면 근거 풀의 청크 본문과 각 단계 LLM 원문도 출력한다.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Dict, List

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG_DIR = os.path.join(BACKEND_DIR, "logs")


def _short(text: str, n: int = 90) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[:n] + "…"


def _chunk_label(pool: Dict, cid: str) -> str:
    c = pool.get(cid) or {}
    score = c.get("score")
    sc = f"{score:.2f}" if isinstance(score, (int, float)) else "확장"
    return f"{os.path.basename(c.get('source', cid))} p.{c.get('page', '?')} c{c.get('chunk_index', '?')} ({sc})"


def show_record(rec: Dict, full: bool = False) -> None:
    run = rec.get("run") or {}
    pool = (run.get("pool") or {}).get("chunks", {})
    print("=" * 78)
    print(f"[{rec.get('saved_at')}] {rec.get('question')}")
    print(f"  언어 {rec.get('language')} | 한국어 질의 '{rec.get('ko_query')}' | 경로 모드 {rec.get('routing_mode')}")
    if rec.get("history"):
        print(f"  이전 대화 {len(rec['history'])}개")

    router = rec.get("router")
    if router:
        r = router.get("result") or {}
        print(f"\n⓪ 라우터: {r.get('route')} ({', '.join(r.get('route_reasons') or [])})"
              + ("  [fallback]" if router.get("fallback_used") else ""))
        for a in r.get("asks") or []:
            dep = f" ← {a.get('depends_on')}" if a.get("depends_on") else ""
            print(f"   [{a.get('ask_id')}] {a.get('kind')} {a.get('text')} | 검색어 '{a.get('query_ko')}'{dep}")
        for c in r.get("user_conditions") or []:
            print(f"   조건 {c.get('field_id')}={c.get('value')} ('{c.get('quote')}')")

    ar = run.get("analysis_run") or {}
    an = ar.get("analysis") or {}
    print(f"\n① 분석 ({ar.get('latency_ms', 0) / 1000:.1f}초): 유형 {an.get('primary_type')} + {an.get('additional_types')}"
          f" | 다음 행동 {an.get('next_action')}")
    if an.get("intent_summary"):
        print(f"   의도: {_short(an['intent_summary'], 150)}")
    for c in an.get("conditions") or []:
        print(f"   조건 {c.get('field_id')}={c.get('value')} ({c.get('subject')}) '{c.get('quote')}'")
    slots = [s for s in an.get("document_slots") or [] if s.get("active")]
    print("   문서 칸: " + ", ".join(f"{s['slot_id']}({s.get('requirement')})" for s in slots))
    us = [u for u in an.get("user_slots") or [] if u.get("active")]
    if us:
        print("   사용자 칸: " + ", ".join(f"{u['field_id']}={u.get('status')}" for u in us))
    fs = an.get("first_search") or {}
    if fs:
        print(f"   첫 검색어: '{fs.get('query_ko')}' → {fs.get('target_slot_ids')}")
    for w in ar.get("warnings") or []:
        print(f"   경고: {w}")
    if ar.get("error"):
        print(f"   오류: {ar['error']}")

    print("\n② 검색 계획")
    for i, p in enumerate(run.get("plan_runs") or [], 1):
        pl = p.get("plan") or {}
        print(f"   {i}. {pl.get('action')} {pl.get('target_slot_id') or ''} {pl.get('search_type') or ''} "
              f"'{pl.get('query_ko') or ''}'" + (" (①의 첫 검색어)" if pl.get("from_first_search") else "")
              + (f" — {_short(pl.get('reason'), 80)}" if pl.get("reason") else ""))
        if p.get("error"):
            print(f"      오류: {p['error']}")

    print("\n③ 검색 결과")
    for i, s in enumerate(run.get("search_runs") or [], 1):
        pl = s.get("plan") or {}
        new = set(s.get("new_chunk_ids") or [])
        head = f"   {i}. {pl.get('search_type')} '{pl.get('query_ko') or ''}'"
        if not s.get("ok", True):
            print(head + f"  실패 [{s.get('error_type')}] {s.get('error')}")
            continue
        print(head + f"  ({len(s.get('chunk_ids') or [])}개, 새 {len(new)})")
        for cid in s.get("chunk_ids") or []:
            print(f"      {'+' if cid in new else ' '} {_chunk_label(pool, cid)}")

    print("\n④ 판정")
    for i, v in enumerate(run.get("verify_runs") or [], 1):
        d = v.get("decision") or {}
        va = v.get("analysis") or {}
        st = " ".join(f"{s['slot_id']}={s.get('status')}" for s in va.get("document_slots") or [] if s.get("active"))
        print(f"   {i}. {d.get('next_action')} ({v.get('latency_ms', 0) / 1000:.1f}초, 청크 {len(v.get('shown_chunk_ids') or [])}개 봄)"
              f" — {_short(d.get('reason'), 100)}")
        print(f"      {st}")
        for w in v.get("warnings") or []:
            print(f"      경고: {_short(w, 120)}")
        if v.get("error"):
            print(f"      오류: {v['error']}")
    if run.get("verification_skips"):
        print(f"   (④ 생략 {run['verification_skips']}회)")

    final = run.get("analysis") or {}
    print(f"\n최종 칸 (종료: {run.get('stopped')}, 라운드 {run.get('rounds')})")
    for s in final.get("document_slots") or []:
        if not s.get("active"):
            continue
        print(f"   {s['slot_id']} [{s.get('status')}] {_short(s.get('value'), 100)}")
        for r in s.get("evidence_refs") or []:
            print(f"      ← {_chunk_label(pool, r.get('evidence_id'))}: '{_short(r.get('quote'), 80)}'")
        if s.get("missing_detail"):
            print(f"      남은 것: {_short(s['missing_detail'], 100)}")
    for u in final.get("user_slots") or []:
        if u.get("active"):
            br = "; ".join(b.get("value", "") for b in u.get("branches") or [])
            print(f"   사용자 {u['field_id']} [{u.get('status')}]" + (f" 갈래: {br}" if br else ""))

    a = run.get("answer_run") or {}
    fin = rec.get("final") or {}
    print(f"\n⑤ 답변 ({a.get('mode')}, {a.get('latency_ms', 0) / 1000:.1f}초)")
    print("   " + (fin.get("answer_sent") or a.get("answer") or "").replace("\n", "\n   "))
    for s in a.get("sources") or []:
        print(f"   [{s.get('number')}] {os.path.basename(s.get('source', ''))} p.{s.get('page')}")
    for w in (run.get("warnings") or []) + (a.get("warnings") or []):
        print(f"   경고: {_short(w, 120)}")
    print(f"\n총 {run.get('latency_ms', 0) / 1000:.1f}초")

    if full:
        print("\n── 근거 풀 ──")
        for cid, c in pool.items():
            print(f"\n[{_chunk_label(pool, cid)}]\n{c.get('text', '')}")
        print("\n── LLM 원문 ──")
        print("① " + (ar.get("raw_output") or ""))
        for i, v in enumerate(run.get("verify_runs") or [], 1):
            print(f"④-{i} " + (v.get("raw_output") or ""))


def show_routes(log_dir: str, n: int) -> None:
    path = os.path.join(log_dir, "routes.jsonl")
    if not os.path.exists(path):
        print(f"기록 없음: {path}")
        return
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()[-n:]
    for line in lines:
        e = json.loads(line)
        print(f"{e.get('at')} {e.get('route'):6s} {_short(e.get('question'), 60)} | {', '.join(e.get('reasons') or [])}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="에이전트 실행 기록 보기")
    ap.add_argument("target", nargs="?", default="1", help="기록 파일 경로 또는 최근 개수 (기본 1)")
    ap.add_argument("--log-dir", default=DEFAULT_LOG_DIR)
    ap.add_argument("--full", action="store_true", help="청크 본문·LLM 원문까지 출력")
    ap.add_argument("--routes", type=int, metavar="N", help="최근 라우터 판단 N건")
    a = ap.parse_args()

    if a.routes:
        show_routes(a.log_dir, a.routes)
        return 0
    if a.target.isdigit():
        files: List[str] = sorted(glob.glob(os.path.join(a.log_dir, "agent_runs", "*.json")))[-int(a.target):]
        if not files:
            print(f"기록 없음: {os.path.join(a.log_dir, 'agent_runs')} (AGENT_RUN_LOG가 켜져 있고 에이전트 경로로 간 질문이 있어야 함)")
            return 1
    else:
        files = [a.target]
    for path in files:
        with open(path, encoding="utf-8") as f:
            show_record(json.load(f), full=a.full)
        print(f"\n(파일: {path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
