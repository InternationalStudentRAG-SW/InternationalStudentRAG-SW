"""
기존 방식(하이브리드 + BGE 리랭커 → 바로 답변)과 single agent(①~⑤)의 최종 답변을 dev 질문으로 비교한다.

  python -m evaluate.compare_answers                      # dev 9문항, 3회, gpt-4o
  python -m evaluate.compare_answers --only D1,D6 --repeat 1
  python -m evaluate.compare_answers --no-judge           # LLM 심판 없이 자동 채점만

공정 비교: 두 방식 모두 같은 모델(기본 gpt-4o), 같은 코퍼스를 쓴다. 차이는 검색·검증 구조뿐.
시간: 기존 방식은 검색(질문당 1회 측정, 첫 질문은 모델 로딩 포함) + 답변 생성, single agent는 전체 파이프라인.
자동 채점 (dev_questions.py의 gold)
  recall_ctx   : gold 청크 묶음(must_cite + final.outside_pool) 중 답변 모델이 본 청크에 들어간 비율
  recall_cited : 같은 묶음 중 답변이 [번호]로 인용한 청크에 들어간 비율
  bad_cited    : must_not_cite 청크(다른 대상·제도)를 인용한 수 (must_cite에도 있는 청크는 제외)
LLM 심판 (gpt-4o, 두 답변 순서를 섞고 방식 이름은 가림)
  facts        : gold 핵심 사실(final.key_facts) 중 답변에 맞게 들어간 비율
  condition    : 조건·대상별로 답이 갈리는 부분을 제대로 나눴는가 (1~5)
  unsupported  : 핵심 사실과 어긋나거나 근거 없어 보이는 주장 수
  overall      : 종합 (1~5), winner: 더 나은 답변
결과: evaluate/results/compare_<시각>.json, compare_<시각>.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
import zlib
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from evaluate.dev_questions import DEV_QUESTIONS

RESULTS_DIR = Path(__file__).resolve().parent / "results"
DEFAULT_MODEL = "gpt-4o"

BASELINE_SYSTEM = (
    "당신은 동아대학교 유학생 안내 챗봇입니다. 아래 참고 문서만 근거로 답하세요.\n"
    "문서에 없는 내용은 추측하지 말고 확인할 수 없다고 말하세요.\n"
    "근거로 쓴 문장 끝에 참고 문서 번호를 [1]처럼 붙이세요. 질문과 같은 언어로 답하세요."
)

JUDGE_SYSTEM = (
    "당신은 대학 유학생 안내 챗봇의 답변을 채점하는 엄격한 평가자입니다.\n"
    "정답 핵심 사실과 기대하는 답의 모양을 기준으로 두 답변을 각각 채점하고 JSON으로만 출력하세요.\n"
    "- facts_covered: 답변에 맞게 들어간 핵심 사실의 번호 목록 (값이 틀리면 넣지 않음)\n"
    "- condition: 조건·대상(트랙, 과정, 장학생 여부 등)에 따라 답이 갈리는 부분을 제대로 나누거나 되물었는가 1~5"
    " (갈리지 않는 질문이면 불필요한 분기 없이 답했는지로 평가)\n"
    "- unsupported: 핵심 사실과 어긋나거나 근거 없이 단정한 주장 목록 (없으면 [])\n"
    "- overall: 종합 점수 1~5 (정확성 > 조건 처리 > 간결성)\n"
    '출력: {"A": {"facts_covered": [..], "condition": n, "unsupported": [..], "overall": n},'
    ' "B": {...}, "winner": "A"|"B"|"tie", "reason": "한두 문장"}'
)


# ── gold ─────────────────────────────────────────────────────────────────

def gold_groups(q: Dict) -> List[List[str]]:
    g = q["gold"]
    groups = [grp for slot_groups in g["round1"].get("must_cite", {}).values() for grp in slot_groups]
    groups += [[i] for i in g.get("final", {}).get("outside_pool", [])]
    uniq, seen = [], set()
    for grp in groups:
        key = tuple(sorted(grp))
        if key not in seen:
            seen.add(key)
            uniq.append(grp)
    return uniq


def bad_ids(q: Dict) -> set:
    r1 = q["gold"]["round1"]
    good = {i for gs in r1.get("must_cite", {}).values() for grp in gs for i in grp}
    return {i for ids in r1.get("must_not_cite", {}).values() for i in ids} - good


def recall(groups: List[List[str]], ids: List[str]) -> Optional[float]:
    if not groups:
        return None
    s = set(ids)
    return sum(1 for g in groups if s & set(g)) / len(groups)


def cited_numbers(answer: str) -> List[int]:
    return sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer or "")})


# ── 기존 방식 ─────────────────────────────────────────────────────────────

def _default_search(query: str, k: int):
    from app.core.retriever import retriever
    return retriever.retrieve(query, k=k)


def docs_to_contexts(docs) -> List[Dict]:
    from app.core.single_agent.evidence_schema import make_evidence_id
    out, seen = [], set()
    for d in docs:
        meta = getattr(d, "metadata", None) or {}
        try:
            eid = make_evidence_id(meta["source"], int(meta["page"]), int(meta["chunk_index"]))
        except (KeyError, TypeError, ValueError):
            eid = f"{meta.get('source', '?')}#p?#c?{len(out)}"
        if eid in seen:
            continue
        seen.add(eid)
        out.append({"evidence_id": eid, "source": meta.get("source", ""), "page": meta.get("page"),
                    "text": str(getattr(d, "page_content", "") or "")})
    return out


def run_baseline(question: str, contexts: List[Dict], model: str, client, search_ms: int = 0) -> Dict:
    ctx = "\n\n".join(f"[{i}] ({c['source']} p.{c['page']})\n{c['text']}" for i, c in enumerate(contexts, 1))
    t = time.perf_counter()
    resp = client.chat.completions.create(
        model=model, temperature=0,
        messages=[{"role": "system", "content": BASELINE_SYSTEM},
                  {"role": "user", "content": f"## 참고 문서\n{ctx}\n\n## 질문\n{question}"}])
    answer = resp.choices[0].message.content or ""
    u = getattr(resp, "usage", None)
    nums = cited_numbers(answer)
    return {
        "answer": answer, "mode": "baseline",
        "context_ids": [c["evidence_id"] for c in contexts],
        "cited_ids": [contexts[n - 1]["evidence_id"] for n in nums if 1 <= n <= len(contexts)],
        "search_ms": search_ms,
        "latency_ms": search_ms + int((time.perf_counter() - t) * 1000),   # 검색 + 답변 생성
        "tokens": (u.prompt_tokens + u.completion_tokens) if u else 0, "llm_calls": 1,
    }


# ── single agent ─────────────────────────────────────────────────────────

def run_single(question: str, model: str, pipeline_fn: Optional[Callable] = None) -> Dict:
    from evaluate.check_pipeline import summarize
    if pipeline_fn is None:
        from app.core.single_agent.pipeline import run_pipeline as pipeline_fn
    run = pipeline_fn(question, model=model, verify_model=model, answer_model=model)
    a = run.answer_run
    sm = summarize(run)
    pool_ids = list(run.pool.chunks.keys()) if run.pool else []
    shown = list(a.shown_evidence_ids) if a else []
    return {
        "answer": a.answer if a else "", "mode": sm["mode"],
        "context_ids": shown or pool_ids, "pool_ids": pool_ids,
        "cited_ids": [s.evidence_id for s in a.sources] if a else [],
        "latency_ms": run.latency_ms, "tokens": sm["tokens"], "llm_calls": sm["llm_calls"],
        "telemetry": sm,
        "rounds": run.rounds, "stopped": run.stopped,
    }


# ── 심판 ─────────────────────────────────────────────────────────────────

def judge(q: Dict, answers: Dict[str, str], model: str, client, seed: int) -> Dict:
    """answers: {방식: 답변}. 순서를 섞어 A/B로 보여주고, 결과를 방식 이름으로 돌려준다."""
    names = list(answers)
    random.Random(seed).shuffle(names)
    label = dict(zip("AB", names))
    facts = q["gold"]["final"].get("key_facts", [])
    user = (f"## 질문\n{q['question']}\n\n## 기대하는 답의 모양\n{q['gold']['final'].get('mode', '')}\n\n"
            "## 정답 핵심 사실\n" + "\n".join(f"{i}. {f}" for i, f in enumerate(facts, 1)) + "\n\n"
            + "\n\n".join(f"## 답변 {k}\n{answers[v]}" for k, v in label.items()))
    resp = client.chat.completions.create(
        model=model, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}])
    try:
        out = json.loads(resp.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return {"error": "심판 JSON 파싱 실패"}
    res: Dict = {"order": label, "reason": out.get("reason", "")}
    w = out.get("winner")
    res["winner"] = label.get(w, "tie") if w in label else "tie"
    for k, name in label.items():
        s = out.get(k, {}) or {}
        cov = {int(i) for i in s.get("facts_covered", []) if str(i).isdigit() and 1 <= int(i) <= len(facts)}
        res[name] = {"facts": len(cov) / len(facts) if facts else None,
                     "condition": s.get("condition"), "unsupported": len(s.get("unsupported", []) or []),
                     "unsupported_list": s.get("unsupported", []), "overall": s.get("overall")}
    return res


# ── 실행 ─────────────────────────────────────────────────────────────────

def score(q: Dict, r: Dict) -> None:
    groups, bad = gold_groups(q), bad_ids(q)
    r["recall_ctx"] = recall(groups, r["context_ids"])
    r["recall_cited"] = recall(groups, r["cited_ids"])
    r["bad_cited"] = len(set(r["cited_ids"]) & bad)


def compare(only: Optional[set] = None, repeat: int = 3, model: str = DEFAULT_MODEL, k: Optional[int] = None,
            use_judge: bool = True, client=None, search_fn=None, pipeline_fn=None, log=print) -> List[Dict]:
    if client is None:
        from app.core.single_agent.llm import get_client
        client = get_client()
    if k is None:
        from app.config import settings
        k = settings.top_k_results
    search = search_fn or _default_search
    rows: List[Dict] = []
    for q in DEV_QUESTIONS:
        if only and q["id"] not in only:
            continue
        t0 = time.perf_counter()
        contexts = docs_to_contexts(search(q["question"], k))   # 검색은 결정적이라 한 번만 하고 모든 반복에 재사용
        search_ms = int((time.perf_counter() - t0) * 1000)
        for t in range(1, repeat + 1):
            log(f"[{q['id']} #{t}] {q['question']}")
            res: Dict[str, Dict] = {}
            for name, fn in (("baseline", lambda: run_baseline(q["question"], contexts, model, client, search_ms)),
                             ("single_agent", lambda: run_single(q["question"], model, pipeline_fn))):
                try:
                    r = fn()
                except Exception as e:   # 한 방식이 실패해도 비교는 계속
                    r = {"answer": "", "mode": "error", "context_ids": [], "cited_ids": [], "latency_ms": 0,
                         "tokens": 0, "llm_calls": 0, "error": f"{type(e).__name__}: {e}"}
                score(q, r)
                res[name] = r
                log(f"   {name:12s} {r['mode']:20s} recall_ctx={_f(r['recall_ctx'])} "
                    f"cited={_f(r['recall_cited'])} bad={r['bad_cited']} {r['latency_ms'] / 1000:.1f}s {r['tokens']}tok")
            j = None
            if use_judge and all(res[n]["answer"] for n in res):
                try:
                    j = judge(q, {n: res[n]["answer"] for n in res}, model, client, seed=zlib.crc32(f"{q['id']}#{t}".encode()))
                except Exception as e:
                    j = {"error": f"{type(e).__name__}: {e}"}
                if "error" not in j:
                    log(f"   심판: 승자 {j['winner']} | " + " / ".join(
                        f"{n} 사실 {_f(j[n]['facts'])} 조건 {j[n]['condition']} 종합 {j[n]['overall']}" for n in res))
            rows.append({"id": q["id"], "try": t, "question": q["question"], "results": res, "judge": j})
    return rows


def _f(x) -> str:
    return "-" if x is None else f"{x:.2f}"


def _avg(xs) -> Optional[float]:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else None


def summarize_rows(rows: List[Dict]) -> Dict[str, Dict]:
    out = {}
    for name in ("baseline", "single_agent"):
        rs = [r["results"][name] for r in rows]
        js = [r["judge"][name] for r in rows if r.get("judge") and name in r["judge"]]
        out[name] = {
            "recall_ctx": _avg(r["recall_ctx"] for r in rs), "recall_cited": _avg(r["recall_cited"] for r in rs),
            "bad_cited": sum(r["bad_cited"] for r in rs),
            "facts": _avg(j["facts"] for j in js), "condition": _avg(j["condition"] for j in js),
            "unsupported": sum(j["unsupported"] for j in js), "overall": _avg(j["overall"] for j in js),
            "wins": sum(1 for r in rows if r.get("judge") and r["judge"].get("winner") == name),
            "latency_s": _avg(r["latency_ms"] / 1000 for r in rs), "tokens": _avg(r["tokens"] for r in rs),
            "llm_calls": _avg(r["llm_calls"] for r in rs), "errors": sum(1 for r in rs if r.get("error")),
        }
    out["ties"] = sum(1 for r in rows if r.get("judge") and r["judge"].get("winner") == "tie")
    return out


def print_summary(s: Dict, n: int) -> None:
    keys = ["recall_ctx", "recall_cited", "bad_cited", "facts", "condition", "unsupported", "overall", "wins",
            "latency_s", "tokens", "llm_calls", "errors"]
    print(f"\n{'':14s}" + "".join(f"{k:>13s}" for k in ("baseline", "single_agent")))
    for k in keys:
        print(f"{k:14s}" + "".join(
            f"{(_f(s[m][k]) if isinstance(s[m][k], float) else str(s[m][k])):>13s}" for m in ("baseline", "single_agent")))
    print(f"(실행 {n}회, 무승부 {s['ties']})")


def save(rows: List[Dict], summary: Dict, meta: Dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"compare_{ts}.json"
    path.write_text(json.dumps({"meta": meta, "summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    with open(RESULTS_DIR / f"compare_{ts}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "try", "method", "mode", "recall_ctx", "recall_cited", "bad_cited", "facts", "condition",
                    "unsupported", "overall", "winner", "latency_s", "tokens", "llm_calls"])
        for r in rows:
            for name, x in r["results"].items():
                j = (r.get("judge") or {}).get(name, {})
                w.writerow([r["id"], r["try"], name, x["mode"], x["recall_ctx"], x["recall_cited"], x["bad_cited"],
                            j.get("facts"), j.get("condition"), j.get("unsupported"), j.get("overall"),
                            (r.get("judge") or {}).get("winner"), round(x["latency_ms"] / 1000, 1), x["tokens"],
                            x["llm_calls"]])
    return path


def main() -> int:
    p = argparse.ArgumentParser(description="기존 방식 vs single agent 답변 비교 (dev 질문)")
    p.add_argument("--only", help="D1,D6 처럼 일부 질문만")
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--k", type=int, default=None, help="기존 방식 검색 청크 수 (기본 settings.top_k_results)")
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--label", default="", help="실험 변경 이름")
    p.add_argument("--corpus-version", default="", help="문서/색인 버전")
    args = p.parse_args()
    from evaluate.experiment_metadata import experiment_metadata
    metadata = experiment_metadata(args.label, args.corpus_version)
    only = set(args.only.split(",")) if args.only else None
    rows = compare(only, args.repeat, args.model, args.k, not args.no_judge)
    summary = summarize_rows(rows)
    print_summary(summary, len(rows))
    path = save(rows, summary, {**metadata, "model": args.model, "repeat": args.repeat, "k": args.k, "only": args.only,
                                "judge": not args.no_judge})
    print(f"\n결과 저장: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
