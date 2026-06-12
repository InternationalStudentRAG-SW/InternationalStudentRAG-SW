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

TRANSLATE_GROUND_TRUTH_PROMPTS = {
    "en": "Translate the following Korean answer into natural English. Output only the translated answer.",
    "vi": "Dịch câu trả lời tiếng Hàn sau sang tiếng Việt tự nhiên. Chỉ xuất câu trả lời đã dịch.",
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

    def _translate_text(self, text: str, prompt_prefix: str) -> str | None:
        try:
            response = self.llm.invoke(f"{prompt_prefix}\n\n{text}")
            return response.content.strip()
        except Exception as e:
            print(f"  ⚠️ 번역 실패: {e}, 원문 사용")
            return None

    def _translate_qa_list(self, ko_qa_list: list[dict], target_lang: str, use_cache: bool) -> list[dict]:
        cache_path = os.path.join(OUTPUT_DIR, f"qa_dataset_cache_{target_lang}.json")

        if use_cache and os.path.exists(cache_path):
            cached = json.load(open(cache_path, "r", encoding="utf-8"))
            # ground_truth가 한국어인 구버전 캐시는 재생성
            if cached and re.search(r'[가-힣]', cached[0].get("ground_truth", "")):
                print(f"[{target_lang}] 구버전 캐시 감지 (ground_truth 한국어) → 재번역합니다.")
            else:
                print(f"[{target_lang}] 번역 캐시 로드: {cache_path}")
                return cached

        q_prompt = TRANSLATE_PROMPTS[target_lang]
        gt_prompt = TRANSLATE_GROUND_TRUTH_PROMPTS[target_lang]

        translated = []
        print(f"[{target_lang}] 질문 및 정답 번역 중 ({len(ko_qa_list)}개)...")
        for i, item in enumerate(ko_qa_list):
            print(f"  ⏳ {i+1}/{len(ko_qa_list)} 번째 항목 번역 중...")
            q_result = self._translate_text(item["question"], q_prompt)
            gt_result = self._translate_text(item["ground_truth"], gt_prompt)
            translated.append({
                "question": q_result or item["question"],
                "ground_truth": gt_result or item["ground_truth"],
                "source": item.get("source", ""),
                "original_question": item["question"],
            })

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