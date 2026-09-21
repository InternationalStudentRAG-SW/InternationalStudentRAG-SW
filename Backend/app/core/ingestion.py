from pathlib import Path
from app.config import settings


def sync_documents() -> None:
    """DATA/documents 폴더와 ChromaDB를 증분 동기화."""
    from app.core.knowledge_base import knowledge_base

    document_path = Path(settings.document_path)
    document_path.mkdir(parents=True, exist_ok=True)

    current_pdfs = {f.name: f for f in document_path.glob("*.pdf")}
    existing_data = knowledge_base.vector_store.get()
    existing_filenames = {m["source"] for m in existing_data["metadatas"] if m}

    # 폴더에서 삭제된 파일 → DB 제거
    for filename in existing_filenames - set(current_pdfs):
        knowledge_base.vector_store.delete(where={"source": filename})
        print(f"[삭제] {filename}")

    # DB에 없는 신규 파일 → 추가
    new_files = set(current_pdfs) - existing_filenames
    if not new_files and not (existing_filenames - set(current_pdfs)):
        print("모든 문서가 최신 상태입니다.")
    else:
        print(f"신규 {len(new_files)}개 추가 시작")

    for filename in new_files:
        pages = knowledge_base.splitter.extract_from_pdf(str(current_pdfs[filename]))
        if not pages:
            print(f"  {filename}: 추출 내용 없음")
            continue
        for page in pages:
            knowledge_base.add_document(page["content"], page["metadata"])
        print(f"[추가] {filename} — {len(pages)} 페이지")

    total = knowledge_base.get_document_count()
    print(f"동기화 완료 — 총 청크: {total}")


if __name__ == "__main__":
    sync_documents()
