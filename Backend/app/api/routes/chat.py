import re
import asyncio
from typing import Optional
from langdetect import detect, DetectorFactory, LangDetectException
DetectorFactory.seed = 0
from fastapi import APIRouter, BackgroundTasks, HTTPException
from app.models.schemas import ChatRequest, ChatResponse, Source
from app.core.llm import rag_chain, DEFAULT_TOP_K
from app.core.translation import translator
from app.core.retriever import retriever
from app.core.cache import semantic_cache
from app.db.database import supabase

router = APIRouter(prefix="/chat", tags=["chat"])


def _detect_language(question: str, explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    if re.search(r'[가-힣]', question):
        return "ko"
    if re.search(r'[぀-ヿ]', question):   # 히라가나/카타카나 → 일본어 우선
        return "ja"
    if re.search(r'[一-鿿㐀-䶿]', question):
        return "zh"
    if re.search(r'[؀-ۿ]', question):
        return "ar"
    try:
        detected = detect(question)
        return detected if detected in {"en", "vi", "es", "ko", "zh"} else "auto"
    except LangDetectException:
        return "auto"


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
    try:
        language = _detect_language(request.question, request.language)

        # history 없는 첫 질문만 캐시 조회
        if not request.history:
            cached = await asyncio.to_thread(semantic_cache.get, request.question, language)
            if cached:
                return ChatResponse(
                    answer=cached["answer"],
                    sources=cached["sources"],
                    suggestions=cached["suggestions"],
                    language=cached["language"],
                    question=request.question,
                )

        # 번역(OpenAI API)과 벡터 검색을 동시에 실행 → 번역 대기 시간 제거
        ko_query, vector_docs = await asyncio.gather(
            asyncio.to_thread(translator.translate_to_ko, request.question),
            asyncio.to_thread(retriever.vector_search_only, request.question),
        )

        answer, sources, suggestions = rag_chain.generate_answer_with_language(
            question=request.question,
            language=language,
            top_k=request.top_k if request.top_k is not None else DEFAULT_TOP_K,
            ko_query=ko_query,
            history=[{"role": m.role, "content": m.content} for m in (request.history or [])],
            prefetched_vector_docs=vector_docs,
        )

        formatted_sources = [
            Source(
                source=src["source"],
                chunk_index=src["chunk_index"],
                similarity_score=src["similarity_score"]
            )
            for src in sources
        ]

        # history 없는 첫 질문만 캐시 저장 (백그라운드 → 응답 지연 없음)
        if not request.history:
            background_tasks.add_task(
                semantic_cache.set,
                request.question,
                language,
                {
                    "answer": answer,
                    "sources": [s.model_dump() for s in formatted_sources],
                    "suggestions": suggestions or [],
                },
            )

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
            suggestions=suggestions if suggestions else []
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))