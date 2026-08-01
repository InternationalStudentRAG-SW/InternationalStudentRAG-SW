import json
import uuid
import numpy as np
from typing import Optional, List, Dict, Any

from openai import OpenAI
from app.config import settings


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    va, vb = np.array(a), np.array(b)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(np.dot(va, vb) / denom) if denom > 0 else 0.0


class SemanticCache:
    """
    Upstash Redis 기반 시맨틱 캐시.
    UPSTASH_REDIS_URL이 비어있으면 캐시 비활성화 후 정상 동작(graceful degradation).

    Redis 구조:
        rag_cache:index        → List[str]  캐시 ID 목록
        rag_cache:{id}         → Hash       {question, embedding, answer, sources, suggestions, language}
    """

    _INDEX_KEY = "rag_cache:index"
    _PREFIX = "rag_cache:"

    def __init__(self):
        self._enabled = bool(settings.upstash_redis_url)
        self._redis = None
        self._openai = None

    def _get_redis(self):
        if self._redis is None:
            import sys
            import redis as redis_lib
            # macOS는 Python이 시스템 인증서를 기본 사용 안 함 → 검증 비활성화
            # Linux(배포 환경)는 인증서 체인 정상 → 검증 유지
            ssl_opts = {"ssl_cert_reqs": None} if sys.platform == "darwin" else {}
            self._redis = redis_lib.from_url(
                settings.upstash_redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
                **ssl_opts,
            )
        return self._redis

    def _get_openai(self) -> OpenAI:
        if self._openai is None:
            self._openai = OpenAI(api_key=settings.openai_api_key)
        return self._openai

    def _embed(self, text: str) -> List[float]:
        resp = self._get_openai().embeddings.create(
            input=text,
            model="text-embedding-3-small",
        )
        return resp.data[0].embedding

    def get(self, question: str, language: str) -> Optional[Dict[str, Any]]:
        """유사 질문 캐시 조회. threshold 이상이면 캐시된 응답 반환, 없으면 None."""
        if not self._enabled:
            return None
        try:
            r = self._get_redis()
            ids = r.lrange(self._INDEX_KEY, 0, -1)
            if not ids:
                return None

            q_emb = self._embed(question)

            pipe = r.pipeline()
            for cid in ids:
                pipe.hgetall(f"{self._PREFIX}{cid}")
            entries = pipe.execute()

            best_score, best_entry = -1.0, None
            for entry in entries:
                if not entry or entry.get("language") != language:
                    continue
                try:
                    cached_emb = json.loads(entry["embedding"])
                    score = _cosine_similarity(q_emb, cached_emb)
                    if score > best_score:
                        best_score, best_entry = score, entry
                except Exception:
                    continue

            if best_score >= settings.semantic_cache_threshold and best_entry:
                return {
                    "answer": best_entry["answer"],
                    "sources": json.loads(best_entry["sources"]),
                    "suggestions": json.loads(best_entry["suggestions"]),
                    "language": best_entry["language"],
                    "question": question,
                }
        except Exception:
            pass
        return None

    def set(self, question: str, language: str, response: Dict[str, Any]) -> None:
        """답변을 Redis에 캐시 저장. 실패해도 예외를 무시(응답에 영향 없음)."""
        if not self._enabled:
            return
        try:
            r = self._get_redis()
            q_emb = self._embed(question)
            cid = str(uuid.uuid4())
            key = f"{self._PREFIX}{cid}"

            r.hset(key, mapping={
                "question": question,
                "embedding": json.dumps(q_emb),
                "answer": response["answer"],
                "sources": json.dumps(response["sources"]),
                "suggestions": json.dumps(response["suggestions"]),
                "language": language,
            })
            r.expire(key, settings.semantic_cache_ttl)
            r.lpush(self._INDEX_KEY, cid)
        except Exception:
            pass


semantic_cache = SemanticCache()
