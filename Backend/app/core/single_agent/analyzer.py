"""
① 질문 분석.

입력: 현재 질문 + 대화 기록
출력: 질문 유형(대표·추가), 사례 조건, 이번 질문의 문서 칸·사용자 칸, 첫 검색어, 다음 행동

흐름
  1. 체크리스트 설정으로 프롬프트를 만든다 (유형 요약 + 칸 ID 목록).
  2. LLM을 JSON 모드로 1회 호출한다. 형식이 틀리면 오류를 알려주고 1회 재시도한다 (llm.py).
  3. 서버 검증: 칸 ID·선택지 확인, 필수도 하향 복구, 인용 문구 대조, ① 단계 상태 강제.
     고친 내용은 warnings에 남긴다.

검색·답변은 하지 않는다. 문서 칸은 이 단계에서 항상 unchecked다.
"""
from __future__ import annotations

import json
import time
from typing import Dict, List, Optional, Tuple

from app.core.single_agent import checklist_config as cfg
from app.core.single_agent.llm import get_client, model_for, run_json_loop
from app.core.single_agent.text_match import quote_in_text
from app.core.single_agent.analysis_schema import (
    AnalysisRun,
    DocSlot,
    QuestionAnalysis,
)

MAX_HISTORY_MESSAGES = 10  # 프롬프트에 넣을 최근 대화 수

_REQ_RANK = {"required": 2, "conditional": 1, "optional": 0}


class AnalysisFormatError(ValueError):
    """LLM 출력이 다음 단계로 넘길 수 없을 만큼 틀렸을 때 (재시도 대상)."""


# ── 프롬프트 ─────────────────────────────────────────────────────────────

def _type_catalog() -> str:
    lines = []
    for tid, p in cfg.PROFILES.items():
        slots = ", ".join(
            f"{sid}({cfg.DOC_SLOTS[sid]['label']}·{cfg.REQUIREMENTS[req]})"
            for sid, req in p["doc_slots"]
        )
        lines.append(
            f"- {tid} {p['name']}: {p['answer_shape']}\n"
            f"  예시: {' / '.join(p['examples'])}\n"
            f"  문서 칸: {slots}\n"
            f"  사용자 칸 후보: {', '.join(p['user_field_candidates'])}"
        )
    return "\n".join(lines)


def _user_field_catalog() -> str:
    return "\n".join(
        f"- {fid}({f['label']}): 값 {f['values']} | 필요한 때: {f['activation']}"
        for fid, f in cfg.USER_FIELDS.items()
    )


def _options(d: Dict[str, str]) -> str:
    return " / ".join(f"{k}({v})" for k, v in d.items())


SYSTEM_PROMPT_TEMPLATE = """당신은 동아대학교 유학생 생활·행정 안내 챗봇의 '질문 분석' 단계입니다.
질문에 답하지 않습니다. 검색 전에, 이 질문에 답하려면 무엇을 확인해야 하는지 구조화합니다.
결과는 반드시 JSON 객체 하나로만 출력합니다.

## 질문 유형 (답의 모양 기준)
{type_catalog}

## 사용자 칸 후보
{user_field_catalog}

## 규칙
[유형]
1. 단어가 아니라 사용자가 원하는 답의 모양으로 고릅니다. 예: "결핵 증명서는 언제 내?"는 T1(기한 값)이며, '증명서'라는 단어 때문에 T3 전체 서류 목록을 요구하지 않습니다.
2. 대표 유형 1개를 고르고, 한 질문에 다른 모양의 요구가 더 있으면 additional_types에 넣습니다. 예: "아르바이트 가능해? 어떤 서류를 어디에 내?" → 대표 T5, 추가 T3·T4. 이때 "어디에 내?"까지 명시적으로 물었으므로 T3의 submission_method 칸도 active=true, requirement=required로 올립니다(제출처를 묻지 않았다면 기본값을 따릅니다).
3. 단순 질문을 억지로 쪼개지 않습니다.

[문서 칸]
4. 대표·추가 유형에 속한 칸만 사용하되, 그 유형들의 칸을 하나도 빠짐없이 모두 document_slots에 적습니다(비활성으로 둘 칸도 active=false로 적음). 칸마다 active, requirement, activation_reason을 적습니다.
5. 필수도: {requirements}
   - 사용자가 명시적으로 요구한 정보는 required로 올립니다. (예: "언제 어디에 내?" → 기한·제출처 required)
   - 제출처·제출방법을 명시적으로 물으면("어디에 내?", "어떻게 제출해?") submission_method가 존재하는 유형에서는 그 칸을 active=true, required로 올립니다. 기본값이 optional/비활성이어도 이 경우에는 올립니다.
   - 유형의 기본 필수도보다 낮추지 않습니다.
   - conditional 칸에는 activation_state를 적습니다: {activation_states}
     질문이 명시적으로 요구하면 triggered, 그 밖에는 모두 unresolved(active=true 유지)입니다.
     not_triggered는 문서 근거가 있어야 정할 수 있으므로 이 단계에서는 쓰지 않습니다(④가 문서를 보고 정함).
   - optional 칸은 질문 해결에 도움이 될 때만 active=true.
6. status는 모두 "unchecked"입니다. 규정 내용·수치·가능 여부를 추측해 적지 않습니다.

[사례 조건]
7. conditions에는 사용자(user) 메시지에 명시된 조건만 넣습니다. quote에는 그 메시지의 구절을 한 글자도 바꾸지 않고 그대로 옮깁니다. 어시스턴트 메시지는 조건의 근거가 아닙니다.
8. subject 구분: {subjects}
   - "GKS 장학생은 ~할 수 있어?" → question_target (사용자 본인이 장학생이라는 증거 아님)
   - "저 GKS 장학생인데 ~" → user_self
   - "친구가 GKS 장학생인데 ~" → other_person
9. 질문 언어·이름·말투로 국적, 체류자격, GKS 여부 등을 추정하지 않습니다. 명확한 정정 발언이 있으면 최신 값을 씁니다.
10. answer_scope: {answer_scopes}
   - conditions에 user_self 조건이 있으면 personal, other_person 조건만 있으면 third_party입니다.

[사용자 칸]
11. 대표·추가 유형의 사용자 칸 후보 중 이 질문과 관련 있는 것만 적습니다. conditions에 있으면 confirmed, 없으면 unknown.
12. 이 단계에서는 문서 근거가 없으므로 unknown 칸을 active=true로 만들지 않고 required_by_evidence는 빈 목록입니다. 되묻기는 검색 후 문서가 조건에 따라 답이 갈린다고 확인될 때만 합니다.

[다음 행동]
13. next_action: {actions}
14. 개인 조건이 없어도 일반 안내가 가능하면 search입니다. 개인 조건이 없다는 이유로 되묻지 않습니다.
15. clarify_scope는 요청 대상 자체가 불분명해 첫 검색어를 정할 수 없을 때만 씁니다. 판별 기준: 질문에 목적어·맥락(무엇을 위해서, 어떤 상황에서)이 전혀 없이 명사 하나만 던지는 요청이면(예: "서류 알려줘", "절차 알려줘", "조건이 뭐야") 대표 유형조차 정하지 말고(primary_type: null) clarify_scope로 갑니다. "입학 지원할 때 필요한 서류"처럼 목적이 이미 문장에 있으면 clarify하지 않고 search로 갑니다.
   - 절대 하지 말 것: "서류 알려줘"를 보고 가장 흔해 보이는 목적(예: 입학 지원 서류)을 임의로 짐작해 그 유형으로 검색하는 것. 실제로 수업료 서류일 수도, 아르바이트 서류일 수도, 비자 서류일 수도 있으므로 짐작이 아니라 반드시 되묻습니다.
   - clarification_question은 요청 대상만 좁히는 짧은 질문이며, 사용자의 질문 언어로 씁니다.
16. search이면 first_search에 첫 검색어 1개를 적습니다. 한국어로 쓰고 GKS, D-4, TOPIK 같은 공식 명칭·코드는 그대로 둡니다. 가장 먼저 확인할 필수 칸을 target_slot_ids에 적습니다(active인 문서 칸만). 확인된 조건은 검색어에 반영할 수 있습니다.

## 출력 JSON 형식
{{
  "intent_summary": "질문 의도 한 줄 (한국어)",
  "answer_scope": "general",
  "primary_type": "T5",
  "additional_types": [],
  "type_reason": "유형을 고른 이유",
  "conditions": [
    {{"field_id": "gks_status", "value": "예", "subject": "question_target", "status": "confirmed",
      "source_message_id": "m1", "quote": "GKS 장학생은"}}
  ],
  "document_slots": [
    {{"slot_id": "rule", "active": true, "requirement": "required", "activation_state": null,
      "activation_reason": "허용 여부의 기본 규정 필요", "status": "unchecked"}},
    {{"slot_id": "approval_reporting", "active": true, "requirement": "conditional", "activation_state": "unresolved",
      "activation_reason": "승인이 허용의 전제인지 문서 확인 필요", "status": "unchecked"}}
  ],
  "user_slots": [
    {{"field_id": "gks_stage", "status": "unknown", "active": false, "reason": "단계별 규정 차이 여부는 검색 후 판단",
      "required_by_evidence": []}}
  ],
  "first_search": {{"query_ko": "GKS 장학생 시간제 취업 허용 기준", "target_slot_ids": ["rule", "applicable_scope"],
    "reason": "허용 원칙과 적용 범위부터 확인"}},
  "next_action": "search",
  "next_action_reason": "일반 규정으로 먼저 안내 가능",
  "clarification_question": null
}}

## clarify_scope 출력 예시 (질문: "서류 알려줘" — 목적·맥락 없음)
{{
  "intent_summary": "서류를 알려달라는 요청이나 어떤 목적의 서류인지 불명확",
  "answer_scope": "general",
  "primary_type": null,
  "additional_types": [],
  "type_reason": "목적·맥락이 없어 유형을 정할 수 없음. 입학 지원 서류 등으로 짐작하지 않음",
  "conditions": [],
  "document_slots": [],
  "user_slots": [],
  "first_search": null,
  "next_action": "clarify_scope",
  "next_action_reason": "어떤 서류인지(입학 지원, 아르바이트, 비자 등) 알아야 검색어를 정할 수 있음",
  "clarification_question": "어떤 것에 필요한 서류를 말씀하시는 건가요? (예: 입학 지원, 아르바이트, 비자 신청 등)"
}}
clarify_scope, out_of_scope, no_retrieval이면 primary_type은 null, document_slots·user_slots는 빈 목록, first_search는 null입니다."""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        type_catalog=_type_catalog(),
        user_field_catalog=_user_field_catalog(),
        requirements=_options(cfg.REQUIREMENTS),
        activation_states=_options(cfg.ACTIVATION_STATES),
        subjects=_options(cfg.CONDITION_SUBJECTS),
        answer_scopes=_options(cfg.ANSWER_SCOPES),
        actions=_options(cfg.ANALYSIS_ACTIONS),
    )


def number_messages(question: str, history: Optional[List[Dict]]) -> List[Dict]:
    """대화 기록 + 현재 질문에 m1, m2 ... ID를 붙인다. 현재 질문이 마지막."""
    recent = list(history or [])[-MAX_HISTORY_MESSAGES:]
    numbered = []
    for i, h in enumerate(recent, 1):
        role = "user" if h.get("role") == "user" else "assistant"
        numbered.append({"id": f"m{i}", "role": role, "content": str(h.get("content", ""))})
    numbered.append({"id": f"m{len(recent) + 1}", "role": "user", "content": question})
    return numbered


def build_user_prompt(numbered: List[Dict]) -> str:
    convo = "\n".join(f"[{m['id']}] {m['role']}: {m['content']}" for m in numbered[:-1]) or "(없음)"
    current = numbered[-1]
    return (
        f"## 이전 대화\n{convo}\n\n"
        f"## 현재 질문 [{current['id']}]\n{current['content']}\n\n"
        "위 규칙에 따라 분석 JSON을 출력하세요."
    )


# ── 서버 검증 ─────────────────────────────────────────────────────────────

def validate_analysis(a: QuestionAnalysis, numbered: List[Dict]) -> Tuple[QuestionAnalysis, List[str]]:
    """
    LLM 출력을 체크리스트 규칙에 맞게 검사·보정한다.
    다음 단계로 넘길 수 없는 오류는 AnalysisFormatError (재시도 대상).
    고친 내용은 warnings로 돌려준다.
      [수정] 값을 규칙에 맞게 바꿈  [제거] 걸러냄  [보완] 빠진 것을 채움  [확인 필요] 그대로 두었지만 볼 만함
    """
    w: List[str] = []

    # 다음 행동
    if a.next_action not in cfg.ANALYSIS_ACTIONS:
        raise AnalysisFormatError(f"next_action '{a.next_action}'은 허용되지 않음")
    if a.answer_scope not in cfg.ANSWER_SCOPES:
        w.append(f"[수정] answer_scope '{a.answer_scope}' → general")
        a.answer_scope = "general"

    # search가 아닌 행동(clarify_scope 포함)은 유형·칸·첫 검색을 갖지 않는다.
    # clarify_scope는 프롬프트가 primary_type=null을 요구하므로 유형 검사를 하면 안 된다.
    no_search = a.next_action != "search"

    # 유형
    if no_search:
        if a.primary_type or a.additional_types or a.document_slots or a.user_slots or a.first_search:
            w.append(f"[수정] {a.next_action}이므로 유형·문서 칸·사용자 칸·첫 검색을 비움")
        a.primary_type, a.additional_types = None, []
        a.document_slots, a.user_slots, a.first_search = [], [], None
    else:
        if a.primary_type not in cfg.PROFILES:
            raise AnalysisFormatError(f"primary_type '{a.primary_type}'은 T1~T6이 아님")
        extra = []
        for t in a.additional_types:
            if t not in cfg.PROFILES:
                w.append(f"[제거] 추가 유형 '{t}' (T1~T6 아님)")
            elif t != a.primary_type and t not in extra:
                extra.append(t)
        a.additional_types = extra

    types = [a.primary_type] + a.additional_types if a.primary_type else []
    allowed = cfg.slots_for_types(types)

    # 문서 칸
    seen = {}
    for s in a.document_slots:
        if s.slot_id not in allowed:
            w.append(f"[제거] 문서 칸 '{s.slot_id}' (선택한 유형 {types}에 없음)")
            continue
        if s.slot_id in seen:
            w.append(f"[제거] 문서 칸 '{s.slot_id}' 중복")
            continue
        default = allowed[s.slot_id]
        if s.requirement not in cfg.REQUIREMENTS:
            w.append(f"[수정] {s.slot_id} 필수도 '{s.requirement}' → 기본값 {default}")
            s.requirement = default
        elif _REQ_RANK[s.requirement] < _REQ_RANK[default]:
            w.append(f"[수정] {s.slot_id} 필수도를 {s.requirement}로 낮춤 → 기본값 {default} 복구")
            s.requirement = default

        if s.requirement == "conditional":
            if s.activation_state not in cfg.ACTIVATION_STATES:
                w.append(f"[수정] {s.slot_id} activation_state '{s.activation_state}' → unresolved")
                s.activation_state = "unresolved"
            if s.activation_state in ("triggered", "unresolved") and not s.active:
                w.append(f"[수정] {s.slot_id}: 발동 {s.activation_state}인데 비활성 → 활성 (임의 비활성화 금지)")
                s.active = True
            if s.activation_state == "not_triggered":
                # ①은 문서를 보기 전이라 '문서상 발동 안 함'을 정할 근거가 없다. 꺼 버리면 ④가 다시 볼 수 없다.
                w.append(f"[수정] {s.slot_id}: ①은 문서 근거가 없어 not_triggered 불가 → unresolved(활성) (④가 문서로 판단)")
                s.activation_state = "unresolved"
                s.active = True
        else:
            s.activation_state = None

        if s.requirement == "required" and not s.active:
            if s.activation_reason.strip():
                w.append(f"[확인 필요] 필수 칸 {s.slot_id} 비활성: {s.activation_reason}")
            else:
                w.append(f"[수정] 필수 칸 {s.slot_id}를 이유 없이 비활성 → 활성")
                s.active = True

        if s.status != "unchecked":
            w.append(f"[수정] {s.slot_id} status '{s.status}' → unchecked (① 단계는 검색 전)")
            s.status = "unchecked"
        seen[s.slot_id] = s

    for slot_id, default in allowed.items():
        if slot_id in seen:
            continue
        active = default != "optional"
        seen[slot_id] = DocSlot(
            slot_id=slot_id,
            active=active,
            requirement=default,
            activation_state="unresolved" if default == "conditional" else None,
            activation_reason="(서버 보완) 분석 결과에 없어 기본값으로 추가",
        )
        w.append(f"[보완] 문서 칸 {slot_id} 누락 → 기본값({default}, {'활성' if active else '비활성'})")

    order = list(allowed.keys())
    a.document_slots = sorted(seen.values(), key=lambda s: order.index(s.slot_id))

    # 사례 조건: 사용자 메시지 인용 대조
    by_id = {m["id"]: m for m in numbered}
    kept = []
    for c in a.conditions:
        msg = by_id.get(c.source_message_id)
        label = f"{c.field_id}={c.value!r}"
        if c.field_id not in cfg.USER_FIELDS:
            w.append(f"[제거] 조건 {label}: 정의되지 않은 칸")
        elif c.subject not in cfg.CONDITION_SUBJECTS:
            w.append(f"[제거] 조건 {label}: subject '{c.subject}' 잘못됨")
        elif msg is None or msg["role"] != "user":
            w.append(f"[제거] 조건 {label}: {c.source_message_id}가 없거나 사용자 메시지가 아님")
        elif not quote_in_text(c.quote, msg["content"]):
            w.append(f"[제거] 조건 {label}: 인용 '{c.quote}'이 {c.source_message_id}에 없음 (추정 의심)")
        elif not c.value.strip():
            w.append(f"[제거] 조건 {c.field_id}: 값 없음")
        else:
            if c.status not in cfg.CONDITION_STATUSES:
                w.append(f"[수정] 조건 {label} status '{c.status}' → ambiguous")
                c.status = "ambiguous"
            kept.append(c)
    a.conditions = kept
    confirmed_fields = {c.field_id for c in kept if c.status == "confirmed"}

    # 답변 범위: 조건의 subject와 어긋나면 조건 쪽을 따른다 (general일 때만 올림)
    subjects = {c.subject for c in kept}
    if a.answer_scope == "general":
        if "user_self" in subjects:
            w.append("[수정] answer_scope general → personal (사용자 본인 조건 user_self가 있음)")
            a.answer_scope = "personal"
        elif "other_person" in subjects:
            w.append("[수정] answer_scope general → third_party (다른 사람 조건 other_person만 있음)")
            a.answer_scope = "third_party"

    # 사용자 칸
    users, seen_fields = [], set()
    for u in a.user_slots:
        if u.field_id not in cfg.USER_FIELDS:
            w.append(f"[제거] 사용자 칸 '{u.field_id}' (정의되지 않음)")
            continue
        if u.field_id in seen_fields:
            continue
        seen_fields.add(u.field_id)
        if u.status not in cfg.USER_SLOT_STATUSES:
            w.append(f"[수정] 사용자 칸 {u.field_id} status '{u.status}' → unknown")
            u.status = "unknown"
        if u.status == "confirmed" and u.field_id not in confirmed_fields:
            w.append(f"[수정] 사용자 칸 {u.field_id}: 인용된 조건이 없는데 confirmed → unknown")
            u.status = "unknown"
        if u.status == "unknown" and u.field_id in confirmed_fields:
            w.append(f"[수정] 사용자 칸 {u.field_id}: 조건이 확인됐으므로 unknown → confirmed")
            u.status = "confirmed"
        if u.required_by_evidence:
            w.append(f"[수정] 사용자 칸 {u.field_id}: ① 단계에는 문서 근거가 없으므로 required_by_evidence 비움")
            u.required_by_evidence = []
        if u.active and u.status != "confirmed":
            w.append(f"[수정] 사용자 칸 {u.field_id}: 문서 근거 전이라 되묻기 대상으로 활성화하지 않음")
            u.active = False
        users.append(u)
    a.user_slots = users

    # 첫 검색 / 되묻기
    active_slots = {s.slot_id for s in a.document_slots if s.active}
    if a.next_action == "search":
        if not a.first_search or not a.first_search.query_ko.strip():
            raise AnalysisFormatError("next_action이 search인데 first_search.query_ko가 없음")
        targets = []
        for sid in a.first_search.target_slot_ids:
            if sid in active_slots:
                targets.append(sid)
            else:
                w.append(f"[제거] 첫 검색 대상 칸 '{sid}' (활성 문서 칸 아님)")
        if not targets:
            targets = [s.slot_id for s in a.document_slots if s.active and s.requirement == "required"]
            w.append(f"[보완] 첫 검색 대상 칸이 없어 활성 필수 칸으로 채움: {targets}")
        a.first_search.target_slot_ids = targets
        a.clarification_question = None
    elif a.next_action == "clarify_scope":
        if not (a.clarification_question or "").strip():
            raise AnalysisFormatError("next_action이 clarify_scope인데 clarification_question이 없음")
        a.first_search = None

    return a, w


# ── LLM 호출 ─────────────────────────────────────────────────────────────

def analyze_question(
    question: str,
    history: Optional[List[Dict]] = None,
    model: Optional[str] = None,
    client=None,
) -> AnalysisRun:
    """
    질문 하나를 분석한다. 실패해도 예외 대신 AnalysisRun.error에 이유를 담아 돌려준다.
    client: 테스트용으로 OpenAI 클라이언트를 바꿔 끼울 때 사용.
    """
    model = model or model_for("analyze")
    client = client or get_client()

    numbered = number_messages(question, history)
    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": build_user_prompt(numbered)},
    ]
    run = AnalysisRun(
        question=question,
        history=list(history or []),
        model=model,
        checklist_version=cfg.CHECKLIST_VERSION,
    )

    started = time.perf_counter()
    value, ok = run_json_loop(
        run, client, model, messages,
        parse=lambda raw: validate_analysis(QuestionAnalysis.model_validate(json.loads(raw)), numbered),
        temperature=0, max_tokens=2000,
        format_hint="규칙과 JSON 형식을 지켜 JSON만 다시 출력하세요.",
    )
    if ok:
        run.analysis, w = value
        run.warnings += w

    run.latency_ms = int((time.perf_counter() - started) * 1000)
    return run
