import os
from dotenv import load_dotenv 

from typing import List, Tuple, Dict, Optional
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from app.core.knowledge_base import knowledge_base
from app.core.data_preprocessing import HybridPipeline
from app.core.translation import QueryTranslator
from app.config import settings

load_dotenv()

class RAGRetriever:
    def __init__(self):
        self.pipeline = HybridPipeline()
        self.translator = QueryTranslator() 
        
        # BGE-Reranker 초기화
        self.reranker = CrossEncoder('BAAI/bge-reranker-v2-m3')
        
        self.bm25 = None
        self.corpus_docs = [] 
        self.doc_mapping = {}  # 문서 순서 추적을 위한 딕셔너리
        self._refresh_bm25()

    def _refresh_bm25(self):
        """지식베이스의 최신 텍스트를 가져와 BM25 색인과 매핑 테이블을 생성합니다."""
        all_data = knowledge_base.get_all_documents()
        if all_data:
            self.corpus_docs = all_data
            
            # 각 문서의 고유 키(source_chunkIndex)와 배열 인덱스를 매핑
            self.doc_mapping = {}
            for idx, d in enumerate(all_data):
                source = d['metadata'].get('source', 'unknown')
                chunk_idx = d['metadata'].get('chunk_index', 0)
                self.doc_mapping[f"{source}_{chunk_idx}"] = idx
                
            # 논문 7단계 전처리 적용 
            tokenized_corpus = [self.pipeline.run_pipeline(d['content']) for d in all_data]
            self.bm25 = BM25Okapi(tokenized_corpus)

    def _normalize_scores(self, scores: np.ndarray) -> np.ndarray:
        """논문 방식의 합산을 위해 점수를 0~1 사이로 정규화합니다."""
        max_score = np.max(scores)
        min_score = np.min(scores)
        if max_score == min_score:
            return np.ones_like(scores)
        return (scores - min_score) / (max_score - min_score)

    def retrieve_vector_only(self, query: str, k=3):
        """[실험 1] Baseline: 단순 벡터 검색"""
        return knowledge_base.vector_store.similarity_search_with_score(query, k=k)

    def retrieve_hybrid(self, query: str, k=5):
        """[가중치 합산 하이브리드] 점수를 정규화하고 Vector에 더 높은 가중치를 부여합니다."""
        # 방어 코드 (DB가 비어있을 경우 에러 방지)
        if not self.corpus_docs or self.bm25 is None:
            return []
            
        expanded_query = self.translator.combine_ko_en(query)
        fast_k = 40 
        alpha = 0.85 
        
        print(f"\n==================================================")
        print(f"🤖 [하이브리드 검색 디버깅 시작] 질문: '{query}'")
        print(f"==================================================")
        
        # 1. Vector 검색
        vec_results = knowledge_base.vector_store.similarity_search_with_score(query, k=fast_k)
        
        # 🚨 추가됨: Vector 검색 결과 확인 (상위 5개)
        print("\n🔍 [Vector (의미 검색) 상위 5개]")
        for i, (doc, score) in enumerate(vec_results[:5]):
            source = doc.metadata.get('source', 'unknown')
            chunk_idx = doc.metadata.get('chunk_index', 0)
            # 텍스트가 너무 길면 잘라서 보여주기 (50글자)
            snippet = doc.page_content.replace('\n', ' ')[:50] + "..." 
            print(f" {i+1}위 | 출처: {source} (청크 {chunk_idx}) | 거리 점수: {score:.4f}")
            print(f"      내용: {snippet}")
        
        # 2. BM25 검색
        tokenized_query = self.pipeline.run_pipeline(expanded_query)
        bm25_scores_all = np.array(self.bm25.get_scores(tokenized_query))
        bm25_top_indices = np.argsort(bm25_scores_all)[::-1][:fast_k]
        
        # 🚨 추가됨: BM25 검색 결과 확인 (상위 5개)
        print("\n🔑 [BM25 (키워드 검색) 상위 5개]")
        for i, idx in enumerate(bm25_top_indices[:5]):
            doc_info = self.corpus_docs[idx]
            source = doc_info['metadata'].get('source', 'unknown')
            chunk_idx = doc_info['metadata'].get('chunk_index', 0)
            score = bm25_scores_all[idx]
            snippet = doc_info['content'].replace('\n', ' ')[:50] + "..."
            print(f" {i+1}위 | 출처: {source} (청크 {chunk_idx}) | 단어 매칭 점수: {score:.4f}")
            print(f"      내용: {snippet}")
            
        print("==================================================\n")

        # --- 점수 정규화 (0.0 ~ 1.0) 준비 ---
        vec_scores_only = [score for _, score in vec_results]
        v_min, v_max = min(vec_scores_only), max(vec_scores_only)
        
        b_min, b_max = min(bm25_scores_all), max(bm25_scores_all)
        
        combined_scores = {}
        
        # --- 3-1. Vector 점수 계산 (가중치 alpha 적용) ---
        for doc, score in vec_results:
            key = f"{doc.metadata.get('source')}_{doc.metadata.get('chunk_index')}"
            if v_max == v_min:
                norm_score = 1.0
            else:
                norm_score = (v_max - score) / (v_max - v_min)
            combined_scores[key] = combined_scores.get(key, 0.0) + (alpha * norm_score)
            
        # --- 3-2. BM25 점수 계산 (가중치 1 - alpha 적용) ---
        for rank, idx in enumerate(bm25_top_indices):
            doc_info = self.corpus_docs[idx]
            key = f"{doc_info['metadata'].get('source')}_{doc_info['metadata'].get('chunk_index')}"
            raw_score = bm25_scores_all[idx]
            if b_max == b_min:
                norm_score = 1.0
            else:
                norm_score = (raw_score - b_min) / (b_max - b_min)
            combined_scores[key] = combined_scores.get(key, 0.0) + ((1.0 - alpha) * norm_score)
            
        # 4. 최종 합산 점수로 내림차순 정렬
        sorted_combined = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
        
        # 5. 결과 조립 (k개만큼 반환)
        hybrid_results = []
        for key, score in sorted_combined[:k]:
            idx = self.doc_mapping.get(key)
            if idx is not None:
                doc_info = self.corpus_docs[idx]
                hybrid_results.append((doc_info['content'], score, doc_info['metadata']))
                
        return hybrid_results

    def retrieve_with_rerank(self, query: str, k=3):
        """[실험 3] Ultimate: 하이브리드 + BGE-Reranker"""
        # 🚨 변경점 2: 리랭커에게 10개가 아닌 '30개'의 후보를 검토하라고 지시합니다!
        candidates = self.retrieve_hybrid(query, k=30)
        
        pairs = [[query, c[0]] for c in candidates]
        rerank_scores = self.reranker.predict(pairs)
        sorted_indices = np.argsort(rerank_scores)[::-1][:k]
        
        final_results = []
        for idx in sorted_indices:
            content, _, metadata = candidates[idx]
            final_results.append((content, float(rerank_scores[idx]), metadata))
            
        return final_results

    def retrieve(self, query: str, k=5, mode="hybrid_rerank"):
        if mode == "vector":
            docs = self.retrieve_vector_only(query, k=k)
            return [(d[0].page_content, d[1], d[0].metadata) for d in docs]
        elif mode == "hybrid":
            return self.retrieve_hybrid(query, k=k)
        else:
            return self.retrieve_with_rerank(query, k=k)
        
    def format_context(self, retrieved_docs: List[Tuple[str, float, dict]]) -> str:
        if not retrieved_docs:
            return "관련 문서를 찾을 수 없습니다."

        context_parts = []
        for i, (content, score, metadata) in enumerate(retrieved_docs, 1):
            source = metadata.get("source", "알 수 없음")
            chunk_idx = metadata.get("chunk_index", 0)
            
            # 🚨 수정됨: 점수(score)를 프롬프트에서 제거했습니다!
            context_parts.append(
                f"[문서 {i}] (출처: {source}, 청크 {chunk_idx})\n{content}"
            )
        return "\n\n".join(context_parts)

    def retrieve_with_sources(self, query: str, k: Optional[int] = None) -> Tuple[str, List[dict]]:
        if k is None:
            k = settings.top_k_results
            
        docs = self.retrieve(query, k=k, mode="vector") 
        context = self.format_context(docs)

        sources = [
            {
                "source": metadata.get("source", "알 수 없음"),
                "chunk_index": metadata.get("chunk_index", 0),
                "similarity_score": float(score)
            }
            for _, score, metadata in docs
        ]
        return context, sources

retriever = RAGRetriever()