from sqlalchemy import Column, Integer, String, Text, TIMESTAMP
from sqlalchemy.sql import func
from app.db.database import Base

class Document(Base):
    __tablename__ = "documents"

    doc_id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    source_url = Column(Text, nullable=True)
    category = Column(String(50), nullable=False)
    uploaded_by = Column(Integer, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    user_id = Column(Integer, nullable=True)