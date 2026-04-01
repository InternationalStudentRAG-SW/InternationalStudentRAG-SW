from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, JSON
from sqlalchemy.sql import func
from app.db.database import Base

class ChattingLog(Base):
    __tablename__ = "chatting_log"

    log_id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), nullable=False)
    user_id = Column(Integer, nullable=True)
    sender_type = Column(String(10), nullable=False) # 'USER' or 'AI'
    message = Column(Text, nullable=False)
    referenced_docs = Column(JSON, nullable=True) # JSONB 대응
    created_at = Column(TIMESTAMP, server_default=func.now())
    user_id2 = Column(Integer, nullable=True)