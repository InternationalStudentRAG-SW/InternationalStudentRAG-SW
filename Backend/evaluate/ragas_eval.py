import json
import os
from dataclasses import dataclass
from collections import defaultdict
from typing import Optional

from langchain_openai import ChatOpenAI

from app.config import settings
from app.core.knowledge_base import knowledge_base

OUTPUT_DIR = "evaluate/results"
QA_CACHE_PATH = os.path.join(OUTPUT_DIR, "qa_dataset_cache.json")

EVAL_LLM = ChatOpenAI(
    api_key=settings.openai_api_key,
    model="gpt-4o-mini",
    temperature=0,
)

@dataclass
class QAGenerator:
    llm: ChatOpenAI
    max_chunks: int = 30

    def _load_chunks_from_chroma(self) -> list[dict]:
        result = knowledge_base.vector_store._collection.get(include=["documents", "metadatas"])
        chunks = []
        for text, meta in zip(result["documents"], result["metadatas"]):
            chunks.append({"text": text, "metadata": meta or {}})
        return chunks

    def _generate_qa_from_chunk(self, chunk_text: str, source: str = "") -> Optional[dict]:
        prompt = f"""아래 대학교 관련 텍스트를 읽고, 유학생이 궁금해할 만한 질문 1개와 그에 대한 정확한 정답을 생성하세요.
반드시 JSON 형식으로 답변하세요.

[텍스트]: {chunk_text[:1500]}
[출력형식]: {{"question": "질문", "ground_truth": "정답"}}"""
        try:
            response = self.llm.invoke(prompt)
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            result = json.loads(content)
            result["source"] = source
            return result
        except:
            return None

    def generate(self, use_cache: bool = True) -> list[dict]:
        if use_cache and os.path.exists(QA_CACHE_PATH):
            print(f"캐시 파일 로드: {QA_CACHE_PATH}")
            with open(QA_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)

        chunks = self._load_chunks_from_chroma()

        # 파일별 균등 샘플링
        source_map = defaultdict(list)
        for chunk in chunks:
            source = chunk["metadata"].get("source", "unknown")
            source_map[source].append(chunk)

        per_source = max(1, self.max_chunks // len(source_map))
        target_chunks = []
        for source, src_chunks in source_map.items():
            target_chunks.extend(src_chunks[:per_source])
        target_chunks = target_chunks[:self.max_chunks]

        qa_list = []
        print(f"총 {len(target_chunks)}개 청크로부터 QA 생성 중...")
        for i, chunk in enumerate(target_chunks):
            print(f"  ⏳ {i+1}/{len(target_chunks)} 번째 청크 처리 중...")
            qa = self._generate_qa_from_chunk(
                chunk["text"],
                source=chunk["metadata"].get("source", "unknown")
            )
            if qa:
                qa_list.append(qa)

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(QA_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(qa_list, f, ensure_ascii=False, indent=2)
        print(f"QA 데이터셋 저장 완료: {QA_CACHE_PATH} ({len(qa_list)}개)")
        return qa_list


if __name__ == "__main__":
    gen = QAGenerator(llm=EVAL_LLM, max_chunks=30)
    qa_list = gen.generate(use_cache=False)  # 새로 생성할 땐 False

    # 파일별 분포 출력
    from collections import Counter
    sources = [qa["source"] for qa in qa_list]
    print("\n[파일별 QA 분포]")
    for src, cnt in Counter(sources).items():
        print(f"  {src}: {cnt}개")