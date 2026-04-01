from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional
import requests

# 기존 라우터 및 설정 임포트
from app.api.routes import chat, admin
from app.config import settings
from app.db.database import engine, Base, get_db
from app.models.tables.users import User

# DB 테이블 생성
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="International Student RAG API",
    description="RAG-based Q&A system for international students",
    version="1.0.0"
)

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(chat.router)
app.include_router(admin.router)

# --- 요청 데이터 규격 정의 ---

class SignupRequest(BaseModel):
    email: str
    password: str
    nationality: str
    major: Optional[str] = None
    role: str = "STUDENT"
    status: str = "ACTIVE"

class LoginRequest(BaseModel):
    email: str
    password: str

class GoogleLoginRequest(BaseModel):
    token: str

# [추가] 추가 정보 업데이트를 위한 요청 모델
class AdditionalInfoRequest(BaseModel):
    email: str
    nationality: str
    major: Optional[str] = None

# --- API 엔드포인트 ---

@app.get("/db-test")
def test_db_connection(db: Session = Depends(get_db)):
    try:
        result = db.execute(text("SELECT 1")).fetchone()
        return {"status": "success", "test_query_result": result[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB 연결 실패: {str(e)}")

@app.get("/")
def read_root():
    return {"name": "International Student RAG API", "status": "running"}

@app.post("/api/signup")
def signup(data: SignupRequest, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")

    new_user = User(
        email=data.email,
        password_hash=data.password,
        social_provider='NONE',
        role=data.role.upper(),
        nationality=data.nationality,
        major=data.major,
        status=data.status.upper()
    )
    
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return {"message": "회원가입 성공!", "user_id": new_user.user_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"데이터베이스 오류: {str(e)}")

@app.post("/api/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or user.password_hash != data.password:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    
    return {
        "message": "로그인 성공",
        "access_token": f"fake-jwt-token-for-{user.user_id}", 
        "token_type": "bearer"
    }

# [수정] 구글 로그인 시 신규 유저 여부를 반환하도록 변경
@app.post("/api/google-login")
def google_login(data: GoogleLoginRequest, db: Session = Depends(get_db)):
    google_url = f"https://www.googleapis.com/oauth2/v3/userinfo?access_token={data.token}"
    response = requests.get(google_url)
    
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="유효하지 않은 구글 토큰입니다.")
    
    user_info = response.json()
    email = user_info.get("email")

    user = db.query(User).filter(User.email == email).first()
    is_new_user = False # [추가] 신규 유저 판별 플래그

    if not user:
        is_new_user = True # [추가] DB에 없으면 신규 유저
        user = User(
            email=email,
            password_hash=None,
            social_provider='GOOGLE',
            role='STUDENT',
            nationality='Unknown', # 초기값은 Unknown으로 설정
            major=None,
            status='ACTIVE'
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    
    # [수정] 구글로 가입은 했지만 아직 국적 설정을 안한 경우도 신규 유저로 취급 (선택사항)
    elif user.nationality == 'Unknown':
        is_new_user = True

    return {
        "message": "구글 로그인 성공",
        "access_token": f"google-token-for-{user.user_id}",
        "token_type": "bearer",
        "user_email": user.email,
        "is_new_user": is_new_user # [추가] 프론트엔드에서 이 값을 보고 페이지 이동 결정
    }

# [추가] 구글 로그인 후 추가 정보를 업데이트하는 엔드포인트
@app.post("/api/update-additional-info")
def update_additional_info(data: AdditionalInfoRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    
    # 전달받은 정보로 업데이트
    user.nationality = data.nationality
    user.major = data.major
    
    try:
        db.add(user)
        db.commit()
        return {"message": "정보 업데이트 성공"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"업데이트 중 오류 발생: {str(e)}")

@app.get("/health")
def health_check():
    return {"status": "healthy"}