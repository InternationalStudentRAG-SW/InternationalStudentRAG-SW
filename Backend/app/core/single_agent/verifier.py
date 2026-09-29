"""
④ 충분성 검증.

입력: ①의 분석(칸·조건) + ③이 쌓은 근거 풀 + 예산·검색 기록 + 이번 라운드 새 청크
출력: 칸 상태·근거가 갱신된 분석 + 다음 행동 1개 (VerificationRun)

흐름 (설계 원칙: 판정은 LLM, 검증과 다음 행동은 서버)
  1. 판정 대상: 활성 칸 중 supported / not_applicable / unavailable_in_corpus가 아닌 칸을 모두 한 번에.
     한 번 검색한 청크가 여러 칸의 근거가 되는 경우가 많아서 칸별로 따로 부르지 않는다.
  2. 보여줄 청크: 이미 칸에 연결된 청크 → 이번 라운드에 검색된 청크(이미 풀에 있던 것 포함) →
     나머지 풀(들어온 순서) 순으로 최대 VERIFY_MAX_CHUNKS개. 한 번 놓친 청크도 다시 보이게 하기 위함.
  3. LLM을 JSON 모드로 1회 호출 (형식 오류면 1회 재시도).
  4. 서버 검증
     - 근거 ID가 이번에 보여준 청크가 아니거나, 인용이 그 청크 본문에 없으면 근거를 버린다.
     - 근거가 하나도 남지 않은 supported/partial/conflicting은 강등한다.
     - 검색한 적 없는 칸은 missing이 아니라 unchecked로 둔다(missing = '검색 후 미확보', 2.1절).
     - unavailable_in_corpus는 자료 범위표로만 정하므로 ④가 쓰지 못한다.
     - 필수 칸은 not_applicable로 바꿀 수 없다. 조건부 칸은 근거가 있을 때만.
     - 사용자 칸은 문서 근거가 있을 때만 활성화한다(①에서 막아 둔 되묻기가 여기서 열린다).
     - 문서상 갈래가 있는 사용자 조건이 미확인인데 적용 범위 칸이 그 갈래 근거를 다 인용하지 않으면
       적용 범위를 partial로 낮춘다(한 갈래만 보고 범위를 확정하는 판정을 막음).
  5. 다음 행동은 서버 규칙(체크리스트 2.4절)으로 정한다. LLM에게 고르게 하지 않는다.

입력 analysis는 바꾸지 않고, 갱신한 사본을 run.analysis로 돌려준다.
"""
from __future__ import annotations

import json
import re
import time
from typing import Dict, List, Optional, Set, Tuple

from pydantic import ValidationError

from app.core.single_agent import checklist_config as cfg
from app.core.single_agent.analysis_schema import DocSlot, EvidenceRef, QuestionAnalysis, UserSlot
from app.core.single_agent.evidence_schema import EvidencePool
from app.core.single_agent.search_planner import (
    check_budget,
    count_attempts,
    rank_candidates,
    slot_attempt_limit,
)
from app.core.single_agent.search_schema import SearchAttempt, SearchBudget
from app.core.single_agent.verify_schema import (
    SlotVerdict,
    UserFieldNeed,
    VerificationRun,
    VerifyDecision,
    VerifyOutput,
)

MAX_ATTEMPTS = 2


def _norm(text: str) -> str:
    """인용 대조용 정규화: 공백 제거, 마크다운 굵게(*) 제거, 소문자."""
    return re.sub(r"[\s*]+", "", text or "").lower()


# ── 대상 칸·청크 선택 (규칙) ────────────────────────────────────────────────

def is_needed(slot: DocSlot) -> bool:
    """답변에 반드시 확인해야 하는 칸: 활성 필수, 또는 발동 안 함이 아닌 활성 조건부."""
    if not slot.active:
        return False
    if slot.requirement == "required":
        return True
    return slot.requirement == "conditional" and slot.activation_state != "not_triggered"


def judge_targets(analysis: QuestionAnalysis) -> List[DocSlot]:
    done = cfg.RESOLVED_STATUSES | {"unavailable_in_corpus"}
    return [s for s in analysis.document_slots if s.active and s.status not in done]


def select_chunks(
    analysis: QuestionAnalysis, pool: EvidencePool, round_chunk_ids: Optional[List[str]],
) -> List[str]:
    """
    보여줄 청크 순서: 칸에 연결된 청크 → 이번 라운드에 검색된 청크 → 나머지 풀(들어온 순서), 상한까지.
    round_chunk_ids는 ③이 이번에 돌려준 청크 전부(run.chunk_ids)다. 새 청크만 넘기면, 예전에 LLM이
    놓친 청크가 다시 검색돼도 '새 것이 아니라서' 영영 안 보이는 문제가 생긴다.
    """
    linked = [r.evidence_id for s in analysis.document_slots for r in s.evidence_refs]
    this_round = list(round_chunk_ids or [])
    rest = list(pool.chunks.keys())
    ordered: List[str] = []
    for cid in linked + this_round + rest:
        if cid in pool and cid not in ordered:
            ordered.append(cid)
    return ordered[: cfg.VERIFY_MAX_CHUNKS]


def searched_slot_ids(history: List[SearchAttempt]) -> Set[str]:
    return {h.target_slot_id for h in history}


# ── 프롬프트 ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """당신은 동아대학교 유학생 챗봇의 '충분성 검증' 단계입니다.
검색된 문서 청크만 보고, 각 문서 칸이 근거로 채워졌는지 판정합니다. 답변을 쓰지 않습니다.
결과는 반드시 JSON 객체 하나로만 출력합니다.

## 칸 상태 (이 중에서만 고릅니다)
- supported: 적용 가능한 근거가 칸의 충족 기준을 만족함
- partial: 관련 근거는 있으나 목록·표·조건·관련 조항이 불완전함 (예: 다음 페이지로 이어짐, 단서 조항 일부만 보임)
- missing: 보여준 청크에 이 칸을 뒷받침하는 근거가 없음
- conflicting: 적용 가능한 근거끼리 내용이 달라 해소하지 못함 (근거 2개 이상 필요)
- not_applicable: 문서상 이 칸의 발동 조건이 성립하지 않음 (조건부 칸만, 그 근거가 있어야 함)

## 규칙
1. 오직 아래 청크의 내용만 근거로 씁니다. 일반 지식·상식·추측으로 칸을 채우지 않습니다.
2. evidence_refs의 quote는 해당 청크 본문에서 한 글자도 바꾸지 않고 그대로 옮긴 짧은 구절(한 문장 이내)입니다.
   요약·번역·말 바꾸기를 하지 않습니다. evidence_id는 아래 청크 ID를 그대로 씁니다.
3. 주제만 언급하는 청크는 근거가 아닙니다. 칸에 필요한 값·규정을 실제로 제공해야 합니다.
4. 질문 대상(예: GKS 장학생)과 청크의 적용 대상이 맞는지 봅니다. 대상이 다른 규정을 이 칸의 근거로 쓰지 않습니다.
5. 같은 문서의 한국어판·영어판처럼 번역 관계인 청크는 같은 내용이므로 conflicting이 아닙니다. 둘 다 근거로 쓸 수 있습니다.
6. "예외가 없다"는 결론은 예외를 못 찾았다는 사실만으로 내리지 않습니다. 예외·관련 조항 칸은 보여준 조항 범위를 value에 적습니다.
7. "추후 공지"는 정확한 날짜·절차를 확보했다는 뜻이 아닙니다.
8. 조건부 칸의 activation_state: 문서상 이 칸이 필요하면 triggered, 문서상 성립하지 않으면 not_triggered(이때 status는 not_applicable), 아직 모르면 unresolved.
9. value에는 근거로 확인한 내용을 한국어로 짧게 요약합니다. partial·missing·conflicting이면 missing_detail에 무엇이 부족한지 적습니다.
10. user_field_needs: 문서가 어떤 사용자 조건(교육 과정, GKS 단계 등)에 따라 답을 다르게 정하고 있으면 그 칸 ID와 근거 청크 ID, 갈래 요약을 적습니다.
    문서 근거 없이 '물어보면 좋겠다'는 이유로 적지 않습니다. 사용자의 언어·이름으로 국적 등을 추정하지 않습니다.
11. 판정 대상 칸은 빠짐없이 모두 slot_verdicts에 적습니다.
12. 칸마다 모든 청크를 처음부터 끝까지 다시 훑습니다. 한 청크에 근거를 몰지 말고, 칸마다 가장 알맞은 청크를 따로 고릅니다.
    한 칸에 근거가 여러 청크에 나뉘어 있으면 모두 evidence_refs에 넣습니다.
13. 조건·한도·승인 칸은 청크에 나온 조건을 빠짐없이 담습니다(허용 시간, 허용 시기, 승인·허가 주체, 선행 기간 등).
    하나라도 빠뜨렸으면 supported가 아니라 partial입니다.
14. 예외 칸은 '다만', '단', 'However', 'exception', 'shall not apply', 'Notwithstanding' 같은 단서 조항을 찾아 근거로 씁니다.
15. user_field_needs에 갈래를 적었다면, 그 사용자 조건이 확인되지 않은 한 적용 범위(applicable_scope) 칸은
    갈래마다 근거 청크를 인용해야 합니다. 한 갈래만 인용했다면 partial입니다.

## 출력 JSON 형식
{
  "slot_verdicts": [
    {"slot_id": "rule", "status": "supported",
     "evidence_refs": [{"evidence_id": "문서.pdf#p11#c0", "quote": "청크 본문에서 그대로 옮긴 구절"}],
     "value": "학위과정 GKS 장학생은 총장 승인 시에만 시간제 취업 가능", "missing_detail": "",
     "activation_state": null, "reason": "판정 이유 한 줄"}
  ],
  "user_field_needs": [
    {"field_id": "gks_stage", "evidence_ids": ["문서.pdf#p11#c0", "문서.pdf#p10#c3"],
     "branches": ["학위과정: 총장 승인 시 가능", "한국어연수: 6개월 이후 방학 중에만"],
     "reason": "단계별로 규정이 다름"}
  ]
}"""


def _slot_block(slot: DocSlot) -> str:
    d = cfg.DOC_SLOTS.get(slot.slot_id, {})
    lines = [
        f"- {slot.slot_id} ({d.get('label', slot.slot_id)}, {cfg.REQUIREMENTS.get(slot.requirement, slot.requirement)})",
        f"  충족 기준: {d.get('criterion', '')}",
        f"  이 질문에서 필요한 이유: {slot.activation_reason or '-'}",
        f"  현재 상태: {slot.status}",
    ]
    if slot.requirement == "conditional":
        lines.append(f"  발동 여부: {slot.activation_state or 'unresolved'}")
    if slot.evidence_refs:
        lines.append("  기존 근거: " + ", ".join(r.evidence_id for r in slot.evidence_refs))
    if slot.missing_detail:
        lines.append(f"  이전 판정에서 부족했던 점: {slot.missing_detail}")
    return "\n".join(lines)


def build_user_prompt(
    analysis: QuestionAnalysis, targets: List[DocSlot], chunk_ids: List[str],
    pool: EvidencePool, question: Optional[str],
) -> str:
    types = [t for t in [analysis.primary_type] + analysis.additional_types if t in cfg.PROFILES]
    field_ids: List[str] = []
    for t in types:
        for f in cfg.PROFILES[t]["user_field_candidates"]:
            if f not in field_ids:
                field_ids.append(f)
    for u in analysis.user_slots:
        if u.field_id not in field_ids:
            field_ids.append(u.field_id)
    fields = "\n".join(
        f"- {f}({cfg.USER_FIELDS[f]['label']}): {cfg.USER_FIELDS[f]['activation']}"
        for f in field_ids if f in cfg.USER_FIELDS
    ) or "(없음)"
    conds = "\n".join(
        f"- {c.field_id}={c.value} ({cfg.CONDITION_SUBJECTS.get(c.subject, c.subject)})" for c in analysis.conditions
    ) or "(확인된 조건 없음)"
    chunks = "\n\n".join(
        f"[{cid}]\n{pool.get(cid).text.strip()}" for cid in chunk_ids
    )
    return (
        (f"## 사용자 질문\n{question}\n\n" if question else "")
        + f"## 질문 의도\n{analysis.intent_summary}\n"
        f"답변 범위: {analysis.answer_scope} ({cfg.ANSWER_SCOPES.get(analysis.answer_scope, '')})\n\n"
        f"## 확인된 사례 조건\n{conds}\n\n"
        f"## 판정 대상 문서 칸\n" + "\n".join(_slot_block(s) for s in targets) + "\n\n"
        f"## 사용자 칸 후보 (user_field_needs에 쓸 수 있는 ID)\n{fields}\n\n"
        f"## 검색된 청크 ({len(chunk_ids)}개)\n{chunks}\n\n"
        "위 규칙에 따라 판정 JSON을 출력하세요."
    )


# ── 서버 검증: 칸 판정 ──────────────────────────────────────────────────────

def _valid_refs(
    v: SlotVerdict, shown: Set[str], pool: EvidencePool, w: List[str],
) -> List[EvidenceRef]:
    refs: List[EvidenceRef] = []
    seen = set()
    for r in v.evidence_refs:
        tag = f"{v.slot_id} 근거 {r.evidence_id}"
        if r.evidence_id not in shown:
            w.append(f"[제거] {tag}: 이번에 보여준 청크가 아님")
            continue
        chunk = pool.get(r.evidence_id)
        if chunk is None or not r.quote.strip() or _norm(r.quote) not in _norm(chunk.text):
            w.append(f"[제거] {tag}: 인용 '{r.quote[:60]}'이 청크 본문에 없음 (추정·요약 의심)")
            continue
        key = (r.evidence_id, _norm(r.quote))
        if key in seen:
            continue
        seen.add(key)
        refs.append(EvidenceRef(evidence_id=r.evidence_id, quote=r.quote.strip()))
    return refs


def apply_verdicts(
    targets: Dict[str, DocSlot], verdicts: List[SlotVerdict], shown: Set[str],
    pool: EvidencePool, searched: Set[str], w: List[str],
) -> None:
    """LLM 판정을 검증해 targets(갱신할 사본의 칸)에 반영한다."""

    def fallback(slot: DocSlot) -> str:
        # 근거가 없을 때의 상태: 검색했거나 이미 판정된 적 있으면 missing, 아니면 unchecked(②가 검색하도록)
        return "missing" if (slot.slot_id in searched or slot.status != "unchecked") else "unchecked"

    seen: Set[str] = set()
    for v in verdicts:
        slot = targets.get(v.slot_id)
        if slot is None:
            w.append(f"[제거] 판정 '{v.slot_id}': 이번 판정 대상 칸이 아님")
            continue
        if v.slot_id in seen:
            w.append(f"[제거] 판정 '{v.slot_id}': 중복")
            continue
        seen.add(v.slot_id)
        sid = v.slot_id

        status = v.status
        if status == "unavailable_in_corpus":
            w.append(f"[수정] {sid}: unavailable_in_corpus는 자료 범위표로만 정함 → missing으로 판정")
            status = "missing"
        elif status not in cfg.VERIFIABLE_STATUSES:
            w.append(f"[수정] {sid}: 알 수 없는 상태 '{status}' → missing으로 판정")
            status = "missing"

        refs = _valid_refs(v, shown, pool, w)

        activation = slot.activation_state
        if slot.requirement == "conditional" and v.activation_state:
            if v.activation_state in cfg.ACTIVATION_STATES:
                activation = v.activation_state
            else:
                w.append(f"[제거] {sid}: activation_state '{v.activation_state}' 잘못됨")

        if status == "not_applicable":
            if slot.requirement == "required":
                w.append(f"[수정] {sid}: 필수 칸은 not_applicable로 바꿀 수 없음 → 근거 없음으로 처리")
                status = fallback(slot)
                refs = []
            elif slot.requirement == "conditional" and not refs:
                w.append(f"[수정] {sid}: 근거 없이 조건부 칸을 not_applicable로 둘 수 없음 → 발동 미확인 유지")
                status, activation = fallback(slot), "unresolved"
            elif slot.requirement == "conditional":
                activation = "not_triggered"
        elif slot.requirement == "conditional" and activation == "not_triggered":
            w.append(f"[수정] {sid}: 발동 안 함인데 status {status} → 발동 미확인 유지 (근거 없이 비활성화 금지)")
            activation = "unresolved"

        if status in ("supported", "partial", "conflicting") and not refs:
            new = fallback(slot)
            w.append(f"[수정] {sid}: {status}인데 유효한 근거가 없음 → {new}")
            status = new
        if status == "conflicting" and len({r.evidence_id for r in refs}) < 2:
            w.append(f"[수정] {sid}: 충돌은 근거 2개 이상이 필요 → partial")
            status = "partial"
        if status == "missing" and sid not in searched and slot.status == "unchecked":
            w.append(f"[수정] {sid}: 검색한 적 없는 칸은 missing이 아니라 unchecked 유지 (②가 검색)")
            status = "unchecked"
        if slot.requirement == "conditional" and status == "supported" and activation in (None, "unresolved"):
            activation = "triggered"  # 문서에서 이 칸의 내용이 확인됐으므로 발동

        if slot.evidence_refs and not refs:
            w.append(f"[확인 필요] {sid}: 기존 근거 {len(slot.evidence_refs)}개가 이번 판정에서 빠짐 ({status})")

        slot.status = status
        slot.evidence_refs = refs
        slot.value = v.value.strip() if refs else ""
        slot.missing_detail = v.missing_detail.strip()
        if slot.requirement == "conditional":
            slot.activation_state = activation or "unresolved"

    for sid, slot in targets.items():
        if sid in seen:
            continue
        w.append(f"[확인 필요] {sid}: LLM이 판정하지 않음 (상태 유지)")
        if slot.status == "unchecked" and sid in searched:
            slot.status = "missing"
            w.append(f"[수정] {sid}: 검색했는데 판정이 없어 missing")


# ── 서버 검증: 사용자 칸 ────────────────────────────────────────────────────

def apply_user_needs(
    analysis: QuestionAnalysis, needs: List[UserFieldNeed], shown: Set[str], w: List[str],
) -> Dict[str, List[str]]:
    """문서 근거가 있는 사용자 조건만 활성화한다. 반환: {field_id: 갈래 요약}."""
    confirmed = {c.field_id for c in analysis.conditions if c.status == "confirmed"}
    by_field = {u.field_id: u for u in analysis.user_slots}
    branches: Dict[str, List[str]] = {}
    for n in needs:
        if n.field_id not in cfg.USER_FIELDS:
            w.append(f"[제거] 사용자 조건 '{n.field_id}': 정의되지 않은 칸")
            continue
        ids = [i for i in n.evidence_ids if i in shown]
        if not ids:
            w.append(f"[제거] 사용자 조건 '{n.field_id}': 보여준 청크 중 근거가 없음 (문서 근거 없이 되묻기 금지)")
            continue
        u = by_field.get(n.field_id)
        if u is None:
            u = UserSlot(field_id=n.field_id, status="confirmed" if n.field_id in confirmed else "unknown")
            analysis.user_slots.append(u)
            by_field[n.field_id] = u
        u.active = True
        u.required_by_evidence = list(dict.fromkeys(u.required_by_evidence + ids))
        u.reason = n.reason.strip() or u.reason
        if n.branches:
            u.reason = f"{u.reason} | 갈래: " + " / ".join(b.strip() for b in n.branches if b.strip())
        if u.status == "not_required":
            u.status = "confirmed" if n.field_id in confirmed else "unknown"
        branches[n.field_id] = [b.strip() for b in n.branches if b.strip()]
    return branches


def check_scope_covers_branches(
    analysis: QuestionAnalysis, needs: List[UserFieldNeed], shown: Set[str], w: List[str],
) -> None:
    """
    미확인 사용자 조건에 따라 문서 답이 갈리면, supported인 적용 범위 칸은 그 갈래 근거를 모두 인용해야 한다.
    하나라도 빠지면 partial로 낮춘다. (예: 학위과정 조항만 보고 '적용 범위 확인'이라 판정하는 경우)
    """
    scope = next((s for s in analysis.document_slots if s.slot_id == "applicable_scope"), None)
    if scope is None or scope.status != "supported":
        return
    confirmed = {c.field_id for c in analysis.conditions if c.status == "confirmed"}
    cited = {r.evidence_id for r in scope.evidence_refs}
    for n in needs:
        if n.field_id in confirmed or n.field_id not in cfg.USER_FIELDS:
            continue
        ids = [i for i in n.evidence_ids if i in shown]
        uncited = [i for i in ids if i not in cited]
        if len(ids) >= 2 and uncited:
            scope.status = "partial"
            detail = f"{n.field_id} 갈래 근거 중 적용 범위에 인용되지 않은 청크: {', '.join(uncited)}"
            scope.missing_detail = (scope.missing_detail + " / " if scope.missing_detail else "") + detail
            w.append(f"[수정] applicable_scope: supported → partial ({detail})")
            return


# ── 다음 행동 (서버 규칙, 체크리스트 2.4절) ─────────────────────────────────

def _can_search_more(analysis: QuestionAnalysis, budget: SearchBudget, history: List[SearchAttempt]) -> Tuple[bool, str]:
    n = cfg.MAX_NO_PROGRESS_ROUNDS
    if len(history) >= n and not any(h.found_new_evidence for h in history[-n:]):
        return False, f"최근 검색 {n}회 연속 새 근거 없음"
    needed_ids = {s.slot_id for s in analysis.document_slots if is_needed(s)}
    reasons = []
    for slot, search_type in rank_candidates(analysis.document_slots):
        if slot.slot_id not in needed_ids:
            continue
        if count_attempts(history, slot.slot_id, search_type) >= slot_attempt_limit(search_type):
            reasons.append(f"{slot.slot_id}: 칸별 상한")
            continue
        msg = check_budget(budget, search_type)
        if msg:
            reasons.append(f"{slot.slot_id}: {msg}")
            continue
        return True, ""
    return False, "; ".join(reasons) or "검색할 후보 칸 없음"


def decide(
    analysis: QuestionAnalysis, budget: SearchBudget, history: List[SearchAttempt],
    branches: Optional[Dict[str, List[str]]] = None,
) -> VerifyDecision:
    branches = branches or {}
    needed = [s for s in analysis.document_slots if is_needed(s)]
    unresolved = [s.slot_id for s in needed if s.status not in cfg.RESOLVED_STATUSES]
    has_evidence = any(s.evidence_refs for s in analysis.document_slots if s.active)
    pending = [
        u.field_id for u in analysis.user_slots
        if u.active and u.status in ("unknown", "ambiguous") and u.required_by_evidence
    ]

    if not unresolved:
        if pending:
            picked = {f: branches.get(f, []) for f in pending}
            if analysis.answer_scope in ("personal", "third_party"):
                ask = pending[: cfg.MAX_CLARIFY_FIELDS]
                return VerifyDecision(
                    next_action="ask_clarification",
                    reason=f"문서 근거는 충분하나 개인별 결론을 바꾸는 조건 미확인: {ask}",
                    clarify_field_ids=ask, condition_branches={f: picked[f] for f in ask},
                )
            return VerifyDecision(
                next_action="answer_by_condition",
                reason=f"일반 질문이며 문서상 {pending}에 따라 답이 갈림 → 조건별 안내",
                condition_field_ids=pending, condition_branches=picked,
            )
        return VerifyDecision(next_action="answer", reason="필요한 문서 칸이 모두 근거로 확인됨")

    can, why = _can_search_more(analysis, budget, history)
    if can:
        anchors = {
            s.slot_id: [r.evidence_id for r in s.evidence_refs]
            for s in analysis.document_slots if s.slot_id in unresolved and s.status == "partial" and s.evidence_refs
        }
        return VerifyDecision(
            next_action="continue_search", reason=f"미해결 칸 {unresolved}, 예산 남음",
            unresolved_slot_ids=unresolved, expand_anchors=anchors,
        )
    if has_evidence:
        return VerifyDecision(
            next_action="partial_answer", reason=f"미해결 칸 {unresolved}, 더 검색할 수 없음 ({why})",
            unresolved_slot_ids=unresolved, condition_field_ids=pending,
            condition_branches={f: branches.get(f, []) for f in pending},
        )
    return VerifyDecision(
        next_action="no_evidence", reason=f"사용할 근거가 없고 더 검색할 수 없음 ({why})",
        unresolved_slot_ids=unresolved,
    )


# ── 실행 ─────────────────────────────────────────────────────────────────

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        from app.config import settings
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def verify_evidence(
    analysis: QuestionAnalysis,
    pool: EvidencePool,
    budget: Optional[SearchBudget] = None,
    history: Optional[List[SearchAttempt]] = None,
    round_chunk_ids: Optional[List[str]] = None,
    question: Optional[str] = None,
    model: Optional[str] = None,
    client=None,
) -> VerificationRun:
    """
    근거 풀로 칸 상태를 판정하고 다음 행동을 정한다. 실패해도 예외 대신 run.error에 이유를 담는다.
    round_chunk_ids: 이번 라운드에 ③이 돌려준 청크 전부(run.chunk_ids, 새 청크가 아니어도). 없으면 풀 순서대로.
    LLM 호출이 끝내 실패하면 칸 상태는 바꾸지 않고, 결정 없이(error) 돌려준다.
    """
    budget = budget or SearchBudget()
    history = history or []
    run = VerificationRun(checklist_version=cfg.CHECKLIST_VERSION)
    started = time.perf_counter()
    a = analysis.model_copy(deep=True)
    run.analysis = a

    targets = judge_targets(a)
    run.judged_slot_ids = [s.slot_id for s in targets]
    shown = select_chunks(a, pool, round_chunk_ids)
    run.shown_chunk_ids = shown
    branches: Dict[str, List[str]] = {}

    if targets and shown:
        if model is None:
            from app.config import settings
            model = settings.openai_model
        run.model = model
        client = client or _get_client()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(a, targets, shown, pool, question)},
        ]
        output: Optional[VerifyOutput] = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            run.attempts = attempt
            run.llm_called = True
            try:
                resp = client.chat.completions.create(
                    model=model, messages=messages, temperature=0, max_tokens=3000,
                    response_format={"type": "json_object"},
                )
            except Exception as e:
                run.error = f"LLM 호출 실패: {type(e).__name__}: {e}"
                break
            usage = getattr(resp, "usage", None)
            if usage:
                run.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
                run.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            raw = resp.choices[0].message.content or ""
            run.raw_output = raw
            try:
                output = VerifyOutput.model_validate(json.loads(raw))
                run.error = None
                break
            except (json.JSONDecodeError, ValidationError) as e:
                run.error = f"형식 오류: {type(e).__name__}: {str(e)[:500]}"
                messages += [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": f"출력 형식 오류입니다: {run.error}\nJSON 형식을 지켜 JSON만 다시 출력하세요."},
                ]
        if output is None:
            run.analysis = analysis.model_copy(deep=True)   # 판정 실패: 상태를 바꾸지 않음
            run.latency_ms = int((time.perf_counter() - started) * 1000)
            return run
        shown_set = set(shown)
        apply_verdicts({s.slot_id: s for s in targets}, output.slot_verdicts, shown_set, pool,
                       searched_slot_ids(history), run.warnings)
        branches = apply_user_needs(a, output.user_field_needs, shown_set, run.warnings)
        check_scope_covers_branches(a, output.user_field_needs, shown_set, run.warnings)
    elif targets:
        run.warnings.append("[건너뜀] 판정할 청크가 없어 LLM을 부르지 않음")
        for s in targets:
            if s.status == "unchecked" and s.slot_id in searched_slot_ids(history):
                s.status = "missing"

    run.decision = decide(a, budget, history, branches)
    run.latency_ms = int((time.perf_counter() - started) * 1000)
    return run
