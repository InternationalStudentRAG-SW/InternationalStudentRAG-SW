"""
단일 에이전트 전체 흐름: ① 질문 분석 → (② 검색 계획 → ③ 근거 검색 → ④ 충분성 검증) 반복 → ⑤ 답변.

루프 규칙 (서버가 정함)
  - ①이 검색하지 않기로 하면(clarify_scope / out_of_scope / no_retrieval) 바로 ⑤로 간다.
  - 한 라운드 = ② 검색 1개 → ③ 실행 → ④ 판정. 첫 라운드는 ①의 first_search를 쓰고(LLM 없음),
    AUTO_EXPAND_FIRST_ROUND이면 1순위 청크 앞뒤를 바로 확장한다(LLM 없음).
  - ④의 다음 행동이 continue_search가 아니면 끝. continue_search면 다음 라운드.
    원문 확장 앵커는 ④가 준 expand_anchors를 ③에 넘긴다.
  - 멈추는 조건: MAX_VERIFY_ROUNDS 도달, ②가 더 검색할 칸이 없다고 함(예산·상한·중복), 검색 도구 오류, ④ 실패.
    이때 마지막 결정이 continue_search로 남아 있으면 근거가 있으면 partial_answer, 없으면 no_evidence로 바꾼다.
  - 어느 단계가 실패해도 예외를 밖으로 던지지 않는다. 사용자는 항상 답변(또는 안내 문구)을 받는다.

on_event(stage, info)를 넘기면 단계마다 진행 상황을 알려준다 (확인 스크립트 출력, 나중에 SSE 스트리밍용).
"""
from __future__ import annotations

import re
import time
from typing import Callable, Dict, List, Optional

from app.core.single_agent import checklist_config as cfg
from app.core.single_agent.analysis_schema import QuestionAnalysis
from app.core.single_agent.analyzer import analyze_question
from app.core.single_agent.answer_schema import PipelineRun
from app.core.single_agent.answerer import write_answer
from app.core.single_agent.branching import branch_lines
from app.core.single_agent.evidence_schema import EvidencePool
from app.core.single_agent.search_planner import check_budget, plan_search
from app.core.single_agent.search_schema import SearchAttempt, SearchBudget, SearchPlan
from app.core.single_agent.text_match import normalize
from app.core.single_agent.searcher import execute_search
from app.core.single_agent.verifier import decide, verify_evidence
from app.core.single_agent.verify_schema import VerifyDecision

EventFn = Callable[[str, Dict], None]


_ASK_REF_RE = re.compile(r"#A\d+")


def ask_seed_plans(route_asks, target_slot_id: str, tried: List[str]) -> List[SearchPlan]:
    """
    ⓪ 라우터 요구마다 첫 라운드 검색 계획을 만든다. 요구가 2개 미만이면 만들지 않는다.
    의존 요구의 '#A1' 자리 표시는 지우고, 이미 시도한 검색어와 같으면 건너뛴다.
    """
    asks = []
    for a in route_asks or []:
        d = a.model_dump() if hasattr(a, "model_dump") else dict(a)
        q = " ".join(_ASK_REF_RE.sub(" ", str(d.get("query_ko") or d.get("text") or "")).split())
        if q:
            asks.append((d.get("ask_id", ""), q, " ".join(_ASK_REF_RE.sub(" ", str(d.get("query_en") or "")).split())))
    if len(asks) < 2:
        return []
    seen = {normalize(t) for t in tried}
    plans = []
    for ask_id, q, en in asks[: cfg.ROUTER_MAX_ASKS]:
        if normalize(q) in seen:
            continue
        seen.add(normalize(q))
        plans.append(SearchPlan(action="search", target_slot_id=target_slot_id, search_type="new",
                                query_ko=q, query_en=en or None, reason=f"첫 라운드 요구별 검색 ({ask_id})"))
    return plans


def general_query_for(analysis: QuestionAnalysis, question: str = "") -> str:
    """
    사용자 조건을 뺀 일반 규정 검색어. 첫 검색어에서 사용자 사례 조건(user_self / other_person)의 단어
    (GENERAL_QUERY_STRIP_WORDS)를 뺀다. 질문의 구체적인 내용(예: '첫 학기')이 그대로 남아서 ①이 따로 적은
    general_query_ko보다 우선한다(①은 'GKS 장학생 휴학 규정'처럼 조건을 남기거나 핵심어를 빠뜨린 적이 있음, 2026-10-02).
    첫 검색어로 만들 수 없을 때만 general_query_ko를 같은 방식으로 다듬어 쓴다. 둘 다 안 되면 빈 문자열.
    """
    fs = analysis.first_search
    if fs is None:
        return ""
    fields = {c.field_id for c in analysis.conditions if c.subject in ("user_self", "other_person")}
    words = sorted({w for f in fields for w in cfg.GENERAL_QUERY_STRIP_WORDS.get(f, [])}, key=len, reverse=True)
    if not words:
        return ""

    def strip(text: str) -> str:
        q = text or ""
        for w in words:
            q = re.sub(re.escape(w), " ", q, flags=re.IGNORECASE)
        q = re.sub(r"\s+", " ", q).strip(" ,·의")
        if len(normalize(q)) < cfg.GENERAL_QUERY_MIN_CHARS or normalize(q) == normalize(fs.query_ko or ""):
            return ""
        return q

    return strip(fs.query_ko) or strip(fs.general_query_ko)


def finalize_decision(
    analysis: QuestionAnalysis, decision: Optional[VerifyDecision], reason: str,
) -> VerifyDecision:
    """루프가 끝났는데 결정이 없거나 continue_search로 남았으면 답변 가능한 행동으로 바꾼다."""
    if decision is not None and decision.next_action != "continue_search":
        return decision
    has_evidence = any(s.evidence_refs for s in analysis.document_slots if s.active)
    unresolved = decision.unresolved_slot_ids if decision else [
        s.slot_id for s in analysis.document_slots if s.active and s.status not in cfg.RESOLVED_STATUSES]
    if not has_evidence:
        return VerifyDecision(next_action="no_evidence", reason=f"사용할 근거 없음 ({reason})",
                              unresolved_slot_ids=unresolved)
    pending = [u for u in analysis.user_slots
               if u.active and u.status in ("unknown", "ambiguous") and u.required_by_evidence]
    return VerifyDecision(
        next_action="partial_answer", reason=f"미해결 칸 {unresolved}, 더 진행하지 않음 ({reason})",
        unresolved_slot_ids=unresolved, condition_field_ids=[u.field_id for u in pending],
        condition_branches={u.field_id: branch_lines(u) for u in pending},
    )


def run_pipeline(
    question: str,
    history: Optional[List[Dict]] = None,
    model: Optional[str] = None,
    verify_model: Optional[str] = None,
    answer_model: Optional[str] = None,
    max_rounds: Optional[int] = None,
    client=None,
    search_fn=None,
    store=None,
    on_event: Optional[EventFn] = None,
    route_asks=None,
) -> PipelineRun:
    """
    질문 1개를 끝까지 처리한다. history: 이전 대화 [{"role": "user"/"assistant", "content": ...}].
    model: ①② 모델, verify_model: ④ 모델, answer_model: ⑤ 모델 (None이면 설정값).
    client/search_fn/store는 테스트용 가짜를 끼울 때만 쓴다.
    """
    emit = on_event or (lambda stage, info: None)
    started = time.perf_counter()
    run = PipelineRun(question=question, checklist_version=cfg.CHECKLIST_VERSION)
    max_rounds = max_rounds or cfg.MAX_VERIFY_ROUNDS

    def finish(mode: str, analysis=None, pool=None, decision=None):
        run.decision = decision
        emit("answer_start", {"mode": mode})
        run.answer_run = write_answer(question, mode, analysis, pool, decision, model=answer_model, client=client,
                                      asks=route_asks)
        emit("answer", {"mode": run.answer_run.mode, "answer": run.answer_run.answer,
                        "sources": [s.model_dump() for s in run.answer_run.sources]})
        run.latency_ms = int((time.perf_counter() - started) * 1000)
        return run

    # ① 질문 분석
    a_run = analyze_question(question, history, model=model, client=client, asks=route_asks)
    run.analysis_run = a_run
    if a_run.analysis is None:
        run.stopped = f"analysis_error: {a_run.error}"
        emit("analysis", {"error": a_run.error})
        return finish("error")
    analysis = a_run.analysis
    run.analysis = analysis
    emit("analysis", {"type": analysis.primary_type, "next_action": analysis.next_action,
                      "slots": [s.slot_id for s in analysis.document_slots if s.active]})
    if analysis.next_action != "search":
        run.stopped = f"no_search: {analysis.next_action}"
        return finish(analysis.next_action, analysis)

    pool, budget = EvidencePool(), SearchBudget()
    attempts: List[SearchAttempt] = []
    decision: Optional[VerifyDecision] = None
    anchors_by_slot: Dict[str, List[str]] = {}
    completed_expansions = set()

    for rnd in range(1, max_rounds + 1):
        # ② 검색 계획
        p_run = plan_search(
            analysis, budget=budget, history=attempts, model=model, client=client,
            anchors_by_slot=anchors_by_slot, completed_expansions=completed_expansions,
        )
        run.plan_runs.append(p_run)
        plan = p_run.plan
        if plan is None or plan.action != "search":
            run.stopped = f"plan: {p_run.error or (plan.action if plan else 'none')}"
            emit("plan", {"round": rnd, "action": plan.action if plan else None, "error": p_run.error})
            break
        emit("plan", {"round": rnd, "slot": plan.target_slot_id, "type": plan.search_type, "query": plan.query_ko})

        # ③ 근거 검색
        round_chunks: List[str] = []
        anchors = anchors_by_slot.get(plan.target_slot_id) if plan.search_type == "expand_context" else None
        ex = execute_search(plan, pool, budget, anchor_evidence_ids=anchors, search_fn=search_fn, store=store)
        run.search_runs.append(ex)
        if not ex.ok:
            run.warnings.append(f"③ 검색 실패 [{ex.error_type}]: {ex.error}")
            emit("search", {"round": rnd, "error": ex.error, "error_type": ex.error_type})
            run.stopped = f"search: {ex.error_type}"
            break
        budget = ex.budget
        attempts.append(ex.attempt)
        if plan.search_type == "expand_context" and ex.anchor_ids:
            completed_expansions.add((tuple(sorted(set(ex.anchor_ids))), cfg.EXPAND_WINDOW))
        round_chunks += ex.chunk_ids
        round_new_chunks = list(ex.new_chunk_ids)
        if rnd == 1 and cfg.PER_ASK_FIRST_ROUND and plan.search_type == "new":
            # 요구별 검색: 예산 계산에 넣지 않도록 복사본 예산으로 실행하고 결과 예산은 버린다 (상한은 요구 수)
            for seed in ask_seed_plans(route_asks, plan.target_slot_id, [h.query_ko for h in attempts]):
                exs = execute_search(seed, pool, SearchBudget(), search_fn=search_fn, store=store)
                run.search_runs.append(exs)
                if exs.ok:
                    # 검색 기록(attempts)에는 넣지 않는다: 칸별 시도 상한을 쓰면 ②가 그 칸을 더 못 찾는다
                    round_chunks += exs.chunk_ids
                    round_new_chunks += exs.new_chunk_ids
                else:
                    run.warnings.append(f"③ 요구별 검색 실패 [{exs.error_type}]: {exs.error}")
        if (rnd == 1 and cfg.AUTO_EXPAND_FIRST_ROUND and plan.search_type == "new" and ex.chunk_ids
                and check_budget(budget, "expand_context") is None):
            plan2 = SearchPlan(action="search", target_slot_id=plan.target_slot_id, search_type="expand_context",
                               query_ko=plan.query_ko, reason="첫 바퀴 1순위 청크 앞뒤 확장")
            ex2 = execute_search(plan2, pool, budget, anchor_evidence_ids=[ex.chunk_ids[0]],
                                 search_fn=search_fn, store=store)
            run.search_runs.append(ex2)
            if ex2.ok:
                budget = ex2.budget
                attempts.append(ex2.attempt)
                if ex2.anchor_ids:
                    completed_expansions.add((tuple(sorted(set(ex2.anchor_ids))), cfg.EXPAND_WINDOW))
                round_chunks += ex2.chunk_ids
                round_new_chunks += ex2.new_chunk_ids
            else:
                run.warnings.append(f"③ 첫 바퀴 확장 실패 [{ex2.error_type}]: {ex2.error}")
        general = general_query_for(analysis, question) if rnd == 1 else ""
        if (rnd == 1 and cfg.GENERAL_QUERY_FIRST_ROUND and plan.from_first_search and general
                and normalize(general) != normalize(plan.query_ko or "")
                and check_budget(budget, "new") is None):
            plan3 = SearchPlan(action="search", target_slot_id=plan.target_slot_id, search_type="new",
                               query_ko=general, reason="첫 바퀴 일반 규정 검색 (사용자 조건 제외)")
            ex3 = execute_search(plan3, pool, budget, search_fn=search_fn, store=store)
            run.search_runs.append(ex3)
            if ex3.ok:
                budget = ex3.budget
                attempts.append(ex3.attempt)
                round_chunks += ex3.chunk_ids
                round_new_chunks += ex3.new_chunk_ids
            else:
                run.warnings.append(f"③ 일반 규정 검색 실패 [{ex3.error_type}]: {ex3.error}")
        emit("search", {"round": rnd, "chunks": len(round_chunks), "pool": len(pool),
                        "new": len(round_new_chunks)})

        # 이전 성공 판정에서 이미 본 청크만 다시 반환됐으면 상태 입력이 변하지 않았다.
        # 같은 전체 근거를 다시 LLM에 보내지 않고 서버 규칙으로 다음 행동을 정한다.
        previously_shown = {cid for v in run.verify_runs if v.decision is not None
                            for cid in v.shown_chunk_ids}
        if (decision is not None and not round_new_chunks
                and set(round_chunks).issubset(previously_shown)):
            decision = decide(analysis, budget, attempts)
            anchors_by_slot = decision.expand_anchors
            run.rounds = rnd
            run.verification_skips += 1
            msg = f"④ 건너뜀: 신규·미판정 근거 없음 ({len(round_chunks)}개 모두 이전 판정 입력)"
            run.warnings.append(msg)
            emit("verify", {"round": rnd, "next_action": decision.next_action, "reason": msg,
                            "statuses": {s.slot_id: s.status for s in analysis.document_slots if s.active},
                            "skipped": True})
            if decision.next_action != "continue_search":
                run.stopped = f"decided: {decision.next_action}"
                break
            continue

        # ④ 충분성 검증
        emit("verify_start", {"round": rnd})
        v_run = verify_evidence(
            analysis, pool, budget, attempts, round_chunk_ids=round_chunks,
            round_new_chunk_ids=round_new_chunks, prior_runs=run.verify_runs,
            question=question, model=verify_model, client=client,
        )
        run.verify_runs.append(v_run)
        run.rounds = rnd
        if v_run.decision is None:
            run.warnings.append(f"④ 판정 실패: {v_run.error}")
            emit("verify", {"round": rnd, "error": v_run.error})
            run.stopped = f"verify_error: {v_run.error}"
            break
        analysis, decision = v_run.analysis, v_run.decision
        run.analysis = analysis
        anchors_by_slot = decision.expand_anchors
        emit("verify", {"round": rnd, "next_action": decision.next_action, "reason": decision.reason,
                        "statuses": {s.slot_id: s.status for s in analysis.document_slots if s.active}})
        if decision.next_action != "continue_search":
            run.stopped = f"decided: {decision.next_action}"
            break
    else:
        run.stopped = f"max_rounds: {max_rounds}"

    run.pool, run.budget = pool, budget
    final = finalize_decision(analysis, decision, run.stopped)
    return finish(final.next_action, analysis, pool, final)
