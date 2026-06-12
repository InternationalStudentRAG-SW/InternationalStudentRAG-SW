import argparse
import json
import os
from datetime import datetime
import time
from ragas.run_config import RunConfig

from langchain_community.callbacks import get_openai_callback

import pandas as pd
from datasets import Dataset
from langchain_openai import ChatOpenAI
from ragas import evaluate
from ragas.metrics import (
    Faithfulness,
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
)

from app.config import settings
from app.core.knowledge_base import knowledge_base
from app.core.retriever import RAGRetriever
from app.core.translation import translator
from app.core.llm import rag_chain

OUTPUT_DIR = "evaluate/results"
TARGET_LANGUAGES = ["ko", "en", "vi"]
MODES = ["hybrid_rerank"]

EVAL_LLM = ChatOpenAI(
    api_key=settings.openai_api_key,
    model="gpt-4o-mini",
    temperature=0,
)

def get_metrics_for_lang(lang: str) -> list:
    ar = AnswerRelevancy()
    if lang == "ko":
        ar.question_generation.instruction = (
            "반드시 한국어로만 질문을 생성하세요. "
            "주어진 답변으로부터 해당 답변이 대답할 수 있는 질문을 생성하세요."
        )
    elif lang == "en":
        ar.question_generation.instruction = (
            "Generate questions in English only. "
            "Generate a question that the given answer can answer."
        )
    elif lang == "vi":
        ar.question_generation.instruction = (
            "Chỉ tạo câu hỏi bằng tiếng Việt. "
            "Tạo câu hỏi mà câu trả lời đã cho có thể trả lời được."
        )
    return [Faithfulness(), ar, ContextPrecision(), ContextRecall()]


def load_qa_dataset(lang: str) -> list[dict]:
    if lang == "ko":
        path = os.path.join(OUTPUT_DIR, "qa_dataset_cache.json")
    else:
        path = os.path.join(OUTPUT_DIR, f"qa_dataset_cache_{lang}.json")

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"[{lang}] QA 캐시 파일이 없습니다. 먼저 generate_multilingual_qa.py를 실행하세요.\n경로: {path}"
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_evaluation_dataset(
    qa_list: list[dict],
    retriever: RAGRetriever,
    lang: str,
    top_k: int = 3,
    mode: str = "hybrid_rerank",
) -> Dataset:
    questions, answers, contexts, ground_truths = [], [], [], []

    print(f"[{lang.upper()} / {mode.upper()}] 검색 결과 수집 중 (k={top_k})...")
    for i, item in enumerate(qa_list):
        q = item["question"]
        print(f"  ⏳ {i+1}/{len(qa_list)} 번째 질문 처리 중...")

        # 비한국어 질문은 한국어로 변환 후 검색
        if lang == "ko":
            ko_query = None
        else:
            ko_query = item.get("original_question") or translator.translate_to_ko(q)
        retrieved_docs = retriever.retrieve(q, k=top_k, ko_query=ko_query)
        ctx_list = [
            doc.page_content.replace('\x00', '').replace('\ufffd', '').encode('utf-8', 'ignore').decode('utf-8')
            for doc in retrieved_docs
        ]

        context_str = "\n\n".join(ctx_list)
        answer, _ = rag_chain.generate_answer(
            question=q,
            context=context_str,
            lang=lang,
        )

        questions.append(q)
        answers.append(answer)
        contexts.append(ctx_list)
        ground_truths.append(item["ground_truth"])

    return Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths,
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=TARGET_LANGUAGES, default=None,
                        help="평가할 언어 (생략 시 전체 언어 실행)")
    args = parser.parse_args()
    langs_to_run = [args.lang] if args.lang else TARGET_LANGUAGES

    retrievers = {
        mode: RAGRetriever(mode=mode) for mode in MODES
    }

    all_summaries = []

    with get_openai_callback() as cb:
        for lang in langs_to_run:
            try:
                qa_list = load_qa_dataset(lang)
                print(f"[{lang}] QA 데이터셋 로드 완료: {len(qa_list)}개")
            except FileNotFoundError as e:
                print(f"⚠️ {e}")
                continue

            for mode, ret in retrievers.items():
                print(f"\n{'='*55}")
                print(f" 🚀 실험 시작: {lang.upper()} × {mode.upper()} 모드 평가")
                print(f"{'='*55}")

                eval_dataset = build_evaluation_dataset(
                    qa_list,
                    retriever=ret,
                    lang=lang,
                    top_k=settings.top_k_results,
                    mode=mode,
                )

                print(f"[{lang.upper()} / {mode.upper()}] RAGAS 지표 계산 중...")
                result = evaluate(
                    eval_dataset,
                    metrics=get_metrics_for_lang(lang),
                    llm=EVAL_LLM,
                    embeddings=knowledge_base.embeddings,
                    run_config=RunConfig(max_workers=2, timeout=120),
                    raise_exceptions=False,
                )

                df = result.to_pandas()
                mean_scores = df[["faithfulness", "answer_relevancy", "context_precision", "context_recall"]].mean()
                mean_scores["language"] = lang
                mean_scores["mode"] = mode
                all_summaries.append(mean_scores)

                print(f"\n[{lang.upper()} / {mode.upper()}] 평균 점수:")
                print(mean_scores.drop(["language", "mode"]))

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                os.makedirs(OUTPUT_DIR, exist_ok=True)
                output_path = os.path.join(OUTPUT_DIR, f"multilingual_{lang}_{mode}_{timestamp}.csv")
                df.to_csv(output_path, index=False)
                print(f"상세 결과 저장 완료: {output_path}")

        print("\n\n" + "="*55)
        print("      API 사용량 요약")
        print("="*55)
        print(f"총 토큰:      {cb.total_tokens:,}")
        print(f"프롬프트 토큰: {cb.prompt_tokens:,}")
        print(f"완성 토큰:    {cb.completion_tokens:,}")
        print(f"총 요청 수:   {cb.successful_requests:,}")
        print(f"예상 비용:    ${cb.total_cost:.4f}")

    if not all_summaries:
        print("평가할 데이터셋이 없습니다. generate_multilingual_qa.py를 먼저 실행하세요.")
        return

    print(f"\n\n{'★'*55}")
    print("      다국어 검색 성능 비교 (언어 × 모드)")
    print(f"{'★'*55}")
    summary_df = pd.DataFrame(all_summaries).set_index(["language", "mode"])
    print(summary_df)

    summary_path = os.path.join(OUTPUT_DIR, "multilingual_comparison_summary.csv")
    summary_df.to_csv(summary_path)
    print(f"\n최종 비교표 저장 완료: {summary_path}")


if __name__ == "__main__":
    main()