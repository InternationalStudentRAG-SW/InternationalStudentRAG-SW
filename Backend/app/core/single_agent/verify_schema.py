"""
④ 충분성 검증의 입출력 구조.

LLM은 칸별 판정(SlotVerdict)과 '문서상 답이 갈리는 사용자 조건'(UserFieldNeed)만 돌려준다.
근거 ID·인용 대조, 상태 보정, 다음 행동 결정은 verifier.py의 서버 규칙이 한다.
구조가 맞는다고 판정 내용까지 옳다는 뜻은 아니다.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from app.core.single_agent.analysis_schema import EvidenceRef, QuestionAnalysis


class SlotVerdict(BaseModel):
    """LLM이 돌려준 문서 칸 1개의 판정."""
    slot_id: str
    status: str                              # supported / partial / missing / conflicting / not_applicable
    evidence_refs: List[EvidenceRef] = []
    value: str = ""
    missing_detail: str = ""
    activation_state: Optional[str] = None   # 조건부 칸만: triggered / unresolved / not_triggered
    reason: str = ""


class AppliesTo(BaseModel):
    """청크 규정의 적용 대상 하나 (사용자 칸 ID + 값)."""
    field_id: str
    value: str


class ChunkNote(BaseModel):
    """LLM이 보여준 청크마다 적는 메모. 갈래 감지·적용 범위 검사는 서버가 이 메모로 한다."""
    evidence_id: str
    applies_to: List[AppliesTo] = []    # 비어 있으면 대상 제한 없음 (모든 유학생)
    relevant_slots: List[str] = []      # 이 청크가 근거가 될 수 있는 문서 칸


class UserFieldNeed(BaseModel):
    """문서가 이 사용자 조건에 따라 답을 달리한다는 판정 (되묻기·조건별 안내의 근거)."""
    field_id: str
    evidence_ids: List[str] = []
    branches: List[str] = []   # 문서상 갈래 요약 (예: ["학위과정: 총장 승인 시 가능", "어학연수: 6개월 후 방학 중"])
    reason: str = ""


class VerifyOutput(BaseModel):
    """LLM 출력 전체."""
    chunk_notes: List[ChunkNote] = []
    slot_verdicts: List[SlotVerdict] = []
    user_field_needs: List[UserFieldNeed] = []


class VerifyDecision(BaseModel):
    """서버가 규칙으로 정한 다음 행동."""
    next_action: str   # checklist_config.VERIFY_ACTIONS
    reason: str = ""
    unresolved_slot_ids: List[str] = []   # 답변에 필요한데 아직 supported/not_applicable이 아닌 칸
    clarify_field_ids: List[str] = []     # ask_clarification일 때 물을 사용자 칸 (최대 MAX_CLARIFY_FIELDS)
    condition_field_ids: List[str] = []   # answer_by_condition일 때 갈래를 나눌 사용자 칸
    condition_branches: dict = {}         # {field_id: [문서상 갈래 요약]} (answer_by_condition·ask_clarification)
    expand_anchors: dict = {}             # continue_search일 때 partial 칸별 원문 확장 앵커 {slot_id: [evidence_id]}


class VerificationRun(BaseModel):
    """④ 1회 실행 기록. 실패해도 예외 대신 error에 이유를 담는다."""
    analysis: Optional[QuestionAnalysis] = None   # 칸 상태·근거가 갱신된 분석 (입력은 바꾸지 않음)
    decision: Optional[VerifyDecision] = None
    judged_slot_ids: List[str] = []    # 이번에 판정 대상이었던 칸
    shown_chunk_ids: List[str] = []    # 프롬프트에 넣은 청크
    llm_called: bool = False
    chunk_notes: List[ChunkNote] = []  # 서버 검증을 통과한 청크 메모
    recheck_slot_ids: List[str] = []   # 1-2 재판정 대상이었던 칸 (비었으면 재판정 안 함)
    warnings: List[str] = []
    error: Optional[str] = None
    model: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attempts: int = 0
    raw_output: str = ""              # 마지막 시도의 LLM 원문
    raw_outputs: List[str] = []        # 시도별 LLM 원문 (형식 오류로 재시도한 경우 확인용)
    checklist_version: str = ""
