import asyncio
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from app.db.database import supabase, auth_client

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/login", auto_error=False)


async def _verify_token(token: str) -> tuple[str, str]:
    """JWT를 검증하고 (user_id, email)을 반환한다. anon 클라이언트 사용으로 service key 오염 방지."""
    try:
        res = await asyncio.to_thread(lambda: auth_client.auth.get_user(token))
        if not res.user:
            raise ValueError("no user")
        return str(res.user.id), res.user.email or ""
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


async def _build_user_dict(user_id: str, email: str = "") -> dict:
    """users 테이블에서 role과 nationality를 조회한다. row가 없으면(Google OAuth 첫 로그인) 자동 생성한다."""
    try:
        profile = await asyncio.to_thread(
            lambda: supabase.table("users")
            .select("role,nationality")
            .eq("id", user_id)
            .execute()
        )
        if not profile.data:
            await asyncio.to_thread(
                lambda: supabase.table("users").upsert({
                    "id": user_id,
                    "email": email,
                    "role": "student",
                    "status": "ACTIVE",
                }).execute()
            )
            return {"id": user_id, "role": "student", "nationality": None}
        data = profile.data[0]
        return {
            "id": user_id,
            "role": data["role"],
            "nationality": data.get("nationality"),
        }
    except Exception:
        raise HTTPException(status_code=401, detail="User not found")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    user_id, email = await _verify_token(token)
    return await _build_user_dict(user_id, email)


async def get_optional_user(token: Optional[str] = Depends(oauth2_scheme_optional)) -> Optional[dict]:
    if not token:
        return None
    try:
        user_id, email = await _verify_token(token)
        return await _build_user_dict(user_id, email)
    except HTTPException:
        return None


async def get_admin_user(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
