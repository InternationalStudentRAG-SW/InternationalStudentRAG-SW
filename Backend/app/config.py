from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # OpenAI Configuration
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    verify_model: str = ""  # 단일 에이전트 ④ 충분성 검증 전용 모델 (환경변수 VERIFY_MODEL, 비우면 openai_model)
    answer_model: str = "ANSWER_MODEL"  # 단일 에이전트 ⑤ 답변 전용 모델 (환경변수 ANSWER_MODEL, 비우면 openai_model). 예: gpt-4o
    # 질문 경로 선택 (환경변수 AGENT_ROUTING)
    #   off    : 모든 질문을 기본 RAG(하이브리드+리랭커)로 (기본값, 기존 동작)
    #   auto   : ⓪ 라우터가 단순 질문은 기본 RAG, 복합 질문은 단일 에이전트로 보냄
    #   always : 모든 질문을 단일 에이전트로 (비교·디버깅용)
    agent_routing: str = "off"
    # 에이전트 실행 기록 저장 (환경변수 AGENT_RUN_LOG). 켜면 {log_dir}/agent_runs/*.json, {log_dir}/routes.jsonl
    agent_run_log: bool = True

    # ChromaDB Configuration
    chroma_db_path: str = "../DATA/chroma_db"

    hf_token: str | None = None

    # Server Configuration
    debug: bool = False
    log_dir: str = "./logs"

    # Document Ingestion
    document_path: str = "../DATA/documents"
    chunk_size: int = 600
    chunk_overlap: int = 150
    # PDF에서 공백 없이 붙어 나온 한국어 줄만 띄어쓰기 복원 (환경변수 PDF_SPACING_FIX, app/core/spacing.py)
    pdf_spacing_fix: bool = True

    # RAG Retrieval
    top_k_results: int = 10 # LLM에게 최종적으로 넘길 chunk 수
    initial_fetch_k: int = 25 # Reranker에게 넘기기 전 1차로 가져올 chunk 수
    # 개발셋에서 최종 채택 근거를 모두 보존한 최소값. 0이면 RRF 병합 후보를 모두 BGE에 전달한다.
    rerank_candidate_limit: int = 40
    min_similarity_score: float = 0.5

    supabase_url: str
    supabase_anon_key: str
    supabase_service_key: str
    admin_secret: str

    # Redis 시맨틱 캐시
    upstash_redis_url: str = ""
    semantic_cache_threshold: float = 0.70
    semantic_cache_ttl: int = 86400

    # CORS
    cors_origins: str = "http://localhost:3000"

    # Neo4j 그래프DB (비어있으면 자동 비활성화)
    neo4j_uri: str = ""
    neo4j_user: str = ""
    neo4j_password: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
