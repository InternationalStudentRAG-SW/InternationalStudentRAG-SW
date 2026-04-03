import os
import numpy as np
from typing import List, Tuple, Optional, Dict, Any, Literal
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.documents import Document
from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever
from sentence_transformers import CrossEncoder
from app.core.knowledge_base import knowledge_base
from app.config import settings

if settings.hf_token:
    os.environ["HF_TOKEN"] = settings.hf_token

RetrieverMode = Literal["vector", "hybrid", "hybrid_rerank"]

class RAGRetriever:
    def __init__(self, mode: RetrieverMode = "hybrid"):
        self.top_k = settings.top_k_results
        self.min_similarity = settings.min_similarity_score
        self.mode = mode
        self._initialize_retriever()

    def _initialize_retriever(self):
        db_data = knowledge_base.vector_store.get()

        # 1. Vector Retriever (공통)
        self.vector_retriever = knowledge_base.vector_store.as_retriever(
            search_kwargs={"k": self.top_k}
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
        keyword_retriever = BM25Retriever.from_documents(langchain_docs)
        keyword_retriever.k = self.top_k

        hybrid_retriever = EnsembleRetriever(
            retrievers=[keyword_retriever, self.vector_retriever],
            weights=[0.35, 0.65]
        )

        if self.mode == "hybrid":
            self.retriever = hybrid_retriever
            print("하이브리드 검색기(BM25 + Vector) 초기화 완료")
            return

        # 3. Hybrid + Reranker
        if self.mode == "hybrid_rerank":
            self.reranker = CrossEncoder("BAAI/bge-reranker-v2-m3")
            self.retriever = hybrid_retriever
            print("하이브리드 + BGE Reranker 초기화 완료")

    def retrieve(self, query: str, k: Optional[int] = None) -> List[Document]:
        docs = self.retriever.invoke(query)
        
        if self.mode == "hybrid_rerank":
            pairs = [[query, doc.page_content] for doc in docs]
            scores = self.reranker.predict(pairs)  # predict()로 변경
            
            scored_docs = sorted(
                zip(scores, docs),
                key=lambda x: x[0],
                reverse=True
            )
            top_k = k or self.top_k
            return [doc for _, doc in scored_docs[:top_k]]
        
        return docs

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

    def retrieve_with_sources(self, query: str, k: Optional[int] = None) -> Tuple[str, List[Dict[str, Any]]]:
        docs = self.retrieve(query, k=k)
        context = self.format_context(docs)
        sources = [
            {
                "source": doc.metadata.get("source", "알 수 없음"),
                "page": doc.metadata.get("page", "-"),
                "chunk_index": doc.metadata.get("chunk_index", i),
                "similarity_score": doc.metadata.get("similarity_score", 0.0),
                "content_preview": doc.page_content[:50] + "..."
            }
            for i, doc in enumerate(docs)
        ]
        return context, sources


# 실서비스용 모델
retriever = RAGRetriever(mode="hybrid_rerank")

# 평가용 모델
vector_retriever = RAGRetriever(mode="vector")
hybrid_retriever = RAGRetriever(mode="hybrid")
hybrid_rerank_retriever = RAGRetriever(mode="hybrid_rerank")