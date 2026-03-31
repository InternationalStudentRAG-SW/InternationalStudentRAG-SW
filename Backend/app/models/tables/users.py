from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP
from sqlalchemy.sql import func
from app.db.database import Base

class User(Base):
    __tablename__ = "users"  # DB에 만든 테이블 이름과 정확히 일치해야 함

    user_id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=True)
    social_provider = Column(String, default="NONE")
    role = Column(String, nullable=False)
    nationality = Column(String, nullable=False)
    major = Column(String, nullable=True)
    is_profile_public = Column(Boolean, default=False)
    status = Column(String, default="ACTIVE")
    created_at = Column(TIMESTAMP, server_default=func.now())