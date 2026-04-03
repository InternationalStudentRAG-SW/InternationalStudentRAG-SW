import numpy as np
from typing import List, Tuple, Optional, Dict, Any
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.documents import Document
from app.core.knowledge_base import knowledge_base
from app.config import settings

class RAGRetriever:
    """
    Hybrid Search(BM25 + Vector)를 사용하여 관련 문서를 검색합니다.
    단순 키워드 매칭과 의미론적 유사성을 동시에 고려하여 최적의 컨텍스트를 제공합니다.
    """

    def __init__(self):
        self.top_k = settings.top_k_results
        self.min_similarity = settings.min_similarity_score
        self._initialize_hybrid_retriever()

    def _initialize_hybrid_retriever(self):
        """
        ChromaDB에 저장된 데이터를 바탕으로 BM25와 Vector 리트리버를 초기화합니다.
        """
        # 1. Vector Store로부터 원본 데이터 로드 (BM25 학습용)
        # ChromaDB에 저장된 모든 텍스트와 메타데이터를 가져옵니다.
        db_data = knowledge_base.vector_store.get()
        
        if not db_data or not db_data['documents']:
            print("⚠️ 지식베이스가 비어있습니다. 동기화를 먼저 진행하세요.")
            # 비어있는 경우를 대비해 기본 리트리버만 설정 (에러 방지)
            self.retriever = knowledge_base.vector_store.as_retriever(
                search_kwargs={"k": self.top_k}
            )
            return

        # 2. BM25 학습을 위한 Document 객체 리스트 생성
        # BM25는 임베딩이 아닌 '원본 텍스트' 통계(TF-IDF 변형)를 기반으로 작동합니다.
        langchain_docs = [
            Document(page_content=text, metadata=meta) 
            for text, meta in zip(db_data['documents'], db_data['metadatas'])
        ]

        # 3. 개별 리트리버 생성
        # 키워드 기반 (정확한 단어/수치 매칭에 강함)
        keyword_retriever = BM25Retriever.from_documents(langchain_docs)
        keyword_retriever.k = self.top_k

        # 의미 기반 (문장의 맥락과 의도 파악에 강함)
        vector_retriever = knowledge_base.vector_store.as_retriever(
            search_kwargs={"k": self.top_k}
        )

        # 4. 하이브리드 앙상블 리트리버 구축
        # 가중치(weights)를 통해 어떤 검색 방식에 더 비중을 둘지 결정합니다.
        # [0.3, 0.7]은 의미 검색에 더 비중을 두되, 키워드 일치성도 30% 반영함을 의미합니다.
        self.retriever = EnsembleRetriever(
            retrievers=[keyword_retriever, vector_retriever],
            weights=[0.3, 0.7]
        )
        print("✅ 하이브리드 검색기(BM25 + Vector) 초기화 완료")

    def retrieve(self, query: str, k: Optional[int] = None) -> List[Document]:
        """
        쿼리에 대해 하이브리드 검색을 수행하여 관련 문서를 반환합니다.
        
        Returns:
            검색된 Document 객체 리스트 (유사도 점수는 앙상블 시 재계산됨)
        """
        # 앙상블 리트리버는 내부적으로 RRF(Reciprocal Rank Fusion) 알고리즘을 사용해
        # 두 검색 방식의 순위를 재조합합니다.
        return self.retriever.invoke(query)

    def format_context(self, retrieved_docs: List[Document]) -> str:
        """검색된 문서를 LLM에 입력할 컨텍스트 문자열로 변환합니다."""
        if not retrieved_docs:
            return "관련 문서를 찾을 수 없습니다."

        context_parts = []
        for i, doc in enumerate(retrieved_docs, 1):
            source = doc.metadata.get("source", "알 수 없음")
            page = doc.metadata.get("page", "-")
            
            # 출처와 페이지 번호를 명시하여 LLM이 정확한 답변 근거를 갖게 합니다.
            context_parts.append(
                f"[문서 {i}] (출처: {source}, {page}페이지)\n{doc.page_content}"
            )

        return "\n\n".join(context_parts)

    def retrieve_with_sources(self, query: str, k: Optional[int] = None) -> Tuple[str, List[Dict[str, Any]]]:
        """
        질의에 대해 검색을 수행하고, 포맷된 컨텍스트와 출처 목록을 함께 반환합니다.
        """
        docs = self.retrieve(query, k=k)
        context = self.format_context(docs)

        # UI 또는 로그 확인용 출처 리스트 생성
        sources = [
            {
                "source": doc.metadata.get("source", "알 수 없음"),
                "page": doc.metadata.get("page", "-"),
                "chunk_index": doc.metadata.get("chunk_index", i),  # 추가
                "similarity_score": doc.metadata.get("similarity_score", 0.0),  # 추가
                "content_preview": doc.page_content[:50] + "..."
            }
            for i, doc in enumerate(docs)  # enumerate로 변경
        ]
        
        return context, sources

# 싱글톤 객체 생성
retriever = RAGRetriever()