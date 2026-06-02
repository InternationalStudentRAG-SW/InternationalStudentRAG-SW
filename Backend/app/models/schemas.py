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
    chunk_index: Optional[int] = 0
    similarity_score: Optional[float] = 0.0


class ChatResponse(BaseModel):
    """채팅 엔드포인트 응답 모델."""
    answer: str
    sources: List[Source] = []
    language: Optional[str] = None
    question: str
    suggestions: List[str] = []


class MessageHistory(BaseModel):
    """대화 히스토리의 단일 메시지."""
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str
    timestamp: Optional[datetime] = None



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

# --- 인증 관련 스키마 ---
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

class AdditionalInfoRequest(BaseModel):
    nationality: str
    major: Optional[str] = None

class AdminSignupRequest(BaseModel):
    email: str
    password: str
    admin_secret: str

class UpdateRoleRequest(BaseModel):
    role: str

class UpdateStatusRequest(BaseModel):
    status: str

# --- FAQ 관련 스키마 ---
class FaqItem(BaseModel):
    id: str
    question_ko: str
    question_en: str
    question_zh: str
    question_es: str
    answer_ko: str
    answer_en: str
    answer_zh: str
    answer_es: str
    is_active: bool
    display_order: int
    created_at: Optional[datetime] = None

class FaqCreateRequest(BaseModel):
    question_ko: str = Field(..., min_length=1)
    answer_ko: str = Field(..., min_length=1)

class FaqUpdateRequest(BaseModel):
    answer_ko: Optional[str] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None

class FaqBulkCreateRequest(BaseModel):
    items: List[FaqCreateRequest]

class FaqCandidate(BaseModel):
    question_ko: str
    answer_ko: str

class FaqAnalyzeRequest(BaseModel):
    date_from: Optional[str] = None
    date_to: Optional[str] = None

class FaqReorderItem(BaseModel):
    id: str
    display_order: int

class FaqReorderRequest(BaseModel):
    items: List[FaqReorderItem]
