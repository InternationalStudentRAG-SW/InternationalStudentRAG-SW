import os
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.models.schemas import DocumentUploadResponse, DocumentUploadRequest, HealthResponse, UpdateRoleRequest, UpdateStatusRequest
from app.core.knowledge_base import knowledge_base
from app.core.ingestion import ingester
from app.core.auth_middleware import get_admin_user
from app.core.llm import rag_chain
from app.db.database import supabase


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/usage")
async def get_api_usage(user: dict = Depends(get_admin_user)):
    """서버 시작 이후 누적 OpenAI API 사용량을 반환합니다."""
    return rag_chain.get_usage()


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...), user: dict = Depends(get_admin_user)):
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
async def upload_text_document(request: DocumentUploadRequest, user: dict = Depends(get_admin_user)):
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
async def list_documents(user: dict = Depends(get_admin_user)):
    """지식베이스에 저장된 파일 목록을 반환합니다."""
    try:
        data = knowledge_base.vector_store.get()
        filenames = sorted({m["source"] for m in data["metadatas"] if m})
        return {"documents": filenames, "total": len(filenames)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{filename}")
async def delete_document(filename: str, user: dict = Depends(get_admin_user)):
    """특정 파일을 지식베이스에서 삭제합니다."""
    try:
        knowledge_base.delete_document_by_filename(filename)
        return {"status": "success", "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=HealthResponse)
async def health_check(user: dict = Depends(get_admin_user)):
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
async def clear_knowledge_base(user: dict = Depends(get_admin_user)):
    """지식베이스에서 모든 문서를 제거합니다. 취소 불가."""
    try:
        knowledge_base.clear_database()
        return {"status": "success", "message": "지식베이스가 초기화되었습니다"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"초기화 오류: {str(e)}")


@router.get("/chat-logs")
async def get_chat_logs(
    page: int = 1,
    limit: int = 20,
    language: str = "",
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    user: dict = Depends(get_admin_user),
):
    """채팅 로그 목록을 페이지네이션으로 반환."""
    try:
        offset = (page - 1) * limit
        q = supabase.table("chat_logs").select("*", count="exact").order("created_at", desc=True)
        if language:
            q = q.eq("language", language)
        if search:
            q = q.ilike("query", f"%{search}%")
        if date_from:
            q = q.gte("created_at", date_from)
        if date_to:
            q = q.lte("created_at", date_to + "T23:59:59")
        res = q.range(offset, offset + limit - 1).execute()
        return {"logs": res.data, "total": res.count, "page": page, "limit": limit}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat-stats")
async def get_chat_stats(user: dict = Depends(get_admin_user)):
    """채팅 로그 요약 통계를 반환."""
    try:
        today = date.today().isoformat()
        total_res = supabase.table("chat_logs").select("id", count="exact").execute()
        today_res = supabase.table("chat_logs").select("id", count="exact").gte("created_at", today).execute()
        lang_res = supabase.table("chat_logs").select("language").execute()
        lang_counts: dict = {}
        for row in lang_res.data:
            lang = row.get("language") or "auto"
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
        return {
            "total": total_res.count,
            "today": today_res.count,
            "by_language": lang_counts,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat-daily")
async def get_chat_daily(user: dict = Depends(get_admin_user)):
    """최근 7일 일별 질문 수 반환."""
    from datetime import timedelta
    try:
        result = []
        for i in range(6, -1, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            res = supabase.table("chat_logs") \
                .select("id", count="exact") \
                .gte("created_at", d) \
                .lte("created_at", d + "T23:59:59") \
                .execute()
            result.append({"date": d[5:], "count": res.count})
        return {"daily": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================
# 회원 관리
# ============================

@router.get("/users")
async def get_users(
    page: int = 1,
    limit: int = 20,
    role: str = "",
    status: str = "",
    search: str = "",
    user: dict = Depends(get_admin_user),
):
    """회원 목록을 페이지네이션으로 반환."""
    try:
        offset = (page - 1) * limit
        q = supabase.table("users").select("*", count="exact").order("created_at", desc=True)
        if role:
            q = q.eq("role", role)
        if status:
            q = q.eq("status", status)
        if search:
            q = q.ilike("email", f"%{search}%")
        res = q.range(offset, offset + limit - 1).execute()
        return {"users": res.data, "total": res.count, "page": page, "limit": limit}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user-stats")
async def get_user_stats(user: dict = Depends(get_admin_user)):
    """회원 요약 통계를 반환."""
    try:
        from datetime import timedelta
        today = date.today().isoformat()
        total_res = supabase.table("users").select("id", count="exact").execute()
        today_res = supabase.table("users").select("id", count="exact").gte("created_at", today).execute()
        nat_res = supabase.table("users").select("nationality").execute()
        nat_counts: dict = {}
        for row in nat_res.data:
            nat = row.get("nationality") or "기타"
            nat_counts[nat] = nat_counts.get(nat, 0) + 1
        result_daily = []
        for i in range(6, -1, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            res = supabase.table("users") \
                .select("id", count="exact") \
                .gte("created_at", d) \
                .lte("created_at", d + "T23:59:59") \
                .execute()
            result_daily.append({"date": d[5:], "count": res.count})
        return {
            "total": total_res.count,
            "today": today_res.count,
            "by_nationality": nat_counts,
            "daily": result_daily,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/users/{user_id}/role")
async def update_user_role(user_id: str, body: UpdateRoleRequest, user: dict = Depends(get_admin_user)):
    """회원 역할을 변경합니다."""
    if body.role not in ("student", "admin"):
        raise HTTPException(status_code=400, detail="role은 'student' 또는 'admin'이어야 합니다")
    try:
        check = supabase.table("users").select("id,role").eq("id", user_id).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다")
        if check.data[0]["role"] == "admin":
            raise HTTPException(status_code=403, detail="관리자 계정은 Supabase에서 직접 관리해주세요")
        supabase.table("users").update({"role": body.role}).eq("id", user_id).execute()
        return {"message": "역할 변경 완료", "user_id": user_id, "role": body.role}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/users/{user_id}/status")
async def update_user_status(user_id: str, body: UpdateStatusRequest, user: dict = Depends(get_admin_user)):
    """회원 상태를 변경합니다."""
    if body.status not in ("ACTIVE", "INACTIVE"):
        raise HTTPException(status_code=400, detail="status는 'ACTIVE' 또는 'INACTIVE'이어야 합니다")
    try:
        check = supabase.table("users").select("id,role").eq("id", user_id).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다")
        if check.data[0]["role"] == "admin":
            raise HTTPException(status_code=403, detail="관리자 계정은 Supabase에서 직접 관리해주세요")
        supabase.table("users").update({"status": body.status}).eq("id", user_id).execute()
        return {"message": "상태 변경 완료", "user_id": user_id, "status": body.status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(get_admin_user)):
    """회원을 삭제합니다."""
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="자기 자신은 삭제할 수 없습니다")
    try:
        check = supabase.table("users").select("id,role").eq("id", user_id).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다")
        if check.data[0]["role"] == "admin":
            raise HTTPException(status_code=403, detail="관리자 계정은 Supabase에서 직접 관리해주세요")
        # users 테이블 먼저 삭제 (FK 제약 해제 후 auth 삭제)
        supabase.table("users").delete().eq("id", user_id).execute()
        import httpx
        from app.config import settings
        url = f"{settings.supabase_url}/auth/v1/admin/users/{user_id}"
        async with httpx.AsyncClient() as c:
            resp = await c.delete(url, headers={
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
            })
        if resp.status_code not in (200, 204, 404):
            raise HTTPException(status_code=resp.status_code, detail="Supabase 회원 삭제 실패")
        return {"message": "회원 삭제 완료", "user_id": user_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
