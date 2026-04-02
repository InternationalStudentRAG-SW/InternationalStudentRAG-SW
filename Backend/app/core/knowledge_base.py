# knowledge_base.py
from typing import List, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from app.config import settings
# 전처리 파이프라인 임포트
from app.core.data_preprocessing import HybridPipeline 


class KnowledgeBase:
    """문서 청킹, 임베딩 및 벡터 데이터베이스를 관리합니다."""

    def __init__(self):
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap
        self.chroma_db_path = settings.chroma_db_path
        
        # 하이브리드 전처리 파이프라인 초기화
        self.pipeline = HybridPipeline()

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
        """임베딩(Vector)과 전처리 토큰(Keyword)을 함께 저장합니다."""
        
        # 1. 원문 분할 (Vector Search용)
        chunks = self.split_documents(documents)
        
        # 2. 각 청크별로 전처리 수행 (Keyword Search용 토큰 생성)
        processed_contents = []
        for chunk in chunks:
            # 파이프라인 실행 후 리스트를 공백으로 합쳐서 문자열화
            tokens = self.pipeline.run_pipeline(chunk)
            processed_contents.append(" ".join(tokens))

        # 3. 메타데이터 구성 (노란 줄 해결 버전)
        final_metadata = []
        
        # 입력된 metadata가 없으면 기본값 생성, 있으면 그것을 기반으로 확장
        # 리스트 컴프리헨션을 사용하여 chunks와 길이를 맞춤
        if metadata is None:
            final_metadata = [
                {
                    "source": "document",
                    "chunk_index": i,
                    "processed_content": processed_contents[i]
                }
                for i in range(len(chunks))
            ]
        else:
            # 외부 메타데이터가 있는 경우 안전하게 복사하며 processed_content 주입
            for i, meta in enumerate(metadata):
                # 인덱스 에러 방지: chunks 개수보다 metadata가 많을 경우 대비
                if i >= len(processed_contents):
                    break
                
                new_meta = meta.copy()
                new_meta["chunk_index"] = i
                new_meta["processed_content"] = processed_contents[i]
                final_metadata.append(new_meta)

        # 4. ChromaDB에 추가
        ids = self.vector_store.add_texts(
            texts=chunks,
            metadatas=final_metadata
        )

        return ids

    def add_pdf_document(self, filename: str, content: str):
        """지식베이스에 PDF 문서를 추가합니다."""
        # 단일 문서이므로 리스트로 감싸서 전달
        metadata = [{"source": filename, "type": "pdf"}]
        return self.add_documents([content], metadata=metadata)

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