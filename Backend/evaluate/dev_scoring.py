"""
개발용 질문의 ④ 결과를 정답 초안(dev_questions.py의 gold.round1)과 비교해 채점한다.

항목 (각각 통과 수 / 전체 수)
  slots     : 칸 상태가 허용 상태 안에 있는가
  cite      : must_cite 묶음마다 하나 이상 그 칸에 인용했는가 (빠뜨림)
  not_cite  : must_not_cite 청크를 그 칸('*'는 모든 칸)에 인용하지 않았는가 (엉뚱한 근거)
  users     : 문서상 갈래로 활성화돼야 할 사용자 칸이 활성화됐는가
  action    : 다음 행동이 허용 목록 안에 있는가
정답이 초안(draft)인 동안의 점수는 참고용이다. 팀이 원문으로 확인한 뒤에 기준으로 쓴다.
"""
from __future__ import annotations

from typing import Dict, List


def score_row(row: Dict, gold_round1: Dict) -> Dict:
    statuses = row.get("statuses", {})
    refs: Dict[str, List[str]] = row.get("refs", {})
    active_users = set(row.get("user_active", []))
    misses: List[str] = []

    def tally(name: str, results: List[bool]) -> Dict:
        return {"pass": sum(results), "total": len(results)}

    slot_res = []
    for slot, allowed in gold_round1.get("slots", {}).items():
        ok = statuses.get(slot) in allowed
        slot_res.append(ok)
        if not ok:
            misses.append(f"[상태] {slot}={statuses.get(slot)} (기대 {'/'.join(allowed)})")

    cite_res = []
    for slot, groups in gold_round1.get("must_cite", {}).items():
        cited = set(refs.get(slot, []))
        for g in groups:
            ok = bool(cited & set(g))
            cite_res.append(ok)
            if not ok:
                misses.append(f"[빠뜨림] {slot}: {g[0].split('#', 1)[-1]} 등 미인용")

    not_res = []
    for slot, bad_ids in gold_round1.get("must_not_cite", {}).items():
        slots = list(refs) if slot == "*" else [slot]
        for s in slots:
            wrong = set(refs.get(s, [])) & set(bad_ids)
            not_res.append(not wrong)
            if wrong:
                misses.append(f"[엉뚱한 근거] {s}: " + ", ".join(sorted(i.split('#', 1)[-1] for i in wrong)))

    user_res = []
    for f in gold_round1.get("user_fields", []):
        ok = f in active_users
        user_res.append(ok)
        if not ok:
            misses.append(f"[갈래 누락] 사용자 칸 {f} 비활성")

    action_ok = row.get("next_action") in gold_round1.get("next_action", [])
    if not action_ok:
        misses.append(f"[다음 행동] {row.get('next_action')} (기대 {'/'.join(gold_round1.get('next_action', []))})")

    return {
        "slots": tally("slots", slot_res), "cite": tally("cite", cite_res), "not_cite": tally("not_cite", not_res),
        "users": tally("users", user_res), "action": {"pass": int(action_ok), "total": 1}, "misses": misses,
    }


def total_score(scores: List[Dict]) -> Dict[str, Dict[str, int]]:
    keys = ["slots", "cite", "not_cite", "users", "action"]
    return {k: {"pass": sum(s[k]["pass"] for s in scores), "total": sum(s[k]["total"] for s in scores)} for k in keys}
