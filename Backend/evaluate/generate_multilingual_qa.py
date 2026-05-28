import json
import os
import re
from dataclasses import dataclass, field

from langchain_openai import ChatOpenAI

from app.config import settings

OUTPUT_DIR = "evaluate/results"
QA_CACHE_PATH = os.path.join(OUTPUT_DIR, "qa_dataset_cache.json")

EVAL_LLM = ChatOpenAI(
    api_key=settings.openai_api_key,
    model="gpt-4o-mini",
    temperature=0,
)

TARGET_LANGUAGES = ["en", "vi"]

TRANSLATE_PROMPTS = {
    "en": "Translate the following Korean question into natural English. Output only the translated question.",
    "vi": "Dịch câu hỏi tiếng Hàn sau sang tiếng Việt tự nhiên. Chỉ xuất câu hỏi đã dịch.",
}


@dataclass
class MultilingualQAGenerator:
    llm: ChatOpenAI
    target_languages: list[str] = field(default_factory=lambda: TARGET_LANGUAGES)

    def _load_ko_qa(self) -> list[dict]:
        if not os.path.exists(QA_CACHE_PATH):
            raise FileNotFoundError(
                f"한국어 QA 캐시가 없습니다. 먼저 generate_qa.py를 실행하세요.\n경로: {QA_CACHE_PATH}"
            )
        with open(QA_CACHE_PATH, "r", encoding="utf-8") as f:
            qa_list = json.load(f)

        # 한국어 질문만 필터링
        filtered = [q for q in qa_list if re.search(r'[가-힣]', q["question"])]
        print(f"한국어 QA 로드: {len(filtered)}개 (전체 {len(qa_list)}개 중)")
        return filtered

    def _translate_question(self, question: str, target_lang: str) -> str | None:
        try:
            prompt = f"{TRANSLATE_PROMPTS[target_lang]}\n\n{question}"
            response = self.llm.invoke(prompt)
            return response.content.strip()
        except Exception as e:
            print(f"  ⚠️ 번역 실패: {e}, 원문 사용")
            return None

    def _translate_qa_list(self, ko_qa_list: list[dict], target_lang: str, use_cache: bool) -> list[dict]:
        cache_path = os.path.join(OUTPUT_DIR, f"qa_dataset_cache_{target_lang}.json")

        if use_cache and os.path.exists(cache_path):
            print(f"[{target_lang}] 번역 캐시 로드: {cache_path}")
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)

        translated = []
        print(f"[{target_lang}] 질문 번역 중 ({len(ko_qa_list)}개)...")
        for i, item in enumerate(ko_qa_list):
            print(f"  ⏳ {i+1}/{len(ko_qa_list)} 번째 질문 번역 중...")
            result = self._translate_question(item["question"], target_lang)
            if result:
                translated.append({
                    "question": result,
                    "ground_truth": item["ground_truth"],
                    "source": item.get("source", ""),
                    "original_question": item["question"],
                })
            else:
                translated.append({**item, "original_question": item["question"]})

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(translated, f, ensure_ascii=False, indent=2)
        print(f"[{target_lang}] 번역 캐시 저장: {cache_path}")
        return translated

    def generate(self, use_cache: bool = True) -> dict[str, list[dict]]:
        ko_qa_list = self._load_ko_qa()

        qa_by_lang = {"ko": ko_qa_list}
        for lang in self.target_languages:
            qa_by_lang[lang] = self._translate_qa_list(ko_qa_list, lang, use_cache=use_cache)

        print("\n모든 언어 번역 완료.")
        for lang, qa_list in qa_by_lang.items():
            print(f"  [{lang}] {len(qa_list)}개")

        return qa_by_lang


if __name__ == "__main__":
    gen = MultilingualQAGenerator(llm=EVAL_LLM, target_languages=TARGET_LANGUAGES)
    qa_by_lang = gen.generate(use_cache=False)