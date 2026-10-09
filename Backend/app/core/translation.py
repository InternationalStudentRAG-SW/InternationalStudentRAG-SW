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
        한글 비율이 70% 이상이면 원문 반환 (GKS·TOPIK 같은 영어 약어 포함 한국어 질문 처리).
        그 외 언어(영어, 중국어, 일본어 등)는 OpenAI로 한국어 번역.
        BM25 키워드 검색 및 CrossEncoder 리랭킹에 사용.
        """
        alpha_chars = [c for c in user_query if c.isalpha()]
        if alpha_chars:
            ko_ratio = sum(1 for c in alpha_chars if '가' <= c <= '힣') / len(alpha_chars)
            if ko_ratio >= 0.7:
                return user_query
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


    _TARGET_LANG_NAMES = {
        "en": "English",
        "zh": "Chinese",
        "vi": "Vietnamese",
        "es": "Spanish",
        "ja": "Japanese",
    }

    def translate_to_en(self, user_query: str) -> str:
        """원문을 영어로 직접 번역. 이중 번역(원문→한국어→영어) 품질 손실 방지용."""
        alpha_chars = [c for c in user_query if c.isalpha()]
        if alpha_chars:
            en_ratio = sum(1 for c in alpha_chars if 'a' <= c.lower() <= 'z') / len(alpha_chars)
            if en_ratio >= 0.7:
                return user_query
        try:
            domain_terms_hint = _load_domain_terms()
            messages = [
                SystemMessage(content=(
                    "Translate the following text into English. "
                    "Keep official names and codes as-is (GKS, TOPIK, D-4, IELTS, etc.). "
                    f"{domain_terms_hint}\n"
                    "Output only the translated text, no explanations."
                )),
                HumanMessage(content=user_query),
            ]
            return self.llm.invoke(messages).content.strip()
        except Exception as e:
            print(f"⚠️ 번역 오류 (→en): {e}")
            return user_query

    def translate_from_ko(self, text: str, target_lang: str) -> str:
        """한국어 텍스트를 target_lang으로 번역. 캐시 HIT 시 언어 변환에 사용."""
        if target_lang in ("ko", "auto"):
            return text
        lang_name = self._TARGET_LANG_NAMES.get(target_lang, target_lang)
        try:
            messages = [
                SystemMessage(content=(
                    f"Translate the following Korean text into {lang_name}. "
                    "Output only the translated text, no explanations."
                )),
                HumanMessage(content=text),
            ]
            return self.llm.invoke(messages).content.strip()
        except Exception as e:
            print(f"⚠️ 번역 오류 (ko→{target_lang}): {e}")
            return text


translator = QueryTranslator()
