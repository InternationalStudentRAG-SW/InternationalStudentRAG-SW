import re
import asyncio
from langdetect import detect, DetectorFactory, LangDetectException
DetectorFactory.seed = 0
from fastapi import APIRouter, BackgroundTasks, HTTPException
from app.models.schemas import ChatRequest, ChatResponse, Source
from app.core.llm import rag_chain
from app.core.translation import translator
from app.db.database import supabase

from app.core.llm import DEFAULT_TOP_K

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
    try:
        if request.language:
            language = request.language
        elif re.search(r'[가-힣]', request.question):
            language = "ko"
        elif re.search(r'[一-鿿㐀-䶿]', request.question):
            language = "zh"
        elif re.search(r'[぀-ヿ]', request.question):
            language = "ja"
        elif re.search(r'[؀-ۿ]', request.question):
            language = "ar"
        else:
            try:
                detected = detect(request.question)
                language = detected if detected in {"en", "vi", "es", "ko", "zh"} else "auto"
            except LangDetectException:
                language = "auto"

        ko_query = translator.translate_to_ko(request.question)

        answer, sources, suggestions = rag_chain.generate_answer_with_language(
            question=request.question,
            language=language,
            top_k=request.top_k if request.top_k is not None else DEFAULT_TOP_K,
            ko_query=ko_query,           # BM25·리랭커: 한국어 번역
            history=[{"role": m.role, "content": m.content} for m in (request.history or [])],
        )

        formatted_sources = [
            Source(
                source=src["source"],
                chunk_index=src["chunk_index"],
                similarity_score=src["similarity_score"]
            )
            for src in sources
        ]

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