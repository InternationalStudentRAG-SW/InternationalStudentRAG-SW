from typing import List, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from app.config import settings


class KnowledgeBase:
    """문서 청킹, 임베딩 및 벡터 데이터베이스를 관리합니다."""

    def __init__(self):
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap
        self.chroma_db_path = settings.chroma_db_path

        # 임베딩 초기화
        self.embeddings = OpenAIEmbeddings(
            api_key=settings.openai_api_key,
            model="text-embedding-3-small"
        )

        # ChromaDB 초기화
        self.vector_store = Chroma(
            embedding_function=self.embeddings,
            persist_directory=self.chroma_db_path,
            collection_name="international_student_rag"
        )

    def split_documents(self, documents: List[str]) -> List[str]:
        """문서를 청크로 분할합니다."""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", " ", ""]
        )

        chunks = []
        for doc in documents:
            doc_chunks = splitter.split_text(doc)
            chunks.extend(doc_chunks)

        return chunks

    def add_documents(
        self,
        documents: List[str],
        metadata: Optional[List[dict]] = None
    ) -> List[str]:
        """임베딩과 함께 지식베이스에 문서를 추가합니다."""
        chunks = self.split_documents(documents)

        # 메타데이터가 제공된 경우 추가
        if metadata is None:
            metadata = [{"source": "document", "chunk_index": i} for i in range(len(chunks))]

        # ChromaDB에 추가
        ids = self.vector_store.add_texts(
            texts=chunks,
            metadatas=metadata
        )

        return ids

    def add_pdf_document(self, filename: str, content: str):
        """지식베이스에 PDF 문서를 추가합니다."""
        chunks = self.split_documents([content])

        metadata = [
            {
                "source": filename,
                "type": "pdf",
                "chunk_index": i
            }
            for i in range(len(chunks))
        ]

        self.vector_store.add_texts(texts=chunks, metadatas=metadata)

    def get_document_count(self) -> int:
        """데이터베이스의 총 청크 수를 반환합니다."""
        return self.vector_store._collection.count()

    def clear_database(self):
        """전체 지식베이스를 초기화합니다."""
        self.vector_store._client.delete_collection(
            name="international_student_rag"
        )
        self.vector_store = Chroma(
            embedding_function=self.embeddings,
            persist_directory=self.chroma_db_path,
            collection_name="international_student_rag"
        )


# 전역 지식베이스 인스턴스
knowledge_base = KnowledgeBase()
