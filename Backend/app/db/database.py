from supabase import create_client, Client
from supabase.client import ClientOptions
from app.config import settings

# 서비스 키 클라이언트 - DB 조작 및 admin auth API 전용
supabase: Client = create_client(
    settings.supabase_url,
    settings.supabase_service_key,
    options=ClientOptions(
        auto_refresh_token=False,
        persist_session=False,
    ),
)

# anon 키 클라이언트 - JWT 검증 전용 (get_user 세션 오염 방지)
auth_client: Client = create_client(
    settings.supabase_url,
    settings.supabase_anon_key,
    options=ClientOptions(
        auto_refresh_token=False,
        persist_session=False,
    ),
)
