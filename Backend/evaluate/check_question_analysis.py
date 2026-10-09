"""
① 질문 분석 결과를 눈으로 확인하는 스크립트.

실제 OpenAI API를 호출한다 (Backend/.env의 OPENAI_API_KEY 사용). 질문 1개당 LLM 1~2회.
CI(pytest tests/)에는 포함되지 않는다.

사용법 (Backend 폴더에서)
  # 질문 하나
  python -m evaluate.check_question_analysis "GKS 장학생은 아르바이트할 수 있어?"

  # 이전 대화가 있는 질문 (JSON 파일: [{"role": "user", "content": "..."}, {"role": "assistant", ...}])
  python -m evaluate.check_question_analysis "학위과정이에요" --history my_history.json

  # 계속 입력하면서 보기 (빈 줄 또는 q 입력 시 종료)
  python -m evaluate.check_question_analysis -i

  # 준비된 시나리오 전체 / 일부 실행 + 기대값 점검 (결과는 evaluate/results에 저장)
  python -m evaluate.check_question_analysis --scenarios
  python -m evaluate.check_question_analysis --scenarios --only S02 S07

옵션
  --model gpt-4o      다른 모델로 비교
  --json              전체 결과를 JSON으로도 출력
  --show-prompt       LLM에 들어간 시스템 프롬프트 출력
  --save              결과를 evaluate/results/question_analysis_*.json으로 저장 (시나리오 모드는 항상 저장)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# `python evaluate/check_question_analysis.py`로 실행해도 app 패키지를 찾도록 Backend를 경로에 추가
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

try:  # Windows 콘솔에서 한글 깨짐 방지
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.single_agent import checklist_config as cfg  # noqa: E402
from app.core.single_agent.analysis_schema import AnalysisRun  # noqa: E402
from app.core.single_agent.analyzer import analyze_question, build_system_prompt  # noqa: E402

RESULTS_DIR = os.path.join(_BACKEND_DIR, "evaluate", "results")
LINE = "─" * 72


# ── 보기 좋게 출력 ────────────────────────────────────────────────────────

def _label(d: Dict[str, str], key: Optional[str]) -> str:
    return f"{key} ({d[key]})" if key in d else str(key)


def print_run(run: AnalysisRun) -> None:
    print(LINE)
    print(f"질문: {run.question}")
    if run.history:
        print(f"이전 대화: {len(run.history)}개 메시지")
        for i, h in enumerate(run.history, 1):
            print(f"  [m{i}] {h.get('role')}: {h.get('content')}")
    print(f"모델: {run.model} | {run.latency_ms / 1000:.1f}초 | 시도 {run.attempts}회 | "
          f"토큰 입력 {run.prompt_tokens:,} / 출력 {run.completion_tokens:,}")

    if run.error and not run.analysis:
        print(f"\n[실패] {run.error}")
        if run.raw_output:
            print(f"LLM 원본 출력:\n{run.raw_output}")
        return

    a = run.analysis
    print(f"\n[의도] {a.intent_summary}")
    print(f"[답변 범위] {_label(cfg.ANSWER_SCOPES, a.answer_scope)}")

    if a.primary_type:
        extra = ", ".join(f"{t} {cfg.PROFILES[t]['name']}" for t in a.additional_types) or "없음"
        print(f"[유형] 대표 {a.primary_type} {cfg.PROFILES[a.primary_type]['name']} | 추가: {extra}")
        if a.type_reason:
            print(f"       이유: {a.type_reason}")

    print("\n[확인된 조건]")
    if not a.conditions:
        print("  없음")
    for c in a.conditions:
        f = cfg.USER_FIELDS[c.field_id]["label"]
        print(f"  - {f}({c.field_id}) = {c.value} | 대상: {cfg.CONDITION_SUBJECTS[c.subject]} | "
              f"{cfg.CONDITION_STATUSES.get(c.status, c.status)} | 근거 {c.source_message_id} \"{c.quote}\"")

    if a.document_slots:
        print("\n[문서 칸]  (O 활성 / - 비활성, 모두 unchecked)")
        for s in a.document_slots:
            mark = "O" if s.active else "-"
            req = cfg.REQUIREMENTS[s.requirement]
            if s.activation_state:
                req += f"·{s.activation_state}"
            label = cfg.DOC_SLOTS[s.slot_id]["label"]
            print(f"  {mark} {label}({s.slot_id}) [{req}]")
            if s.activation_reason:
                print(f"      └ {s.activation_reason}")

    if a.user_slots:
        print("\n[사용자 칸]")
        for u in a.user_slots:
            mark = "O" if u.active else "-"
            label = cfg.USER_FIELDS[u.field_id]["label"]
            status = cfg.USER_SLOT_STATUSES.get(u.status, u.status)
            print(f"  {mark} {label}({u.field_id}) [{status}] {u.reason}")

    if a.first_search:
        fs = a.first_search
        print("\n[첫 검색]")
        print(f"  검색어: {fs.query_ko}")
        print(f"  채울 칸: {', '.join(fs.target_slot_ids)}")
        if fs.reason:
            print(f"  이유: {fs.reason}")

    print(f"\n[다음 행동] {_label(cfg.ANALYSIS_ACTIONS, a.next_action)}")
    if a.next_action_reason:
        print(f"  이유: {a.next_action_reason}")
    if a.clarification_question:
        print(f"  되물을 질문: {a.clarification_question}")

    print("\n[서버 검증에서 고친 것]")
    if not run.warnings:
        print("  없음")
    for w in run.warnings:
        print(f"  {w}")
    if run.attempts > 1:
        print(f"  (첫 출력이 형식 오류라 재시도함)")


# ── 기대값 점검 ──────────────────────────────────────────────────────────

def check_expect(run: AnalysisRun, expect: Dict) -> List[Tuple[bool, str]]:
    if not run.analysis:
        return [(False, f"분석 실패: {run.error}")]
    a = run.analysis
    out: List[Tuple[bool, str]] = []

    def chk(ok: bool, msg: str):
        out.append((ok, msg))

    if "primary_type" in expect:
        chk(a.primary_type == expect["primary_type"], f"대표 유형 {expect['primary_type']} (실제 {a.primary_type})")
    if "primary_type_in" in expect:
        chk(a.primary_type in expect["primary_type_in"], f"대표 유형 ∈ {expect['primary_type_in']} (실제 {a.primary_type})")
    for t in expect.get("additional_includes", []):
        chk(t in a.additional_types, f"추가 유형에 {t} 포함 (실제 {a.additional_types})")
    for t in expect.get("additional_excludes", []):
        chk(t not in a.additional_types, f"추가 유형에 {t} 없음 (실제 {a.additional_types})")
    if "next_action" in expect:
        chk(a.next_action == expect["next_action"], f"다음 행동 {expect['next_action']} (실제 {a.next_action})")
    if "answer_scope" in expect:
        chk(a.answer_scope == expect["answer_scope"], f"답변 범위 {expect['answer_scope']} (실제 {a.answer_scope})")
    if "condition" in expect:
        e = expect["condition"]
        found = [
            c for c in a.conditions
            if c.field_id == e["field_id"]
            and ("subject" not in e or c.subject == e["subject"])
            and ("value_contains" not in e or e["value_contains"] in c.value)
        ]
        actual = [(c.field_id, c.value, c.subject) for c in a.conditions]
        chk(bool(found), f"조건 {e} 있음 (실제 {actual})")
    for f in expect.get("no_condition", []):
        chk(all(c.field_id != f for c in a.conditions), f"조건 {f} 없음 (추정 금지)")
    active = {s.slot_id for s in a.document_slots if s.active}
    for sid in expect.get("inactive_slots", []):
        chk(sid not in active, f"문서 칸 {sid} 비활성")
    for sid in expect.get("active_slots", []):
        chk(sid in active, f"문서 칸 {sid} 활성")
    return out


# ── 실행 모드 ─────────────────────────────────────────────────────────────

def _save(payload: Dict, tag: str) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"question_analysis_{tag}_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def run_single(question: str, history: List[Dict], args) -> AnalysisRun:
    run = analyze_question(question, history=history, model=args.model)
    print_run(run)
    if args.json:
        print("\n[전체 JSON]")
        print(run.model_dump_json(indent=2))
    return run


def run_scenarios(args) -> None:
    from evaluate.question_analysis_scenarios import SCENARIOS

    selected = [s for s in SCENARIOS if not args.only or s["id"] in args.only]
    if not selected:
        print(f"해당 시나리오 없음: {args.only}")
        return

    results, total_ok, total_n = [], 0, 0
    for sc in selected:
        print(f"\n\n### {sc['id']} {sc['title']}")
        run = run_single(sc["question"], sc.get("history", []), args)
        checks = check_expect(run, sc.get("expect", {}))
        print("\n[기대값 점검]")
        for ok, msg in checks:
            print(f"  {'[통과]' if ok else '[실패]'} {msg}")
        n_ok = sum(ok for ok, _ in checks)
        total_ok, total_n = total_ok + n_ok, total_n + len(checks)
        results.append({
            "id": sc["id"],
            "title": sc["title"],
            "passed": n_ok == len(checks),
            "checks": [{"ok": ok, "message": msg} for ok, msg in checks],
            "run": run.model_dump(),
        })

    print(f"\n\n{LINE}\n요약")
    for r in results:
        run = r["run"]
        a = run.get("analysis") or {}
        n_fail = sum(not c["ok"] for c in r["checks"])
        status = "통과" if r["passed"] else f"실패 {n_fail}개"
        print(f"  {r['id']} [{status}] 유형 {a.get('primary_type')}+{a.get('additional_types', [])} | "
              f"{a.get('next_action')} | 고친 것 {len(run['warnings'])}개 | {run['latency_ms'] / 1000:.1f}초")
    tokens_in = sum(r["run"]["prompt_tokens"] for r in results)
    tokens_out = sum(r["run"]["completion_tokens"] for r in results)
    avg_latency = sum(r["run"]["latency_ms"] for r in results) / len(results) / 1000
    print(f"  기대값 {total_ok}/{total_n} 통과 | 평균 {avg_latency:.1f}초 | 토큰 입력 {tokens_in:,} / 출력 {tokens_out:,}")

    path = _save({
        "created_at": datetime.now().isoformat(),
        "model": args.model,
        "checklist_version": cfg.CHECKLIST_VERSION,
        "passed_checks": total_ok,
        "total_checks": total_n,
        "scenarios": results,
    }, "scenarios")
    print(f"  결과 저장: {path}")


def run_interactive(args) -> None:
    print("질문을 입력하세요. (빈 줄 또는 q: 종료)")
    runs = []
    while True:
        try:
            q = input("\n질문> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q or q.lower() == "q":
            break
        runs.append(run_single(q, [], args).model_dump())
    if args.save and runs:
        print(f"결과 저장: {_save({'runs': runs}, 'interactive')}")


def main() -> None:
    p = argparse.ArgumentParser(description="① 질문 분석 결과 확인")
    p.add_argument("question", nargs="?", help="분석할 질문")
    p.add_argument("--history", help="이전 대화 JSON 파일 경로")
    p.add_argument("-i", "--interactive", action="store_true", help="계속 입력하며 확인")
    p.add_argument("--scenarios", action="store_true", help="준비된 시나리오 실행 + 기대값 점검")
    p.add_argument("--only", nargs="*", help="시나리오 ID 일부만 (예: S02 S07)")
    p.add_argument("--model", default=None, help="모델 (기본: .env의 OPENAI_MODEL 또는 gpt-4o-mini)")
    p.add_argument("--json", action="store_true", help="전체 결과 JSON 출력")
    p.add_argument("--show-prompt", action="store_true", help="시스템 프롬프트 출력")
    p.add_argument("--save", action="store_true", help="결과 JSON 저장")
    args = p.parse_args()

    if args.model is None:
        from app.config import settings
        args.model = settings.openai_model

    if args.show_prompt:
        print(f"{LINE}\n[시스템 프롬프트] 체크리스트 {cfg.CHECKLIST_VERSION}\n{LINE}")
        print(build_system_prompt())
        if not (args.question or args.scenarios or args.interactive):
            return

    if args.scenarios:
        run_scenarios(args)
    elif args.interactive:
        run_interactive(args)
    elif args.question:
        history = []
        if args.history:
            with open(args.history, encoding="utf-8") as f:
                history = json.load(f)
        run = run_single(args.question, history, args)
        if args.save:
            print(f"결과 저장: {_save(run.model_dump(), 'single')}")
    else:
        p.print_help()


if __name__ == "__main__":
    main()
