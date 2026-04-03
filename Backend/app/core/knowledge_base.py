from typing import List, Optional, Dict
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from app.config import settings

class KnowledgeBase:
    """문서 청킹, 임베딩 및 벡터 데이터베이스를 관리합니다."""

    def __init__(self):
        # settings에서 값 로드 (chunk_size: 1000, overlap: 200 권장) 
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap
        self.chroma_db_path = settings.chroma_db_path

        # OpenAI 임베딩 초기화 (사용자 지정 모델 적용)
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

    def add_document(self, content: str, metadata: Dict):
        """
        [수정됨] 단일 페이지의 내용과 메타데이터를 받아 청킹 후 ChromaDB에 저장합니다.
        - ingest.py에서 'add_document'를 호출하므로 이름을 맞췄습니다.
        """
        # 1. 텍스트 분할기 설정 (문맥 보존을 위해 overlap 적용) 
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", " ", ""]
        )

        # 2. 현재 페이지 내용을 청크로 분할
        chunks = splitter.split_text(content)

        # 3. 각 청크에 동일한 메타데이터(파일명, 페이지) 적용 + 순번 추가
        chunk_metadatas = []
        for i in range(len(chunks)):
            m = metadata.copy()
            m["chunk_index"] = i # 한 페이지 내에서의 조각 순서
            chunk_metadatas.append(m)

        # 4. ChromaDB에 실제 저장
        self.vector_store.add_texts(
            texts=chunks,
            metadatas=chunk_metadatas
        )

    def get_document_count(self) -> int:
        """데이터베이스에 저장된 총 청크(조각) 수를 반환합니다."""
        return self.vector_store._collection.count()

    def clear_database(self):
        """기존 데이터를 모두 지우고 초기화합니다."""
        self.vector_store.delete_collection()
        self.vector_store = Chroma(
            embedding_function=self.embeddings,
            persist_directory=self.chroma_db_path,
            collection_name="international_student_rag"
        )

# 전역 지식베이스 인스턴스
knowledge_base = KnowledgeBase()