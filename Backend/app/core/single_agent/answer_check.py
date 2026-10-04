"""
⑤ 답변 검사 (서버 규칙, LLM 호출 없음).

배경 (2026-10-03 안정성 확인)
  ④는 근거 인용을 원문과 대조하지만, ⑤가 쓴 답변 문장은 아무도 확인하지 않았다.
  그래서 근거에 없는 서류("건강보험 가입 증명서")나 숫자를 지어내고 [1]을 붙여도 그대로 나갔다.

검사 단위
  답변을 문장·글머리표 단위로 나누고, 단위마다 붙은 [번호]의 근거 청크(원문 전체)와 대조한다.
  번호가 없는 단위는 ⑤에 보여준 근거 전체와 대조한다(느슨하게).
  '확인하지 못한 내용', '문의하세요' 같은 안내 문장은 검사하지 않는다.

검사 항목
  1. 숫자: 답변의 숫자(횟수·기간·점수·비율 등)가 근거 본문에 그대로 있어야 한다.
     숫자는 언어와 무관하므로 영어 청크와도 대조한다.
  2. 서류명(한국어): '…증명서', '…신청서', '…사본' 같은 서류 이름이 근거 본문에 있어야 한다.
     '증명서'처럼 머리말만 있으면 아무 데나 맞으므로 앞 낱말까지 붙여서 찾는다("가입 증명서" → "가입증명서").
     인용한 근거에 한글이 없으면(영어 청크만) 번역 차이 때문에 검사하지 않는다.

한계
  숫자가 근거에 있기만 하면 통과한다. "경고 2번이면 자격 상실"처럼 다른 조항의 숫자를 잘못 붙인 경우는
  못 잡는다(근거에 "two (2) academic warnings"가 있으면 통과). 그건 ④ 인용 규칙과 ⑤ 프롬프트 규칙으로 줄인다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.core.single_agent.text_match import normalize

_MARK_RE = re.compile(r"\[(\d+)\]")
_HANGUL_RE = re.compile(r"[가-힣]")

# 문장 끝(마침표 등) 뒤 공백에서 나누되, 바로 뒤가 [번호]면 앞 문장에 붙인다
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+(?!\[\d+\])")
_TRAIL_MARK_RE = re.compile(r"([.!?。])[ \t]*((?:\[\d+\])+)")
# 줄 맨 앞의 글머리표·번호 ("- ", "1. ", "2) ")
_BULLET_RE = re.compile(r"^\s*(?:[-*•·]|\d{1,2}[.)])\s+")
# 숫자: 1,500,000 / 3.5 / 80 (단어 속 숫자 D-2, TOPIK2 등은 앞 글자가 붙어 있어 제외)
_NUM_RE = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)*)(?![\w])|(?<![\w.,])(\d+(?:[.,]\d+)*)(?=[가-힣%])")

DOC_SUFFIXES = (
    "증명서", "증명원", "허가서", "신청서", "확인서", "동의서", "면책서", "내역서", "등록증", "졸업증",
    "보증서", "계획서", "추천서", "소개서", "진단서", "확약서", "서약서", "사본", "통지서", "성적표",
)
# 서류명 뒤에 붙는 조사
_PARTICLE_RE = re.compile(r"(?:으로|에서|와|과|을|를|이|가|은|는|도|만|로|에|의|및)$")
# 앞 낱말로 붙이지 않을 말
_PREV_STOP = {"및", "등", "또는", "그리고", "서류", "필요", "제출", "각종", "기타", "관련", "해당", "추가"}

# 이런 문장은 '확인 못 함·문의 안내'라서 검사하지 않는다
SKIP_MARKERS = (
    "확인하지 못", "확인되지 않", "찾지 못", "확인할 수 없", "문의", "알 수 없",
    "could not", "couldn't", "unable to", "not able to", "not confirm", "contact",
    "không tìm thấy", "liên hệ", "未能", "请咨询", "確認できません", "お問い合わせ",
)


@dataclass
class Unit:
    text: str            # 원문 그대로 (재조립용)
    sep: str             # 다음 단위와의 구분자
    numbers: List[int] = field(default_factory=list)  # 붙은 [번호]


@dataclass
class CheckIssue:
    unit_index: int
    kind: str            # "number" / "document"
    item: str
    sentence: str

    def describe(self) -> str:
        what = "숫자" if self.kind == "number" else "서류명"
        return f"{what} '{self.item}' — 문장: \"{self.sentence.strip()[:120]}\""


def split_units(answer: str) -> List[Unit]:
    """줄 → 문장 단위로 나눈다. 구분자를 남겨 두어 일부 문장만 빼고 다시 이어 붙일 수 있게 한다."""
    units: List[Unit] = []
    # "…입니다. [1][2] 다음 문장" → "…입니다[1][2]. 다음 문장" (번호가 앞 문장에 붙도록)
    answer = _TRAIL_MARK_RE.sub(r"\2\1", answer)
    lines = answer.split("\n")
    for li, line in enumerate(lines):
        line_sep = "\n" if li < len(lines) - 1 else ""
        pieces = _SENT_SPLIT_RE.split(line) if line.strip() else [line]
        # split은 구분 공백을 버리므로 단순히 " "로 다시 잇는다
        for pi, piece in enumerate(pieces):
            sep = " " if pi < len(pieces) - 1 else line_sep
            units.append(Unit(text=piece, sep=sep, numbers=[int(n) for n in _MARK_RE.findall(piece)]))
    return units


def join_units(units: List[Unit]) -> str:
    text = "".join(u.text + u.sep for u in units)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _plain(text: str) -> str:
    """검사용: [번호]·글머리표를 지운 문장."""
    t = _MARK_RE.sub(" ", text)
    return _BULLET_RE.sub("", t)


def _numbers_in(text: str) -> List[str]:
    out = []
    for m in _NUM_RE.finditer(_plain(text)):
        n = (m.group(1) or m.group(2) or "").replace(",", "")
        n = n.rstrip(".")
        if n and n not in out:
            out.append(n)
    return out


_EN_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
    "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "once": "1", "twice": "2", "half": "50",
}
_KO_NUMBER_WORDS = {"한": "1", "두": "2", "세": "3", "네": "4", "다섯": "5", "여섯": "6"}


def _evidence_numbers(text: str) -> set:
    t = unicodedata.normalize("NFKC", text or "")
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)
    nums = set(re.findall(r"\d+(?:\.\d+)?", t))
    # 영어 원문의 "Two tardies", 한국어 "두 번"처럼 숫자를 글자로 쓴 경우 (답변은 "2번"으로 씀)
    nums |= {d for w, d in _EN_NUMBER_WORDS.items() if re.search(rf"\b{w}\b", t, re.IGNORECASE)}
    nums |= {d for w, d in _KO_NUMBER_WORDS.items() if re.search(rf"(?<![가-힣]){w}\s?(?:번|회|명|개|달|해|학기)", t)}
    return nums


def _strip_particle(word: str) -> str:
    w = re.sub(r"[^\w가-힣]+$", "", word)
    w = re.sub(r"^[^\w가-힣]+", "", w)
    for _ in range(2):
        stripped = _PARTICLE_RE.sub("", w)
        if stripped != w and stripped.endswith(DOC_SUFFIXES):
            w = stripped
        else:
            break
    return w


def _doc_names_in(text: str) -> List[Tuple[str, str]]:
    """(표시용 서류명, 대조용 정규화 문자열) 목록."""
    words = re.split(r"\s+", _plain(re.sub(r"[()（）\[\]{}<>\"'“”‘’]", " ", text)))
    out: List[Tuple[str, str]] = []
    for i, raw in enumerate(words):
        w = _strip_particle(raw)
        if not w or not _HANGUL_RE.search(w) or not w.endswith(DOC_SUFFIXES):
            continue
        name = [w]
        # 머리말만 있는 낱말("증명서", "가입증명서" 아닌 "증명서")은 앞 낱말을 1~2개 붙인다
        suffix = next(s for s in DOC_SUFFIXES if w.endswith(s))
        j = i - 1
        while len(normalize("".join(name))) <= len(suffix) + 2 and j >= 0 and len(name) < 3:
            prev = re.sub(r"[^\w가-힣]+", "", words[j])
            if not prev or prev in _PREV_STOP or not _HANGUL_RE.search(prev):
                break
            name.insert(0, prev)
            j -= 1
        if len(normalize("".join(name))) <= len(suffix):
            continue  # "증명서" 하나만으로는 판단하지 않음
        shown = " ".join(name)
        key = normalize(shown)
        if all(key != k for _, k in out):
            out.append((shown, key))
    return out


def should_skip(text: str) -> bool:
    low = text.lower()
    return any(m.lower() in low for m in SKIP_MARKERS)


def check_answer(answer: str, evidence_texts: Dict[int, str]) -> Tuple[List[Unit], List[CheckIssue]]:
    """
    evidence_texts: {근거 번호: 청크 원문}. ⑤에 보여준 근거 전체.
    반환: (문장 단위 목록, 문제 목록)
    """
    units = split_units(answer)
    issues: List[CheckIssue] = []
    all_ids = sorted(evidence_texts)
    num_cache = {n: _evidence_numbers(t) for n, t in evidence_texts.items()}
    norm_cache = {n: normalize(t) for n, t in evidence_texts.items()}
    hangul = {n: bool(_HANGUL_RE.search(t or "")) for n, t in evidence_texts.items()}

    for ui, u in enumerate(units):
        if not _plain(u.text).strip() or should_skip(u.text):
            continue
        cited = [n for n in u.numbers if n in evidence_texts] or all_ids
        if not cited:
            continue
        ev_nums = set().union(*(num_cache[n] for n in cited))
        for num in _numbers_in(u.text):
            if num not in ev_nums:
                issues.append(CheckIssue(ui, "number", num, u.text))
        if any(hangul[n] for n in cited):
            body = "".join(norm_cache[n] for n in cited)
            for shown, key in _doc_names_in(u.text):
                if key not in body:
                    issues.append(CheckIssue(ui, "document", shown, u.text))
    return units, issues


def drop_units(units: List[Unit], issues: List[CheckIssue]) -> Tuple[str, List[str]]:
    """문제가 남은 문장을 뺀 답변과, 뺀 문장 목록."""
    bad = {i.unit_index for i in issues}
    kept = [u for i, u in enumerate(units) if i not in bad]
    dropped = [units[i].text.strip() for i in sorted(bad)]
    return join_units(kept), dropped


def feedback_message(issues: List[CheckIssue]) -> str:
    lines = "\n".join(f"- {i.describe()}" for i in issues)
    return (
        "답변을 검사했더니 아래 항목이 그 문장에 붙인 근거 본문에 없습니다.\n"
        f"{lines}\n\n"
        "고치는 방법:\n"
        "- 근거 목록에 실제로 있는 표현(서류 이름·숫자·조건)으로 바꾸거나, 근거가 없으면 그 내용을 지웁니다.\n"
        "- 서류 이름은 근거에 적힌 이름 그대로 씁니다. 근거에 없는 서류를 추가하지 않습니다.\n"
        "- 다른 내용은 바꾸지 않고, 근거 번호 규칙도 그대로 지킵니다.\n"
        '{"answer": "..."} 형식의 JSON만 다시 출력하세요.'
    )
