from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # OpenAI Configuration
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"

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

    # RAG Retrieval
    top_k_results: int = 7 # LLM에게 최종적으로 넘길 chunk 수
    initial_fetch_k: int = 25 # Reranker에게 넘기기 전 1차로 가져올 chunk 수
    min_similarity_score: float = 0.5

    supabase_url: str
    supabase_anon_key: str
    supabase_service_key: str
    admin_secret: str

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
