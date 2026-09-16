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
    if re.search(r'[぀-ヿ]', question):
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

        # history 없는 첫 질문만 캐시 사용
        if not request.history:
            # 번역을 먼저 수행 (캐시 키로 한국어 임베딩 사용)
            ko_query, vector_docs = await asyncio.gather(
                asyncio.to_thread(translator.translate_to_ko, request.question),
                asyncio.to_thread(retriever.vector_search_only, request.question),
            )

            # ko_query로 캐시 조회
            cached = await asyncio.to_thread(semantic_cache.get, ko_query, language)
            if cached:
                # 요청 언어 답변이 없어서 answer_ko가 반환된 경우 → 번역 후 저장
                if cached.get("_needs_translation"):
                    cache_key = cached["_cache_key"]
                    translated_answer = await asyncio.to_thread(
                        translator.translate_from_ko, cached["answer"], language
                    )
                    translated_suggestions = []
                    for s in cached["suggestions"]:
                        ts = await asyncio.to_thread(translator.translate_from_ko, s, language)
                        translated_suggestions.append(ts)
                    background_tasks.add_task(
                        semantic_cache.add_language,
                        cache_key, language, translated_answer, translated_suggestions,
                    )
                    return ChatResponse(
                        answer=translated_answer,
                        sources=cached["sources"],
                        suggestions=translated_suggestions,
                        language=language,
                        question=request.question,
                    )

                return ChatResponse(
                    answer=cached["answer"],
                    sources=cached["sources"],
                    suggestions=cached["suggestions"],
                    language=language,
                    question=request.question,
                )
        else:
            # history 있는 경우 번역과 벡터검색 병렬 실행
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

        # history 없는 첫 질문만 캐시 저장 (ko_query를 키로 사용)
        if not request.history:
            background_tasks.add_task(
                semantic_cache.set,
                ko_query,
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
