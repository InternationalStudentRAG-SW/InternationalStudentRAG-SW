from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from app.config import settings

router = APIRouter(prefix="/documents", tags=["documents"])

# config.py에서 문서 폴더 경로 가져오기
DOCUMENTS_DIR = Path(settings.document_path).resolve()


@router.get("/{filename}")
def get_document(filename: str):
    file_path = (DOCUMENTS_DIR / filename).resolve()

    # 보안 체크
    if not str(file_path).startswith(str(DOCUMENTS_DIR)):
        raise HTTPException(status_code=400, detail="잘못된 파일 경로입니다.")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    
    # PDF 를 브라우저로 반환
    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="application/pdf",
        content_disposition_type="attachment", # 다운로드 기능
    )