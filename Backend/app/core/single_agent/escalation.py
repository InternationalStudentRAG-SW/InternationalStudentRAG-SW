"""
안전장치: 라우터가 simple(기본 RAG: 하이브리드+리랭커)로 보낸 질문을, 검색 결과를 보고 agent로 올릴지 정한다.

라우터는 문서를 보기 전에 판단하므로 '문서를 봐야 보이는 복잡함'을 놓칠 수 있다.
그래서 기본 경로의 검색 결과(retriever.retrieve_with_sources의 sources)로 한 번 더 확인한다.
LLM 호출 없이 서버 규칙만 쓴다. 답변 생성(스트리밍) 전에 부르므로 사용자는 답을 두 번 받지 않는다.

올리는 경우
  1. low_relevance : 관련도 최고 점수 < ESCALATE_MIN_SCORE
                     (기본 경로라면 '문서에서 못 찾음'으로 끝날 질문. 에이전트는 검색어를 바꿔 다시 찾는다)
  2. scope_split   : 쓸 만한 출처가 같은 사용자 칸의 서로 다른 대상 문서에 걸쳐 있음
                     (예: 한국어트랙 모집요강 + 영어트랙 모집요강 → 트랙에 따라 답이 갈릴 수 있음)
                     단, 사용자가 질문·이전 발언에서 그 대상을 이미 밝혔으면(DOC_SCOPES 별칭, 라우터 사용자 조건) 올리지 않는다.

올리지 않는 경우: 라우터가 이미 agent로 보냈거나, 검색이 필요 없는 행동(out_of_scope, no_retrieval)일 때.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel

from app.core.single_agent import checklist_config as cfg
from app.core.single_agent.branching import doc_scopes_for
from app.core.single_agent.router_schema import RouteResult
from app.core.single_agent.text_match import normalize


class EscalationCheck(BaseModel):
    escalate: bool = False
    reasons: List[str] = []
    max_score: float = 0.0
    scope_values: Dict[str, List[str]] = {}   # 사용자 칸 → 출처에서 본 대상 값들


def _score(s: Dict) -> float:
    try:
        return float(s.get("similarity_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _mentioned_fields(question: str, history: Optional[List[Dict]], route: Optional[RouteResult]) -> set:
    """사용자가 이미 대상을 밝힌 사용자 칸 (질문·이전 사용자 발언의 DOC_SCOPES 별칭 + 라우터 사용자 조건)."""
    texts = [question] + [h.get("content", "") for h in (history or []) if h.get("role") == "user"]
    norm = normalize(" ".join(texts))
    fields = {d["field_id"] for d in cfg.DOC_SCOPES
              if any(normalize(a) and normalize(a) in norm for a in d.get("aliases", []))}
    if route is not None:
        fields |= {c.field_id for c in route.user_conditions}
    return fields


def check_escalation(
    question: str,
    sources: List[Dict],
    route: Optional[RouteResult] = None,
    history: Optional[List[Dict]] = None,
    min_score: Optional[float] = None,
    scope_min_score: Optional[float] = None,
) -> EscalationCheck:
    """기본 경로의 검색 결과로 에이전트 승격 여부를 정한다 (LLM 없음)."""
    min_score = cfg.ESCALATE_MIN_SCORE if min_score is None else min_score
    scope_min_score = cfg.ESCALATE_SCOPE_MIN_SCORE if scope_min_score is None else scope_min_score
    sources = sources or []
    out = EscalationCheck(max_score=max((_score(s) for s in sources), default=0.0))

    if route is not None and (route.route == "agent" or route.action != "search"):
        return out

    if out.max_score < min_score:
        out.reasons.append(f"low_relevance: 최고 점수 {out.max_score:.2f} < {min_score}")

    values: Dict[str, List[str]] = {}
    for s in sources:
        if _score(s) < scope_min_score:
            continue
        for d in doc_scopes_for(str(s.get("source", ""))):
            vs = values.setdefault(d["field_id"], [])
            if d["value"] not in vs:
                vs.append(d["value"])
    out.scope_values = values
    mentioned = _mentioned_fields(question, history, route)
    for field_id, vs in values.items():
        if len(vs) >= 2 and field_id not in mentioned:
            out.reasons.append(f"scope_split: {field_id} 대상이 {vs}로 갈림 (질문에서 대상을 밝히지 않음)")

    out.escalate = bool(out.reasons)
    return out
