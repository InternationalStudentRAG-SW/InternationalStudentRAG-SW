from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class ChatRequest(BaseModel):
    """채팅 엔드포인트 요청 모델."""
    question: str = Field(..., min_length=1, max_length=5000)
    language: Optional[str] = Field(default=None, description="언어 코드 (예: 'en', 'ko')")
    top_k: Optional[int] = Field(default=3, ge=1, le=10)


class Source(BaseModel):
    """출처 문서 메타데이터."""
    source: str
    chunk_index: int
    similarity_score: float


class ChatResponse(BaseModel):
    """채팅 엔드포인트 응답 모델."""
    answer: str
    sources: List[Source] = []
    language: Optional[str] = None
    question: str


class MessageHistory(BaseModel):
    """대화 히스토리의 단일 메시지."""
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str
    timestamp: Optional[datetime] = None


class ConversationRequest(BaseModel):
    """전체 대화 컨텍스트가 포함된 요청."""
    messages: List[MessageHistory]
    language: Optional[str] = None
    top_k: Optional[int] = Field(default=3, ge=1, le=10)


class DocumentUploadResponse(BaseModel):
    """문서 업로드 응답."""
    filename: str
    status: str
    message: str
    chunks_created: int = 0


class DocumentUploadRequest(BaseModel):
    """문서 업로드 요청."""
    filename: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)


class HealthResponse(BaseModel):
    """상태 확인 응답."""
    status: str
    database_status: str
    total_chunks: int
