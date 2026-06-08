# 데이터셋 기반으로 평가 시작
import json
import os
import warnings
from datetime import datetime
import time

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

OUTPUT_DIR = "evaluate/results"
QA_CACHE_PATH = os.path.join(OUTPUT_DIR, "qa_dataset_cache.json")

# 답변 생성용 LLM (build_evaluation_dataset에서 .invoke() 사용)
ANSWER_LLM = ChatOpenAI(
    api_key=settings.openai_api_key,
    model="gpt-4o-mini",
    temperature=0,
)


def load_qa_dataset() -> list[dict]:
    if not os.path.exists(QA_CACHE_PATH):
        raise FileNotFoundError(f"QA 캐시 파일이 없습니다. 먼저 generate_qa.py를 실행하세요.\n경로: {QA_CACHE_PATH}")
    with open(QA_CACHE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_evaluation_dataset(qa_list: list[dict], retriever: RAGRetriever, top_k: int = 3, mode: str = "vector") -> Dataset:
    questions, answers, contexts, ground_truths = [], [], [], []

    print(f"[{mode.upper()}] 검색 결과 수집 중 (k={top_k})...")
    for i, item in enumerate(qa_list):
        q = item["question"]
        print(f"  ⏳ {i+1}/{len(qa_list)} 번째 질문 처리 중...")

        retrieved_docs = retriever.retrieve(q, k=top_k)
        ctx_list = [doc.page_content for doc in retrieved_docs]

        context_str = "\n\n".join(ctx_list)
        context_str = context_str.replace('\x00', '').replace('\ufffd', '')
        context_str = context_str.encode('utf-8', 'ignore').decode('utf-8')

        prompt = f"다음 컨텍스트를 참고하여 답변하세요.\n\n컨텍스트:\n{context_str}\n\n질문: {q}"
        for attempt in range(3):
            try:
                response = ANSWER_LLM.invoke(prompt)
                break
            except Exception as e:
                err = str(e)
                if "requests per day" in err or "RPD" in err:
                    print("  🚫 일일 요청 한도(RPD) 초과. 평가를 중단합니다.")
                    raise SystemExit(1)
                elif "rate_limit" in err.lower() or "429" in err:
                    wait = 60 * (attempt + 1)
                    print(f"  ⚠️ TPM Rate limit, {wait}초 대기 후 재시도...")
                    time.sleep(wait)
                else:
                    raise

        questions.append(q)
        answers.append(response.content)
        contexts.append(ctx_list)
        ground_truths.append(item["ground_truth"])

    return Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths
    })


def main():
    qa_list = load_qa_dataset()
    print(f"QA 데이터셋 로드 완료: {len(qa_list)}개")

    retrievers = {
        "vector": RAGRetriever(mode="vector"),
        "hybrid": RAGRetriever(mode="hybrid"),
        "hybrid_rerank": RAGRetriever(mode="hybrid_rerank"),
    }

    all_summaries = []

    with get_openai_callback() as cb:
        for mode, ret in retrievers.items():
            print("\n" + "="*50)
            print(f" 🚀 실험 시작: {mode.upper()} 모드 평가")
            print("="*50)

            eval_dataset = build_evaluation_dataset(
                qa_list,
                retriever=ret,
                top_k=settings.top_k_results,
                mode=mode
            )

            print(f"[{mode.upper()}] RAGAS 지표 계산 중...")
            ar = AnswerRelevancy()
            ar.question_generation.instruction = (
                "반드시 한국어로만 질문을 생성하세요. "
                "주어진 답변으로부터 해당 답변이 대답할 수 있는 질문을 생성하세요."
            )

            result = evaluate(
                eval_dataset,
                metrics=[Faithfulness(), ar, ContextPrecision(), ContextRecall()],
                llm=ANSWER_LLM,
                embeddings=knowledge_base.embeddings,
            )

            df = result.to_pandas()
            mean_scores = df[['faithfulness', 'answer_relevancy', 'context_precision', 'context_recall']].mean()
            mean_scores['mode'] = mode
            all_summaries.append(mean_scores)

            print(f"\n[{mode.upper()}] 평균 점수:")
            print(mean_scores.drop('mode'))

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            output_path = os.path.join(OUTPUT_DIR, f"{mode}_result_{timestamp}.csv")
            df.to_csv(output_path, index=False)
            print(f"상세 결과 저장 완료: {output_path}")

        print("\n\n" + "="*50)
        print("      API 사용량 요약")
        print("="*50)
        print(f"총 토큰:      {cb.total_tokens:,}")
        print(f"프롬프트 토큰: {cb.prompt_tokens:,}")
        print(f"완성 토큰:    {cb.completion_tokens:,}")
        print(f"총 요청 수:   {cb.successful_requests:,}")
        print(f"예상 비용:    ${cb.total_cost:.4f}")

    print("\n\n" + "★"*50)
    print("      최종 성능 비교 결과 (Summary)")
    print("★"*50)
    summary_df = pd.DataFrame(all_summaries).set_index('mode')
    print(summary_df)

    summary_path = os.path.join(OUTPUT_DIR, "final_comparison_summary.csv")
    summary_df.to_csv(summary_path)
    print(f"\n최종 비교표 저장 완료: {summary_path}")


if __name__ == "__main__":
    main()