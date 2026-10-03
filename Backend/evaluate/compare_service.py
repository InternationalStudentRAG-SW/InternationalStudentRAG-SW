"""
실제 서비스 기준 비교: 기존 검색(AGENT_ROUTING=off) vs 현재 서비스(AGENT_ROUTING=auto).

  python -m evaluate.compare_service                 # 복합 질문 5개 × 1회
  python -m evaluate.compare_service --only Q7,E3 --repeat 1
  python -m evaluate.compare_service --label "⑤ gpt-4o"

무엇을 돌리나 (서버 없이, 서비스 코드를 그대로 호출)
  기존 검색  : app.core.rag_stream.run_rag_stream   — 서비스의 기본 경로 그대로 (프롬프트·점수 필터·OPENAI_MODEL)
  현재 서비스: ⓪ 라우터(route_question) → agent면 app.core.agent_stream.run_agent_stream,
               simple이면 기존 검색 답을 그대로 씀 (chat.py의 AGENT_ROUTING=auto와 같은 분기)
  모델은 .env 설정을 그대로 따른다 (OPENAI_MODEL, VERIFY_MODEL, ANSWER_MODEL). 실험 결과에 함께 기록한다.

채점 (지표 2개)
  핵심 사실 포함률 : 질문마다 PDF 원문으로 확인한 핵심 사실 목록 중 답에 맞게 들어간 비율
                     (포함 1점, 일부만 0.5점, 누락·틀림 0점)
  틀린 내용 수     : 핵심 사실과 어긋나는 내용 (값이 다르거나, 금지를 허용으로 쓰는 등)
  심판은 LLM(기본 gpt-4o) 1회. 답변마다 따로 채점하고, 어느 방식의 답인지 알려주지 않는다.

결과: evaluate/results/service_compare_<시각>.json + .md (질문별 답변 나란히, 요약 표)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Callable, Dict, List, Optional, Tuple

RESULTS_DIR = Path(__file__).resolve().parent / "results"
DEFAULT_JUDGE_MODEL = "gpt-4o"

# 2026-10-03에 원문 PDF로 확인한 핵심 사실. 문서명·조항은 확인용 메모.
QUESTIONS: List[Dict] = [
    {"id": "Q7", "question": "GKS 장학생으로 동아대 학부에 신입학했는데, 첫 학기에 휴학할 수 있어? 휴학하면 장학금은 어떻게 돼?",
     "facts": ["입학 후 첫 학기에는 휴학할 수 없다 (예외 조건 없이 불가)",
               "휴학 기간에는 학업장려금(월 생활비)을 원칙적으로 지급하지 않는다",
               "휴학 기간은 장학 기간에 포함되지 않는다 (장학 기간은 연장되지 않음)"],
     "source": "한국어트랙 모집요강 p.14 카항 / GKS 학사운영지침 제4조③·제22조④"},
    {"id": "LANG", "question": "동아대 학부 신입학에 지원하려는데, 한국어 트랙과 영어 트랙의 어학 기준이 각각 뭐야? 영어 트랙에서 어학 성적을 안 내도 되는 경우도 있어?",
     "facts": ["한국어 트랙 신입학: TOPIK 2급 이상 또는 이에 상응하는 성적",
               "영어 트랙: IELTS 5.5, TOEFL iBT 3.5, New TEPS 202 중 하나 이상",
               "영어가 모국어인 국가(남아공·뉴질랜드·미국·아일랜드·영국·캐나다·호주)에서 고등학교 과정을 마친 지원자는 영어 트랙 어학 요건이 면제된다"],
     "source": "한국어트랙 모집요강 p.2 / 영어트랙 Admission Guidelines p.2"},
    {"id": "GKSW", "question": "동아대 한국어과정을 듣는 GKS 장학생이 있다고 해보자. 무단결석이 몇 번이면 GKS 경고를 받고, 한국어과정 다음 급으로 올라가려면 최소 얼마나 출석해야 해? 경고는 몇 번 받으면 자격을 잃어?",
     "facts": ["한국어연수 기간 중 무단결석이 연속 3일 이상이거나 월 누계 5일 이상이면 경고를 받는다",
               "한국어과정 다음 급으로 올라가려면 출석률 80% 이상이 필요하다 (성적 70점 이상과 함께)",
               "경고를 3회 이상 받으면 장학생 자격을 잃는다"],
     "source": "GKS 학사운영지침 제18조 1호·제19조 9호 / Korean Language Course 안내 p.2"},
    {"id": "E2", "question": "GKS 학위과정 장학생이 학기 중간에 휴학하려면 어떤 경우에만 가능해? 휴학은 최대 얼마나 할 수 있어?",
     "facts": ["본국의 긴급 소환, 긴급한 가정 사정, 본인의 중대한 질병 등 부득이한 사유가 있을 때만 가능하다",
               "휴학 신청서와 함께 사유를 증빙하는 자료를 제출해야 한다",
               "휴학은 학기 단위로 신청하며 총 휴학 기간은 1년을 넘을 수 없다",
               "수학기관장이 특별한 사유로 인정하면 최대 1년 범위에서 추가로 연장할 수 있다"],
     "source": "GKS 학사운영지침 제12조 ③④"},
    {"id": "E3", "question": "동아대 한국어과정에서 다음 급으로 올라가려면 성적이랑 출석률이 각각 얼마 이상이어야 해? 지각은 어떻게 계산돼?",
     "facts": ["성적 70점 이상이어야 한다",
               "출석률 80% 이상이어야 한다 (두 조건을 모두 충족해야 진급)",
               "지각 2번은 결석 1번으로 계산한다"],
     "source": "Korean Language Course 안내 p.2 Grading"},
]

JUDGE_SYSTEM = (
    "당신은 대학 유학생 안내 챗봇의 답변을 채점하는 엄격한 평가자입니다. 정답 핵심 사실을 기준으로 답변 하나를 채점합니다.\n"
    "핵심 사실마다 status를 하나 고릅니다.\n"
    "- included: 답변에 그 사실이 맞게 들어 있음 (표현이 달라도 뜻과 값이 같으면 포함)\n"
    "- partial: 일부만 들어 있음 (예: 조건 두 개 중 하나, 시험 세 개 중 일부)\n"
    "- missing: 언급이 없거나 '확인하지 못했다'고 함\n"
    "- wrong: 값이 다르거나 사실과 어긋나게 씀 (예: 3회를 2회로, '불가'를 '조건부 가능'으로)\n"
    "contradictions에는 핵심 사실과 어긋나는 답변 속 문장을 옮겨 적습니다 (없으면 빈 목록). "
    "핵심 사실에 없는 추가 내용은 사실과 어긋나지 않으면 문제 삼지 않습니다.\n"
    '출력(JSON만): {"facts": [{"no": 1, "status": "included|partial|missing|wrong", "reason": "짧게"}], '
    '"contradictions": ["..."]}'
)
POINTS = {"included": 1.0, "partial": 0.5, "missing": 0.0, "wrong": 0.0}


# ── SSE 수집 ─────────────────────────────────────────────────────────────

async def collect_sse(stream: AsyncIterator[str]) -> Tuple[str, List[Dict]]:
    """서비스 SSE(data: {...})에서 답변 글자(token·clarify)와 출처(done)를 모은다. 하트비트(: ping)는 무시."""
    parts: List[str] = []
    sources: List[Dict] = []
    async for chunk in stream:
        for line in str(chunk).splitlines():
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if ev.get("type") in ("token", "clarify"):
                parts.append(ev.get("content", ""))
            elif ev.get("type") == "done":
                sources = ev.get("sources") or []
    return "".join(parts).strip(), sources


# ── 두 방식 실행 ──────────────────────────────────────────────────────────

async def run_baseline(question: str, rag_stream_fn: Optional[Callable] = None) -> Dict:
    if rag_stream_fn is None:
        from app.core.rag_stream import run_rag_stream as rag_stream_fn
    t = time.perf_counter()
    answer, sources = await collect_sse(rag_stream_fn(question, "ko", ko_query=question, history=[]))
    return {"route": "simple", "answer": answer, "sources": sources, "latency_s": round(time.perf_counter() - t, 1)}


async def run_service(question: str, baseline: Dict, route_fn: Optional[Callable] = None,
                      agent_stream_fn: Optional[Callable] = None) -> Dict:
    """chat.py의 AGENT_ROUTING=auto 분기와 같다. simple이면 기존 검색 답을 그대로 쓴다(같은 코드라 다시 돌리지 않음)."""
    if route_fn is None:
        from app.core.single_agent.router import route_question as route_fn
    if agent_stream_fn is None:
        from app.core.agent_stream import run_agent_stream as agent_stream_fn
    t = time.perf_counter()
    rrun = await asyncio.to_thread(route_fn, question, [])
    route = rrun.result.route or "agent"
    if route != "agent":
        return {**baseline, "route": route, "router_reasons": rrun.result.route_reasons}
    meta = {"routing_mode": "auto", "router": rrun.model_dump()}
    answer, sources = await collect_sse(agent_stream_fn(question, "ko", ko_query=question, history=[], log_meta=meta))
    return {"route": "agent", "router_reasons": rrun.result.route_reasons, "answer": answer, "sources": sources,
            "latency_s": round(time.perf_counter() - t, 1)}


# ── 채점 ─────────────────────────────────────────────────────────────────

def judge_answer(q: Dict, answer: str, client, model: str = DEFAULT_JUDGE_MODEL) -> Dict:
    facts = "\n".join(f"{i}. {f}" for i, f in enumerate(q["facts"], 1))
    user = f"## 질문\n{q['question']}\n\n## 정답 핵심 사실\n{facts}\n\n## 답변\n{answer or '(빈 답변)'}"
    resp = client.chat.completions.create(
        model=model, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}])
    data = json.loads(resp.choices[0].message.content or "{}")
    return score_judgement(q, data)


def score_judgement(q: Dict, data: Dict) -> Dict:
    """심판 출력 → 지표. 심판이 빠뜨린 사실은 missing으로 본다."""
    by_no = {}
    for f in data.get("facts") or []:
        try:
            n = int(f.get("no"))
        except (TypeError, ValueError):
            continue
        st = str(f.get("status", "")).strip().lower()
        by_no[n] = {"status": st if st in POINTS else "missing", "reason": str(f.get("reason", ""))}
    per_fact = [by_no.get(i, {"status": "missing", "reason": "(심판 누락)"}) for i in range(1, len(q["facts"]) + 1)]
    contradictions = [str(c) for c in (data.get("contradictions") or []) if str(c).strip()]
    n_wrong = sum(1 for f in per_fact if f["status"] == "wrong")
    return {
        "coverage": sum(POINTS[f["status"]] for f in per_fact) / len(per_fact),
        "wrong": max(n_wrong, len(contradictions)),
        "per_fact": per_fact,
        "contradictions": contradictions,
    }


# ── 집계·보고서 ──────────────────────────────────────────────────────────

def _avg(xs: List[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def summarize(rows: List[Dict]) -> Dict:
    out: Dict = {}
    for m in ("baseline", "service"):
        rs = [r[m] for r in rows if "score" in r[m]]
        out[m] = {
            "coverage": _avg([r["score"]["coverage"] for r in rs]),
            "wrong": sum(r["score"]["wrong"] for r in rs),
            "full_correct": sum(1 for r in rs if r["score"]["coverage"] == 1.0 and r["score"]["wrong"] == 0),
            "latency_s": _avg([r["latency_s"] for r in rs]),
            "n": len(rs),
        }
    per_q = {}
    for r in rows:
        d = per_q.setdefault(r["id"], {"baseline": [], "service": []})
        for m in ("baseline", "service"):
            if "score" in r[m]:
                d[m].append(r[m]["score"]["coverage"])
    out["per_question"] = {k: {m: _avg(v[m]) for m in v} for k, v in per_q.items()}
    out["routes"] = {r["id"]: r["service"].get("route") for r in rows}
    return out


def _pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def print_summary(s: Dict) -> None:
    b, a = s["baseline"], s["service"]
    print("\n                     기존 검색    현재 서비스")
    print(f"핵심 사실 포함률     {_pct(b['coverage']):>8s}    {_pct(a['coverage']):>8s}")
    print(f"틀린 내용 수(합계)   {b['wrong']:>8d}    {a['wrong']:>8d}")
    print(f"완전 정답 답변 수    {b['full_correct']:>5d}/{b['n']:<2d}    {a['full_correct']:>5d}/{a['n']:<2d}")
    print(f"평균 응답 시간       {b['latency_s'] or 0:>7.1f}s    {a['latency_s'] or 0:>7.1f}s")
    print("\n질문별 핵심 사실 포함률")
    for qid, v in s["per_question"].items():
        print(f"  {qid:5s} {_pct(v['baseline']):>8s} → {_pct(v['service']):>8s}   (경로: {s['routes'].get(qid)})")


def to_markdown(rows: List[Dict], s: Dict, meta: Dict) -> str:
    b, a = s["baseline"], s["service"]
    lines = [
        "# 기존 검색 vs 현재 서비스 비교", "",
        f"- 실행: {meta['started_at']} · 질문 {len({r['id'] for r in rows})}개 × {meta['repeat']}회 · 심판 {meta['judge_model']}",
        f"- 모델: 기본 {meta['models']['openai_model']} · ④ {meta['models']['verify_model'] or '(기본)'}"
        f" · ⑤ {meta['models']['answer_model'] or '(기본)'}", "",
        "| 지표 | 기존 검색 | 현재 서비스 |", "|---|---|---|",
        f"| 핵심 사실 포함률 | {_pct(b['coverage'])} | {_pct(a['coverage'])} |",
        f"| 틀린 내용 수 (합계) | {b['wrong']} | {a['wrong']} |",
        f"| 완전 정답 답변 수 | {b['full_correct']}/{b['n']} | {a['full_correct']}/{a['n']} |",
        f"| 평균 응답 시간 | {b['latency_s'] or 0:.1f}초 | {a['latency_s'] or 0:.1f}초 |", "",
        "## 질문별 답변", "",
    ]
    qmap = {q["id"]: q for q in QUESTIONS}
    for r in rows:
        q = qmap.get(r["id"], {"facts": []})
        lines += [f"### {r['id']} (#{r['try']}) {r['question']}", "",
                  "핵심 사실: " + " / ".join(f"({i}) {f}" for i, f in enumerate(q["facts"], 1)), ""]
        for m, name in (("baseline", "기존 검색"), ("service", f"현재 서비스 ({r['service'].get('route')})")):
            x = r[m]
            sc = x.get("score")
            head = f"**{name}** — 포함률 {_pct(sc['coverage'])}, 틀린 내용 {sc['wrong']}" if sc else f"**{name}** — 채점 실패"
            marks = " ".join(f"({i}){'✅' if f['status'] == 'included' else '🔸' if f['status'] == 'partial' else '❌' if f['status'] == 'wrong' else '·'}"
                             for i, f in enumerate(sc["per_fact"], 1)) if sc else ""
            lines += [head + (f" · {marks}" if marks else ""), "", "> " + (x.get("answer") or "(빈 답변)").replace("\n", "\n> "), ""]
            if sc and sc["contradictions"]:
                lines += ["틀린 내용: " + " / ".join(sc["contradictions"]), ""]
    lines += ["범례: ✅ 포함 · 🔸 일부 · · 누락 · ❌ 틀림", ""]
    return "\n".join(lines)


def _models() -> Dict:
    from app.config import settings
    return {"openai_model": settings.openai_model, "verify_model": getattr(settings, "verify_model", ""),
            "answer_model": getattr(settings, "answer_model", "")}


async def compare(only: Optional[set] = None, repeat: int = 1, judge_model: str = DEFAULT_JUDGE_MODEL,
                  client=None, log=print, **fns) -> List[Dict]:
    if client is None:
        from app.core.single_agent.llm import get_client
        client = get_client()
    rows: List[Dict] = []
    for q in QUESTIONS:
        if only and q["id"] not in only:
            continue
        for t in range(1, repeat + 1):
            log(f"[{q['id']} #{t}] {q['question']}")
            row = {"id": q["id"], "try": t, "question": q["question"]}
            try:
                row["baseline"] = await run_baseline(q["question"], fns.get("rag_stream_fn"))
            except Exception as e:  # 한쪽이 실패해도 계속
                row["baseline"] = {"route": "simple", "answer": "", "sources": [], "latency_s": 0, "error": repr(e)}
            try:
                row["service"] = await run_service(q["question"], row["baseline"], fns.get("route_fn"),
                                                   fns.get("agent_stream_fn"))
            except Exception as e:
                row["service"] = {"route": "error", "answer": "", "sources": [], "latency_s": 0, "error": repr(e)}
            for m in ("baseline", "service"):
                try:
                    row[m]["score"] = await asyncio.to_thread(judge_answer, q, row[m]["answer"], client, judge_model)
                except Exception as e:
                    row[m]["judge_error"] = repr(e)
            sb, sa = row["baseline"].get("score"), row["service"].get("score")
            log(f"   기존 {_pct(sb and sb['coverage'])} 틀림 {sb and sb['wrong']} | "
                f"서비스({row['service'].get('route')}) {_pct(sa and sa['coverage'])} 틀림 {sa and sa['wrong']}")
            rows.append(row)
    return rows


def save(rows: List[Dict], summary: Dict, meta: Dict) -> Tuple[Path, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    jp = RESULTS_DIR / f"service_compare_{ts}.json"
    jp.write_text(json.dumps({"meta": meta, "summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
                  encoding="utf-8")
    mp = RESULTS_DIR / f"service_compare_{ts}.md"
    mp.write_text(to_markdown(rows, summary, meta), encoding="utf-8")
    return jp, mp


def main() -> int:
    p = argparse.ArgumentParser(description="기존 검색 vs 현재 서비스 (실제 서비스 코드·설정 기준)")
    p.add_argument("--only", help="Q7,E3 처럼 일부 질문만 (Q7, LANG, GKSW, E2, E3)")
    p.add_argument("--repeat", type=int, default=1, help="질문당 반복 횟수 (기본 1)")
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    p.add_argument("--label", default="")
    args = p.parse_args()
    only = set(args.only.split(",")) if args.only else None
    meta = {"started_at": datetime.now().isoformat(timespec="seconds"), "label": args.label, "repeat": args.repeat,
            "judge_model": args.judge_model, "models": _models(), "questions": QUESTIONS}
    try:
        import subprocess
        meta["git_commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                            text=True, cwd=Path(__file__).resolve().parent).stdout.strip()
    except Exception:
        meta["git_commit"] = None
    rows = asyncio.run(compare(only, args.repeat, args.judge_model))
    summary = summarize(rows)
    print_summary(summary)
    jp, mp = save(rows, summary, meta)
    print(f"\n결과 저장: {jp}\n보고서: {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
