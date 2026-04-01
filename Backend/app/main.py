from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

# 라우터 임포트
from app.api.routes import chat, admin, auth
# from app.db.database import engine, Base, get_db

# DB 테이블 생성
# Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="International Student RAG API",
    description="RAG-based Q&A system for international students",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(admin.router)

# 시스템 관련 엔드포인트만 유지
# @app.get("/db-test")
# def test_db_connection(db: Session = Depends(get_db)):
#     try:
#         result = db.execute(text("SELECT 1")).fetchone()
#         return {"status": "success", "test_query_result": result[0]}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"DB 연결 실패: {str(e)}")

@app.get("/")
def read_root():
    return {"name": "International Student RAG API", "status": "running"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}