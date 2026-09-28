"""
① 질문 분석의 출력 구조.

LLM이 돌려준 JSON을 이 모델로 읽은 뒤, analyzer.py의 서버 검증이
칸 ID·선택지·인용 문구를 한 번 더 확인한다.
구조가 맞는다고 판정 내용까지 옳다는 뜻은 아니다.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Condition(BaseModel):
    """대화에서 확인된 사례 조건. 반드시 사용자 발언을 그대로 인용해야 한다."""
    field_id: str
    value: str
    subject: str = Field(description="user_self / question_target / other_person")
    status: str = "confirmed"
    source_message_id: str
    quote: str = Field(description="해당 메시지에서 그대로 옮긴 구절")


class DocSlot(BaseModel):
    """이번 질문에 대한 문서 칸. ① 단계에서는 status가 항상 unchecked."""
    slot_id: str
    active: bool
    requirement: str = Field(description="required / conditional / optional")
    activation_state: Optional[str] = None  # 조건부 필수일 때만: triggered / unresolved / not_triggered
    activation_reason: str = ""
    status: str = "unchecked"


class UserSlot(BaseModel):
    """사용자 칸 후보. 문서 근거 없이 되묻기 대상으로 활성화하지 않는다."""
    field_id: str
    status: str = Field(description="confirmed / unknown / ambiguous / not_required")
    active: bool = False
    reason: str = ""
    required_by_evidence: List[str] = []


class FirstSearch(BaseModel):
    """순차 루프의 첫 번째 하위 질문 (한 바퀴에 하나)."""
    query_ko: str
    target_slot_ids: List[str] = []
    reason: str = ""


class QuestionAnalysis(BaseModel):
    intent_summary: str
    answer_scope: str
    primary_type: Optional[str] = None
    additional_types: List[str] = []
    type_reason: str = ""
    conditions: List[Condition] = []
    document_slots: List[DocSlot] = []
    user_slots: List[UserSlot] = []
    first_search: Optional[FirstSearch] = None
    next_action: str
    next_action_reason: str = ""
    clarification_question: Optional[str] = None


class AnalysisRun(BaseModel):
    """분석 1회 실행 기록 (확인 스크립트·로그용)."""
    question: str
    history: List[dict] = []
    analysis: Optional[QuestionAnalysis] = None
    warnings: List[str] = []   # 서버 검증에서 고치거나 걸러낸 내용
    error: Optional[str] = None
    model: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attempts: int = 0
    raw_output: str = ""
    checklist_version: str = ""
