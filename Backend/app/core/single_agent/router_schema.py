"""
⓪ 라우터의 출력 구조.

라우터는 질문을 '요구 단위(ask)'로 한 번에 나누고, 서버 규칙(router.decide_route)이
그 결과로 경로(simple: 기존 하이브리드+리랭커 / agent: 단일 에이전트)를 정한다.
LLM은 경로를 정하지 않는다. route·route_reasons는 서버가 채운다.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.core.single_agent.metrics import LLMMetrics


class Ask(BaseModel):
    """사용자가 알고 싶은 것 하나. 답의 모양이 다르면 다른 ask다."""
    ask_id: str                              # "A1", "A2" ...
    text: str                                # 요구 요약 (한국어)
    quote: str = Field(description="현재 질문에서 그대로 옮긴 구절 (서버가 대조)")
    kind: Optional[str] = None               # T1~T6 (답의 모양). 잘못된 값이면 서버가 None으로 둔다
    query_ko: str = ""                       # 이 요구의 첫 검색어 (한국어). 의존이면 "#A1" 참조 가능
    query_en: str = ""                       # 같은 뜻의 영어 검색어 (영어로만 된 문서용, 2026-10-03)
    depends_on: List[str] = []               # 이 요구보다 앞에 있는 ask_id만 허용
    only_if: str = ""                        # 앞 요구 결과가 이럴 때만 필요 (예: "A1이 허용일 때")


class RouteCondition(BaseModel):
    """질문 사례의 사용자 조건. 본인(user_self)·다른 사람(other_person) 사례만 해당한다."""
    field_id: str
    value: str = ""
    subject: str                             # user_self / other_person
    source_message_id: str                   # m1, m2 ... (사용자 메시지만)
    quote: str


class RouteResult(BaseModel):
    action: str                              # search / clarify_scope / out_of_scope / no_retrieval
    asks: List[Ask] = []
    user_conditions: List[RouteCondition] = []
    reason: str = ""                         # LLM이 적은 한 줄 설명 (판단에는 쓰지 않음)
    # 서버가 채움
    route: Optional[str] = None              # simple / agent
    route_reasons: List[str] = []


class RouteRun(LLMMetrics):
    """라우터 1회 실행 기록 (확인 스크립트·로그용)."""
    question: str
    history: List[dict] = []
    result: Optional[RouteResult] = None
    fallback_used: bool = False              # 라우터가 실패해서 안전하게 agent로 보냈는지
    warnings: List[str] = []
    error: Optional[str] = None
    model: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attempts: int = 0
    raw_output: str = ""
    checklist_version: str = ""
