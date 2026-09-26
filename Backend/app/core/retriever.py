import os
import time
from typing import List, Tuple, Optional, Dict, Any, Literal

from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers.ensemble import EnsembleRetriever
from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

from app.core.knowledge_base import knowledge_base
from app.config import settings


# ===========================================================================
# Hugging Face 설정
# ===========================================================================

if settings.hf_token:
    os.environ["HF_TOKEN"] = settings.hf_token


RetrieverMode = Literal["vector", "hybrid", "hybrid_rerank"]


# ===========================================================================
# RAG Retriever
# ===========================================================================

class RAGRetriever:

    def __init__(
        self,
        mode: RetrieverMode = "hybrid"
    ):
        self.top_k = settings.top_k_results

        self.initial_fetch_k = getattr(
            settings,
            "initial_fetch_k",
            self.top_k
        )

        self.min_similarity = settings.min_similarity_score
        self.mode = mode

        # ---------------------------------------------------------------
        # 성능 측정값 저장
        # ---------------------------------------------------------------
        # llm.py에서 최종 요약 로그를 출력할 때 사용
        self.last_metrics: Dict[str, Any] = {}

        # vector_search_only() 측정값
        self.last_vector_only_time: float = 0.0

        self._initialize_retriever()


    # =======================================================================
    # Retriever 초기화
    # =======================================================================

    def _initialize_retriever(self):

        db_data = knowledge_base.vector_store.get()

        fetch_k = (
            self.initial_fetch_k
            if self.mode == "hybrid_rerank"
            else self.top_k
        )


        # -------------------------------------------------------------------
        # 1. Vector Retriever
        # -------------------------------------------------------------------

        vector_k = (
            fetch_k
            if self.mode == "hybrid_rerank"
            else self.top_k
        )

        self.vector_retriever = (
            knowledge_base.vector_store.as_retriever(
                search_kwargs={
                    "k": vector_k
                }
            )
        )


        # -------------------------------------------------------------------
        # Vector Only
        # -------------------------------------------------------------------

        if self.mode == "vector":

            self.retriever = self.vector_retriever

            print(
                "Vector 검색기 초기화 완료 "
                f"(k={vector_k})"
            )

            return


        # -------------------------------------------------------------------
        # DB가 비어 있는 경우
        # -------------------------------------------------------------------

        if not db_data or not db_data["documents"]:

            print("지식베이스가 비어있습니다.")

            self.retriever = self.vector_retriever

            return


        # -------------------------------------------------------------------
        # 2. BM25 + Vector Hybrid
        # -------------------------------------------------------------------

        langchain_docs = [

            Document(
                page_content=text,
                metadata=meta
            )

            for text, meta in zip(
                db_data["documents"],
                db_data["metadatas"]
            )
        ]


        self.keyword_retriever = (
            BM25Retriever.from_documents(
                langchain_docs
            )
        )

        self.keyword_retriever.k = fetch_k


        self._rrf = EnsembleRetriever(
            retrievers=[
                self.keyword_retriever,
                self.vector_retriever
            ],
            weights=[
                0.5,
                0.5
            ],
        )


        # -------------------------------------------------------------------
        # Hybrid
        # -------------------------------------------------------------------

        if self.mode == "hybrid":

            print(
                "하이브리드 검색기(BM25 + Vector) 초기화 완료 "
                f"(k={fetch_k})"
            )

            return


        # -------------------------------------------------------------------
        # 3. Hybrid + BGE Reranker
        # -------------------------------------------------------------------

        if self.mode == "hybrid_rerank":

            print("BGE Reranker 로딩 중...")

            reranker_load_start = time.perf_counter()

            self.reranker = CrossEncoder(
                "BAAI/bge-reranker-v2-m3"
            )

            reranker_load_time = (
                time.perf_counter()
                - reranker_load_start
            )

            print(
                "하이브리드 + BGE Reranker 초기화 완료 "
                f"(fetch_k={fetch_k}, "
                f"load={reranker_load_time:.3f}s)"
            )


    # =======================================================================
    # Vector Search Only
    # =======================================================================

    def vector_search_only(
        self,
        query: str,
        k: Optional[int] = None
    ) -> List[Document]:
        """
        번역 없이 원문으로 벡터 검색만 수행.

        chat.py에서 번역과 병렬 실행하기 위해 사용하는 메서드.

        기존에는 여기서 매번 로그를 출력했지만,
        이제 시간만 last_vector_only_time에 저장합니다.
        """

        fetch_k = k or self.initial_fetch_k

        start = time.perf_counter()

        docs = (
            knowledge_base.vector_store.similarity_search(
                query,
                k=fetch_k
            )
        )

        elapsed = (
            time.perf_counter()
            - start
        )

        # 출력하지 않고 저장만 함
        self.last_vector_only_time = elapsed

        return docs


    # =======================================================================
    # Main Retrieval
    # =======================================================================

    def retrieve(
        self,
        query: str,
        k: Optional[int] = None,
        ko_query: Optional[str] = None,
        prefetched_vector_docs: Optional[List[Document]] = None
    ) -> List[Document]:

        # -------------------------------------------------------------------
        # 전체 Retrieval 시간
        # -------------------------------------------------------------------

        total_start = time.perf_counter()


        bm25_q_ko = ko_query or query
        vector_q = query
        rerank_q = ko_query or query


        # -------------------------------------------------------------------
        # 성능 측정 변수
        # -------------------------------------------------------------------

        bm25_time = 0.0
        vector_time = 0.0
        rrf_time = 0.0
        rerank_time = 0.0

        bm25_count = 0
        vector_count = 0
        candidate_count = 0

        vector_was_prefetched = (
            prefetched_vector_docs is not None
        )


        # ===================================================================
        # Hybrid / Hybrid + Rerank
        # ===================================================================

        if self.mode in (
            "hybrid",
            "hybrid_rerank"
        ):

            # ---------------------------------------------------------------
            # 1. BM25
            # ---------------------------------------------------------------

            start = time.perf_counter()

            bm25_docs_ko = (
                self.keyword_retriever.invoke(
                    bm25_q_ko
                )
            )


            # 번역된 한국어 query와 원문 query가 다르면
            # 두 BM25 결과를 RRF로 결합
            if (
                ko_query
                and ko_query != query
            ):

                bm25_docs_orig = (
                    self.keyword_retriever.invoke(
                        query
                    )
                )

                bm25_docs = (
                    self._rrf.weighted_reciprocal_rank(
                        [
                            bm25_docs_ko,
                            bm25_docs_orig
                        ]
                    )
                )

            else:

                bm25_docs = bm25_docs_ko


            bm25_time = (
                time.perf_counter()
                - start
            )

            bm25_count = len(
                bm25_docs
            )


            # ---------------------------------------------------------------
            # 2. Vector Search
            # ---------------------------------------------------------------

            start = time.perf_counter()


            if prefetched_vector_docs is not None:

                vector_docs = (
                    prefetched_vector_docs
                )

            else:

                vector_docs = (
                    self.vector_retriever.invoke(
                        vector_q
                    )
                )


            vector_time = (
                time.perf_counter()
                - start
            )

            vector_count = len(
                vector_docs
            )


            # ---------------------------------------------------------------
            # 3. RRF
            # ---------------------------------------------------------------

            start = time.perf_counter()

            docs = (
                self._rrf.weighted_reciprocal_rank(
                    [
                        bm25_docs,
                        vector_docs
                    ]
                )
            )

            rrf_time = (
                time.perf_counter()
                - start
            )

            candidate_count = len(
                docs
            )


        # ===================================================================
        # Vector Only Mode
        # ===================================================================

        else:

            start = time.perf_counter()


            if prefetched_vector_docs is not None:

                docs = (
                    prefetched_vector_docs
                )

            else:

                docs = (
                    self.vector_retriever.invoke(
                        vector_q
                    )
                )


            vector_time = (
                time.perf_counter()
                - start
            )

            vector_count = len(
                docs
            )

            candidate_count = len(
                docs
            )


        # ===================================================================
        # 4. BGE Reranker
        # ===================================================================

        if self.mode == "hybrid_rerank":

            start = time.perf_counter()


            pairs = [

                [
                    rerank_q,
                    doc.page_content
                ]

                for doc in docs
            ]


            scores = (
                self.reranker.predict(
                    pairs,
                    batch_size=8
                )
            )


            rerank_time = (
                time.perf_counter()
                - start
            )


            scored_docs = sorted(
                zip(
                    scores,
                    docs
                ),
                key=lambda x: x[0],
                reverse=True
            )


            final_k = (
                k or self.top_k
            )

            final_docs = []


            for score, doc in scored_docs[:final_k]:

                doc.metadata[
                    "similarity_score"
                ] = float(score)

                final_docs.append(
                    doc
                )


            total_time = (
                time.perf_counter()
                - total_start
            )


            # ---------------------------------------------------------------
            # 성능 측정값 저장
            # ---------------------------------------------------------------
            # 여기서는 출력하지 않음.
            # llm.py에서 최종 로그 출력 시 사용.

            self.last_metrics = {
                "mode": self.mode,

                "bm25_time": bm25_time,
                "vector_time": vector_time,
                "rrf_time": rrf_time,

                "bge_time": rerank_time,

                "bm25_count": bm25_count,
                "vector_count": vector_count,
                "candidate_count": candidate_count,

                "final_count": len(final_docs),

                "vector_prefetched": vector_was_prefetched,

                "total_time": total_time,
            }


            return final_docs


        # ===================================================================
        # Reranker를 사용하지 않는 경우
        # ===================================================================

        final_k = (
            k or self.top_k
        )

        final_docs = (
            docs[:final_k]
        )

        total_time = (
            time.perf_counter()
            - total_start
        )


        # -------------------------------------------------------------------
        # 성능 측정값 저장
        # -------------------------------------------------------------------

        self.last_metrics = {
            "mode": self.mode,

            "bm25_time": bm25_time,
            "vector_time": vector_time,
            "rrf_time": rrf_time,

            "bge_time": 0.0,

            "bm25_count": bm25_count,
            "vector_count": vector_count,
            "candidate_count": candidate_count,

            "final_count": len(final_docs),

            "vector_prefetched": vector_was_prefetched,

            "total_time": total_time,
        }


        return final_docs


    # =======================================================================
    # Context Formatting
    # =======================================================================

    def format_context(
        self,
        retrieved_docs: List[Document]
    ) -> str:

        if not retrieved_docs:

            return (
                "관련 문서를 찾을 수 없습니다."
            )


        context_parts = []


        for i, doc in enumerate(
            retrieved_docs,
            1
        ):

            source = (
                doc.metadata.get(
                    "source",
                    "알 수 없음"
                )
            )

            page = (
                doc.metadata.get(
                    "page",
                    "-"
                )
            )

            context_parts.append(
                f"[문서 {i}] "
                f"(출처: {source}, "
                f"{page}페이지)\n"
                f"{doc.page_content}"
            )


        return "\n\n".join(
            context_parts
        )


    # =======================================================================
    # Retrieve + Source Information
    # =======================================================================

    def retrieve_with_sources(
        self,
        query: str,
        k: Optional[int] = None,
        ko_query: Optional[str] = None,
        prefetched_vector_docs: Optional[List[Document]] = None
    ) -> Tuple[
        str,
        List[Dict[str, Any]]
    ]:

        docs = self.retrieve(
            query,
            k=k,
            ko_query=ko_query,
            prefetched_vector_docs=prefetched_vector_docs
        )


        context = (
            self.format_context(
                docs
            )
        )


        seen_sources = set()

        sources = []


        for i, doc in enumerate(
            docs
        ):

            source = (
                doc.metadata.get(
                    "source",
                    "알 수 없음"
                )
            )


            if source not in seen_sources:

                seen_sources.add(
                    source
                )

                sources.append(
                    {
                        "source": source,

                        "page": (
                            doc.metadata.get(
                                "page",
                                "-"
                            )
                        ),

                        "chunk_index": (
                            doc.metadata.get(
                                "chunk_index",
                                i
                            )
                        ),

                        "similarity_score": (
                            doc.metadata.get(
                                "similarity_score",
                                0.0
                            )
                        ),

                        "content_preview": (
                            doc.page_content[:50]
                            + "..."
                        ),
                    }
                )


        return (
            context,
            sources
        )


# ===========================================================================
# Retriever Instances
# ===========================================================================

# 실서비스용
retriever = RAGRetriever(
    mode="hybrid_rerank"
)


# 평가용
vector_retriever = RAGRetriever(
    mode="vector"
)

hybrid_retriever = RAGRetriever(
    mode="hybrid"
)

hybrid_rerank_retriever = RAGRetriever(
    mode="hybrid_rerank"
)