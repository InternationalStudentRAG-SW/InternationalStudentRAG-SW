import re
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.config import settings


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
        # 영어·중국어·일본어 문자가 없으면 순수 한국어 → 번역 스킵
        if not re.search(r'[a-zA-Z一-鿿぀-ヿ]', user_query):
            return user_query
        try:
            messages = [
                SystemMessage(content=(
                    "다음 텍스트에 포함된 외국어 단어를 모두 한국어로 바꾸세요. "
                    "이미 한국어인 단어는 그대로 두고, 영어·중국어·일본어 등 외국어만 한국어로 교체하세요. "
                    "결과만 출력하고 설명은 하지 마세요."
                )),
                HumanMessage(content=user_query),
            ]
            return self.llm.invoke(messages).content.strip()
        except Exception as e:
            print(f"⚠️ 번역 오류: {e}")
            return user_query


translator = QueryTranslator()
