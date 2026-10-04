"""
⑤ 금지 규정 검사 (서버 규칙, LLM 호출 없음).

배경 (2026-10-04 본 실험, Q7)
  모집요강 "입학 후 첫 학기에는 휴학 불가"와 GKS 지침 "학기 중 휴학은 부득이한 사유가 있을 때만"을
  ⑤가 3번 모두 섞어서 "부득이한 사유가 없으면 첫 학기에 휴학할 수 없다"고 썼다.
  프롬프트 규칙(10번)과 단서 확인 규칙으로는 막지 못했다. 그래서 답이 나온 뒤 서버가 직접 찾는다.

무엇을 찾나
  1. 금지 근거: ⑤가 facts에 옮긴 인용 중 '불가·할 수 없·금지·not permitted' 같은 허락 금지 문장.
     기간·횟수 상한('1년을 초과할 수 없다', 'shall not exceed')은 금지가 아니라 한도라서 제외한다.
  2. 금지 구간: 답변에서 금지 근거 번호를 붙인 문장, 또는 금지 상황 표현(예: '첫 학기에')이 들어간 문장부터,
     같은 요구의 근거만 붙인(또는 번호가 없는) 문장이 이어지는 동안.
  3. 위반: 금지 구간 안의 문장이 예외·허용 표현('부득이', '불가피', '사유가 없으면', '할 수 있', '허용')을 쓰면서
     금지 근거와 다른 문서의 번호를 붙였거나 번호가 없는 경우.
     금지 근거 문서 스스로 적은 예외(같은 문서 번호)는 문제 삼지 않는다.
     '첫 학기 이후', '두 번째 학기부터'처럼 다른 상황임을 밝힌 문장도 문제 삼지 않는다.

한계
  한국어·영어 답변만 검사한다 (표현 목록이 두 언어뿐). 다른 언어 답변은 그대로 통과한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from app.core.single_agent.answer_check import Unit, join_units, split_units
from app.core.single_agent.text_match import normalize

# 허락 금지 (한도·상한은 제외)
_PROHIBIT_RE = re.compile(
    r"(불가합니다|불가하다|불가함|불가\b|불가\.|할\s*수\s*없|허용되지\s*않|허용하지\s*않|금지|허가하지\s*않|"
    r"not\s+permitted|not\s+allowed|prohibited|may\s+not|cannot|can\s*not|shall\s+not\s+be\s+(?:permitted|allowed))",
    re.I,
)
_LIMIT_RE = re.compile(r"(초과|넘을|넘지|넘어|이내|exceed|more\s+than|beyond|up\s+to)", re.I)

# 예외·허용 표현 ('불가능'은 먼저 지우고 찾는다)
_EXCEPTION_RE = re.compile(
    r"(부득이|불가피|사유가\s*없으면|사유가\s*있|예외|허용될\s*수|허용됩니다|허용되며|가능합니다|가능하며|가능할\s*수|할\s*수\s*있|"
    r"unless|unavoidable|except|may\s+be\s+permitted|permitted\s+only|only\s+(?:under|if|when)|can\s+be\s+allowed|may\s+be\s+allowed)",
    re.I,
)
# 다른 상황임을 밝힌 문장
_OTHER_SITUATION_RE = re.compile(
    r"(이후|부터는|두\s*번째\s*학기|2학기부터|다음\s*학기부터|after\s+the\s+first|from\s+the\s+second|subsequent\s+semester)",
    re.I,
)
_MARK_RE = re.compile(r"\[(\d+)\]")
_SCOPE_MIN = 5   # 금지 상황 표현이 같다고 볼 최소 공통 글자 수 (조사·흔한 말을 지우고 정규화한 뒤)
# 낱말 끝 조사 (비교 전에 지운다: '첫 학기에는 휴학' ↔ '첫 학기에 휴학')
_PARTICLE_END_RE = re.compile(r"(에는|에서는|에서|에게|으로는|으로|로는|에도|에|은|는|이|가|을|를|도|의)$")
# 어느 문장에나 나오는 말 (금지 상황을 가리키지 않음)
_GENERIC_WORDS = {"gks", "장학생", "학생", "외국인", "유학생", "정부초청", "recipient", "recipients", "the", "a", "an",
                  "student", "students", "scholarship", "동아대", "동아대학교", "본교"}
_EVID_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|\n+|\s(?=-\s)|\s(?=[①-⑳])")


@dataclass
class ProhibitionIssue:
    unit_index: int
    sentence: str
    prohibition_number: int
    prohibition_quote: str

    def describe(self) -> str:
        return f"금지 근거 [{self.prohibition_number}]에 다른 허용 조건을 붙임 — 문장: \"{self.sentence.strip()[:120]}\""


@dataclass
class _Rule:
    number: int
    quote: str
    source: str
    ask: str
    scope: str                       # 금지어 앞부분 (정규화)
    same_ask_numbers: Set[int] = field(default_factory=set)
    same_source_numbers: Set[int] = field(default_factory=set)


def is_prohibition(quote: str) -> bool:
    q = quote or ""
    return bool(_PROHIBIT_RE.search(q)) and not _LIMIT_RE.search(q)


def _has_exception(text: str) -> bool:
    t = re.sub(r"불가능", " ", text or "")
    return bool(_EXCEPTION_RE.search(t))


def _core(text: str) -> str:
    """조사·흔한 말을 지우고 정규화한 문자열 ('GKS 장학생은 첫 학기에 휴학' → '첫학기휴학')."""
    words = []
    for w in re.split(r"\s+", _MARK_RE.sub(" ", text or "")):
        w = re.sub(r"[^\w가-힣]+", "", w)
        stripped = _PARTICLE_END_RE.sub("", w) if len(w) > 2 else w
        if stripped and stripped.lower() not in _GENERIC_WORDS:
            words.append(stripped)
    return normalize("".join(words))


def _scope_of(quote: str) -> str:
    m = _PROHIBIT_RE.search(quote or "")
    head = (quote or "")[: m.start()] if m else (quote or "")
    return _core(head)


def _shares_scope(sentence: str, scope: str) -> bool:
    """금지어 앞부분(예: '입학후첫학기휴학')과 _SCOPE_MIN 글자 이상 이어서 같은 부분이 있으면 True."""
    s = _core(sentence)
    if len(scope) < _SCOPE_MIN or not s:
        return False
    for i in range(len(scope) - _SCOPE_MIN + 1):
        if scope[i: i + _SCOPE_MIN] in s:
            return True
    return False


def _ask_groups(facts: List[dict]) -> Dict[str, Set[int]]:
    groups: Dict[str, Set[int]] = {}
    for f in facts or []:
        n = f.get("evidence")
        if isinstance(n, int):
            groups.setdefault(str(f.get("ask", "")), set()).add(n)
    return groups


def _new_rule(n: int, quote: str, ask: str, sources: Dict[int, str], same_ask: Set[int]) -> _Rule:
    src = sources.get(n, "")
    return _Rule(number=n, quote=quote, source=src, ask=ask, scope=_scope_of(quote),
                 same_ask_numbers=set(same_ask) | {n},
                 same_source_numbers={k for k, s in sources.items() if s and s == src} | {n})


def prohibition_rules(facts: List[dict], sources: Dict[int, str],
                      evidence_texts: Optional[Dict[int, str]] = None, answer: str = "") -> List[_Rule]:
    """
    금지 근거를 고른다.
      facts: ⑤가 원문 대조를 통과시킨 인용 {ask, evidence(번호), quote}
      sources: {근거 번호: 문서 이름}
      evidence_texts: {근거 번호: 청크 원문}. ⑤가 금지 문장을 facts에 옮기지 않은 경우를 위해,
        보여준 근거 안의 금지 문장 중 답변 문장과 금지 상황이 겹치는 것도 고른다.
    """
    rules: List[_Rule] = []
    groups = _ask_groups(facts)
    seen = set()
    for f in facts or []:
        n = f.get("evidence")
        quote = str(f.get("quote", ""))
        if not isinstance(n, int) or f.get("verified") is False or not is_prohibition(quote):
            continue
        key = (n, normalize(quote))
        if key in seen:
            continue
        seen.add(key)
        ask = str(f.get("ask", ""))
        rules.append(_new_rule(n, quote, ask, sources, groups.get(ask, set())))

    if evidence_texts and answer:
        answer_units = [u.text for u in split_units(answer)]
        for n, text in evidence_texts.items():
            for sent in _EVID_SPLIT_RE.split(text or ""):
                sent = sent.strip(" -|*")
                if not sent or not is_prohibition(sent):
                    continue
                key = (n, normalize(sent))
                if key in seen or any(normalize(sent) in k[1] or k[1] in normalize(sent) for k in seen if k[0] == n):
                    continue
                scope = _scope_of(sent)
                if not any(_shares_scope(u, scope) for u in answer_units):
                    continue
                seen.add(key)
                same_ask: Set[int] = set()
                for ask, nums in groups.items():
                    if _shares_scope(ask, scope):
                        same_ask |= nums
                rules.append(_new_rule(n, sent, "", sources, same_ask))
    return rules


def find_issues(answer: str, facts: List[dict], sources: Dict[int, str],
                evidence_texts: Optional[Dict[int, str]] = None) -> List[ProhibitionIssue]:
    rules = prohibition_rules(facts, sources, evidence_texts, answer)
    if not rules:
        return []
    units = split_units(answer)
    issues: List[ProhibitionIssue] = []
    seen: Set[int] = set()
    for r in rules:
        in_block = False
        for ui, u in enumerate(units):
            nums = set(u.numbers)
            starts = r.number in nums or _shares_scope(u.text, r.scope)
            if starts:
                in_block = True
            elif in_block and nums and not nums <= r.same_ask_numbers:
                in_block = False      # 다른 요구의 근거로 넘어감
            if not in_block or ui in seen:
                continue
            if not _has_exception(u.text) or _OTHER_SITUATION_RE.search(u.text):
                continue
            if u.text.strip().rstrip("[]0123456789").endswith(("?", "？")):
                continue              # 되묻는 문장
            foreign = nums - r.same_source_numbers
            if nums and not foreign:
                continue              # 금지 문서 스스로 적은 예외
            seen.add(ui)
            issues.append(ProhibitionIssue(ui, u.text, r.number, r.quote))
    issues.sort(key=lambda i: i.unit_index)
    return issues


def feedback_message(issues: List[ProhibitionIssue]) -> str:
    rules = []
    for i in issues:
        line = f"- 금지 근거 [{i.prohibition_number}]: \"{i.prohibition_quote.strip()[:200]}\""
        if line not in rules:
            rules.append(line)
    sents = "\n".join(f"- \"{i.sentence.strip()[:200]}\"" for i in issues)
    return (
        "답변을 검사했더니 '불가' 근거에 다른 규정의 예외·허용 조건이 붙었습니다.\n"
        + "\n".join(rules)
        + f"\n문제 문장:\n{sents}\n\n"
        "고치는 방법:\n"
        "- 금지 근거가 말하는 상황(예: 입학 후 첫 학기)에는 '불가'라고만 씁니다. '부득이한 사유가 없으면', '예외적으로 가능' 같은 말을 붙이지 않습니다.\n"
        "- 다른 근거의 허용 조건(예: 학기 중 휴학은 부득이한 사유가 있을 때만)은 금지 상황의 예외가 아닙니다. "
        "꼭 필요하면 그 규정이 적용되는 다른 상황을 밝혀서 따로 씁니다 (예: '첫 학기 이후 학기 중에 휴학하려면 …').\n"
        "- 다른 내용과 근거 번호 규칙은 그대로 둡니다.\n"
        '{"answer": "..."} 형식의 JSON만 다시 출력하세요.'
    )


def fallback_fix(answer: str, issues: List[ProhibitionIssue]) -> str:
    """다시 써도 남으면: 문제 문장을 빼고, 금지 문장이 사라졌으면 금지 근거 원문(한글일 때)을 그 자리에 넣는다."""
    units = split_units(answer)
    bad = {i.unit_index for i in issues}
    kept: List[Unit] = []
    inserted: Set[int] = set()
    for ui, u in enumerate(units):
        if ui not in bad:
            kept.append(u)
            continue
        iss = next(i for i in issues if i.unit_index == ui)
        n = iss.prohibition_number
        scope = _scope_of(iss.prohibition_quote)
        still_there = any(
            not _has_exception(k.text) and (n in k.numbers or (is_prohibition(k.text) and _shares_scope(k.text, scope)))
            for ki, k in enumerate(units) if ki not in bad)
        if n not in inserted and not still_there and re.search(r"[가-힣]", iss.prohibition_quote):
            q = iss.prohibition_quote.strip().rstrip(".")
            kept.append(Unit(text=f"{q}[{n}].", sep=u.sep, numbers=[n]))
            inserted.add(n)
        elif kept:
            kept[-1].sep = kept[-1].sep or u.sep
    text = join_units(kept)
    # 앞 문장을 뺐으면 '그러나 …'로 시작하는 문장이 어색하므로 접속어를 지운다
    return re.sub(r"(^|(?<=[.!?。]\s))(그러나|하지만|다만|However,|But)\s+", r"\1", text)
