from fastapi import APIRouter, HTTPException, UploadFile, File
from app.models.schemas import DocumentUploadResponse, DocumentUploadRequest, HealthResponse
from app.core.knowledge_base import knowledge_base
from app.core.ingestion import ingester
import pdfplumber
from io import BytesIO


router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """
    지식베이스에 문서(PDF)를 업로드합니다.

    - **file**: PDF 문서 파일
    """
    try:
        # 파일 콘텐츠 읽기
        content = await file.read()

        # PDF 검증
        if file.filename and not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="PDF 파일만 지원합니다")

        # PDF에서 텍스트 추출
        try:
            pdf_file = BytesIO(content)
            pages_text = []

            with pdfplumber.open(pdf_file) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        pages_text.append(f"--- 페이지 {page_num + 1} ---\n{text}")

            full_text = "\n".join(pages_text)

            if not full_text.strip():
                raise HTTPException(status_code=400, detail="PDF에서 텍스트를 찾을 수 없습니다")

            # 지식베이스에 추가
            knowledge_base.add_pdf_document(file.filename, full_text)

            # 청크 개수 카운팅
            chunk_count = len(full_text.split("\n\n"))

            return DocumentUploadResponse(
                filename=file.filename,
                status="success",
                message=f"문서 '{file.filename}'가 성공적으로 업로드 및 처리되었습니다",
                chunks_created=chunk_count
            )

        except Exception as e:
            raise HTTPException(status_code=400, detail=f"PDF 처리 오류: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"업로드 오류: {str(e)}")


@router.post("/upload-text", response_model=DocumentUploadResponse)
async def upload_text_document(request: DocumentUploadRequest):
    """
    텍스트 콘텐츠를 지식베이스에 직접 업로드합니다.

    - **filename**: 문서의 이름
    - **content**: 텍스트 콘텐츠
    """
    try:
        if not request.content.strip():
            raise HTTPException(status_code=400, detail="콘텐츠는 비어있을 수 없습니다")

        # 지식베이스에 추가
        knowledge_base.add_pdf_document(request.filename, request.content)

        # 청크 개수 추정
        chunk_count = len(request.content.split("\n\n"))

        return DocumentUploadResponse(
            filename=request.filename,
            status="success",
            message=f"문서 '{request.filename}'가 성공적으로 추가되었습니다",
            chunks_created=chunk_count
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"업로드 오류: {str(e)}")


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    시스템 상태와 지식베이스 상태를 확인합니다.
    """
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
    """
    지식베이스에서 모든 문서를 제거합니다.
    경고: 이 작업은 취소할 수 없습니다.
    """
    try:
        knowledge_base.clear_database()

        return {
            "status": "success",
            "message": "지식베이스가 성공적으로 초기화되었습니다"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"데이터베이스 초기화 오류: {str(e)}")
