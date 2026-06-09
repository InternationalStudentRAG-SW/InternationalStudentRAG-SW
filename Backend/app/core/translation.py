import re
import json
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.config import settings

_DOMAIN_TERMS_PATH = Path(__file__).parent / "domain_terms.json"


def _load_domain_terms() -> str:
    """ingestion 시 자동 추출된 도메인 용어를 로드하여 프롬프트용 문자열로 반환."""
    if not _DOMAIN_TERMS_PATH.exists():
        return ""
    terms = json.loads(_DOMAIN_TERMS_PATH.read_text(encoding="utf-8"))
    if not terms:
        return ""
    return "번역 시 다음 용어들은 반드시 원문 그대로 유지하세요: " + ", ".join(terms)


class QueryTranslator:
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=0.0,
            max_tokens=256,
        )

    def translate_to_ko(self, user_query: str) -> str:
        """
        한글 문자(가-힣)가 포함되어 있으면 원문 반환 (번역 API 스킵).
        그 외 언어(영어, 중국어, 일본어 등)는 OpenAI로 한국어 번역.
        BM25 키워드 검색 및 CrossEncoder 리랭킹에 사용.
        """
        if not re.search(r'[a-zA-Z一-鿿぀-ヿ]', user_query):
            return user_query
        try:
            domain_terms_hint = _load_domain_terms()
            messages = [
                SystemMessage(content=(
                    "다음 텍스트를 한국어로 번역하세요. "
                    "이미 한국어인 단어는 그대로 두세요. "
                    f"{domain_terms_hint}\n"
                    "결과만 출력하고 설명은 하지 마세요."
                )),
                HumanMessage(content=user_query),
            ]
            return self.llm.invoke(messages).content.strip()
        except Exception as e:
            print(f"⚠️ 번역 오류: {e}")
            return user_query


translator = QueryTranslator()
