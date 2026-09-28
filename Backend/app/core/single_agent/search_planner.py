"""
② 검색 계획.

입력: ①(또는 이전 바퀴 ④)이 만든 체크리스트 상태(QuestionAnalysis.document_slots) +
      확인된 조건 + 예산 사용 현황 + 이전 검색 기록
출력: 이번 바퀴에 실행할 검색 액션 1개 (SearchPlan)

설계 원칙 (수유니 확정)
  - 대상 문서 칸 선택은 규칙 기반이다. LLM에게 고르라고 하지 않는다.
    우선순위: 필수도(필수 > 조건부 필수 > 선택) > 같은 필수도 안에서는
    원문 확장(partial)이 신규 검색보다 먼저 > 유형에 정의된 칸 순서.
  - LLM은 선택된 슬롯 하나에 대한 자연어 검색어 문구만 만든다.
  - 예산(하위 질문 3개 / 검색 호출 총 6회 / 원문 확장 3회)은 서버가 강제한다.
    LLM이 뭐라고 하든 한도를 넘으면 budget_exhausted로 덮어쓴다.
  - 같은 슬롯에 같은 검색어를 반복하지 않는다.
"""
from __future__ import annotations

import json
import re
import time
from typing import List, Optional, Tuple

from pydantic import ValidationError

from app.core.single_agent import checklist_config as cfg
from app.core.single_agent.analysis_schema import Condition, DocSlot, QuestionAnalysis
from app.core.single_agent.search_schema import (
    SearchAttempt,
    SearchBudget,
    SearchPlan,
    SearchPlanRun,
)

MAX_ATTEMPTS = 2
_REQ_RANK = {"required": 2, "conditional": 1, "optional": 0}


class SearchPlanFormatError(ValueError):
    """LLM 출력이 다음 단계로 넘길 수 없을 만큼 틀렸을 때 (재시도 대상)."""


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


# ── 대상 슬롯 선택 (규칙 기반, LLM 호출 없음) ───────────────────────────────

def select_target_slot(document_slots: List[DocSlot]) -> Tuple[Optional[DocSlot], Optional[str]]:
    """
    다음에 확인할 문서 칸을 규칙으로 고른다.

    후보: active=true이고 status가 검색이 필요한 상태(unchecked/missing/conflicting/partial)인 칸.
    supported / not_applicable / unavailable_in_corpus는 이미 처리됐거나 검색이 필요 없으므로 제외한다.

    우선순위
      1) 필수도: 필수 > 조건부 필수 > 선택
      2) 같은 필수도 안에서는 원문 확장(partial)이 신규 검색보다 먼저
         (이미 찾은 근거를 완성하는 쪽이 새 슬롯을 여는 것보다 저렴하고 실패 위험이 낮음)
      3) document_slots에 나열된 순서(유형 프로파일 순서)

    반환: (선택된 슬롯 또는 None, "new"/"expand_context" 또는 None)
    """
    order = {s.slot_id: i for i, s in enumerate(document_slots)}
    candidates: List[Tuple[DocSlot, str]] = []
    for s in document_slots:
        if not s.active:
            continue
        if s.status in cfg.NEEDS_EXPAND_STATUSES:
            candidates.append((s, "expand_context"))
        elif s.status in cfg.NEEDS_NEW_SEARCH_STATUSES:
            candidates.append((s, "new"))
        # NO_SEARCH_NEEDED_STATUSES(supported/not_applicable/unavailable_in_corpus)는 건너뜀

    if not candidates:
        return None, None

    candidates.sort(key=lambda pair: (
        -_REQ_RANK.get(pair[0].requirement, 0),
        0 if pair[1] == "expand_context" else 1,
        order.get(pair[0].slot_id, 999),
    ))
    slot, search_type = candidates[0]
    return slot, search_type


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
    tried: List[str],
) -> str:
    cond_lines = "\n".join(
        f"- {c.field_id}={c.value} ({c.subject})" for c in conditions
    ) or "(확인된 조건 없음)"
    tried_lines = "\n".join(f"- {q}" for q in tried) or "(없음)"
    slot_def = cfg.DOC_SLOTS.get(slot.slot_id, {})
    return (
        f"## 질문 의도\n{analysis_intent}\n\n"
        f"## 확인된 조건\n{cond_lines}\n\n"
        f"## 확인할 문서 칸\n"
        f"- ID: {slot.slot_id}\n- 이름: {slot_def.get('label', slot.slot_id)}\n"
        f"- 충족 기준: {slot_def.get('criterion', '')}\n"
        f"- 이 칸을 확인하려는 이유: {slot.activation_reason}\n\n"
        f"## 검색 종류\n{search_type} ({'원문 확장' if search_type == 'expand_context' else '신규 검색'})\n\n"
        f"## 이미 시도한 검색어 (이 칸 기준)\n{tried_lines}\n\n"
        "위 규칙에 따라 검색어 JSON을 출력하세요."
    )


_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        from app.config import settings
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def plan_search(
    analysis: QuestionAnalysis,
    budget: Optional[SearchBudget] = None,
    history: Optional[List[SearchAttempt]] = None,
    model: Optional[str] = None,
    client=None,
) -> SearchPlanRun:
    """
    이번 바퀴에 실행할 검색 액션 1개를 정한다.
    실패해도 예외 대신 SearchPlanRun.error에 이유를 담아 돌려준다.
    """
    budget = budget or SearchBudget()
    history = history or []
    run = SearchPlanRun(model=model or "", checklist_version=cfg.CHECKLIST_VERSION)

    # 1) 대상 슬롯 선택 — 규칙 기반, LLM 호출 없음
    slot, search_type = select_target_slot(analysis.document_slots)
    if slot is None:
        run.plan = SearchPlan(
            action="no_target_left",
            reason="검색이 필요한 활성 문서 칸이 남아있지 않음 (모두 supported/not_applicable/unavailable_in_corpus)",
        )
        return run

    # 2) 예산 검사 — 서버가 강제, LLM 호출 전에 차단
    budget_msg = check_budget(budget, search_type)
    if budget_msg:
        run.plan = SearchPlan(
            action="budget_exhausted",
            target_slot_id=slot.slot_id,
            search_type=search_type,
            reason=budget_msg,
        )
        return run

    # 3) 검색어 문구 생성 — LLM 1회 (슬롯·종류는 이미 정해져 있음)
    if model is None:
        from app.config import settings
        model = settings.openai_model
        run.model = model
    client = client or _get_client()

    tried_for_slot = [h.query_ko for h in history if h.target_slot_id == slot.slot_id]
    messages = [
        {"role": "system", "content": SEARCH_QUERY_SYSTEM_PROMPT},
        {"role": "user", "content": _build_query_user_prompt(
            analysis.intent_summary, analysis.conditions, slot, search_type, tried_for_slot,
        )},
    ]

    started = time.perf_counter()
    query_ko, reason = None, ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        run.attempts = attempt
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            run.error = f"LLM 호출 실패: {type(e).__name__}: {e}"
            break

        raw = resp.choices[0].message.content or ""
        try:
            data = json.loads(raw)
            q = str(data.get("query_ko", "")).strip()
            if not q:
                raise SearchPlanFormatError("query_ko가 비어 있음")
            query_ko = q
            reason = str(data.get("reason", "")).strip()
            run.error = None
            break
        except (json.JSONDecodeError, SearchPlanFormatError) as e:
            run.error = f"형식 오류: {type(e).__name__}: {str(e)[:300]}"
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"출력 형식 오류입니다: {run.error}\nJSON만 다시 출력하세요."},
            ]

    run.latency_ms = int((time.perf_counter() - started) * 1000)

    if query_ko is None:
        # LLM이 끝내 검색어를 못 만들면, 슬롯 라벨로 최소한의 검색어를 만들어 진행한다.
        slot_def = cfg.DOC_SLOTS.get(slot.slot_id, {})
        query_ko = f"{analysis.intent_summary} {slot_def.get('label', slot.slot_id)}".strip()
        reason = "(서버 보완) LLM 검색어 생성 실패 → 슬롯 라벨로 대체"
        run.warnings.append(reason)

    # 4) 중복 검사
    is_dup = any(
        h.target_slot_id == slot.slot_id
        and h.search_type == search_type
        and _norm(h.query_ko) == _norm(query_ko)
        for h in history
    )
    if is_dup:
        run.warnings.append(f"[확인 필요] 검색어 '{query_ko}'가 {slot.slot_id}에 이미 시도됨 (중복)")

    run.plan = SearchPlan(
        action="search",
        target_slot_id=slot.slot_id,
        search_type=search_type,
        query_ko=query_ko,
        reason=reason,
        is_duplicate=is_dup,
    )
    return run
