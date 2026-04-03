import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

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

EVAL_LLM = ChatOpenAI(
    api_key=settings.openai_api_key,
    model="gpt-4o-mini",
    temperature=0,
)

# 1. QA 데이터셋 생성기
@dataclass
class QAGenerator:
    llm: ChatOpenAI
    max_chunks: int = 50

    def _load_chunks_from_chroma(self) -> list[dict]:
        result = knowledge_base.vector_store._collection.get(include=["documents", "metadatas"])
        chunks = []
        for text, meta in zip(result["documents"], result["metadatas"]):
            chunks.append({"text": text, "metadata": meta or {}})
        return chunks

    def _generate_qa_from_chunk(self, chunk_text: str) -> Optional[dict]:
        prompt = f"""아래 대학교 관련 텍스트를 읽고, 유학생이 궁금해할 만한 질문 1개와 그에 대한 정확한 정답을 생성하세요.
반드시 JSON 형식으로 답변하세요.

[텍스트]: {chunk_text[:1500]}
[출력형식]: {{"question": "질문", "ground_truth": "정답"}}"""
        try:
            response = self.llm.invoke(prompt)
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            return json.loads(content)
        except:
            return None

    def generate(self, use_cache: bool = True) -> list[dict]:
        if use_cache and os.path.exists(QA_CACHE_PATH):
            with open(QA_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)

        chunks = self._load_chunks_from_chroma()
        target_chunks = chunks[:self.max_chunks]

        qa_list = []
        print(f"총 {len(target_chunks)}개 청크로부터 QA 생성 중...")
        for chunk in target_chunks:
            qa = self._generate_qa_from_chunk(chunk["text"])
            if qa:
                qa_list.append(qa)

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(QA_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(qa_list, f, ensure_ascii=False, indent=2)
        return qa_list


# 2. RAGAS 데이터셋 빌더 (mode별 RAGRetriever 인스턴스 사용)
def build_evaluation_dataset(qa_list: list[dict], retriever: RAGRetriever, top_k: int = 3, mode: str = "vector") -> Dataset:
    questions, answers, contexts, ground_truths = [], [], [], []

    print(f"[{mode.upper()}] 검색 결과 수집 중 (k={top_k})...")
    for i, item in enumerate(qa_list):
        q = item["question"]
        print(f"  ⏳ {i+1}/{len(qa_list)} 번째 질문 처리 중...")

        # retriever.retrieve()는 Document 객체 리스트 반환
        retrieved_docs = retriever.retrieve(q, k=top_k)
        ctx_list = [doc.page_content for doc in retrieved_docs]  # Document.page_content로 접근

        context_str = "\n\n".join(ctx_list)
        context_str = context_str.replace('\x00', '').replace('\ufffd', '')
        context_str = context_str.encode('utf-8', 'ignore').decode('utf-8')

        prompt = f"다음 컨텍스트를 참고하여 답변하세요.\n\n컨텍스트:\n{context_str}\n\n질문: {q}"
        response = EVAL_LLM.invoke(prompt)

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


# 3. 실행
def main():
    gen = QAGenerator(llm=EVAL_LLM, max_chunks=10)
    qa_list = gen.generate(use_cache=True)

    if not qa_list:
        print("평가할 QA 데이터가 없습니다.")
        return

    # 모드별 RAGRetriever 인스턴스 생성
    retrievers = {
        "vector": RAGRetriever(mode="vector"),
        "hybrid": RAGRetriever(mode="hybrid"),
        "hybrid_rerank": RAGRetriever(mode="hybrid_rerank"),
    }

    all_summaries = []

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
        result = evaluate(
            eval_dataset,
            metrics=[Faithfulness(), AnswerRelevancy(), ContextPrecision(), ContextRecall()],
            llm=EVAL_LLM,
            embeddings=knowledge_base.embeddings
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