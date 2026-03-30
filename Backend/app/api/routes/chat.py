from fastapi import APIRouter, HTTPException
from app.models.schemas import ChatRequest, ChatResponse, Source
from app.core.llm import rag_chain
from app.utils.language import detector
from app.utils.logger import log_query


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    채팅 쿼리를 처리하고 답변과 출처를 반환합니다.

    - **question**: 사용자의 질문
    - **language**: 선택 사항인 언어 코드 (미제공 시 자동 감지)
    - **top_k**: 검색할 문서 개수 (기본값: 3, 최대: 10)
    """
    try:
        # 언어가 제공되지 않으면 자동 감지
        language = request.language
        if not language:
            language = detector.detect(request.question)

        # RAG를 사용하여 답변 생성
        answer, sources = rag_chain.generate_answer_with_language(
            question=request.question,
            language=language,
            top_k=request.top_k or 3
        )

        # 출처 포맷팅
        formatted_sources = [
            Source(
                source=src["source"],
                chunk_index=src["chunk_index"],
                similarity_score=src["similarity_score"]
            )
            for src in sources
        ]

        # 쿼리 로깅
        log_query(
            question=request.question,
            answer=answer,
            language=language,
            sources=sources
        )

        return ChatResponse(
            answer=answer,
            sources=formatted_sources,
            language=language,
            question=request.question
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing question: {str(e)}")


@router.post("/simple", response_model=ChatResponse)
async def simple_chat(request: ChatRequest):
    """
    언어 감지 없이 간단한 채팅을 처리합니다.
    """
    try:
        answer, sources = rag_chain.generate_answer(
            question=request.question,
            top_k=request.top_k or 3
        )

        formatted_sources = [
            Source(
                source=src["source"],
                chunk_index=src["chunk_index"],
                similarity_score=src["similarity_score"]
            )
            for src in sources
        ]

        return ChatResponse(
            answer=answer,
            sources=formatted_sources,
            question=request.question
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"질문 처리 오류: {str(e)}")
