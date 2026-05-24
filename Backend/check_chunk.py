# chunk_check.py
from app.core.knowledge_base import knowledge_base

result = knowledge_base.vector_store._collection.get(include=["documents", "metadatas"])

for doc, meta in zip(result["documents"], result["metadatas"]):
    sources = set(meta.get("source", "") for meta in result["metadatas"])
    for s in sources:
        print(s)