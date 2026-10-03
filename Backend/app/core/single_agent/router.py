"""
⓪ 라우터: 질문을 요구 단위(ask)로 한 번에 나누고, 서버 규칙으로 경로를 정한다.

입력: 현재 질문 + 최근 대화
출력: RouteResult (asks, user_conditions, route = simple / agent, route_reasons)

흐름
  1. LLM(JSON 모드) 1회: 요구 단위·의존 관계·첫 검색어·사용자 조건을 뽑는다.
     형식이 틀리면 오류를 알려주고 1회 재시도한다 (llm.run_json_loop).
  2. 서버 검증(validate_route): 인용 대조, 의존 관계 정리, 개수 상한. 고친 내용은 warnings에.
  3. 경로 규칙(decide_route): LLM이 아니라 서버가 정한다. 걸린 규칙은 route_reasons에 남긴다.
  4. 어느 단계든 끝내 실패하면 cfg.ROUTER_FAIL_ROUTE(agent)로 보낸다. 복합 질문을 단순 경로로 놓치는 것보다
     단순 질문에 비용을 더 쓰는 쪽이 안전하다.

검색·답변은 하지 않는다. simple로 간 질문도 escalation.py가 검색 결과를 보고 agent로 올릴 수 있다.
"""
from __future__ import annotations

import json
import re
import time
from typing import Dict, List, Optional, Tuple

from app.core.single_agent import checklist_config as cfg
from app.core.single_agent.analyzer import number_messages
from app.core.single_agent.llm import get_client, model_for, run_json_loop
from app.core.single_agent.router_schema import RouteResult, RouteRun
from app.core.single_agent.text_match import quote_in_text

ROUTER_HISTORY_MESSAGES = 6   # 프롬프트에 넣을 최근 대화 수 (후속 질문의 맥락·사용자 조건 확인용)
ROUTER_MAX_TOKENS = 700

_REF_RE = re.compile(r"#(A\d+)")


class RouteFormatError(ValueError):
    """LLM 출력이 쓸 수 없을 만큼 틀렸을 때 (재시도 대상)."""


# ── 프롬프트 ─────────────────────────────────────────────────────────────

def _kind_catalog() -> str:
    return "\n".join(f"- {tid} {p['name']}: {p['answer_shape']}" for tid, p in cfg.PROFILES.items())


def _user_field_catalog() -> str:
    return ", ".join(f"{fid}({f['label']})" for fid, f in cfg.USER_FIELDS.items())


def _options(d: Dict[str, str]) -> str:
    return " / ".join(f"{k}({v})" for k, v in d.items())


SYSTEM_PROMPT_TEMPLATE = """당신은 동아대학교 유학생 생활·행정 안내 챗봇의 '질문 접수' 단계입니다.
질문에 답하지 않습니다. 사용자가 알고 싶은 것을 요구 단위로 나누고, 각 요구의 첫 검색어를 적습니다.
결과는 반드시 JSON 객체 하나로만 출력합니다.

## 답의 모양 (kind)
{kind_catalog}

## 사용자 조건 칸
{user_field_catalog}

## 규칙
[요구 단위 asks]
1. 사용자가 알고 싶은 것 하나가 ask 1개입니다. 답의 모양이 다르거나 따로 찾아야 하는 정보일 때만 나눕니다.
   예: "수업료랑 지원 기간 알려줘" → 2개 (수업료 / 지원 기간)
2. 같은 요구를 다르게 표현한 것은 나누지 않습니다. 예: "등록금 얼마예요? 금액이 궁금해요" → 1개
3. 한 서류·절차의 세부 항목은 하나로 묶습니다. 예: "어떤 서류를 어디에 내요?" → 1개 (서류와 제출처)
4. 최대 {max_asks}개입니다.
5. quote에는 현재 질문에서 그 요구에 해당하는 구절을 한 글자도 바꾸지 않고 옮깁니다. 이전 대화에서 인용하지 않습니다.
6. 후속 질문(예: 이전 대화가 기숙사 이야기일 때 "비용은요?")은 이전 대화를 반영해 text·query_ko를 완성합니다.
7. kind는 단어가 아니라 원하는 답의 모양으로 T1~T6 중 하나를 고릅니다.
8. text와 query_ko는 한국어로 씁니다. query_ko는 검색어이며 GKS, D-4, TOPIK 같은 공식 명칭·코드는 그대로 둡니다.

[의존 관계]
9. 뒤 요구가 필요한지, 무엇을 찾을지가 앞 요구의 답에 따라 달라지면 depends_on에 앞 요구의 ask_id를 적고
   only_if에 조건을 적습니다. 예: "아르바이트 해도 돼요? 된다면 어떤 서류를 내요?" → A2 depends_on ["A1"], only_if "A1이 허용일 때"
   이때 query_ko에서 앞 요구의 결과가 들어갈 자리는 #A1처럼 적을 수 있습니다.
10. 서로 상관없는 요구는 depends_on을 비웁니다.

[사용자 조건 user_conditions]
11. 위 사용자 조건 칸(목록에 없으면 비슷한 이름의 field_id를 새로 적음, 예: visa_status)에 해당하는 사실을 사용자가 자기 사례(user_self, 예: "저 GKS 장학생인데")나
    다른 사람의 사례(other_person, 예: "친구가 영어트랙인데")로 밝혔을 때만 적습니다.
    이전 대화의 사용자 메시지에서 밝힌 것도 포함하며, quote는 그 메시지에서 그대로 옮기고 source_message_id에 그 메시지 ID를 적습니다.
12. "GKS 장학생은 ~할 수 있어?"처럼 일반 대상을 묻는 것은 사용자 조건이 아닙니다. 언어·이름·말투로 국적 등을 추정하지 않습니다.
    이전 대화의 사용자 질문이 "GKS 장학생이 장학금 받는 기간이 얼마나 돼?"처럼 일반 규정을 물은 것이면 그것도 사용자 조건이 아닙니다.
    이전 대화에서 가져오는 조건은 사용자가 자기 상황을 직접 말한 경우로 한정하고, 현재 질문의 답에 영향을 줄 때만 적습니다.

[행동 action]
13. action: {actions}
14. out_of_scope는 동아대 유학생의 학교생활·행정(입학, 비자·체류, 장학금, 기숙사, 학사, 보험, 학교 생활 안내 등)과
    무관한 요청입니다. 예: 맛집·관광 추천, 연예, 날씨, 다른 대학 정보("서울대 장학금"처럼 동아대가 아닌 학교에 대한 질문 포함). clarify_scope보다 먼저 판단합니다.
15. clarify_scope는 무엇에 관한 요청인지 전혀 알 수 없을 때만 씁니다: 목적·대상 없이 명사만 던진 요청
    (예: "서류 알려줘", "절차 알려줘", "조건이 뭐야"). "입학 지원할 때 필요한 서류", "기숙사 신청 방법"처럼
    대상이 있으면 세부 조건이 빠져 보여도 search입니다. 세부 조건은 검색한 뒤에 확인합니다.
16. search가 아니면 asks는 빈 목록입니다.

## 출력 JSON 형식
{{"action": "search",
  "asks": [{{"ask_id": "A1", "text": "요구 요약", "quote": "질문 구절 그대로", "kind": "T5",
            "query_ko": "검색어", "depends_on": [], "only_if": ""}}],
  "user_conditions": [{{"field_id": "gks_status", "value": "예", "subject": "user_self",
                       "source_message_id": "m1", "quote": "저 GKS 장학생인데"}}],
  "reason": "한 줄 설명"}}

## 예시
질문: "저 GKS 장학생인데 아르바이트 해도 돼요? 된다면 어떤 서류를 어디에 내야 해요?"
{{"action": "search",
  "asks": [{{"ask_id": "A1", "text": "GKS 장학생 아르바이트 허용 여부", "quote": "아르바이트 해도 돼요", "kind": "T5",
            "query_ko": "GKS 장학생 시간제 취업 허용 기준", "depends_on": [], "only_if": ""}},
           {{"ask_id": "A2", "text": "아르바이트 신청 서류와 제출처", "quote": "어떤 서류를 어디에 내야 해요", "kind": "T3",
            "query_ko": "#A1 GKS 장학생 시간제 취업 신청 서류 제출처", "depends_on": ["A1"], "only_if": "A1이 허용일 때"}}],
  "user_conditions": [{{"field_id": "gks_status", "value": "예", "subject": "user_self",
                       "source_message_id": "m1", "quote": "저 GKS 장학생인데"}}],
  "reason": "허용 여부를 알아야 서류가 필요한지 정해짐"}}

질문: "GKS 장학생은 아르바이트할 수 있어?"
{{"action": "search",
  "asks": [{{"ask_id": "A1", "text": "GKS 장학생 아르바이트 허용 여부", "quote": "아르바이트할 수 있어", "kind": "T5",
            "query_ko": "GKS 장학생 시간제 취업 허용 기준", "depends_on": [], "only_if": ""}}],
  "user_conditions": [],
  "reason": "일반 대상(GKS 장학생)에 대한 단일 요구"}}"""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        kind_catalog=_kind_catalog(),
        user_field_catalog=_user_field_catalog(),
        max_asks=cfg.ROUTER_MAX_ASKS,
        actions=_options(cfg.ROUTER_ACTIONS),
    )


def build_user_prompt(numbered: List[Dict]) -> str:
    convo = "\n".join(f"[{m['id']}] {m['role']}: {m['content']}" for m in numbered[:-1]) or "(없음)"
    current = numbered[-1]
    return (
        f"## 이전 대화\n{convo}\n\n"
        f"## 현재 질문 [{current['id']}]\n{current['content']}\n\n"
        "위 규칙에 따라 JSON을 출력하세요."
    )


# ── 서버 검증 ─────────────────────────────────────────────────────────────

def validate_route(r: RouteResult, numbered: List[Dict]) -> Tuple[RouteResult, List[str]]:
    """
    LLM 출력을 검사·보정한다. 쓸 수 없는 출력은 RouteFormatError (재시도 대상).
      [수정] 값을 규칙에 맞게 바꿈  [제거] 걸러냄  [보완] 빠진 것을 채움
    """
    w: List[str] = []
    if r.action not in cfg.ROUTER_ACTIONS:
        raise RouteFormatError(f"action '{r.action}'은 허용되지 않음 ({', '.join(cfg.ROUTER_ACTIONS)})")

    current = numbered[-1]

    # 사용자 조건 (행동과 상관없이 검사: 사용자 메시지 인용만 인정)
    by_id = {m["id"]: m for m in numbered}
    conds = []
    for c in r.user_conditions:
        label = f"{c.field_id}={c.value!r}"
        msg = by_id.get(c.source_message_id)
        if not c.field_id.strip():
            w.append(f"[제거] 사용자 조건 {label}: 칸 이름 없음")
        elif c.subject not in cfg.ROUTER_CONDITION_SUBJECTS:
            w.append(f"[제거] 사용자 조건 {label}: subject '{c.subject}'는 본인·다른 사람 사례가 아님")
        elif msg is None or msg["role"] != "user":
            w.append(f"[제거] 사용자 조건 {label}: {c.source_message_id}가 없거나 사용자 메시지가 아님")
        elif not quote_in_text(c.quote, msg["content"], min_chars=2):
            w.append(f"[제거] 사용자 조건 {label}: 인용 '{c.quote}'이 {c.source_message_id}에 없음")
        else:
            if c.field_id not in cfg.USER_FIELDS:
                # 체크리스트에 없는 칸(예: 체류자격)이어도 '본인·다른 사람 사례'라는 사실은 경로 판단에 쓴다.
                # ①은 자기 검증에서 이 칸을 다시 걸러내므로 에이전트의 조건으로는 쓰이지 않는다.
                w.append(f"[확인 필요] 사용자 조건 {label}: 체크리스트에 없는 칸 → 경로 판단에만 사용")
            conds.append(c)
    r.user_conditions = conds

    if r.action != "search":
        if r.asks:
            w.append(f"[수정] {r.action}이므로 요구 단위를 비움")
        r.asks = []
        return r, w

    # 요구 단위: 인용 대조·중복 제거
    asks, seen_ids = [], set()
    for a in r.asks:
        if a.ask_id in seen_ids:
            w.append(f"[제거] 요구 {a.ask_id}: ID 중복")
            continue
        if not quote_in_text(a.quote, current["content"], min_chars=2):
            w.append(f"[제거] 요구 {a.ask_id}: 인용 '{a.quote}'이 현재 질문에 없음 (지어낸 요구 의심)")
            continue
        if a.kind is not None and a.kind not in cfg.PROFILES:
            w.append(f"[수정] 요구 {a.ask_id}: kind '{a.kind}'은 T1~T6이 아님 → 비움")
            a.kind = None
        if not a.query_ko.strip():
            w.append(f"[보완] 요구 {a.ask_id}: 검색어가 없어 요약(text)으로 채움")
            a.query_ko = a.text
        seen_ids.add(a.ask_id)
        asks.append(a)

    if not asks:
        raise RouteFormatError("search인데 현재 질문에서 인용을 확인할 수 있는 요구(asks)가 없음. "
                               "quote에는 현재 질문의 구절을 그대로 옮기세요.")
    if len(asks) > cfg.ROUTER_MAX_ASKS:
        w.append(f"[제거] 요구 {[a.ask_id for a in asks[cfg.ROUTER_MAX_ASKS:]]}: 최대 {cfg.ROUTER_MAX_ASKS}개 초과")
        asks = asks[:cfg.ROUTER_MAX_ASKS]

    # 의존 관계: 앞에 있는 요구만 가리킬 수 있다 (순서로 순환을 막는다)
    earlier: List[str] = []
    for a in asks:
        deps = []
        for d in a.depends_on:
            if d in earlier and d not in deps:
                deps.append(d)
            else:
                w.append(f"[제거] 요구 {a.ask_id}의 의존 '{d}': 앞에 있는 요구가 아님")
        for ref in _REF_RE.findall(a.query_ko):
            if ref in earlier and ref not in deps:
                deps.append(ref)
                w.append(f"[보완] 요구 {a.ask_id}: 검색어가 #{ref}를 참조하므로 의존 추가")
            elif ref not in earlier:
                a.query_ko = a.query_ko.replace(f"#{ref}", "").strip()
                w.append(f"[수정] 요구 {a.ask_id}: 앞에 없는 #{ref} 참조를 검색어에서 뺌")
        a.depends_on = deps
        if not deps and a.only_if:
            w.append(f"[수정] 요구 {a.ask_id}: 의존이 없으므로 only_if 비움")
            a.only_if = ""
        earlier.append(a.ask_id)
    r.asks = asks
    return r, w


# ── 경로 규칙 ─────────────────────────────────────────────────────────────

def decide_route(r: RouteResult) -> RouteResult:
    """검증된 RouteResult에 route·route_reasons를 채운다 (서버 규칙, LLM 없음)."""
    reasons: List[str] = []
    if r.action in cfg.ROUTER_SIMPLE_ACTIONS:
        r.route, r.route_reasons = "simple", [f"{r.action}: 기존 경로의 안내로 충분"]
        return r
    if r.action in cfg.ROUTER_AGENT_ACTIONS:
        r.route, r.route_reasons = "agent", [f"{r.action}: ①의 범위 되묻기 사용"]
        return r

    if len(r.asks) >= 2:
        reasons.append(f"요구 {len(r.asks)}개 ({', '.join(a.text for a in r.asks)})")
    deps = [a for a in r.asks if a.depends_on]
    if deps:
        reasons.append("의존 관계 " + ", ".join(f"{a.ask_id}←{'/'.join(a.depends_on)}" for a in deps))
    conds = ", ".join(f"{c.subject}:{c.quote}" for c in r.user_conditions)
    if len(r.user_conditions) >= cfg.ROUTER_MIN_CONDITIONS_FOR_AGENT:
        reasons.append(f"사용자 조건 {len(r.user_conditions)}개 ({conds})")
    kinds = sorted({a.kind for a in r.asks if a.kind in cfg.ROUTER_AGENT_KINDS})
    if kinds:
        reasons.append(f"에이전트 유형 {kinds}")

    if reasons:
        r.route, r.route_reasons = "agent", reasons
    else:
        note = f"사용자 조건 {len(r.user_conditions)}개({conds})는 기존 경로로 충분" if r.user_conditions else "의존·사용자 조건 없음"
        r.route, r.route_reasons = "simple", [f"단일 요구, {note}"]
    return r


def fallback_result(reason: str) -> RouteResult:
    return RouteResult(action="search", route=cfg.ROUTER_FAIL_ROUTE,
                       route_reasons=[f"라우터 실패 → 안전하게 {cfg.ROUTER_FAIL_ROUTE} ({reason})"])


# ── LLM 호출 ─────────────────────────────────────────────────────────────

def route_question(
    question: str,
    history: Optional[List[Dict]] = None,
    model: Optional[str] = None,
    client=None,
) -> RouteRun:
    """
    질문 하나의 경로를 정한다. 실패해도 예외 대신 fallback 경로(agent)를 담아 돌려준다.
    client: 테스트용으로 OpenAI 클라이언트를 바꿔 끼울 때 사용.
    """
    model = model or model_for("route")
    run = RouteRun(question=question, history=list(history or []), model=model,
                   checklist_version=cfg.CHECKLIST_VERSION)
    started = time.perf_counter()
    try:
        client = client or get_client()
        numbered = number_messages(question, list(history or [])[-ROUTER_HISTORY_MESSAGES:])
        messages = [
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": build_user_prompt(numbered)},
        ]
        value, ok = run_json_loop(
            run, client, model, messages,
            parse=lambda raw: validate_route(RouteResult.model_validate(json.loads(raw)), numbered),
            temperature=0, max_tokens=ROUTER_MAX_TOKENS,
            format_hint="규칙과 JSON 형식을 지켜 JSON만 다시 출력하세요.",
            purpose="route",
        )
        if ok:
            result, w = value
            run.warnings += w
            run.result = decide_route(result)
    except Exception as e:  # 클라이언트 생성 실패 등: 라우터 때문에 답변이 막히면 안 된다
        run.error = f"{type(e).__name__}: {e}"

    if run.result is None:
        run.fallback_used = True
        run.result = fallback_result(run.error or "알 수 없는 오류")
    run.latency_ms = int((time.perf_counter() - started) * 1000)
    return run
