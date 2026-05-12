import kss
import pysbd
from typing import List, Optional, Dict
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from app.config import settings

_MARKDOWN_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]

_PYSBD_SUPPORTED = {
    "en", "hi", "mr", "zh", "es", "am", "ar", "hy", "bg",
    "ur", "ru", "pl", "fa", "nl", "da", "fr", "my", "el",
    "it", "ja", "de", "kk", "sk"
}


class MultilingualSentenceSplitter:
    """
    1단계: MarkdownHeaderTextSplitter — 헤더 경계로 섹션 분리
    2단계: 언어별 문장 분리 (ko → kss, 기타 → pysbd)
    3단계: RecursiveCharacterTextSplitter — 초과 청크 폴백
    """

    def __init__(self, chunk_size: int = 600, chunk_overlap: int = 150):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=_MARKDOWN_HEADERS,
            strip_headers=False,
        )
        self._fallback = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def _split_sentences(self, text: str, lang: str) -> List[str]:
        if lang == "ko":
            try:
                return kss.split_sentences(text, backend="auto")
            except Exception:
                return kss.split_sentences(text, backend="punct")
        else:
            normalized = lang.split("-")[0]  # zh-cn → zh, zh-tw → zh
            pysbd_lang = normalized if normalized in _PYSBD_SUPPORTED else "en"
            seg = pysbd.Segmenter(language=pysbd_lang, clean=False)
            return seg.segment(text)

    def split_text(self, text: str, lang: str = "unknown") -> List[str]:
        sections = self._header_splitter.split_text(text)
        final = []

        for doc in sections:
            section = doc.page_content if hasattr(doc, "page_content") else doc
            if len(section) <= self.chunk_size:
                final.append(section)
                continue

            sents = self._split_sentences(section, lang)

            chunks, cur, cur_len = [], [], 0
            for s in sents:
                if cur_len + len(s) > self.chunk_size and cur:
                    chunks.append(" ".join(cur))
                    overlap, ol = [], 0
                    for prev in reversed(cur):
                        if ol + len(prev) > self.chunk_overlap:
                            break
                        overlap.insert(0, prev)
                        ol += len(prev)
                    cur, cur_len = overlap + [s], ol + len(s)
                else:
                    cur.append(s)
                    cur_len += len(s)
            if cur:
                chunks.append(" ".join(cur))

            for c in chunks:
                if len(c) > self.chunk_size * 1.2:
                    final.extend(self._fallback.split_text(c))
                else:
                    final.append(c)

        return [c for c in final if c.strip()]


class KnowledgeBase:
    """문서 청킹, 임베딩 및 벡터 데이터베이스를 관리합니다."""

    def __init__(self):
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap
        self.chroma_db_path = settings.chroma_db_path

        self.embeddings = OpenAIEmbeddings(
            api_key=settings.openai_api_key,
            model="text-embedding-3-small"
        )

        self.vector_store = Chroma(
            embedding_function=self.embeddings,
            persist_directory=self.chroma_db_path,
            collection_name="international_student_rag"
        )

    def add_document(self, content: str, metadata: Dict) -> int:
        lang = metadata.get("lang", "unknown")
        splitter = MultilingualSentenceSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        chunks = splitter.split_text(content, lang=lang)

        chunk_metadatas = []
        for i in range(len(chunks)):
            m = metadata.copy()
            m["chunk_index"] = i
            chunk_metadatas.append(m)

        self.vector_store.add_texts(texts=chunks, metadatas=chunk_metadatas)
        return len(chunks)

    def get_all_documents(self) -> List[Dict]:
        """BM25 색인을 위해 DB에 저장된 모든 청크와 메타데이터를 가져옵니다."""
        results = self.vector_store.get()
        return [
            {"content": doc, "metadata": meta}
            for doc, meta in zip(results['documents'], results['metadatas'])
        ]

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

    def delete_document_by_filename(self, filename: str):
        try:
            self.vector_store.delete(where={"source": filename})
            print(f"  지식베이스에서 '{filename}' 데이터를 성공적으로 제거했습니다.")
        except Exception as e:
            print(f"  '{filename}' 삭제 중 오류 발생: {e}")


# 전역 지식베이스 인스턴스
knowledge_base = KnowledgeBase()
