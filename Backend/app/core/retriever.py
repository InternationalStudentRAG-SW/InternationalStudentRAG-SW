import os
import numpy as np
from typing import List, Tuple, Optional, Dict, Any, Literal
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers.ensemble import EnsembleRetriever
from langchain_core.documents import Document
from sentence_transformers import CrossEncoder
from app.core.knowledge_base import knowledge_base
from app.config import settings

if settings.hf_token:
    os.environ["HF_TOKEN"] = settings.hf_token

RetrieverMode = Literal["vector", "hybrid", "hybrid_rerank"]

class RAGRetriever:
    def __init__(self, mode: RetrieverMode = "hybrid"):
        self.top_k = settings.top_k_results
        self.initial_fetch_k = getattr(settings, 'initial_fetch_k', self.top_k)
        self.min_similarity = settings.min_similarity_score
        self.mode = mode

        self._initialize_retriever()

    def _initialize_retriever(self):
        db_data = knowledge_base.vector_store.get()

        fetch_k = self.initial_fetch_k if self.mode == "hybrid_rerank" else self.top_k

        # 1. Vector Retriever
        # hybrid_rerank 모드에서는 reranker에 넘길 충분한 후보군 확보를 위해 fetch_k 사용
        vector_k = fetch_k if self.mode == "hybrid_rerank" else self.top_k
        self.vector_retriever = knowledge_base.vector_store.as_retriever(
            search_kwargs={"k": vector_k}
        )

        if self.mode == "vector":
            self.retriever = self.vector_retriever
            print("Vector 검색기 초기화 완료")
            return

        if not db_data or not db_data['documents']:
            print("지식베이스가 비어있습니다.")
            self.retriever = self.vector_retriever
            return

        # 2. BM25 + Vector Hybrid
        langchain_docs = [
            Document(page_content=text, metadata=meta)
            for text, meta in zip(db_data['documents'], db_data['metadatas'])
        ]
        self.keyword_retriever = BM25Retriever.from_documents(langchain_docs)
        self.keyword_retriever.k = fetch_k
        self._rrf = EnsembleRetriever(
            retrievers=[self.keyword_retriever, self.vector_retriever],
            weights=[0.5, 0.5],
        )

        if self.mode == "hybrid":
            print("하이브리드 검색기(BM25 + Vector) 초기화 완료")
            return

        # 3. Hybrid + Reranker
        if self.mode == "hybrid_rerank":
            self.reranker = CrossEncoder("BAAI/bge-reranker-v2-m3")
            print("하이브리드 + BGE Reranker 초기화 완료")

    def vector_search_only(self, query: str, k: Optional[int] = None) -> List[Document]:
        """번역 없이 원문으로 벡터 검색만 수행. 번역과 병렬 실행하기 위한 메서드."""
        fetch_k = k or self.initial_fetch_k
        return knowledge_base.vector_store.similarity_search(query, k=fetch_k)

    def retrieve(self, query: str, k: Optional[int] = None, ko_query: Optional[str] = None,
                 prefetched_vector_docs: Optional[List[Document]] = None) -> List[Document]:
        bm25_q_ko = ko_query or query  # BM25: 한국어 번역 (없으면 원문)
        vector_q  = query              # Vector: 원문 (다국어 임베딩)
        rerank_q  = ko_query or query  # 리랭커: 한국어 번역 (없으면 원문)

        if self.mode in ("hybrid", "hybrid_rerank"):
            bm25_docs_ko = self.keyword_retriever.invoke(bm25_q_ko)

            # 원문이 한국어와 다를 때(영어 등) 원문으로 추가 BM25 → 영어 PDF 커버
            if ko_query and ko_query != query:
                bm25_docs_orig = self.keyword_retriever.invoke(query)
                bm25_docs = self._rrf.weighted_reciprocal_rank(
                    [bm25_docs_ko, bm25_docs_orig]
                )
            else:
                bm25_docs = bm25_docs_ko

            # 병렬로 미리 가져온 벡터 검색 결과가 있으면 재사용, 없으면 직접 검색
            vector_docs = prefetched_vector_docs if prefetched_vector_docs is not None \
                else self.vector_retriever.invoke(vector_q)
            docs = self._rrf.weighted_reciprocal_rank([bm25_docs, vector_docs])
        else:
            docs = prefetched_vector_docs if prefetched_vector_docs is not None \
                else self.vector_retriever.invoke(vector_q)

        if self.mode == "hybrid_rerank":
            pairs = [[rerank_q, doc.page_content] for doc in docs]
            # batch_size를 작게 나눠서 처리 → MPS/GPU OOM 방지
            scores = self.reranker.predict(pairs, batch_size=8)

            scored_docs = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)

            final_k = k or self.top_k
            final_docs = []
            for score, doc in scored_docs[:final_k]:
                doc.metadata["similarity_score"] = float(score)
                final_docs.append(doc)
            return final_docs

        # hybrid 모드: RRF 결과를 top_k로 자름 (BM25+Vector 합집합이 top_k 초과 가능)
        final_k = k or self.top_k
        return docs[:final_k]

    def format_context(self, retrieved_docs: List[Document]) -> str:
        if not retrieved_docs:
            return "관련 문서를 찾을 수 없습니다."
        context_parts = []
        for i, doc in enumerate(retrieved_docs, 1):
            source = doc.metadata.get("source", "알 수 없음")
            page = doc.metadata.get("page", "-")
            context_parts.append(
                f"[문서 {i}] (출처: {source}, {page}페이지)\n{doc.page_content}"
            )
        return "\n\n".join(context_parts)

    def retrieve_with_sources(self, query: str, k: Optional[int] = None, ko_query: Optional[str] = None,
                              prefetched_vector_docs: Optional[List[Document]] = None) -> Tuple[str, List[Dict[str, Any]]]:
        docs = self.retrieve(query, k=k, ko_query=ko_query, prefetched_vector_docs=prefetched_vector_docs)
        context = self.format_context(docs)

        seen_sources = set()
        sources = []
        for i, doc in enumerate(docs):
            source = doc.metadata.get("source", "알 수 없음")
            if source not in seen_sources:
                seen_sources.add(source)
                sources.append({
                    "source": source,
                    "page": doc.metadata.get("page", "-"),
                    "chunk_index": doc.metadata.get("chunk_index", i),
                    "similarity_score": doc.metadata.get("similarity_score", 0.0),
                    "content_preview": doc.page_content[:50] + "..."
                })

        return context, sources


# 실서비스용 모델
retriever = RAGRetriever(mode="hybrid_rerank")

# 평가용 모델
vector_retriever = RAGRetriever(mode="vector")
hybrid_retriever = RAGRetriever(mode="hybrid")
hybrid_rerank_retriever = RAGRetriever(mode="hybrid_rerank")