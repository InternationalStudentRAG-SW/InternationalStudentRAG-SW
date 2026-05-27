import json
import os
from datetime import datetime

import pandas as pd
from datasets import Dataset
from langchain_openai import ChatOpenAI
from ragas import evaluate
from ragas.metrics import ContextPrecision, ContextRecall

from app.config import settings
from app.core.knowledge_base import knowledge_base

OUTPUT_DIR = "evaluate/results"
TARGET_LANGUAGES = ["ko", "en", "vi"]
MODES = ["hybrid_rerank"]

EVAL_LLM = ChatOpenAI(
    api_key=settings.openai_api_key,
    model="gpt-4o-mini",
    temperature=0,
)


def load_dataset(lang: str, mode: str) -> Dataset | None:
    path = os.path.join(OUTPUT_DIR, f"multilingual_dataset_{lang}_{mode}.json")
    if not os.path.exists(path):
        print(f"⚠️ 데이터셋 없음 (스킵): {path}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Dataset.from_dict(data)


def main():
    all_summaries = []

    for lang in TARGET_LANGUAGES:
        for mode in MODES:
            print(f"\n{'='*55}")
            print(f" 평가: {lang.upper()} × {mode.upper()}")
            print(f"{'='*55}")

            dataset = load_dataset(lang, mode)
            if dataset is None:
                continue

            result = evaluate(
                dataset,
                metrics=[ContextPrecision(), ContextRecall()],
                llm=EVAL_LLM,
                embeddings=knowledge_base.embeddings,
            )

            df = result.to_pandas()
            mean_scores = df[["context_precision", "context_recall"]].mean()
            mean_scores["language"] = lang
            mean_scores["mode"] = mode
            all_summaries.append(mean_scores)

            print(f"\n[{lang.upper()} / {mode.upper()}] 평균 점수:")
            print(mean_scores.drop(["language", "mode"]))

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(OUTPUT_DIR, f"multilingual_{lang}_{mode}_{timestamp}.csv")
            df.to_csv(output_path, index=False)
            print(f"상세 결과 저장: {output_path}")

    if not all_summaries:
        print("평가할 데이터셋이 없습니다. generate_multilingual_dataset.py를 먼저 실행하세요.")
        return

    print(f"\n\n{'★'*55}")
    print("      다국어 검색 성능 비교 (언어 × 모드)")
    print(f"{'★'*55}")
    summary_df = pd.DataFrame(all_summaries).set_index(["language", "mode"])
    print(summary_df)

    summary_path = os.path.join(OUTPUT_DIR, "multilingual_comparison_summary.csv")
    summary_df.to_csv(summary_path)
    print(f"\n최종 비교표 저장: {summary_path}")


if __name__ == "__main__":
    main()