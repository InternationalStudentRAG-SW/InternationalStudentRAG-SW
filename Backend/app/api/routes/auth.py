import asyncio
import httpx
from fastapi import APIRouter, Depends, HTTPException
from app.db.database import supabase
from app.config import settings
from app.core.auth_middleware import get_current_user
from app.models.schemas import SignupRequest, LoginRequest, AdditionalInfoRequest, AdminSignupRequest

router = APIRouter(prefix="/api", tags=["auth"])

_SUPABASE_HEADERS = {
    "apikey": settings.supabase_service_key,
    "Authorization": f"Bearer {settings.supabase_service_key}",
    "Content-Type": "application/json",
}


async def _create_user(email: str, password: str) -> str:
    """Supabase Admin API로 유저를 생성하고 user_id를 반환한다."""
    url = f"{settings.supabase_url}/auth/v1/admin/users"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers=_SUPABASE_HEADERS,
            json={"email": email, "password": password, "email_confirm": True},
        )
    if resp.status_code not in (200, 201):
        detail = resp.json().get("msg") or resp.json().get("message") or resp.text
        raise HTTPException(status_code=400, detail=detail)
    return resp.json()["id"]


@router.post("/signup")
async def signup(data: SignupRequest):
    try:
        user_id = await _create_user(data.email, data.password)
        await asyncio.to_thread(
            lambda: supabase.table("users").upsert({
                "id": user_id,
                "email": data.email,
                "role": "student",
                "nationality": data.nationality,
                "major": data.major,
                "status": "ACTIVE",
            }).execute()
        )
        return {"message": "회원가입 성공", "user_id": user_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin-signup")
async def admin_signup(data: AdminSignupRequest):
    if not settings.admin_secret or data.admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="유효하지 않은 관리자 코드입니다")
    try:
        user_id = await _create_user(data.email, data.password)
        uid_copy = str(user_id)
        # httpx가 반환될 때 트리거는 완료 상태. 즉시 update 시도, 최대 10초 재시도
        for i in range(11):
            if i > 0:
                await asyncio.sleep(1)
            res = await asyncio.to_thread(
                lambda: supabase.table("users").update({"role": "admin", "status": "ACTIVE"}).eq("id", uid_copy).execute()
            )
            if res.data:
                break
        return {"message": "관리자 계정 생성 완료", "user_id": user_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


_SUPABASE_ANON_HEADERS = {
    "apikey": settings.supabase_anon_key,
    "Content-Type": "application/json",
}


@router.post("/login")
async def login(data: LoginRequest):
    # httpx로 직접 호출해서 supabase 서비스 키 클라이언트 세션 오염 방지
    url = f"{settings.supabase_url}/auth/v1/token?grant_type=password"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers=_SUPABASE_ANON_HEADERS,
            json={"email": data.email, "password": data.password},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")
    session = resp.json()
    uid = session["user"]["id"]
    try:
        role_res = await asyncio.to_thread(
            lambda: supabase.table("users").select("role").eq("id", uid).single().execute()
        )
        role = role_res.data["role"]
    except Exception:
        role = "student"
    return {
        "access_token": session["access_token"],
        "token_type": "bearer",
        "user_id": uid,
        "role": role,
    }


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    return {"id": user["id"], "role": user["role"], "nationality": user.get("nationality")}


@router.post("/update-additional-info")
async def update_additional_info(data: AdditionalInfoRequest, user: dict = Depends(get_current_user)):
    try:
        await asyncio.to_thread(
            lambda: supabase.table("users")
            .update({"nationality": data.nationality, "major": data.major})
            .eq("id", user["id"])
            .execute()
        )
        return {"message": "정보 업데이트 성공"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
