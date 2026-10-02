"""Reproducibility metadata without credentials, prompts, or database mutation."""
import hashlib
import platform
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from app.core.single_agent.metrics import METRICS_VERSION


def experiment_metadata(label: str = "", corpus_version: str = "") -> dict:
    backend = Path(__file__).resolve().parents[1]
    paths = sorted(set((backend / "app").rglob("*.py")) | set((backend / "evaluate").glob("*.py")))
    files = {str(p.relative_to(backend)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in paths}
    digest = hashlib.sha256("\n".join(f"{p}:{v}" for p, v in files.items()).encode()).hexdigest()
    packages = {}
    for name in ("openai", "sentence-transformers", "torch", "langchain-community", "chromadb"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    from app.core.single_agent import checklist_config as cfg
    from app.config import settings
    return {
        "started_at": datetime.now(timezone.utc).isoformat(), "label": label,
        "metrics_version": METRICS_VERSION, "code_sha256": digest, "source_sha256": files,
        "corpus_version": corpus_version or None,  # explicitly unknown unless supplied; not a DB fingerprint
        "python": platform.python_version(), "packages": packages,
        "retrieval": {k: getattr(settings, k) for k in ("top_k_results", "initial_fetch_k",
                       "rerank_candidate_limit", "chunk_size", "chunk_overlap")},
        "policy": {k: getattr(cfg, k) for k in ("CHECKLIST_VERSION", "SEARCH_TOP_K", "EXPAND_WINDOW",
                   "MAX_VERIFY_ROUNDS", "AUTO_EXPAND_FIRST_ROUND", "EARLY_STOP_ON_CORE", "VERIFY_MAX_CHUNKS")},
        "notes": ["Vector timing includes embedding; embedding token usage is not measured.",
                  "SDK calls exclude SDK-internal HTTP retries; cached prompt tokens are a subset of input tokens.",
                  "First retriever import is not equivalent to hardware/cache warmup."],
    }
