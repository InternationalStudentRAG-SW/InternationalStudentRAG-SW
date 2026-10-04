import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.getLogger("neo4j").propagate = False
logging.getLogger("neo4j").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").propagate = False

from app.api.routes import chat, admin, auth, document
from app.api.routes.faq import router as faq_router
from app.config import settings

app = FastAPI(
    title="International Student RAG API",
    description="RAG-based Q&A system for international students",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(document.router)
app.include_router(faq_router)


_ROUTING_DESC = {
    "off": "모든 질문 → 기존 검색 (하이브리드+리랭커)",
    "auto": "라우터가 분류 → 단순: 기존 검색 / 복합: 단일 에이전트",
    "always": "모든 질문 → 단일 에이전트",
}


@app.on_event("startup")
def print_agent_routing_mode():
    mode = (settings.agent_routing or "off").strip().lower()
    desc = _ROUTING_DESC.get(mode, "알 수 없는 값 → off로 처리")
    print(f"[AGENT_ROUTING] {mode} | {desc}", flush=True)


@app.get("/")
def read_root():
    return {"name": "International Student RAG API", "status": "running"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}
