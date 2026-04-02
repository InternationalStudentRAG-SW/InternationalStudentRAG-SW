# retrievar.py
from typing import List, Tuple, Optional
from app.core.knowledge_base import knowledge_base
from app.config import settings


class RAGRetriever:
    """벡터 유사도 검색을 사용하여 관련 문서를 검색합니다."""

    def __init__(self):
        self.top_k = settings.top_k_results
        self.min_similarity = settings.min_similarity_score

    def retrieve(
        self,
        query: str,
        k: Optional[int] = None,
        min_similarity: Optional[float] = None
    ) -> List[Tuple[str, float, dict]]:
        """
        쿼리에 대해 상위 k개의 유사한 문서를 검색합니다.

        Args:
            query: 사용자 쿼리 문자열
            k: 결과 개수 (기본값: settings.top_k_results)
            min_similarity: 최소 유사도 임계값 (기본값: settings.min_similarity_score)

        Returns:
            (콘텐츠, 점수, 메타데이터) 튜플의 목록
        """
        if k is None:
            k = self.top_k
        if min_similarity is None:
            min_similarity = self.min_similarity

        # 유사도 점수로 검색
        results = knowledge_base.vector_store.similarity_search_with_score(
            query,
            k=k
        )

        # 최소 유사도로 필터링하고 결과 포맷팅
        retrieved_docs = []
        for doc, score in results:
            # ChromaDB의 유사도 점수는 이미 정규화됨 (0-1)
            if score >= min_similarity:
                retrieved_docs.append(
                    (doc.page_content, score, doc.metadata)
                )

        return retrieved_docs

    def format_context(
        self,
        retrieved_docs: List[Tuple[str, float, dict]]
    ) -> str:
        """검색된 문서를 LLM용 컨텍스트로 포맷팅합니다."""
        if not retrieved_docs:
            return "관련 문서를 찾을 수 없습니다."

        context_parts = []
        for i, (content, score, metadata) in enumerate(retrieved_docs, 1):
            source = metadata.get("source", "알 수 없음")
            chunk_idx = metadata.get("chunk_index", 0)
            context_parts.append(
                f"[문서 {i}] (출처: {source}, 청크 {chunk_idx}, 점수: {score:.2f})\n{content}"
            )

        return "\n\n".join(context_parts)

    def retrieve_with_sources(
        self,
        query: str,
        k: Optional[int] = None
    ) -> Tuple[str, List[dict]]:
        """
        문서를 검색하고 출처 정보와 함께 포맷된 컨텍스트를 반환합니다.

        Returns:
            (포맷된_컨텍스트, 출처_목록)
        """
        docs = self.retrieve(query, k=k)
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
