"""
③ 근거 검색의 데이터 구조.

  EvidenceChunk  : 검색·확장으로 얻은 청크 1개 (근거 후보). ID는 source#p{page}#c{chunk_index}.
  RetrievalTag   : 그 청크를 어느 검색(칸·종류·검색어·바퀴)이 찾았는지의 기록.
  EvidencePool   : 한 질문 동안 누적되는 청크 모음. 같은 ID는 하나로 합치고 최고 점수를 유지한다.
  SearchExecutionRun : ③ 1회 실행 기록 (확인 스크립트·로그용).

풀은 청크를 '쌓기만' 한다. 어떤 청크가 어느 칸의 근거인지 판정하는 것은 ④의 몫이다.
retrieved_by 태그는 그 판정을 돕는 이력일 뿐, 칸 소속을 뜻하지 않는다.

문서 버전은 아직 메타데이터에 없어서 source(파일명)로 대신한다(임시).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.core.single_agent.search_schema import SearchAttempt, SearchBudget, SearchPlan

_EVIDENCE_ID_RE = re.compile(r"^(?P<source>.+)#p(?P<page>\d+)#c(?P<idx>\d+)$")


def make_evidence_id(source: str, page: int, chunk_index: int) -> str:
    return f"{source}#p{int(page)}#c{int(chunk_index)}"


def parse_evidence_id(evidence_id: str) -> Optional[Tuple[str, int, int]]:
    """'source#p3#c4' → (source, 3, 4). 형식이 틀리면 None."""
    m = _EVIDENCE_ID_RE.match(evidence_id or "")
    if not m:
        return None
    return m.group("source"), int(m.group("page")), int(m.group("idx"))


class RetrievalTag(BaseModel):
    """이 청크를 찾아낸 검색 1건의 기록."""
    target_slot_id: str
    search_type: str  # "new" / "expand_context"
    query_ko: str
    round_no: int = 0  # 이 검색이 몇 번째 호출이었는지 (budget.total_calls + 1)


class EvidenceChunk(BaseModel):
    evidence_id: str
    source: str
    page: int
    chunk_index: int
    lang: str = ""
    text: str
    score: Optional[float] = Field(
        default=None, description="reranker 점수. 원문 확장으로 가져온 청크는 None"
    )
    tags: List[RetrievalTag] = []


class EvidencePool(BaseModel):
    """한 질문 동안 누적되는 청크 모음 (삽입 순서 유지)."""
    chunks: Dict[str, EvidenceChunk] = {}

    def __len__(self) -> int:
        return len(self.chunks)

    def __contains__(self, evidence_id: str) -> bool:
        return evidence_id in self.chunks

    def get(self, evidence_id: str) -> Optional[EvidenceChunk]:
        return self.chunks.get(evidence_id)

    def add(self, chunk: EvidenceChunk, tag: RetrievalTag) -> bool:
        """
        청크를 넣는다. 새 ID면 True(새 근거), 이미 있던 ID면 False를 돌려준다.
        이미 있던 청크는 더 높은 점수와 새 태그만 반영한다. (본문은 바꾸지 않는다)
        """
        existing = self.chunks.get(chunk.evidence_id)
        if existing is None:
            stored = chunk.model_copy(deep=True)
            stored.tags = [tag]
            self.chunks[stored.evidence_id] = stored
            return True
        if chunk.score is not None and (existing.score is None or chunk.score > existing.score):
            existing.score = chunk.score
        if tag not in existing.tags:
            existing.tags.append(tag)
        return False

    def best_for_slot(self, slot_id: str) -> Optional[EvidenceChunk]:
        """해당 칸을 위해 검색해서 찾은 청크 중 점수가 가장 높은 것 (점수 없는 청크는 뒤로)."""
        mine = [c for c in self.chunks.values() if any(t.target_slot_id == slot_id for t in c.tags)]
        if not mine:
            return None
        return max(mine, key=lambda c: (c.score is not None, c.score if c.score is not None else 0.0))


class SearchExecutionRun(BaseModel):
    """③ 검색 실행 1회의 기록. 실패해도 예외 대신 error에 이유를 담는다."""
    plan: Optional[SearchPlan] = None
    ok: bool = False
    # error_type: invalid_plan / budget_exhausted / no_anchor / tool_error
    error: Optional[str] = None
    error_type: Optional[str] = None
    attempt: Optional[SearchAttempt] = None   # 성공했을 때만. 호출자가 history에 붙인다
    budget: Optional[SearchBudget] = None     # 갱신된 예산. 실패하면 입력 그대로
    chunk_ids: List[str] = []                 # 이번 실행이 돌려준 청크 (검색은 순위순, 확장은 문서 순)
    new_chunk_ids: List[str] = []             # 그중 풀에 처음 들어온 청크
    anchor_ids: List[str] = []                # 원문 확장에 쓴 앵커
    warnings: List[str] = []
    tool_attempts: int = 0                    # 검색 도구를 실제로 부른 횟수 (재시도 포함)
    latency_ms: int = 0
    checklist_version: str = ""
