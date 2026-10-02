"""
② 검색 계획.

입력: ①(또는 이전 바퀴 ④)이 만든 체크리스트 상태(QuestionAnalysis.document_slots) +
      확인된 조건 + 예산 사용 현황 + 이전 검색 기록
출력: 이번 바퀴에 실행할 검색 액션 1개 (SearchPlan)

설계 원칙 (수유니 확정)
  - 대상 문서 칸 선택은 규칙 기반이다. LLM에게 고르라고 하지 않는다.
    우선순위: 필수도(필수 > 조건부 필수 > 선택) > 같은 필수도 안에서는
    원문 확장(partial)이 신규 검색보다 먼저 > 유형에 정의된 칸 순서.
  - LLM은 신규 검색의 검색어만 만든다. 원문 확장은 앵커로 실행하므로 서버가 계획한다.
  - 예산(하위 질문 3개 / 검색 호출 총 6회 / 원문 확장 3회)은 서버가 강제한다.
    LLM이 뭐라고 하든 한도를 넘으면 budget_exhausted로 덮어쓴다.
  - 예산은 후보 칸마다 검사한다. 1순위 칸이 막혀도 예산이 되는 다음 후보로 넘어간다.
  - 칸 하나의 시도 횟수에도 상한이 있다(신규 2회·확장 2회). 상한에 걸린 칸은 이번 계획에서
    건너뛰어 다른 필수 칸이 예산을 쓸 수 있게 하되, status는 바꾸지 않는다(missing·partial·
    conflicting 유지). 검색 한도 소진은 unavailable_in_corpus의 근거가 아니다(체크리스트 2.1절).
    남은 미해결 칸은 ④·⑤가 부분 답변으로 처리한다.
  - 첫 바퀴(검색 기록 없음)에는 ①이 만든 first_search를 그대로 쓴다(LLM 호출 없음).
  - 신규 검색어가 이미 시도한 검색어(칸 무관)와 같으면 한 번 다시 만들게 하고,
    그래도 같으면 그 칸은 이번 바퀴에서 건너뛴다.
"""
from __future__ import annotations

import json
import time
from typing import List, Optional, Tuple

from app.core.single_agent import checklist_config as cfg
from app.core.single_agent.llm import RetryWith, get_client, model_for, run_json_loop
from app.core.single_agent.text_match import normalize as _norm
from app.core.single_agent.analysis_schema import Condition, DocSlot, QuestionAnalysis
from app.core.single_agent.search_schema import (
    SearchAttempt,
    SearchBudget,
    SearchPlan,
    SearchPlanRun,
)

_REQ_RANK = {"required": 2, "conditional": 1, "optional": 0}


class SearchPlanFormatError(ValueError):
    """LLM 출력이 다음 단계로 넘길 수 없을 만큼 틀렸을 때 (재시도 대상)."""


# ── 대상 슬롯 선택 (규칙 기반, LLM 호출 없음) ───────────────────────────────

def rank_candidates(document_slots: List[DocSlot]) -> List[Tuple[DocSlot, str]]:
    """
    검색이 필요한 칸을 우선순위대로 정렬해 모두 돌려준다.

    후보: active=true이고 status가 검색이 필요한 상태(unchecked/missing/conflicting/partial)인 칸.
    supported / not_applicable / unavailable_in_corpus는 이미 처리됐거나 검색이 필요 없으므로 제외한다.

    우선순위
      1) 필수도: 필수 > 조건부 필수 > 선택
    2) 같은 필수도 안에서는 인접 내용이 부족한 partial 확장이 신규 검색보다 먼저
       (다른 조항·적용 범위·충돌이 부족 원인이면 partial도 신규 검색으로 전환)
      3) document_slots에 나열된 순서(유형 프로파일 순서)
    """
    order = {s.slot_id: i for i, s in enumerate(document_slots)}
    candidates: List[Tuple[DocSlot, str]] = []
    for s in document_slots:
        if not s.active:
            continue
        if s.status in cfg.NEEDS_EXPAND_STATUSES:
            search_type = ("new" if s.missing_kind in cfg.MISSING_KINDS_REQUIRING_NEW_SEARCH
                           else "expand_context")
            candidates.append((s, search_type))
        elif s.status in cfg.NEEDS_NEW_SEARCH_STATUSES:
            candidates.append((s, "new"))
        # NO_SEARCH_NEEDED_STATUSES(supported/not_applicable/unavailable_in_corpus)는 건너뜀

    candidates.sort(key=lambda pair: (
        -_REQ_RANK.get(pair[0].requirement, 0),
        0 if pair[1] == "expand_context" else 1,
        order.get(pair[0].slot_id, 999),
    ))
    return candidates


def select_target_slot(document_slots: List[DocSlot]) -> Tuple[Optional[DocSlot], Optional[str]]:
    """1순위 후보 하나만 돌려준다 (예산·상한 무시). 반환: (슬롯 또는 None, "new"/"expand_context" 또는 None)"""
    ranked = rank_candidates(document_slots)
    return ranked[0] if ranked else (None, None)


def count_attempts(history: List[SearchAttempt], slot_id: str, search_type: str) -> int:
    return sum(1 for h in history if h.target_slot_id == slot_id and h.search_type == search_type)


def slot_attempt_limit(search_type: str) -> int:
    return cfg.MAX_NEW_SEARCHES_PER_SLOT if search_type == "new" else cfg.MAX_EXPANSIONS_PER_SLOT


# ── 예산 검사 (서버가 강제) ─────────────────────────────────────────────────

def check_budget(budget: SearchBudget, search_type: str) -> Optional[str]:
    """한도를 넘으면 이유 문자열을, 넘지 않으면 None을 반환한다."""
    if budget.total_calls >= cfg.MAX_SEARCH_CALLS:
        return f"검색 호출 총 한도({cfg.MAX_SEARCH_CALLS}회) 소진"
    if search_type == "expand_context" and budget.expand_calls >= cfg.MAX_CONTEXT_EXPANSIONS:
        return f"원문 확장 한도({cfg.MAX_CONTEXT_EXPANSIONS}회) 소진"
    if search_type == "new" and budget.subqueries >= cfg.MAX_SUBQUERIES:
        return f"하위 질문 한도({cfg.MAX_SUBQUERIES}개) 소진"
    return None


# ── 검색어 문구 생성 (LLM 1회, 슬롯 하나에 대해서만) ────────────────────────

SEARCH_QUERY_SYSTEM_PROMPT = """당신은 동아대학교 유학생 챗봇의 '검색어 생성' 담당입니다.
이미 어떤 문서 칸을 확인해야 하는지는 정해져 있습니다. 그 칸 하나를 확인하기 위한
한국어 검색어 1개만 만듭니다. 유형을 고르거나 다른 칸을 제안하지 않습니다.

규칙
1. 확인된 사용자 조건(있다면)을 검색어에 자연스럽게 반영합니다.
2. GKS, D-4, TOPIK 같은 공식 명칭·코드는 번역하거나 풀어쓰지 않고 그대로 둡니다.
3. search_type이 expand_context이면 새 주제어를 추가하지 않고, 이미 찾은 문서·조항의
   이어지는 부분(다음 페이지, 관련 조항, 표의 나머지)을 좁혀서 확인하는 문구로 만듭니다.
4. 이미 시도한 검색어 목록과 같은 문구를 반복하지 않습니다. 이전 시도가 있다면 관점을 바꿉니다
   (다른 표현, 더 구체적인 범위, 다른 조항 명칭 등).
5. 결과는 반드시 JSON 객체 하나로만 출력합니다: {"query_ko": "...", "reason": "..."}
   reason에는 이 칸을 왜 이 검색어로 확인하려는지 한 줄로 적습니다."""


def _build_query_user_prompt(
    analysis_intent: str,
    conditions: List[Condition],
    slot: DocSlot,
    search_type: str,
    tried_for_slot: List[str],
    tried_other: List[str],
) -> str:
    cond_lines = "\n".join(
        f"- {c.field_id}={c.value} ({c.subject})" for c in conditions
    ) or "(확인된 조건 없음)"
    tried_slot_lines = "\n".join(f"- {q}" for q in tried_for_slot) or "(없음)"
    tried_other_lines = "\n".join(f"- {q}" for q in tried_other) or "(없음)"
    slot_def = cfg.DOC_SLOTS.get(slot.slot_id, {})
    current_value = slot.value.strip() or "(아직 확인된 값 없음)"
    missing_detail = slot.missing_detail.strip() or "(구체적인 부족 내용 없음)"
    return (
        f"## 질문 의도\n{analysis_intent}\n\n"
        f"## 확인된 조건\n{cond_lines}\n\n"
        f"## 확인할 문서 칸\n"
        f"- ID: {slot.slot_id}\n- 이름: {slot_def.get('label', slot.slot_id)}\n"
        f"- 충족 기준: {slot_def.get('criterion', '')}\n"
        f"- 이 칸을 확인하려는 이유: {slot.activation_reason}\n"
        f"- 현재까지 확인된 내용: {current_value}\n"
        f"- 이전 판정에서 부족했던 점: {missing_detail}\n"
        f"- 부족 유형: {slot.missing_kind or 'unknown'}\n\n"
        f"## 검색 종류\n{search_type} ({'원문 확장' if search_type == 'expand_context' else '신규 검색'})\n\n"
        f"## 이미 시도한 검색어 (이 칸)\n{tried_slot_lines}\n\n"
        f"## 이미 시도한 검색어 (다른 칸, 같은 문구 금지)\n{tried_other_lines}\n\n"
        "위 규칙에 따라 검색어 JSON을 출력하세요."
    )


def _generate_query(
    run: SearchPlanRun,
    client,
    model: str,
    analysis: QuestionAnalysis,
    slot: DocSlot,
    search_type: str,
    history: List[SearchAttempt],
) -> Tuple[Optional[str], str, bool]:
    """
    칸 하나에 대한 검색어를 LLM으로 만든다. 형식 오류나 중복이면 1회 다시 만든다.
    반환: (검색어 또는 None, reason, 중복 여부)
      - 검색어가 None이면 LLM이 끝내 형식을 못 맞춘 것 (호출자가 대체 검색어를 만든다)
      - 중복 여부 True면 두 번 다 이미 시도한 문구였다는 뜻 (호출자가 이 칸을 건너뛴다)
    """
    tried_all = {_norm(h.query_ko) for h in history}
    tried_for_slot = [h.query_ko for h in history if h.target_slot_id == slot.slot_id]
    tried_other = [h.query_ko for h in history if h.target_slot_id != slot.slot_id]
    messages = [
        {"role": "system", "content": SEARCH_QUERY_SYSTEM_PROMPT},
        {"role": "user", "content": _build_query_user_prompt(
            analysis.intent_summary, analysis.conditions, slot, search_type, tried_for_slot, tried_other,
        )},
    ]

    def parse(raw: str) -> Tuple[str, str]:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise SearchPlanFormatError("JSON 객체가 아님")
        q = str(data.get("query_ko", "")).strip()
        if not q:
            raise SearchPlanFormatError("query_ko가 비어 있음")
        r = str(data.get("reason", "")).strip()
        if _norm(q) in tried_all:
            raise RetryWith(
                "이미 시도한 검색어와 같습니다. 표현·범위·조항 명칭을 바꿔 다른 검색어를 JSON으로 다시 출력하세요.",
                value=(q, r),
                warning=f"[재시도] 검색어 '{q}'는 이미 시도한 문구 → 다른 표현으로 다시 생성",
            )
        return q, r

    value, ok = run_json_loop(run, client, model, messages, parse=parse,
                              temperature=0.3, max_tokens=300, format_hint="JSON만 다시 출력하세요.")
    if ok:
        return value[0], value[1], False
    if value is not None:          # 두 번 다 이미 시도한 문구
        return value[0], value[1], True
    return None, "", False


def _pick_first_search(
    analysis: QuestionAnalysis,
    candidates: List[Tuple[DocSlot, str]],
) -> Optional[DocSlot]:
    """①의 first_search가 가리키는 칸 중 우선순위가 가장 높은 신규 검색 후보."""
    fs = analysis.first_search
    if not fs or not fs.query_ko.strip():
        return None
    targets = set(fs.target_slot_ids)
    for slot, search_type in candidates:
        if search_type == "new" and slot.slot_id in targets:
            return slot
    return None


def plan_search(
    analysis: QuestionAnalysis,
    budget: Optional[SearchBudget] = None,
    history: Optional[List[SearchAttempt]] = None,
    model: Optional[str] = None,
    client=None,
    anchors_by_slot: Optional[dict] = None,
    completed_expansions: Optional[set] = None,
) -> SearchPlanRun:
    """
    이번 바퀴에 실행할 검색 액션 1개를 정한다.
    실패해도 예외 대신 SearchPlanRun.error에 이유를 담아 돌려준다.

    주의: 이 함수는 analysis.document_slots의 status를 바꾸지 않는다. 칸별 상한에 걸린 칸은
    plan.exhausted_slot_ids에 기록하고 status(missing 등)를 그대로 둔다.
    """
    budget = budget or SearchBudget()
    history = history or []
    run = SearchPlanRun(model=model or "", checklist_version=cfg.CHECKLIST_VERSION)
    started = time.perf_counter()

    candidates = rank_candidates(analysis.document_slots)
    if not candidates:
        run.plan = SearchPlan(
            action="no_target_left",
            reason="검색이 필요한 활성 문서 칸이 남아있지 않음 (모두 supported/not_applicable/unavailable_in_corpus)",
        )
        return run

    # 1) 첫 바퀴: ①의 first_search를 그대로 사용 (LLM 호출 없음)
    if not history and budget.total_calls == 0:
        first_slot = _pick_first_search(analysis, candidates)
        if first_slot is not None and check_budget(budget, "new") is None:
            run.plan = SearchPlan(
                action="search",
                target_slot_id=first_slot.slot_id,
                search_type="new",
                query_ko=analysis.first_search.query_ko.strip(),
                reason=analysis.first_search.reason or "(①의 첫 검색 사용)",
                from_first_search=True,
            )
            return run

    exhausted: List[str] = []
    skipped: List[str] = []
    budget_block: Optional[Tuple[DocSlot, str, str]] = None

    # 2) 후보를 우선순위대로 보면서, 상한·예산을 통과하고 중복이 아닌 첫 칸을 고른다
    for slot, search_type in candidates:
        n = count_attempts(history, slot.slot_id, search_type)
        limit = slot_attempt_limit(search_type)
        if n >= limit:
            # 상한에 걸린 칸은 더 검색하지 않는다. status는 그대로 둔다(부분 답변 대상).
            exhausted.append(slot.slot_id)
            skipped.append(f"{slot.slot_id}({search_type}): 칸별 시도 상한 {limit}회 도달, status={slot.status} 유지")
            run.warnings.append(
                f"[상한] {slot.slot_id}: {search_type} {n}회 도달 → 더 검색하지 않음 (status={slot.status} 유지, 부분 답변 대상)"
            )
            continue

        budget_msg = check_budget(budget, search_type)
        if budget_msg:
            skipped.append(f"{slot.slot_id}({search_type}): {budget_msg}")
            if budget_block is None:
                budget_block = (slot, search_type, budget_msg)
            continue

        # 확장은 query_ko로 검색하지 않는다. 기록용 문구를 만들기 위해 LLM을 호출하지 않는다.
        # 실제 앵커/이웃 탐색과 예산·슬롯 상한은 기존 규칙을 유지한다.
        if search_type == "expand_context":
            anchor_ids = list((anchors_by_slot or {}).get(slot.slot_id) or [])
            signature = (tuple(sorted(set(anchor_ids))), cfg.EXPAND_WINDOW)
            if anchor_ids and signature in (completed_expansions or set()):
                skipped.append(f"{slot.slot_id}(expand_context): 동일 앵커·범위 확장 완료")
                run.warnings.append(
                    f"[건너뜀] {slot.slot_id}: 동일 앵커 {anchor_ids} / window={cfg.EXPAND_WINDOW} 재확장"
                )
                continue
            query = next((h.query_ko for h in reversed(history)
                          if h.target_slot_id == slot.slot_id and h.query_ko.strip()),
                         f"{analysis.intent_summary} {cfg.DOC_SLOTS.get(slot.slot_id, {}).get('label', slot.slot_id)}")
            run.plan = SearchPlan(action="search", target_slot_id=slot.slot_id,
                                  search_type=search_type, query_ko=query,
                                  reason="(서버 계획) 근거 앵커의 앞뒤 청크 확인",
                                  exhausted_slot_ids=exhausted, skipped=skipped)
            run.latency_ms = int((time.perf_counter() - started) * 1000)
            return run

        # 3) 검색어 문구 생성 — LLM (슬롯·종류는 이미 정해져 있음)
        if not model:
            model = model_for("plan")
            run.model = model
        client = client or get_client()

        query_ko, reason, is_dup = _generate_query(run, client, model, analysis, slot, search_type, history)
        if query_ko is None:
            # LLM이 끝내 검색어를 못 만들면, 슬롯 라벨로 최소한의 검색어를 만들어 진행한다.
            slot_def = cfg.DOC_SLOTS.get(slot.slot_id, {})
            query_ko = f"{analysis.intent_summary} {slot_def.get('label', slot.slot_id)}".strip()
            reason = "(서버 보완) LLM 검색어 생성 실패 → 슬롯 라벨로 대체"
            run.warnings.append(reason)
            is_dup = _norm(query_ko) in {_norm(h.query_ko) for h in history}
        if is_dup:
            skipped.append(f"{slot.slot_id}({search_type}): 다시 만들어도 이미 시도한 검색어 '{query_ko}'")
            run.warnings.append(f"[건너뜀] {slot.slot_id}: 중복 검색어 '{query_ko}'")
            continue

        run.latency_ms = int((time.perf_counter() - started) * 1000)
        run.plan = SearchPlan(
            action="search",
            target_slot_id=slot.slot_id,
            search_type=search_type,
            query_ko=query_ko,
            reason=reason,
            exhausted_slot_ids=exhausted,
            skipped=skipped,
        )
        return run

    # 4) 실행할 검색이 없음
    run.latency_ms = int((time.perf_counter() - started) * 1000)
    if budget_block is not None:
        slot, search_type, msg = budget_block
        run.plan = SearchPlan(
            action="budget_exhausted",
            target_slot_id=slot.slot_id,
            search_type=search_type,
            reason=msg,
            exhausted_slot_ids=exhausted,
            skipped=skipped,
        )
    else:
        run.plan = SearchPlan(
            action="no_target_left",
            reason="남은 후보가 모두 칸별 시도 상한에 걸렸거나 중복 검색어뿐임 (미해결 칸은 status 유지 → 부분 답변)",
            exhausted_slot_ids=exhausted,
            skipped=skipped,
        )
    return run
