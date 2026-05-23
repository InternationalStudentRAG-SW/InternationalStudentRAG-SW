import os
from fastapi import APIRouter, HTTPException, UploadFile, File
from app.models.schemas import DocumentUploadResponse, DocumentUploadRequest, HealthResponse
from app.core.knowledge_base import knowledge_base
from app.core.ingestion import ingester


router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """지식베이스에 PDF 문서를 업로드합니다."""
    if file.filename and not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="PDF 파일만 지원합니다")
    try:
        tmp_path = f"/tmp/{file.filename}"
        with open(tmp_path, "wb") as f:
            f.write(await file.read())

        pages_data = ingester.extract_from_pdf(tmp_path)
        os.unlink(tmp_path)

        if not pages_data:
            raise HTTPException(status_code=400, detail="PDF에서 텍스트를 찾을 수 없습니다")

        total_chunks = sum(
            knowledge_base.add_document(p["content"], p["metadata"])
            for p in pages_data
        )
        return DocumentUploadResponse(
            filename=file.filename,
            status="success",
            message=f"'{file.filename}' 업로드 완료",
            chunks_created=total_chunks
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"업로드 오류: {str(e)}")


@router.post("/upload-text", response_model=DocumentUploadResponse)
async def upload_text_document(request: DocumentUploadRequest):
    """텍스트 콘텐츠를 지식베이스에 직접 업로드합니다."""
    try:
        if not request.content.strip():
            raise HTTPException(status_code=400, detail="콘텐츠는 비어있을 수 없습니다")

        chunk_count = knowledge_base.add_document(
            request.content,
            {"source": request.filename, "page": 1}
        )
        return DocumentUploadResponse(
            filename=request.filename,
            status="success",
            message=f"'{request.filename}' 추가 완료",
            chunks_created=chunk_count
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"업로드 오류: {str(e)}")


@router.get("/documents")
async def list_documents():
    """지식베이스에 저장된 파일 목록을 반환합니다."""
    try:
        data = knowledge_base.vector_store.get()
        filenames = sorted({m["source"] for m in data["metadatas"] if m})
        return {"documents": filenames, "total": len(filenames)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{filename}")
async def delete_document(filename: str):
    """특정 파일을 지식베이스에서 삭제합니다."""
    try:
        knowledge_base.delete_document_by_filename(filename)
        return {"status": "success", "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """시스템 상태와 지식베이스 상태를 확인합니다."""
    try:
        total_chunks = knowledge_base.get_document_count()
        return HealthResponse(
            status="healthy",
            database_status="active",
            total_chunks=total_chunks
        )
    except Exception as e:
        return HealthResponse(
            status="error",
            database_status="error",
            total_chunks=0
        )


@router.post("/clear-database")
async def clear_knowledge_base():
    """지식베이스에서 모든 문서를 제거합니다. 취소 불가."""
    try:
        knowledge_base.clear_database()
        return {"status": "success", "message": "지식베이스가 초기화되었습니다"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"초기화 오류: {str(e)}")
