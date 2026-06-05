import re
from fastapi import APIRouter, HTTPException
from app.models.schemas import ChatRequest, ChatResponse, Source
from app.core.llm import rag_chain
from app.core.translation import translator
from app.utils.logger import log_query

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    채팅 쿼리를 처리하고 답변과 출처를 반환합니다.
    """
    try:
        # 한글 포함 여부로 한국어 판별, 나머지는 GPT가 질문 언어로 자동 응답
        if request.language:
            language = request.language
        elif re.search(r'[가-힣]', request.question):
            language = "ko"
        else:
            language = "auto"

        # 한글 포함 시 번역 스킵, 그 외 언어는 OpenAI로 한국어 번역 (BM25·리랭커용)
        ko_query = translator.translate_to_ko(request.question)

        # [수정됨] 기존 코드에 rag_chain 호출이 두 번 중복되어 있어서 하나로 합쳤습니다.
        # RAG를 사용하여 답변 생성 (suggestions 반환받기)
        answer, sources, suggestions = rag_chain.generate_answer_with_language(
            question=request.question,   # Vector 검색·GPT 답변: 원문
            language=language,
            top_k=request.top_k or 3,
            ko_query=ko_query,           # BM25·리랭커: 한국어 번역
            history=[{"role": m.role, "content": m.content} for m in (request.history or [])],

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
            sources=sources,
        )

        # [수정됨] ChatResponse에 suggestions 추가
        return ChatResponse(
            answer=answer,
            sources=formatted_sources,
            language=language,
            question=request.question,
            suggestions=suggestions if suggestions else [] # 프론트로 추천 질문 리스트 전달
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/simple", response_model=ChatResponse)
async def simple_chat(request: ChatRequest):
    """
    언어 감지 없이 간단한 채팅을 처리합니다.
    """
    try:
        # [수정됨] 인자에 정의되지 않은 suggestions=suggestions 가 들어가 있어서 에러가 날 수 있는 부분을 제거했습니다.
        answer, sources, suggestions = rag_chain.generate_answer(
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

        # [수정됨] 모델 스키마에 맞게 suggestions 전달
        return ChatResponse(
            answer=answer,
            sources=formatted_sources,
            question=request.question,
            suggestions=suggestions if suggestions else [] # 프론트로 추천 질문 리스트 전달
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"질문 처리 오류: {str(e)}")