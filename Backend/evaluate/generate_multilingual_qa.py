import json
import os
import re

from langchain_openai import ChatOpenAI
from datasets import Dataset

from app.config import settings
from app.core.retriever import RAGRetriever
from app.core.translation import translator

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


def translate_qa_list(qa_list: list[dict], target_lang: str) -> list[dict]:
    cache_path = os.path.join(OUTPUT_DIR, f"qa_dataset_cache_{target_lang}.json")

    if os.path.exists(cache_path):
        print(f"[{target_lang}] 번역 캐시 로드: {cache_path}")
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    translated = []
    print(f"[{target_lang}] 질문 번역 중 ({len(qa_list)}개)...")
    for i, item in enumerate(qa_list):
        print(f"  ⏳ {i+1}/{len(qa_list)} 번째 질문 번역 중...")
        try:
            response = EVAL_LLM.invoke(f"{TRANSLATE_PROMPTS[target_lang]}\n\n{item['question']}")
            translated.append({
                "question": response.content.strip(),
                "ground_truth": item["ground_truth"],
                "source": item.get("source", ""),
                "original_question": item["question"],
            })
        except Exception as e:
            print(f"  ⚠️ 번역 실패: {e}, 원문 사용")
            translated.append({**item, "original_question": item["question"]})

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(translated, f, ensure_ascii=False, indent=2)
    print(f"[{target_lang}] 번역 캐시 저장: {cache_path}")
    return translated


def build_and_save_dataset(
    qa_list: list[dict],
    retriever: RAGRetriever,
    lang: str,
    top_k: int,
    mode: str,
):
    save_path = os.path.join(OUTPUT_DIR, f"multilingual_dataset_{lang}_{mode}.json")

    if os.path.exists(save_path):
        print(f"[{lang}/{mode}] 데이터셋 캐시 존재, 스킵: {save_path}")
        return

    questions, answers, contexts, ground_truths = [], [], [], []

    print(f"[{lang.upper()} / {mode.upper()}] 검색 결과 수집 중 (k={top_k})...")
    for i, item in enumerate(qa_list):
        q = item["question"]
        print(f"  ⏳ {i+1}/{len(qa_list)} 번째 질문 처리 중...")

        ko_query = None if lang == "ko" else translator.translate_to_ko(q)
        retrieved_docs = retriever.retrieve(q, k=top_k, ko_query=ko_query)
        ctx_list = [
            doc.page_content.replace('\x00', '').replace('\ufffd', '').encode('utf-8', 'ignore').decode('utf-8')
            for doc in retrieved_docs
        ]

        context_str = "\n\n".join(ctx_list)
        response = EVAL_LLM.invoke(
            f"다음 컨텍스트를 참고하여 답변하세요.\n\n컨텍스트:\n{context_str}\n\n질문: {q}"
        )

        questions.append(q)
        answers.append(response.content)
        contexts.append(ctx_list)
        ground_truths.append(item["ground_truth"])

    data = {
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths,
    }
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[{lang}/{mode}] 데이터셋 저장 완료: {save_path}")


def main():
    if not os.path.exists(QA_CACHE_PATH):
        print(f"QA 캐시가 없습니다. generate_qa.py를 먼저 실행하세요: {QA_CACHE_PATH}")
        return

    with open(QA_CACHE_PATH, "r", encoding="utf-8") as f:
        ko_qa_list = json.load(f)

    ko_qa_list = [q for q in ko_qa_list if re.search(r'[가-힣]', q["question"])]
    print(f"한국어 QA 로드: {len(ko_qa_list)}개")

    qa_by_lang = {"ko": ko_qa_list}
    for lang in TARGET_LANGUAGES:
        qa_by_lang[lang] = translate_qa_list(ko_qa_list, lang)

    retrievers = {
        "hybrid_rerank": RAGRetriever(mode="hybrid_rerank"),
    }

    for lang, qa_list in qa_by_lang.items():
        for mode, ret in retrievers.items():
            build_and_save_dataset(
                qa_list,
                retriever=ret,
                lang=lang,
                top_k=settings.top_k_results,
                mode=mode,
            )

    print("\n모든 데이터셋 생성 완료.")


if __name__ == "__main__":
    main()