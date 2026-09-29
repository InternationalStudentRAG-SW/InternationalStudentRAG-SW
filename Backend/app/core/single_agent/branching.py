"""
④의 청크 메모로 사용자 조건별 갈래를 찾고 적용 범위를 검사한다 (서버 규칙, LLM 호출 없음).

  1-1 대상 한정: 필요한 칸에 인용된 근거가 '전부' 한 조건 값(예: gks_status=GKS 장학생)에만 해당하면,
      그 답은 그 대상에게만 확인된 것이다. 적용 범위 칸을 partial로 두고 그 사용자 조건을 연다.
  1-3 갈래 감지: 관련 청크의 적용 대상 값이 한 조건에서 2개 이상이면(예: gks_stage=학위과정 / 어학연수)
      문서가 그 조건에 따라 답을 나눈다. 사용자 조건을 열고, 적용 범위 칸이 갈래마다 근거를 인용하지 않았으면 partial.
  1-5 저장: 찾은 갈래는 UserSlot.branches에 합쳐 저장한다. 다음 라운드·되묻기·조건별 안내는 여기서 읽는다.

이미 확인된 사용자 조건(conditions의 confirmed)은 갈래로 보지 않는다. 사용자가 이미 대상을 밝혔기 때문이다.
질문에 checklist_config.DOC_SCOPES의 별칭(예: "어학당", "GKS")이 있으면 그 사용자 칸도 같은 이유로 뺀다.

문서 단위로 확실한 대상(DOC_SCOPES)은 LLM 메모와 상관없이 서버가 메모에 채운다 (apply_doc_scopes).
"""
from __future__ import annotations

from typing import Dict, List, Set

from app.core.single_agent import checklist_config as cfg
from app.core.single_agent.analysis_schema import Branch, DocSlot, QuestionAnalysis, UserSlot
from app.core.single_agent.text_match import normalize
from app.core.single_agent.verify_schema import AppliesTo, ChunkNote

SCOPE_SLOT = "applicable_scope"


def validate_notes(notes: List[ChunkNote], resolve, slot_ids: Set[str], w: List[str]) -> Dict[str, ChunkNote]:
    """
    LLM의 청크 메모를 검증한다. resolve(evidence_id) → 보여준 청크 ID 또는 None.
    보여주지 않은 청크, 정의되지 않은 사용자 칸, 판정 대상이 아닌 칸은 버린다.
    """
    out: Dict[str, ChunkNote] = {}
    for n in notes:
        eid = resolve(n.evidence_id)
        if eid is None:
            w.append(f"[제거] 청크 메모 '{n.evidence_id}': 이번에 보여준 청크가 아님")
            continue
        if eid in out:
            continue
        applies: List[AppliesTo] = []
        for a in n.applies_to:
            if a.field_id not in cfg.USER_FIELDS:
                w.append(f"[제거] 청크 메모 {eid}: 정의되지 않은 사용자 칸 '{a.field_id}'")
                continue
            if not normalize(a.value):
                continue
            if any(x.field_id == a.field_id and normalize(x.value) == normalize(a.value) for x in applies):
                continue
            applies.append(AppliesTo(field_id=a.field_id, value=a.value.strip()))
        rel = [s for s in dict.fromkeys(n.relevant_slots) if s in slot_ids]
        out[eid] = ChunkNote(evidence_id=eid, applies_to=applies, relevant_slots=rel)
    return out


def doc_scopes_for(source: str) -> List[dict]:
    key = normalize(source)
    return [d for d in cfg.DOC_SCOPES if normalize(d["match"]) in key]


def apply_doc_scopes(notes: Dict[str, ChunkNote], shown: List[str], source_of) -> int:
    """
    보여준 청크의 문서 이름으로 기본 적용 대상을 메모에 채운다. 같은 사용자 칸의 LLM 값은 문서 값으로 바꾼다
    (표기 통일). 메모가 없던 청크는 새로 만든다(relevant_slots는 비움). 반환: 채운 청크 수.
    """
    filled = 0
    for eid in shown:
        scopes = doc_scopes_for(source_of(eid) or "")
        if not scopes:
            continue
        n = notes.get(eid)
        if n is None:
            n = ChunkNote(evidence_id=eid)
            notes[eid] = n
        fields = {d["field_id"] for d in scopes}
        n.applies_to = [a for a in n.applies_to if a.field_id not in fields] + [
            AppliesTo(field_id=d["field_id"], value=d["value"]) for d in scopes]
        filled += 1
    return filled


def fields_named_in_question(question: str) -> Set[str]:
    """질문에 DOC_SCOPES 별칭이 있는 사용자 칸 (사용자가 이미 대상을 가리킴)."""
    q = normalize(question or "")
    if not q:
        return set()
    return {d["field_id"] for d in cfg.DOC_SCOPES
            if any(normalize(al) and normalize(al) in q for al in d.get("aliases", []) + [d["value"]])}


def _needed_ids(analysis: QuestionAnalysis) -> Set[str]:
    from app.core.single_agent.verifier import is_needed
    return {s.slot_id for s in analysis.document_slots if is_needed(s)}


def _cited(analysis: QuestionAnalysis, slot_ids: Set[str]) -> Set[str]:
    return {r.evidence_id for s in analysis.document_slots if s.slot_id in slot_ids for r in s.evidence_refs}


def detect_branches(
    analysis: QuestionAnalysis, notes: Dict[str, ChunkNote], skip_fields: Set[str] = frozenset(), source_of=None,
) -> Dict[str, Dict[str, Branch]]:
    """
    관련 청크(필요한 칸에 인용됐거나, 메모에서 필요한 칸과 관련 있다고 한 청크)의 적용 대상을 조건별로 모은다.
    skip_fields: 질문이 이미 가리킨 사용자 칸. 반환: {field_id: {정규화한 값: Branch}}
    """
    confirmed = {c.field_id for c in analysis.conditions if c.status == "confirmed"} | set(skip_fields)
    needed = _needed_ids(analysis)
    cited = _cited(analysis, needed)
    by_field: Dict[str, Dict[str, Branch]] = {}
    doc_fields = {eid: {d["field_id"] for d in doc_scopes_for(source_of(eid) or "")} for eid in notes} if source_of else {}
    for eid, n in notes.items():
        if eid not in cited and not (set(n.relevant_slots) & needed):
            continue
        for a in n.applies_to:
            if a.field_id in confirmed:
                continue
            # 문서 이름으로 채운 기본 대상은 실제로 인용된 청크만 갈래로 센다 (풀에 섞인 다른 문서 때문에 가짜 갈래가 생김)
            if eid not in cited and a.field_id in doc_fields.get(eid, set()):
                continue
            b = by_field.setdefault(a.field_id, {}).setdefault(
                normalize(a.value), Branch(value=a.value, source="notes"))
            if eid not in b.evidence_ids:
                b.evidence_ids.append(eid)
    return by_field


def upsert_user_slot(analysis: QuestionAnalysis, field_id: str) -> UserSlot:
    confirmed = {c.field_id for c in analysis.conditions if c.status == "confirmed"}
    u = next((x for x in analysis.user_slots if x.field_id == field_id), None)
    if u is None:
        u = UserSlot(field_id=field_id, status="confirmed" if field_id in confirmed else "unknown")
        analysis.user_slots.append(u)
    if u.status == "not_required":
        u.status = "confirmed" if field_id in confirmed else "unknown"
    return u


def merge_branches(u: UserSlot, new: List[Branch]) -> None:
    """같은 값(정규화 기준)의 갈래는 근거·요약을 합치고, 새 값은 추가한다. 이전 라운드 갈래는 지우지 않는다."""
    index = {normalize(b.value): b for b in u.branches}
    for b in new:
        cur = index.get(normalize(b.value))
        if cur is None:
            cur = b.model_copy(deep=True)
            u.branches.append(cur)
            index[normalize(b.value)] = cur
            continue
        cur.evidence_ids = list(dict.fromkeys(cur.evidence_ids + b.evidence_ids))
        if not cur.summary and b.summary:
            cur.summary = b.summary
        if cur.source != b.source and "notes" in (cur.source, b.source):
            cur.source = "notes"


def _activate(u: UserSlot, ids: List[str], reason: str) -> None:
    u.active = True
    u.required_by_evidence = list(dict.fromkeys(u.required_by_evidence + ids))
    if reason and reason not in u.reason:
        u.reason = f"{u.reason} | {reason}" if u.reason else reason


def _lower_scope(scope: DocSlot, detail: str, w: List[str]) -> None:
    scope.status = "partial"
    scope.missing_detail = (scope.missing_detail + " / " if scope.missing_detail else "") + detail
    w.append(f"[수정] {SCOPE_SLOT}: supported → partial ({detail})")


def apply_branch_rules(
    analysis: QuestionAnalysis, notes: Dict[str, ChunkNote], w: List[str], question: str = "", source_of=None,
) -> None:
    """청크 메모로 갈래(1-3)와 대상 한정(1-1)을 판정해 사용자 칸·적용 범위 칸에 반영한다."""
    if not notes:
        return
    named = fields_named_in_question(question)
    if named:
        w.append(f"[확인] 질문이 이미 대상을 가리킴 → 갈래·대상 한정에서 제외: {sorted(named)}")
    by_field = detect_branches(analysis, notes, named, source_of)
    scope = next((s for s in analysis.document_slots if s.slot_id == SCOPE_SLOT and s.active), None)
    scope_cited = {r.evidence_id for r in scope.evidence_refs} if scope else set()
    cited = sorted(_cited(analysis, _needed_ids(analysis)))

    for field_id, vals in by_field.items():
        branches = list(vals.values())
        label = cfg.USER_FIELDS.get(field_id, {}).get("label", field_id)
        if len(branches) >= 2:
            # 1-3: 문서가 이 조건에 따라 답을 나눈다
            u = upsert_user_slot(analysis, field_id)
            merge_branches(u, branches)
            ids = [i for b in branches for i in b.evidence_ids]
            _activate(u, ids, f"문서상 {label}에 따라 규정이 다름 (청크 메모)")
            w.append(f"[갈래] {field_id}: " + " / ".join(f"{b.value}({len(b.evidence_ids)})" for b in branches))
            if scope is not None and scope.status == "supported":
                missing = [b.value for b in branches if not set(b.evidence_ids) & scope_cited]
                if missing:
                    _lower_scope(scope, f"{field_id} 갈래 중 적용 범위에 인용되지 않은 값: {', '.join(missing)}", w)
            continue

        # 1-1: 값이 하나뿐 → 인용된 근거가 전부 그 대상에만 해당하는지 본다
        b = branches[0]
        key = normalize(b.value)
        restricted = bool(cited) and all(
            eid in notes and any(a.field_id == field_id and normalize(a.value) == key for a in notes[eid].applies_to)
            for eid in cited
        )
        if not restricted:
            continue
        u = upsert_user_slot(analysis, field_id)
        only = b.model_copy(deep=True)
        only.summary = only.summary or "확인된 근거가 이 대상에만 해당 (다른 대상 규정은 문서에서 미확인)"
        merge_branches(u, [only])
        _activate(u, b.evidence_ids, f"근거가 모두 {label}={b.value} 대상 규정 (청크 메모)")
        w.append(f"[대상 한정] {field_id}={b.value}: 인용된 근거 {len(cited)}개가 모두 이 대상에만 해당")
        if scope is not None and scope.status == "supported":
            _lower_scope(scope, f"근거가 모두 {field_id}={b.value} 대상 규정 — 그 밖의 대상에 대한 규정 미확인", w)


def branch_lines(u: UserSlot) -> List[str]:
    """되묻기·조건별 안내용 갈래 문구."""
    return [f"{b.value}: {b.summary}" if b.summary else b.value for b in u.branches]
