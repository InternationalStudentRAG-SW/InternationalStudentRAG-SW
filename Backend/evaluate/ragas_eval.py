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
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

# 프로젝트 모듈 로드
from app.config import settings
from app.core.knowledge_base import knowledge_base
from app.core.retriever import retriever 


# 0. 설정 및 모델 수정
OUTPUT_DIR = "evaluate/results"
QA_CACHE_PATH = os.path.join(OUTPUT_DIR, "qa_dataset_cache.json")

# 평가용 LLM 설정
EVAL_LLM = ChatOpenAI(
    api_key=settings.openai_api_key,
    model="gpt-4o-mini", 
    temperature=0,
)

# 1. QA 데이터셋 생성기
@dataclass
class QAGenerator:
    llm: ChatOpenAI
    max_chunks: int = 10  # 테스트를 위해 우선 10개로 설정

    def _load_chunks_from_chroma(self) -> list[dict]:
        # ChromaDB에서 실제 저장된 데이터 추출
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
            # JSON만 추출하는 로직
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
            if qa: qa_list.append(qa)
            
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(QA_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(qa_list, f, ensure_ascii=False, indent=2)
        return qa_list

# 2. RAGAS 데이터셋 빌더 (Vector 전용)
def build_evaluation_dataset(qa_list: list[dict], top_k: int = 3) -> Dataset:
    questions, answers, contexts, ground_truths = [], [], [], []

    print(f"Vector Search 결과 수집 중 (k={top_k})...")
    for item in qa_list:
        q = item["question"]
        
        # 1. 현재 구현된 retriever.py의 로직 사용
        retrieved_docs = retriever.retrieve(q, k=top_k)
        ctx_list = [doc[0] for doc in retrieved_docs] # 콘텐츠만 추출
        
        # 2. LLM 답변 생성 (llm.py의 프롬프트 구조와 유사하게)
        context_str = "\n\n".join(ctx_list)
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

# 3. 실행 및 결과 출력
def main():
    # 1. 데이터 준비
    gen = QAGenerator(llm=EVAL_LLM, max_chunks=10)
    qa_list = gen.generate(use_cache=True)
    
    if not qa_list:
        print("평가할 QA 데이터가 없습니다.")
        return

    # 2. 결과 수집
    eval_dataset = build_evaluation_dataset(qa_list, top_k=settings.top_k_results)

    # 3. RAGAS 평가
    print("RAGAS 평가 지표 계산 중...")
    result = evaluate(
        eval_dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=EVAL_LLM,
        embeddings=knowledge_base.embeddings # 기존 임베딩 재사용
    )

    # 4. 결과 출력
    print("\n" + "="*50)
    print("       VECTOR SEARCH 평가 결과")
    print("="*50)
    df = result.to_pandas()
    print(df[['faithfulness', 'answer_relevancy', 'context_precision', 'context_recall']].mean())
    print("="*50)

    # 5. 저장
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(OUTPUT_DIR, f"vector_only_result_{timestamp}.csv")
    df.to_csv(output_path, index=False)
    print(f"상세 결과 저장 완료: {output_path}")

if __name__ == "__main__":
    main()