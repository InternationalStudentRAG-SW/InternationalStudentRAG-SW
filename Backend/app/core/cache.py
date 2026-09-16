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
        rag_cache:index      → List[str]  캐시 ID 목록
        rag_cache:{id}       → Hash       {
                                    question_ko,   # 한국어 번역 질문 (캐시 키)
                                    embedding,     # 한국어 임베딩 벡터
                                    answer_ko,     # 언어별 답변 (필요시 추가됨)
                                    answer_en,
                                    answer_zh, ...
                                    sources,
                                    suggestions_ko,
                                    suggestions_en, ...
                                  }
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

    def _find_best_entry(self, ko_query: str) -> tuple[float, Optional[Dict], Optional[str]]:
        """ko_query 임베딩으로 가장 유사한 캐시 엔트리를 찾는다. (score, entry, entry_key) 반환"""
        r = self._get_redis()
        ids = r.lrange(self._INDEX_KEY, 0, -1)
        if not ids:
            return -1.0, None, None

        q_emb = self._embed(ko_query)

        pipe = r.pipeline()
        for cid in ids:
            pipe.hgetall(f"{self._PREFIX}{cid}")
        entries = pipe.execute()

        best_score, best_entry, best_key = -1.0, None, None
        for cid, entry in zip(ids, entries):
            if not entry or "embedding" not in entry:
                continue
            try:
                cached_emb = json.loads(entry["embedding"])
                score = _cosine_similarity(q_emb, cached_emb)
                if score > best_score:
                    best_score, best_entry, best_key = score, entry, f"{self._PREFIX}{cid}"
            except Exception:
                continue

        return best_score, best_entry, best_key

    def get(self, ko_query: str, language: str) -> Optional[Dict[str, Any]]:
        """
        ko_query 임베딩으로 캐시 조회.
        - HIT 시 요청 언어의 답변이 있으면 즉시 반환
        - 없으면 answer_ko를 번역해서 반환하고 백그라운드 저장을 위해 (entry_key, translated) 정보도 함께 반환
        """
        if not self._enabled:
            return None
        try:
            best_score, best_entry, best_key = self._find_best_entry(ko_query)
            print(f"[Cache] best_score={best_score:.4f} threshold={settings.semantic_cache_threshold} lang={language}")

            if best_score < settings.semantic_cache_threshold or best_entry is None:
                return None

            print(f"[Cache] HIT: '{best_entry.get('question_ko', '')[:60]}'")

            answer_field = f"answer_{language}"
            suggestions_field = f"suggestions_{language}"

            # 요청 언어 답변이 이미 저장되어 있으면 바로 반환
            if answer_field in best_entry:
                return {
                    "answer": best_entry[answer_field],
                    "sources": json.loads(best_entry["sources"]),
                    "suggestions": json.loads(best_entry.get(suggestions_field, "[]")),
                    "language": language,
                    "question": ko_query,
                    "_cache_key": None,  # 추가 저장 불필요
                }

            # 없으면 answer_ko를 번역해서 반환 (번역은 호출자가 수행)
            base_answer = best_entry.get("answer_ko", "")
            base_suggestions = json.loads(best_entry.get("suggestions_ko", "[]"))
            return {
                "answer": base_answer,
                "sources": json.loads(best_entry["sources"]),
                "suggestions": base_suggestions,
                "language": "ko",           # 번역 전 언어임을 표시
                "question": ko_query,
                "_cache_key": best_key,     # 번역 후 이 키에 필드 추가
                "_needs_translation": True,
            }

        except Exception as e:
            print(f"[Cache] ERROR: {e}")
        return None

    def add_language(self, cache_key: str, language: str, answer: str, suggestions: List[str]) -> None:
        """기존 캐시 엔트리에 새 언어의 답변 필드만 추가한다."""
        if not self._enabled or not cache_key:
            return
        try:
            r = self._get_redis()
            r.hset(cache_key, mapping={
                f"answer_{language}": answer,
                f"suggestions_{language}": json.dumps(suggestions),
            })
            print(f"[Cache] TRANSLATED ko→{language} 저장 완료 | key={cache_key}")
        except Exception as e:
            print(f"[Cache] add_language 실패: {e}")

    def set(self, ko_query: str, language: str, response: Dict[str, Any]) -> None:
        """새 답변을 Redis에 캐시 저장. ko_query를 임베딩 키로 사용."""
        if not self._enabled:
            return
        try:
            r = self._get_redis()
            q_emb = self._embed(ko_query)
            cid = str(uuid.uuid4())
            key = f"{self._PREFIX}{cid}"

            r.hset(key, mapping={
                "question_ko": ko_query,
                "embedding": json.dumps(q_emb),
                f"answer_{language}": response["answer"],
                "sources": json.dumps(response["sources"]),
                f"suggestions_{language}": json.dumps(response["suggestions"]),
            })
            r.expire(key, settings.semantic_cache_ttl)
            r.lpush(self._INDEX_KEY, cid)
            total = r.llen(self._INDEX_KEY)
            print(f"[Cache] SET 완료 | lang={language} | 전체 {total}개 | '{ko_query[:60]}'")
        except Exception as e:
            print(f"[Cache] SET 실패: {e}")


semantic_cache = SemanticCache()
