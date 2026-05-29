import re
import asyncio
from fastapi import APIRouter, BackgroundTasks, HTTPException
from app.models.schemas import ChatRequest, ChatResponse, Source
from app.core.llm import rag_chain
from app.core.translation import translator
from app.db.database import supabase

router = APIRouter(prefix="/chat", tags=["chat"])


def _insert_chat_log(query: str, answer: str, sources: list, language: str):
    try:
        supabase.table("chat_logs").insert({
            "query": query,
            "answer": answer,
            "sources": sources,
            "language": language,
        }).execute()
    except Exception:
        pass


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
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

        # chat_logs DB 저장 (백그라운드, 응답 지연 없음)
        background_tasks.add_task(
            _insert_chat_log,
            query=request.question,
            answer=answer,
            sources=[s.model_dump() for s in formatted_sources],
            language=language,
        )

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
