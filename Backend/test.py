from app.core.ingestion import ingester
from app.core.knowledge_base import knowledge_base

def build_chroma_db():
    print("🚀 ChromaDB 구축을 시작합니다...")

    # 1. 문서 디렉토리(settings.document_path)에서 PDF 파일들 읽기
    # ingester.extract_from_directory()는 (파일명, 전체텍스트) 튜플 리스트를 반환합니다.
    documents = ingester.extract_from_directory()

    if not documents:
        print("❌ 처리할 PDF 파일이 없습니다. 지정된 경로에 PDF 파일을 넣어주세요.")
        return

    for filename, content in documents:
        print(f"📄 '{filename}' 임베딩 및 DB 추가 중...")
        
        # 2. 지식 베이스에 문서 추가
        # 이 과정에서 내부적으로 split_documents -> HybridPipeline(전처리) -> ChromaDB 저장이 수행됩니다.
        doc_id = knowledge_base.add_pdf_document(filename, content)
        
        print(f"✅ '{filename}' 처리 완료 (ID: {len(doc_id)} chunks added)")

    print(f"\n✨ DB 구축 완료! 총 청크 수: {knowledge_base.get_document_count()}")

if __name__ == "__main__":
    build_chroma_db()