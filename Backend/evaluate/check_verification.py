"""
④ 충분성 검증 확인 스크립트.

기본 동작(--live 없이)은 API 호출이 전혀 없다. verify_scenarios.py의 시나리오를 가짜 LLM(FakeClient)과
함께 verify_evidence()에 넣어 서버 규칙(인용 대조·상태 강등·사용자 칸·다음 행동)이 기대대로 동작하는지 확인한다.

--live는 check_search_execution --live가 저장한 결과 JSON(분석 + 근거 풀 + 검색 기록)을 불러와
④만 실제 OpenAI로 돌린다. 검색을 다시 하지 않으므로 LLM 1~2회 비용만 든다.

사용법 (Backend 폴더에서)
  python -m evaluate.check_verification                         # 전체 시나리오 (API 없음)
  python -m evaluate.check_verification --only V01,C01          # 일부만
  python -m evaluate.check_verification --live                  # 가장 최근 search_execution_live_*.json 사용
  python -m evaluate.check_verification --live evaluate/results/search_execution_live_20260929_162516.json
  python -m evaluate.check_verification --live --show-prompt    # 판정 프롬프트도 출력
  python -m evaluate.check_verification --live --model gpt-4o-mini,gpt-4o --repeat 3   # 모델 비교 (LLM 6회)
  python -m evaluate.check_verification --dev --model gpt-4o      # 개발용 질문 9개 전부 (collect_dev_pools 먼저)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from app.core.single_agent.analysis_schema import QuestionAnalysis
from app.core.single_agent.evidence_schema import EvidenceChunk, EvidencePool, RetrievalTag, parse_evidence_id
from app.core.single_agent.search_schema import SearchAttempt, SearchBudget
from app.core.single_agent.verifier import build_user_prompt, judge_targets, select_chunks, verify_evidence
from evaluate.verify_scenarios import SCENARIOS

RESULTS_DIR = Path(__file__).resolve().parent / "results"

T5_SLOTS = [
    {"slot_id": "rule", "active": True, "requirement": "required"},
    {"slot_id": "applicable_scope", "active": True, "requirement": "required"},
    {"slot_id": "conditions_limits", "active": True, "requirement": "conditional", "activation_state": "unresolved"},
    {"slot_id": "exceptions_related", "active": True, "requirement": "required"},
    {"slot_id": "approval_reporting", "active": True, "requirement": "conditional", "activation_state": "unresolved"},
]


class FakeClient:
    """OpenAI 클라이언트 흉내. 정해 둔 응답(dict는 JSON으로, 문자열은 그대로)을 차례로 돌려준다."""

    def __init__(self, responses: Any):
        self._responses = responses if isinstance(responses, list) else [responses]
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        r = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        content = json.dumps(r, ensure_ascii=False) if isinstance(r, dict) else r
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
        )


def build_inputs(s: Dict):
    analysis = QuestionAnalysis(
        intent_summary="GKS 장학생의 아르바이트 가능 여부",
        answer_scope=s.get("answer_scope", "general"),
        primary_type="T5",
        conditions=s.get("conditions", []),
        document_slots=s.get("slots", T5_SLOTS),
        user_slots=s.get("user_slots", []),
        next_action="search",
    )
    pool = EvidencePool()
    for item in s.get("pool", []):
        source, page, idx = parse_evidence_id(item["id"])
        chunk = EvidenceChunk(evidence_id=item["id"], source=source, page=page, chunk_index=idx,
                              text=item["text"], score=item.get("score"))
        for slot in item.get("slots", ["rule"]):
            pool.add(chunk, RetrievalTag(target_slot_id=slot, search_type="new", query_ko="(시나리오)", round_no=1))
    history = [SearchAttempt(**h) for h in s.get("history", [])]
    budget = SearchBudget(**s.get("budget", {}))
    return analysis, pool, history, budget


def run_scenario(s: Dict) -> Dict:
    analysis, pool, history, budget = build_inputs(s)
    before = analysis.model_dump()
    fake = FakeClient(s["llm"])
    run = verify_evidence(analysis, pool, budget, history, round_chunk_ids=s.get("round_chunk_ids"),
                          model="fake", client=fake)
    a, d = run.analysis, run.decision
    slots = {sl.slot_id: sl for sl in a.document_slots}
    users = {u.field_id: u for u in a.user_slots}
    warnings_text = "\n".join(run.warnings)

    got = {
        "next_action": d.next_action if d else None,
        "llm_called": run.llm_called,
        "llm_calls": fake.calls,
        "shown_chunk_ids": run.shown_chunk_ids,
        "judged_slot_ids": run.judged_slot_ids,
        "clarify_field_ids": d.clarify_field_ids if d else None,
        "condition_field_ids": d.condition_field_ids if d else None,
        "expand_anchors": d.expand_anchors if d else None,
    }
    checks = []

    def check(ok: bool, msg: str):
        checks.append({"ok": ok, "message": msg})

    for key, want in s["expect"].items():
        if key == "slot_statuses":
            actual = {k: slots[k].status if k in slots else None for k in want}
            check(actual == want, f"slot_statuses {want!r} (실제 {actual!r})")
        elif key == "slot_ref_ids":
            actual = {k: [r.evidence_id for r in slots[k].evidence_refs] if k in slots else None for k in want}
            check(actual == want, f"slot_ref_ids {want!r} (실제 {actual!r})")
        elif key == "activation":
            actual = {k: slots[k].activation_state if k in slots else None for k in want}
            check(actual == want, f"activation {want!r} (실제 {actual!r})")
        elif key == "user_active":
            actual = {k: users[k].required_by_evidence if k in users and users[k].active else None for k in want}
            check(actual == want, f"user_active {want!r} (실제 {actual!r})")
        elif key == "user_inactive":
            bad = [k for k in want if k in users and users[k].active]
            check(not bad, f"활성화되면 안 되는 사용자 칸 {want!r} (활성화됨 {bad!r})")
        elif key == "warnings_contain":
            phrases = [want] if isinstance(want, str) else list(want)
            missing = [p for p in phrases if p not in warnings_text]
            check(not missing, f"경고에 {phrases!r} 포함 (없는 것 {missing!r}, 실제 {run.warnings!r})")
        elif key == "error_contains":
            check(bool(run.error) and want in run.error, f"오류에 {want!r} 포함 (실제 {run.error!r})")
        elif key == "shown_first":
            actual = run.shown_chunk_ids[: len(want)]
            check(actual == want, f"shown_first {want!r} (실제 {actual!r})")
        elif key == "shown_count":
            check(len(run.shown_chunk_ids) == want, f"shown_count {want} (실제 {len(run.shown_chunk_ids)})")
        elif key == "input_unchanged":
            check(analysis.model_dump() == before, "입력 analysis가 바뀌지 않음")
        else:
            check(got.get(key) == want, f"{key} {want!r} (실제 {got.get(key)!r})")
    if run.error and "error_contains" not in s["expect"]:
        check(False, f"오류 없음 (실제 {run.error})")

    return {"id": s["id"], "title": s["title"], "passed": all(c["ok"] for c in checks),
            "checks": checks, "warnings": run.warnings, "error": run.error}


def print_result(r: Dict) -> None:
    print(f"[{'PASS' if r['passed'] else 'FAIL'}] {r['id']}  {r['title']}")
    if not r["passed"]:
        for c in r["checks"]:
            if not c["ok"]:
                print(f"       ✗ {c['message']}")


# ── 저장된 live 결과로 ④만 실제 LLM 실행 (--live) ─────────────────────────────

def _latest_live_file() -> Optional[Path]:
    files = sorted(RESULTS_DIR.glob("search_execution_live_*.json"))
    return files[-1] if files else None


def load_live(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    analysis = QuestionAnalysis.model_validate(data["analysis"])
    pool = EvidencePool.model_validate(data["pool"])
    runs = [r for r in data.get("runs", []) if r.get("ok")]
    history = [SearchAttempt.model_validate(r["attempt"]) for r in runs if r.get("attempt")]
    budget = SearchBudget.model_validate(runs[-1]["budget"]) if runs else SearchBudget()
    return data.get("question"), analysis, pool, history, budget


def _print_run(run) -> None:
    if run.error:
        print(f"④ 실패: {run.error}")
    print(f"④ 충분성 검증 [{run.model}]: LLM {run.attempts}회, {run.latency_ms}ms, "
          f"토큰 입력 {run.prompt_tokens} / 출력 {run.completion_tokens}")
    print(f"   보여준 청크 {len(run.shown_chunk_ids)}개, 판정 대상 칸 {run.judged_slot_ids}\n")
    for s in run.analysis.document_slots:
        act = f" [{s.activation_state}]" if s.requirement == "conditional" else ""
        print(f"  {s.slot_id:<20} {s.requirement:<11}{act:<16} → {s.status}")
        if s.value:
            print(f"      내용: {s.value}")
        for r in s.evidence_refs:
            print(f"      근거: {r.evidence_id}\n            \"{r.quote[:120]}\"")
        if s.missing_detail:
            print(f"      부족: {s.missing_detail}")
    for u in run.analysis.user_slots:
        if u.active:
            print(f"  사용자 칸 {u.field_id} ({u.status}) 근거 {u.required_by_evidence}\n      {u.reason}")
    if run.decision:
        d = run.decision
        print(f"\n다음 행동: {d.next_action}  ({d.reason})")
        for f, bs in d.condition_branches.items():
            print(f"   {f}: " + " / ".join(bs))
        if d.expand_anchors:
            print(f"   원문 확장 앵커: {d.expand_anchors}")
    for w in run.warnings:
        print(f"   경고: {w}")


def run_live(path: Optional[str], show_prompt: bool = False, models: Optional[List[str]] = None,
             repeat: int = 1, client=None, save: bool = True, verbose: bool = True,
             label: Optional[str] = None, keep_run: bool = False) -> List[Dict]:
    """
    저장된 live JSON으로 ④를 실제 LLM으로 돌린다. models × repeat번 실행하고 마지막에 비교표를 출력한다.
    client는 테스트용(가짜 LLM)이다. 반환: 실행별 요약 목록.
    요약에는 항상 서버 경고(warnings)와 시도별 LLM 원문(raw_outputs)을 담는다.
    keep_run=True면 ④ 실행 기록 전체(run: 칸별 인용·value·missing_detail 포함)도 담는다 (--dev 저장용).
    """
    p = Path(path) if path else _latest_live_file()
    if p is None or not p.exists():
        print("search_execution_live_*.json이 없어. 먼저 python -m evaluate.check_search_execution --live \"질문\"을 실행해줘.")
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    if raw.get("analysis") is None or not (raw.get("analysis") or {}).get("document_slots"):
        print(f"[건너뜀] {p.name}: ①이 검색하지 않은 질문 ({raw.get('stopped')})")
        return [{"label": label or p.stem, "model": None, "try": 0, "skipped": raw.get("stopped")}]
    question, analysis, pool, history, budget = load_live(p)
    print(f"입력: {p.name}\n질문: {question}\n풀 {len(pool)}개 청크, 검색 기록 {len(history)}건, 예산 {budget.model_dump()}\n")
    if show_prompt:
        print(build_user_prompt(analysis, judge_targets(analysis), select_chunks(analysis, pool, None), pool, question), "\n")

    summaries: List[Dict] = []
    runs = []
    for model in (models or [None]):
        for i in range(1, repeat + 1):
            run = verify_evidence(analysis, pool, budget, history, round_chunk_ids=None,
                                  question=question, model=model, client=client)
            if verbose:
                print(f"\n===== {run.model or model} #{i} =====")
                _print_run(run)
            runs.append(run)
            slots = {s.slot_id: s for s in run.analysis.document_slots}
            summaries.append({
                "label": label or p.stem, "model": run.model or model, "try": i,
                "statuses": {k: s.status for k, s in slots.items()},
                "ref_counts": {k: len(s.evidence_refs) for k, s in slots.items()},
                "refs": {k: [r.evidence_id for r in s.evidence_refs] for k, s in slots.items()},
                "user_active": [u.field_id for u in run.analysis.user_slots if u.active],
                "distinct_chunks": len({r.evidence_id for s in slots.values() for r in s.evidence_refs}),
                "next_action": run.decision.next_action if run.decision else None,
                "removed_refs": sum(1 for w in run.warnings if w.startswith("[제거]") and "근거" in w),
                "tokens": run.prompt_tokens + run.completion_tokens, "latency_ms": run.latency_ms,
                "error": run.error,
                "warnings": list(run.warnings),
                "raw_outputs": list(run.raw_outputs),
            })
            if keep_run:
                summaries[-1]["run"] = run.model_dump()

    if len(summaries) > 1:
        slot_ids = list(summaries[0]["statuses"].keys())
        short = {"supported": "S", "partial": "P", "missing": "M", "unchecked": "U", "conflicting": "C", "not_applicable": "NA"}
        print("\n===== 비교 (S=supported P=partial M=missing U=unchecked, 괄호=근거 수) =====")
        print("모델 #  | " + " | ".join(f"{s[:14]:<14}" for s in slot_ids) + " | 청크수 | 제거 | 다음 행동")
        for r in summaries:
            cells = [f"{short.get(r['statuses'][s], r['statuses'][s])}({r['ref_counts'][s]})" for s in slot_ids]
            print(f"{str(r['model'])[:12]:<12} {r['try']} | " + " | ".join(f"{c:<14}" for c in cells)
                  + f" | {r['distinct_chunks']:^6} | {r['removed_refs']:^4} | {r['next_action']}")

    if save:
        RESULTS_DIR.mkdir(exist_ok=True)
        out = RESULTS_DIR / f"verification_live_{datetime.now():%Y%m%d_%H%M%S}.json"
        out.write_text(json.dumps({"input_file": p.name, "question": question, "summaries": summaries,
                                   "runs": [r.model_dump() for r in runs]}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"\n결과 저장: {out}")
    return summaries


DEV_POOL_DIR = RESULTS_DIR / "dev_pools"


def run_dev(models: Optional[List[str]], repeat: int, only: Optional[set] = None, client=None,
            save: bool = True) -> List[Dict]:
    """개발용 질문 풀(results/dev_pools/D*.json) 전부에 ④를 돌리고 질문×모델 비교표를 출력한다."""
    files = sorted(DEV_POOL_DIR.glob("D*.json"), key=lambda f: int(f.stem[1:]) if f.stem[1:].isdigit() else 999)
    if only:
        files = [f for f in files if f.stem in only]
    if not files:
        print("dev_pools가 비어 있어. 먼저 python -m evaluate.collect_dev_pools 를 실행해줘.")
        return []
    rows: List[Dict] = []
    for f in files:
        print(f"\n########## {f.stem} ##########")
        rows += run_live(str(f), models=models, repeat=repeat, client=client, save=False, verbose=False,
                         label=f.stem, keep_run=True)

    from evaluate.dev_questions import DEV_QUESTIONS
    from evaluate.dev_scoring import score_row, total_score
    gold = {q["id"]: q.get("gold", {}).get("round1") for q in DEV_QUESTIONS}
    for r in rows:
        if not r.get("skipped") and gold.get(r["label"]):
            r["score"] = score_row(r, gold[r["label"]])

    short = {"supported": "S", "partial": "P", "missing": "M", "unchecked": "U", "conflicting": "C", "not_applicable": "NA"}
    print("\n===== 개발용 질문 × 모델 (칸 상태: S/P/M/U/C/NA, 괄호=근거 수) =====")
    for r in rows:
        if r.get("skipped"):
            print(f"{r['label']:<4} (건너뜀: {r['skipped']})")
            continue
        cells = " ".join(f"{k}={short.get(v, v)}({r['ref_counts'][k]})" for k, v in r["statuses"].items())
        print(f"{r['label']:<4} {str(r['model'])[:11]:<11} #{r['try']} | 청크 {r['distinct_chunks']:>2} | 제거 {r['removed_refs']} "
              f"| {str(r['next_action']):<19} | {r['tokens']:>5}tok {r['latency_ms']:>6}ms | {cells}")
        if r.get("error"):
            print(f"      ④ 실패: {r['error']}")
        for w in r.get("warnings", []):
            if w.startswith("[제거]") and "근거" in w:
                print(f"      {w}")
        sc = r.get("score")
        if sc:
            print("      채점 " + " ".join(f"{k} {sc[k]['pass']}/{sc[k]['total']}" for k in ("slots", "cite", "not_cite", "users", "action")))
            for m in sc["misses"]:
                print(f"        - {m}")

    by_model: Dict[str, List[Dict]] = {}
    for r in rows:
        if r.get("score"):
            by_model.setdefault(str(r["model"]), []).append(r["score"])
    if by_model:
        print("\n===== 모델별 합계 (정답은 초안: 참고용) =====")
        for m, scs in by_model.items():
            tot = total_score(scs)
            print(f"{m:<14} " + " | ".join(f"{k} {v['pass']}/{v['total']}" for k, v in tot.items()))
    if save:
        RESULTS_DIR.mkdir(exist_ok=True)
        out = RESULTS_DIR / f"verification_dev_{datetime.now():%Y%m%d_%H%M%S}.json"
        out.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n결과 저장: {out}")
    return rows


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="④ 충분성 검증 확인")
    ap.add_argument("--only", help="쉼표로 구분한 시나리오 ID (예: V01,C01)")
    ap.add_argument("--live", nargs="?", const="", metavar="JSON",
                    help="저장된 search_execution_live JSON으로 ④만 실제 LLM 실행 (경로 생략 시 최신 파일)")
    ap.add_argument("--show-prompt", action="store_true", help="--live에서 판정 프롬프트 출력")
    ap.add_argument("--model", help="--live에서 쓸 모델. 쉼표로 여러 개 비교 (예: gpt-4o-mini,gpt-4o)")
    ap.add_argument("--repeat", type=int, default=1, help="--live에서 모델마다 반복 횟수 (판정 흔들림 확인)")
    ap.add_argument("--dev", action="store_true",
                    help="개발용 질문 풀(results/dev_pools) 전부에 ④ 실행 (--model, --repeat, --only 함께 사용 가능)")
    args = ap.parse_args()

    if args.dev:
        models = [m.strip() for m in args.model.split(",")] if args.model else None
        only = {x.strip() for x in args.only.split(",")} if args.only else None
        return 0 if run_dev(models, max(1, args.repeat), only) else 1
    if args.live is not None:
        models = [m.strip() for m in args.model.split(",")] if args.model else None
        return 0 if run_live(args.live or None, args.show_prompt, models, max(1, args.repeat)) else 1

    wanted = {x.strip() for x in args.only.split(",")} if args.only else None
    results = [run_scenario(s) for s in SCENARIOS if wanted is None or s["id"] in wanted]
    for r in results:
        print_result(r)
    passed = sum(1 for r in results if r["passed"])
    print(f"\n{passed}/{len(results)} 시나리오 통과")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
