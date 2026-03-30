from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # OpenAI Configuration
    openai_api_key: str
    openai_model: str = "gpt-5.4-mini"

    # ChromaDB Configuration
    chroma_db_path: str = "./data/chroma_db"

    # Server Configuration
    debug: bool = False
    log_dir: str = "./logs"

    # Document Ingestion
    document_path: str = "./data/documents"
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # RAG Retrieval
    top_k_results: int = 3
    min_similarity_score: float = 0.5

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
