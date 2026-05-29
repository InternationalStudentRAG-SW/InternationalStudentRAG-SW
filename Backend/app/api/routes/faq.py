import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from app.config import settings
from app.db.database import supabase
from app.core.auth_middleware import get_admin_user
from app.models.schemas import FaqItem, FaqCreateRequest, FaqUpdateRequest, FaqBulkCreateRequest, FaqCandidate, FaqAnalyzeRequest, FaqReorderRequest

router = APIRouter(prefix="/faq", tags=["faq"])
_openai = AsyncOpenAI(api_key=settings.openai_api_key)


async def _translate_faq(question_ko: str, answer_ko: str) -> dict:
    """GPT로 question/answer를 en/zh/es로 번역해 dict로 반환."""
    prompt = (
        "Translate the following Korean question and answer into English, Chinese (Simplified), and Spanish.\n"
        "Return ONLY valid JSON with keys: question_en, question_zh, question_es, answer_en, answer_zh, answer_es.\n\n"
        f"question_ko: {question_ko}\n"
        f"answer_ko: {answer_ko}"
    )
    resp = await _openai.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    return json.loads(resp.choices[0].message.content)


@router.get("", response_model=list[FaqItem])
async def get_faqs():
    """활성 FAQ 목록 반환 (display_order 정렬). 인증 불필요."""
    try:
        res = await asyncio.to_thread(
            lambda: supabase.table("faqs")
            .select("*")
            .eq("is_active", True)
            .order("display_order")
            .execute()
        )
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/all", response_model=list[FaqItem])
async def get_all_faqs(user: dict = Depends(get_admin_user)):
    """전체 FAQ 목록 반환 (관리자)."""
    try:
        res = await asyncio.to_thread(
            lambda: supabase.table("faqs").select("*").order("display_order").execute()
        )
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=FaqItem)
async def create_faq(data: FaqCreateRequest, user: dict = Depends(get_admin_user)):
    """FAQ 수동 생성. 한국어 입력 → GPT가 4개 언어 번역."""
    try:
        translations = await _translate_faq(data.question_ko, data.answer_ko)
        row = {
            "question_ko": data.question_ko,
            "question_en": translations.get("question_en", ""),
            "question_zh": translations.get("question_zh", ""),
            "question_es": translations.get("question_es", ""),
            "answer_ko": data.answer_ko,
            "answer_en": translations.get("answer_en", ""),
            "answer_zh": translations.get("answer_zh", ""),
            "answer_es": translations.get("answer_es", ""),
        }
        res = await asyncio.to_thread(
            lambda: supabase.table("faqs").insert(row).execute()
        )
        return res.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bulk-create")
async def bulk_create_faqs(data: FaqBulkCreateRequest, user: dict = Depends(get_admin_user)):
    """FAQ 후보 다수 저장. 각 항목을 GPT로 번역 후 insert."""
    try:
        rows = []
        for item in data.items:
            translations = await _translate_faq(item.question_ko, item.answer_ko)
            rows.append({
                "question_ko": item.question_ko,
                "question_en": translations.get("question_en", ""),
                "question_zh": translations.get("question_zh", ""),
                "question_es": translations.get("question_es", ""),
                "answer_ko": item.answer_ko,
                "answer_en": translations.get("answer_en", ""),
                "answer_zh": translations.get("answer_zh", ""),
                "answer_es": translations.get("answer_es", ""),
            })
        await asyncio.to_thread(
            lambda: supabase.table("faqs").insert(rows).execute()
        )
        return {"message": f"{len(rows)}개 FAQ 저장 완료"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{faq_id}", response_model=FaqItem)
async def update_faq(faq_id: str, data: FaqUpdateRequest, user: dict = Depends(get_admin_user)):
    """FAQ 수정. answer_ko 변경 시 4개 언어 재번역."""
    try:
        check = await asyncio.to_thread(
            lambda: supabase.table("faqs").select("*").eq("id", faq_id).execute()
        )
        if not check.data:
            raise HTTPException(status_code=404, detail="FAQ를 찾을 수 없습니다")

        updates: dict = {}
        if data.answer_ko is not None:
            current_q = check.data[0]["question_ko"]
            translations = await _translate_faq(current_q, data.answer_ko)
            updates.update({
                "answer_ko": data.answer_ko,
                "answer_en": translations.get("answer_en", ""),
                "answer_zh": translations.get("answer_zh", ""),
                "answer_es": translations.get("answer_es", ""),
            })
        if data.is_active is not None:
            updates["is_active"] = data.is_active
        if data.display_order is not None:
            updates["display_order"] = data.display_order

        if not updates:
            return check.data[0]

        res = await asyncio.to_thread(
            lambda: supabase.table("faqs").update(updates).eq("id", faq_id).execute()
        )
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{faq_id}")
async def delete_faq(faq_id: str, user: dict = Depends(get_admin_user)):
    """FAQ 삭제."""
    try:
        check = await asyncio.to_thread(
            lambda: supabase.table("faqs").select("id").eq("id", faq_id).execute()
        )
        if not check.data:
            raise HTTPException(status_code=404, detail="FAQ를 찾을 수 없습니다")
        await asyncio.to_thread(
            lambda: supabase.table("faqs").delete().eq("id", faq_id).execute()
        )
        return {"message": "FAQ 삭제 완료"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reorder")
async def reorder_faqs(data: FaqReorderRequest, user: dict = Depends(get_admin_user)):
    """드래그앤드롭 후 전체 순서를 한 번에 저장."""
    try:
        for item in data.items:
            item_id = item.id
            item_order = item.display_order
            await asyncio.to_thread(
                lambda: supabase.table("faqs").update({"display_order": item_order}).eq("id", item_id).execute()
            )
        return {"message": "순서 저장 완료"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze")
async def analyze_logs(data: FaqAnalyzeRequest = FaqAnalyzeRequest(), user: dict = Depends(get_admin_user)):
    """chat_logs를 GPT로 분석해 FAQ 후보 반환. date_from/date_to로 범위 지정 가능."""
    try:
        q = supabase.table("chat_logs").select("query,answer").order("created_at", desc=True)
        if data.date_from:
            q = q.gte("created_at", data.date_from)
        if data.date_to:
            q = q.lte("created_at", data.date_to + "T23:59:59")
        logs_res = await asyncio.to_thread(lambda: q.limit(200).execute())
        if not logs_res.data:
            return {"candidates": []}

        logs_text = "\n".join(
            f"Q: {r['query']}\nA: {r['answer']}" for r in logs_res.data
        )
        prompt = (
            "다음은 유학생 안내 챗봇의 채팅 로그입니다 (다국어 포함).\n"
            "이 로그를 분석하여 자주 묻는 질문 상위 5~10개를 추출하세요.\n"
            "질문은 한국어로 정리하고, 답변도 한국어로 요약하세요.\n"
            "반드시 JSON 형식으로만 응답하세요: "
            "{\"candidates\": [{\"question_ko\": \"...\", \"answer_ko\": \"...\"}, ...]}\n\n"
            + logs_text
        )
        resp = await _openai.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        result = json.loads(resp.choices[0].message.content)
        return {"candidates": result.get("candidates", [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
