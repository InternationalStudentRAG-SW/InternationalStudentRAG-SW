import json
import os
import random
from dataclasses import dataclass, field
from collections import defaultdict
from difflib import SequenceMatcher
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

    def _is_valid_chunk(self, text: str) -> bool:
        """깨진 청크 사전 필터링"""
        if len(text.strip()) < 50:
            return False
        if '\x00' in text:
            return False
        if text.count('\ufffd') > len(text) * 0.1:  # 깨진 문자 비율 10% 초과
            return False
        return True

    def _is_duplicate(self, question: str, existing: list[str], threshold: float = 0.8) -> bool:
        """유사 중복 질문 필터링"""
        for q in existing:
            ratio = SequenceMatcher(None, question, q).ratio()
            if ratio >= threshold:
                return True
        return False

    def _generate_qa_from_chunk(self, chunk_text: str, source: str = "") -> Optional[dict]:
        prompt = f"""아래 대학교 관련 텍스트를 읽고, 유학생이 궁금해할 만한 질문 1개와 그에 대한 정확한 정답을 생성하세요.
질문과 정답은 반드시 한국어로 작성하세요.
반드시 JSON 형식으로 답변하세요.

단, 아래 두 경우에만 {{"skip": true}} 를 반환하세요:
1. 텍스트가 목차, 표지, 서명란 등 실질적인 내용이 없는 경우
2. 텍스트가 단순 나열이나 코드로만 이루어져 질문 생성이 불가능한 경우

그 외에는 반드시 질문과 정답을 생성하세요.

[텍스트]: {chunk_text[:1500]}
[출력형식]: {{"question": "질문", "ground_truth": "정답"}}"""
        try:
            response = self.llm.invoke(prompt)
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            result = json.loads(content)
            if result.get("skip"):
                return None
            if not isinstance(result.get("ground_truth"), str):
                return None
            result["source"] = source
            return result
        except json.JSONDecodeError:
            print(f"  ⚠️ JSON 파싱 실패: {content[:100]}")
            return None
        except Exception as e:
            print(f"  ⚠️ 오류 발생: {e}")
            return None

    def _sample_chunks(self, chunks: list[dict]) -> tuple[list[dict], list[dict]]:
        """소스별 균등 랜덤 샘플링 + 나머지를 reserve로 반환"""
        source_map = defaultdict(list)
        for chunk in chunks:
            source = chunk["metadata"].get("source", "unknown")
            source_map[source].append(chunk)

        # 각 소스 내 청크 셔플
        for source in source_map:
            random.shuffle(source_map[source])

        per_source = max(1, self.max_chunks // len(source_map))

        selected = []
        reserve = []
        for source, src_chunks in source_map.items():
            selected.extend(src_chunks[:per_source])
            reserve.extend(src_chunks[per_source:])  # 남은 청크는 reserve로

        # selected가 max_chunks 초과 시 초과분도 reserve로
        if len(selected) > self.max_chunks:
            reserve = selected[self.max_chunks:] + reserve
            selected = selected[:self.max_chunks]

        random.shuffle(reserve)
        return selected, reserve

    def generate(self, use_cache: bool = True) -> list[dict]:
        if use_cache and os.path.exists(QA_CACHE_PATH):
            with open(QA_CACHE_PATH, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if len(cached) >= self.max_chunks:
                print(f"캐시 파일 로드: {QA_CACHE_PATH} ({len(cached)}개)")
                return cached
            print(f"캐시 항목 수({len(cached)}개)가 목표치({self.max_chunks}개)보다 적어 재생성합니다.")

        all_chunks = self._load_chunks_from_chroma()

        # 깨진 청크 사전 필터링
        valid_chunks = [c for c in all_chunks if self._is_valid_chunk(c["text"])]
        filtered_count = len(all_chunks) - len(valid_chunks)
        if filtered_count > 0:
            print(f"  ⚠️ 깨진 청크 {filtered_count}개 제외 (전체 {len(all_chunks)}개 중)")

        target_chunks, reserve_chunks = self._sample_chunks(valid_chunks)

        qa_list = []
        used_questions = []

        def try_chunk(chunk) -> bool:
            """청크에서 QA 생성 시도. 추가 성공 시 True 반환"""
            qa = self._generate_qa_from_chunk(
                chunk["text"],
                source=chunk["metadata"].get("source", "unknown")
            )
            if qa is None:
                return False
            if self._is_duplicate(qa["question"], used_questions):
                print(f"  ⚠️ 유사 중복 질문 스킵: {qa['question'][:50]}")
                return False
            used_questions.append(qa["question"])
            qa_list.append(qa)
            return True

        # 1차: target_chunks 순회
        print(f"총 {len(target_chunks)}개 청크로부터 QA 생성 중...")
        for i, chunk in enumerate(target_chunks):
            print(f"  ⏳ {i+1}/{len(target_chunks)} 번째 청크 처리 중... (현재 {len(qa_list)}개 생성됨)")
            try_chunk(chunk)

        # 2차: 목표치 미달이면 reserve에서 보충
        if len(qa_list) < self.max_chunks:
            print(f"\n목표치 미달 ({len(qa_list)}/{self.max_chunks}개). reserve 청크에서 보충 중...")
            for i, chunk in enumerate(reserve_chunks):
                if len(qa_list) >= self.max_chunks:
                    break
                print(f"  ⏳ reserve {i+1}/{len(reserve_chunks)} 번째 청크 처리 중...")
                try_chunk(chunk)

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(QA_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(qa_list, f, ensure_ascii=False, indent=2)
        print(f"\nQA 데이터셋 저장 완료: {QA_CACHE_PATH} ({len(qa_list)}개)")
        return qa_list


if __name__ == "__main__":
    gen = QAGenerator(llm=EVAL_LLM, max_chunks=30)
    qa_list = gen.generate(use_cache=False)

    from collections import Counter
    sources = [qa["source"] for qa in qa_list]
    print("\n[파일별 QA 분포]")
    for src, cnt in Counter(sources).items():
        print(f"  {src}: {cnt}개")