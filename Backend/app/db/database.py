from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 아까 만든 DB 정보 (나중에는 .env 파일로 옮기는 게 좋아요)
SQLALCHEMY_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/sw_rag_data"

# DB 엔진 생성
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# 데이터베이스 세션 생성 도구
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 모델 정의를 위한 베이스 클래스
Base = declarative_base()

# DB 세션을 가져오는 의존성 함수
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()