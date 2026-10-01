"""
② 검색 계획의 입출력 구조.

슬롯 선택은 규칙 기반(서버)이고, LLM은 선택된 슬롯 하나에 대한
자연어 검색어 문구만 만든다. 그래서 이 단계의 출력은 항상
"검색 액션 1개"이며, 여러 개를 한 번에 계획하지 않는다.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel
from app.core.single_agent.metrics import LLMMetrics


class SearchAttempt(BaseModel):
    """이미 실행한 검색 1건의 기록 (중복 검색 방지·예산 계산용)."""
    target_slot_id: str
    search_type: str  # "new" / "expand_context"
    query_ko: str
    found_new_evidence: bool = False


class SearchBudget(BaseModel):
    """예산 사용 현황. 서버가 강제하며 LLM 판단으로 늘리지 않는다."""
    total_calls: int = 0     # 신규 검색 + 원문 확장 합계
    expand_calls: int = 0    # 원문 확장만
    subqueries: int = 0      # 신규 검색(하위 질문)만


class SearchPlan(BaseModel):
    """② 검색 계획의 출력. 한 바퀴에 검색 액션 1개."""
    action: str  # "search" / "budget_exhausted" / "no_target_left"
    target_slot_id: Optional[str] = None
    search_type: Optional[str] = None  # "new" / "expand_context"
    query_ko: Optional[str] = None
    reason: str = ""
    is_duplicate: bool = False  # 중복이면 실행하지 않으므로 action=search일 때는 항상 False
    from_first_search: bool = False  # 첫 바퀴에 ①의 first_search를 그대로 썼는지
    # 이번 계획에서 칸별 시도 상한에 걸려 더 검색하지 않기로 한 칸. status는 바꾸지 않는다
    # (missing·partial 유지 → ④·⑤가 부분 답변으로 처리). 체크리스트 2.1절.
    exhausted_slot_ids: List[str] = []
    # 후보였지만 이번 바퀴에 건너뛴 칸과 이유 (예산·상한·중복)
    skipped: List[str] = []


class SearchPlanRun(LLMMetrics):
    """검색 계획 1회 실행 기록 (확인 스크립트·로그용)."""
    plan: Optional[SearchPlan] = None
    warnings: List[str] = []
    error: Optional[str] = None
    model: str = ""
    latency_ms: int = 0
    attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    checklist_version: str = ""
