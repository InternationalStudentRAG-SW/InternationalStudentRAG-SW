from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text  # 👈 연결 테스트를 위해 추가됨

from app.api.routes import chat, admin
from app.config import settings
from app.db.database import engine, Base, get_db  # 👈 get_db 추가됨
from app.models import tables

# DB 테이블 생성 (이미 있으면 건너뜀)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="International Student RAG API",
    description="RAG-based Q&A system for international students",
    version="1.0.0"
)

# CORS 미들웨어 추가
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

# ✅ 데이터베이스 연결 테스트용 API
@app.get("/db-test")
def test_db_connection(db: Session = Depends(get_db)):
    try:
        # DB에 간단한 쿼리를 날려 연결 상태를 확인합니다.
        result = db.execute(text("SELECT 1")).fetchone()
        return {
            "status": "success",
            "message": "데이터베이스 연결에 성공했습니다!",
            "test_query_result": result[0]
        }
    except Exception as e:
        # 연결 실패 시 상세 에러를 반환합니다.
        raise HTTPException(
            status_code=500, 
            detail=f"데이터베이스 연결 실패: {str(e)}"
        )

@app.get("/")
def read_root():
    return {
        "name": "International Student RAG API",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}