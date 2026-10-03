"""
⑤ 답변 생성과 전체 흐름(①→②③④ 반복→⑤)의 기록 구조.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel
from app.core.single_agent.metrics import LLMMetrics

from app.core.single_agent.analysis_schema import AnalysisRun, QuestionAnalysis
from app.core.single_agent.evidence_schema import EvidencePool, SearchExecutionRun
from app.core.single_agent.search_schema import SearchBudget, SearchPlanRun
from app.core.single_agent.verify_schema import VerificationRun, VerifyDecision


class AnswerSource(BaseModel):
    """답변 본문의 [번호]가 가리키는 청크."""
    number: int
    evidence_id: str
    source: str
    page: int


class AnswerRun(LLMMetrics):
    """⑤ 답변 1회 실행 기록. 실패해도 예외 대신 error에 이유를 담고 answer에는 안내 문구를 넣는다."""
    mode: str                          # answer / answer_by_condition / ask_clarification / partial_answer / no_evidence
                                       # / clarify_scope / out_of_scope / no_retrieval / error
    answer: str = ""
    sources: List[AnswerSource] = []   # 본문에 실제로 쓴 번호만
    shown_evidence_ids: List[str] = [] # 프롬프트에 넣은 근거 청크 (번호 순)
    facts: List[dict] = []             # 인용 먼저 쓰기: 원문 대조를 통과한 {ask, evidence(번호), evidence_id, quote}
    check_issues: List[str] = []       # 답변 검사(answer_check)에서 처음 걸린 항목
    rewrites: int = 0                  # 검사에 걸려 다시 쓴 횟수
    dropped_sentences: List[str] = []  # 다시 써도 근거가 없어 뺀 문장
    warnings: List[str] = []
    error: Optional[str] = None
    model: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attempts: int = 0
    raw_output: str = ""


class PipelineRun(BaseModel):
    """질문 1개의 전체 실행 기록."""
    question: str
    analysis_run: Optional[AnalysisRun] = None
    plan_runs: List[SearchPlanRun] = []
    search_runs: List[SearchExecutionRun] = []
    verify_runs: List[VerificationRun] = []
    verification_skips: int = 0                       # 근거 상태가 같아 ④ LLM을 생략한 라운드 수
    answer_run: Optional[AnswerRun] = None
    analysis: Optional[QuestionAnalysis] = None     # 마지막 상태 (되묻기 후 이어가기용)
    pool: EvidencePool = EvidencePool()
    budget: SearchBudget = SearchBudget()
    decision: Optional[VerifyDecision] = None       # ⑤에 넘긴 최종 결정
    rounds: int = 0                                 # 완료한 검색·검증 루프 라운드 수(④ 생략 포함)
    stopped: str = ""                               # 루프가 끝난 이유
    warnings: List[str] = []
    latency_ms: int = 0
    checklist_version: str = ""

    @property
    def answer(self) -> str:
        return self.answer_run.answer if self.answer_run else ""
