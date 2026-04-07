from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # OpenAI Configuration
    openai_api_key: str
    openai_model: str = "gpt-5.4-mini"

    # ChromaDB Configuration
    chroma_db_path: str = "./data/chroma_db"
    
    hf_token: str | None = None

    # Server Configuration
    debug: bool = False
    log_dir: str = "./logs"

    # Document Ingestion
    document_path: str = "./data/documents"
    chunk_size: int = 800
    chunk_overlap: int = 300

    # RAG Retrieval
    top_k_results: int = 5 # LLM에게 최종적으로 넘길 chunk 수
    initial_fetch_k: int = 15 # Reranker에게 넘기기 전 1차로 가져올 chunk 수
    min_similarity_score: float = 0.5

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
