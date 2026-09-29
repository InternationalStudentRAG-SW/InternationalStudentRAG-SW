"""
인용·검색어 대조용 정규화 (①②④ 공통).

문서 청크는 PDF를 마크다운 표로 바꾼 것이라 `|`, `<br>`, `**` 같은 기호가 많다.
LLM은 인용할 때 이 기호를 빼고 자연스럽게 옮기는 경우가 많아서, 기호 차이 때문에
올바른 인용을 버리지 않도록 양쪽을 같은 방식으로 정규화한 뒤 비교한다.

  1. NFKC 정규화 (전각 문자 등 통일)
  2. 짧은 HTML 태그(<br>, <br/>, </td> 등)를 공백으로
  3. 유니코드 문자·숫자가 아닌 것(공백, 표 기호, 마크다운, 구두점)을 모두 제거
  4. 소문자

문자·숫자 판정은 유니코드 기준이라 한국어·영어뿐 아니라 베트남어·중국어 등
사용자 메시지 인용도 그대로 남는다. (한글·영문만 남기면 다른 언어 인용이 빈 문자열이 되어
어디에나 '일치'해 버린다.)
"""
from __future__ import annotations

import re
import unicodedata

_TAG_RE = re.compile(r"<[^<>]{0,20}>")
_NON_WORD_RE = re.compile(r"[\W_]+")
_LIST_SEP_RE = re.compile(r"[,，、;；]")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = _TAG_RE.sub(" ", t)
    return _NON_WORD_RE.sub("", t).lower()


def quote_in_text(quote: str, text: str, min_chars: int = 1) -> bool:
    """
    정규화한 quote가 정규화한 text 안에 있으면 True.
    정규화 후 길이가 min_chars보다 짧으면 False (빈 인용·너무 짧은 인용은 아무 데나 맞으므로).
    """
    q = normalize(quote)
    return len(q) >= max(1, min_chars) and q in normalize(text)


def list_quote_in_text(quote: str, text: str, min_piece_chars: int = 2) -> bool:
    """
    목록 인용 대조. LLM이 표·목록의 항목을 쉼표로 이어 붙여 인용한 경우
    (예: "입학지원서, 자기소개서, 학력조회동의서" ← 원문은 표의 여러 행)
    쉼표·세미콜론으로 나눈 조각이 모두 같은 본문에 '순서대로' 있으면 True.

    지어낸 인용이 통과하지 않도록
      - 조각이 2개 이상이어야 하고, 조각마다 정규화 후 min_piece_chars자 이상
      - 숫자만으로 된 조각이 있으면 목록으로 보지 않는다 ("1,500,000"을 "1"·"500"·"000"으로 쪼개 맞추는 것 방지)
    """
    pieces = [normalize(p) for p in _LIST_SEP_RE.split(quote or "")]
    pieces = [p for p in pieces if p]
    if len(pieces) < 2:
        return False
    if any(len(p) < min_piece_chars or p.isdigit() for p in pieces):
        return False
    body = normalize(text)
    pos = 0
    for p in pieces:
        i = body.find(p, pos)
        if i < 0:
            return False
        pos = i + len(p)
    return True
