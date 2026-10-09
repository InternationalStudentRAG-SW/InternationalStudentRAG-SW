"""
PDF 추출 텍스트의 한국어 띄어쓰기 복원.

배경 (2026-10-02 확인)
  일부 PDF(예: 한국어트랙 모집요강)는 글자 사이에 공백 문자가 없고 글자 간격으로만 띄어 써 있어서,
  pymupdf4llm으로 뽑으면 "입학후첫학기에는휴학불가합니다"처럼 붙은 텍스트가 된다.
  이런 청크는 BM25(단어 일치)·임베딩·리랭커 모두에서 점수가 낮아 검색되지 않는다.

규칙
  1. 줄을 마크다운 기호(|, **, <br>, #, 연속 공백)로 나눈 조각 단위로 본다. 기호는 건드리지 않는다.
  2. 한글이 MIN_HANGUL자 이상이고, 한글 낱말 사이 공백 수 / 한글 글자 수가 MAX_SPACE_RATIO 미만인 조각만 고친다.
     (정상적으로 띄어 쓴 한국어는 대략 0.25~0.4, 붙은 조각은 0~0.1. 영어 낱말의 공백은 세지 않는다)
  3. 띄어쓰기 교정기(Kiwi)의 결과에서 '새로 넣은 공백'만 받아들인다. 원문에 있던 공백은 절대 지우지 않고,
     글자는 하나도 바꾸지 않는다. (Kiwi는 reset_whitespace=False여도 맞는 공백을 지우는 경우가 있음:
     "제출하여야 한다" → "제출하여야한다")
  4. Kiwi가 설치되지 않았으면 원문을 그대로 돌려준다 (색인이 멈추지 않게).

정상 문서에 교정기를 통째로 적용하면 "수학기관장" → "수학 기관장"처럼 고유 용어를 쪼개고 맞는 공백을 지워
오히려 나빠진다. 그래서 붙은 조각에만, 공백 추가만 한다.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

MIN_HANGUL = 6
MAX_SPACE_RATIO = 0.12

_HANGUL_RE = re.compile(r"[가-힣]")
# 마크다운 표·강조·줄바꿈 태그·헤더·연속 공백은 경계로 보고 그대로 둔다
_SPLIT_RE = re.compile(r"(\*\*|\||<br\s*/?>|^#{1,6} |\s{2,})")

_NO_SPACE_AFTER = set("·ㆍ/(<[{~-")
_NO_SPACE_BEFORE = set("·ㆍ/)>]},.~-")

_kiwi = None
_kiwi_failed = False


def _get_kiwi():
    global _kiwi, _kiwi_failed
    if _kiwi is None and not _kiwi_failed:
        try:
            from kiwipiepy import Kiwi
            _kiwi = Kiwi()
        except Exception as e:  # 설치 안 됨 등
            print(f"[spacing] Kiwi를 쓸 수 없어 띄어쓰기 복원을 건너뜀: {e}")
            _kiwi_failed = True
    return _kiwi


def korean_space_ratio(segment: str) -> Optional[float]:
    """
    한글이 들어 있는 낱말 사이의 공백 수 / 한글 글자 수. 영어 낱말·숫자의 공백은 세지 않는다
    (영어가 섞인 줄은 전체 공백 비율이 높아 붙은 한국어를 놓치기 때문).
    """
    hangul = len(_HANGUL_RE.findall(segment))
    if hangul == 0:
        return None
    kor_tokens = [t for t in segment.split() if _HANGUL_RE.search(t)]
    return max(len(kor_tokens) - 1, 0) / hangul


def needs_spacing(segment: str) -> bool:
    hangul = len(_HANGUL_RE.findall(segment))
    if hangul < MIN_HANGUL:
        return False
    return korean_space_ratio(segment) < MAX_SPACE_RATIO


def insert_spaces_only(original: str, suggested: str) -> str:
    """
    suggested(교정기 결과)에서 원문에 없던 공백만 원문에 끼워 넣는다.
    두 문자열의 공백 아닌 글자가 다르면(교정기가 글자를 바꾼 경우) 원문을 그대로 돌려준다.
    """
    if original.replace(" ", "") != suggested.replace(" ", ""):
        return original
    out = []
    j = 0
    for ch in original:
        if ch == " ":
            out.append(ch)
            if j < len(suggested) and suggested[j] == " ":
                j += 1
            continue
        if j < len(suggested) and suggested[j] == " ":
            # 가운뎃점·괄호·슬래시 옆에는 넣지 않는다 ("학·석사" → "학· 석사" 방지)
            if out and out[-1] != " " and out[-1] not in _NO_SPACE_AFTER and ch not in _NO_SPACE_BEFORE:
                out.append(" ")
            while j < len(suggested) and suggested[j] == " ":
                j += 1
        out.append(ch)
        j += 1
    return "".join(out)


def _space_segment(segment: str, kiwi) -> str:
    lead = segment[: len(segment) - len(segment.lstrip(" "))]
    trail = segment[len(segment.rstrip(" ")):]
    core = segment.strip(" ")
    try:
        suggested = kiwi.space(core, reset_whitespace=False)
    except Exception:
        return segment
    return lead + insert_spaces_only(core, suggested) + trail


def restore_spacing(text: str) -> Tuple[str, int]:
    """
    붙어 있는 한국어 조각에 공백을 넣는다. (고친 텍스트, 고친 조각 수)를 돌려준다.
    """
    if not text or not _HANGUL_RE.search(text):
        return text, 0
    kiwi = None
    fixed = 0
    lines = []
    for line in text.split("\n"):
        parts = _SPLIT_RE.split(line)
        for i, part in enumerate(parts):
            if i % 2 == 1 or not part or not needs_spacing(part):
                continue  # 홀수 번째는 구분 기호
            if kiwi is None:
                kiwi = _get_kiwi()
                if kiwi is None:
                    return text, 0
            new = _space_segment(part, kiwi)
            if new != part:
                parts[i] = new
                fixed += 1
        lines.append("".join(parts))
    return "\n".join(lines), fixed


def spacing_stats(text: str) -> Optional[float]:
    """한글 글자 수 대비 공백 비율 (한글이 없으면 None). 확인 스크립트용."""
    hangul = len(_HANGUL_RE.findall(text or ""))
    return None if hangul == 0 else round((text or "").count(" ") / hangul, 3)
