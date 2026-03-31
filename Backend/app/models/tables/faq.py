from sqlalchemy import Column, Integer, String, Text, Boolean, TIMESTAMP
from sqlalchemy.sql import func
from app.db.database import Base

class FAQ(Base):
    __tablename__ = "faq"

    faq_id = Column(Integer, primary_key=True, index=True)
    category = Column(String(50), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    is_pinned = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())