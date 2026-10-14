import json
import uuid
from typing import List, Dict
from neo4j import GraphDatabase
from openai import OpenAI
from app.config import settings

# [ref:8] GraphRAG (Edge et al., 2024) — 텍스트에서 엔티티/관계를 추출해 지식그래프로 구조화하는 설계 근거
# [ref:10] KGGen (Agarwal et al., 2025) — 2단계 분리 추출: Stage1 엔티티 확정 → Stage2 확정 엔티티 간 관계 추출
#   단일 프롬프트 방식 대비 환각(hallucination) 관계 생성을 억제함

# Stage 1: 엔티티만 추출
_EXTRACT_ENTITIES_PROMPT = """다음 텍스트에서 유학생 관련 핵심 엔티티만 추출하세요.

엔티티 유형: 비자, 서류, 기관, 절차, 자격요건, 기간, 비용, 언어시험

반드시 아래 JSON 형식으로만 응답하세요:
{"entities": [{"name": "엔티티명", "type": "엔티티유형"}]}

텍스트:
"""

# Stage 2: 확정된 엔티티 간 관계만 추출 (목록 외 엔티티 생성 금지)
_EXTRACT_RELATIONS_PROMPT = """아래 엔티티 목록에서만 관계를 추출하세요.
목록에 없는 엔티티는 절대 생성하지 마세요.

엔티티 목록: {entity_names}
관계 유형: 필요서류, 제출기관, 소요기간, 비용, 자격요건, 다음절차, 관련항목

반드시 아래 JSON 형식으로만 응답하세요:
{{"relations": [{{"from": "엔티티명", "relation": "관계유형", "to": "엔티티명"}}]}}

텍스트:
"""


class KnowledgeGraph:
    """Neo4j 기반 지식그래프 관리."""

    def __init__(self):
        self._driver = None
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._enabled = bool(settings.neo4j_uri)
        self._index_ensured = False

    def _get_driver(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
        return self._driver

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    # [ref:7] MTEB (Muennighoff et al., 2022) — 다국어 임베딩 모델은 언어에 무관하게 동일 개념을 유사한
    #   벡터 공간에 매핑 → 한국어·영어 혼합 KG에서 크로스 언어 엔티티 매칭의 간접 근거
    def _embed(self, text: str) -> List[float]:
        resp = self._client.embeddings.create(
            input=text,
            model="text-embedding-3-small",
        )
        return resp.data[0].embedding

    def _ensure_vector_index(self) -> None:
        """Entity 임베딩용 벡터 인덱스 생성 (Neo4j 5.x, 최초 1회)."""
        with self._get_driver().session() as session:
            session.run("""
                CREATE VECTOR INDEX entity_embedding IF NOT EXISTS
                FOR (e:Entity) ON (e.embedding)
                OPTIONS {indexConfig: {
                  `vector.dimensions`: 1536,
                  `vector.similarity_function`: 'cosine'
                }}
            """)

    # ── 엔티티/관계 추출 (2단계) ─────────────────────────────────────────

    def extract_graph_from_text(
        self, text: str, source: str, page: int, chunk_index: int
    ) -> Dict:
        # [ref:10] KGGen 2단계 분리 추출 방식 적용
        # Stage1에서 확정된 엔티티 목록을 Stage2 프롬프트에 주입해
        # 목록 외 엔티티가 관계에 포함되는 환각을 방지함
        truncated = text[:1500]
        system_msg = {"role": "system", "content": "유학생 행정 문서 분석 전문가입니다. JSON만 응답합니다."}

        # Stage 1 — 엔티티만
        try:
            r1 = self._client.chat.completions.create(
                model=settings.openai_model,
                messages=[system_msg, {"role": "user", "content": _EXTRACT_ENTITIES_PROMPT + truncated}],
                temperature=0,
                response_format={"type": "json_object"},
            )
            entities = json.loads(r1.choices[0].message.content).get("entities", [])
        except Exception as e:
            print(f"[KG] Stage1 오류 ({source} p{page} c{chunk_index}): {e}")
            return {"entities": [], "relations": [], "source": source, "page": page, "chunk_index": chunk_index}

        if not entities:
            return {"entities": [], "relations": [], "source": source, "page": page, "chunk_index": chunk_index}

        # Stage 2 — 확정 엔티티 간 관계만
        entity_names = [e["name"] for e in entities]
        valid_names = set(entity_names)
        relations = []
        try:
            prompt2 = _EXTRACT_RELATIONS_PROMPT.format(entity_names=", ".join(entity_names)) + truncated
            r2 = self._client.chat.completions.create(
                model=settings.openai_model,
                messages=[system_msg, {"role": "user", "content": prompt2}],
                temperature=0,
                response_format={"type": "json_object"},
            )
            raw_relations = json.loads(r2.choices[0].message.content).get("relations", [])
            # Stage 1 목록에 없는 엔티티가 포함된 관계 필터링
            relations = [
                r for r in raw_relations
                if r.get("from") in valid_names and r.get("to") in valid_names
            ]
        except Exception as e:
            print(f"[KG] Stage2 오류 ({source} p{page} c{chunk_index}): {e}")

        return {
            "entities": entities,
            "relations": relations,
            "source": source,
            "page": page,
            "chunk_index": chunk_index,
        }

    # ── Neo4j CRUD ───────────────────────────────────────────────────────

    def save_graph(self, graph_data: Dict) -> None:
        """추출된 엔티티/관계를 Neo4j에 저장. 엔티티 임베딩 포함."""
        if not self._enabled:
            return
        if not self._index_ensured:
            self._ensure_vector_index()
            self._index_ensured = True
        source = graph_data["source"]
        page = graph_data["page"]
        chunk_index = graph_data["chunk_index"]

        with self._get_driver().session() as session:
            for entity in graph_data["entities"]:
                # CONTAINS 키워드 매칭의 광범위 반환 문제를 해결하기 위해
                # 엔티티 이름을 임베딩 벡터로 저장 → 유사도 기반 검색으로 대체 (자체 설계)
                embedding = self._embed(entity["name"])
                session.run(
                    """
                    MERGE (e:Entity {name: $name})
                    SET e.type = $type, e.embedding = $embedding
                    WITH e
                    MERGE (c:Chunk {source: $source, page: $page, chunk_index: $chunk_index})
                    MERGE (e)-[:MENTIONED_IN]->(c)
                    """,
                    name=entity["name"],
                    type=entity["type"],
                    embedding=embedding,
                    source=source,
                    page=page,
                    chunk_index=chunk_index,
                )

            for rel in graph_data["relations"]:
                session.run(
                    """
                    MERGE (a:Entity {name: $from_name})
                    MERGE (b:Entity {name: $to_name})
                    MERGE (a)-[r:RELATES {type: $rel_type}]->(b)
                    SET r.source = $source, r.page = $page, r.chunk_index = $chunk_index
                    """,
                    from_name=rel["from"],
                    to_name=rel["to"],
                    rel_type=rel["relation"],
                    source=source,
                    page=page,
                    chunk_index=chunk_index,
                )

    def delete_by_source(self, source: str) -> None:
        """특정 파일 관련 노드/관계 삭제."""
        if not self._enabled:
            return
        with self._get_driver().session() as session:
            session.run(
                """
                MATCH (c:Chunk {source: $source})
                OPTIONAL MATCH (e:Entity)-[:MENTIONED_IN]->(c)
                DETACH DELETE c
                WITH e
                WHERE e IS NOT NULL
                  AND NOT (e)-[:MENTIONED_IN]->()
                DETACH DELETE e
                """,
                source=source,
            )

    def clear_graph(self) -> None:
        """모든 엔티티/관계/청크 노드 삭제."""
        if not self._enabled:
            return
        with self._get_driver().session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        self._index_ensured = False

    # ── 그래프 탐색 ──────────────────────────────────────────────────────

    def search_by_embedding(self, query: str) -> Dict:
        # 엔티티 임베딩 유사도 검색: CONTAINS 광범위 매칭 → 코사인 유사도 0.75 이상 엔티티만 반환 (자체 설계)
        # [ref:7] MTEB — 다국어 임베딩 덕분에 영어 쿼리로 한국어 엔티티 매칭 가능 (크로스 언어 간접 근거)
        if not self._enabled:
            return {"entities": [], "relations": [], "chunks": []}

        try:
            q_emb = self._embed(query)
        except Exception as e:
            print(f"[KG] 임베딩 오류: {e}")
            return {"entities": [], "relations": [], "chunks": []}

        try:
            with self._get_driver().session() as session:
                result = session.run(
                    """
                    CALL db.index.vector.queryNodes('entity_embedding', 5, $q_emb)
                    YIELD node AS e, score
                    WHERE score > 0.75
                    WITH e, score
                    OPTIONAL MATCH (e)-[r:RELATES]->(related:Entity)
                    WITH e, score, collect({rel: r, related: related})[..5] AS out_rels
                    OPTIONAL MATCH (e)<-[r2:RELATES]-(incoming:Entity)
                    WITH e, score, out_rels, collect({rel: r2, incoming: incoming})[..5] AS in_rels
                    OPTIONAL MATCH (e)-[:MENTIONED_IN]->(c:Chunk)
                    RETURN e, out_rels, in_rels, collect(c)[..3] AS chunks, score
                    """,
                    q_emb=q_emb,
                )
                entities, relations, chunks = {}, [], {}
                for record in result:
                    e = record["e"]
                    entities[e["name"]] = {"name": e["name"], "type": e.get("type", "")}
                    for item in record["out_rels"]:
                        if item["related"]:
                            related = item["related"]
                            entities[related["name"]] = {"name": related["name"], "type": related.get("type", "")}
                            relations.append({
                                "from": e["name"],
                                "relation": item["rel"]["type"] if item["rel"] else "",
                                "to": related["name"],
                            })
                    for item in record["in_rels"]:
                        if item["incoming"]:
                            incoming = item["incoming"]
                            entities[incoming["name"]] = {"name": incoming["name"], "type": incoming.get("type", "")}
                            relations.append({
                                "from": incoming["name"],
                                "relation": item["rel"]["type"] if item["rel"] else "",
                                "to": e["name"],
                            })
                    for c in record["chunks"]:
                        if c:
                            key = (c["source"], c["page"], c["chunk_index"])
                            chunks[key] = {
                                "source": c["source"],
                                "page": c["page"],
                                "chunk_index": c["chunk_index"],
                            }

                return {
                    "entities": list(entities.values()),
                    "relations": relations,
                    "chunks": list(chunks.values()),
                }
        except Exception as e:
            # 벡터 인덱스 미생성(build_graph 미실행) 또는 Neo4j 연결 오류 시 빈 결과 반환
            print(f"[KG] search_by_embedding 오류 (인덱스 미생성 또는 연결 오류): {e}")
            return {"entities": [], "relations": [], "chunks": []}

    def search_by_keywords_batch(self, keywords: List[str]) -> Dict:
        """키워드 목록을 배치 임베딩 후 Neo4j 1회 세션으로 처리."""
        if not self._enabled or not keywords:
            return {"entities": [], "relations": [], "chunks": []}

        try:
            resp = self._client.embeddings.create(input=keywords, model="text-embedding-3-small")
            embeddings = [item.embedding for item in resp.data]
        except Exception as e:
            print(f"[KG] 배치 임베딩 오류: {e}")
            return {"entities": [], "relations": [], "chunks": []}

        merged: Dict = {"entities": {}, "relations": [], "chunks": {}}
        try:
            with self._get_driver().session() as session:
                for emb in embeddings:
                    result = session.run(
                        """
                        CALL db.index.vector.queryNodes('entity_embedding', 5, $q_emb)
                        YIELD node AS e, score
                        WHERE score > 0.75
                        WITH e, score
                        OPTIONAL MATCH (e)-[r:RELATES]->(related:Entity)
                        WITH e, score, collect({rel: r, related: related})[..5] AS out_rels
                        OPTIONAL MATCH (e)<-[r2:RELATES]-(incoming:Entity)
                        WITH e, score, out_rels, collect({rel: r2, incoming: incoming})[..5] AS in_rels
                        OPTIONAL MATCH (e)-[:MENTIONED_IN]->(c:Chunk)
                        RETURN e, out_rels, in_rels, collect(c)[..3] AS chunks, score
                        """,
                        q_emb=emb,
                    )
                    for record in result:
                        e = record["e"]
                        merged["entities"][e["name"]] = {"name": e["name"], "type": e.get("type", "")}
                        for item in record["out_rels"]:
                            if item["related"]:
                                related = item["related"]
                                merged["entities"][related["name"]] = {"name": related["name"], "type": related.get("type", "")}
                                merged["relations"].append({
                                    "from": e["name"],
                                    "relation": item["rel"]["type"] if item["rel"] else "",
                                    "to": related["name"],
                                })
                        for item in record["in_rels"]:
                            if item["incoming"]:
                                incoming = item["incoming"]
                                merged["entities"][incoming["name"]] = {"name": incoming["name"], "type": incoming.get("type", "")}
                                merged["relations"].append({
                                    "from": incoming["name"],
                                    "relation": item["rel"]["type"] if item["rel"] else "",
                                    "to": e["name"],
                                })
                        for c in record["chunks"]:
                            if c:
                                key = (c["source"], c["page"], c["chunk_index"])
                                merged["chunks"][key] = {"source": c["source"], "page": c["page"], "chunk_index": c["chunk_index"]}
        except Exception as e:
            print(f"[KG] 배치 검색 오류: {e}")

        return {
            "entities": list(merged["entities"].values()),
            "relations": merged["relations"],
            "chunks": list(merged["chunks"].values()),
        }

    def build_graph_for_document(self, content: str, metadata: Dict) -> None:
        """KG 추출/저장 - 백그라운드 업로드 처리용."""
        if not self._enabled:
            return
        from app.core.knowledge_base import knowledge_base as kb

        content = kb.splitter.normalize_text(content)
        lang = metadata.get("lang")
        if not lang or lang == "unknown":
            lang = kb.splitter.detect_language(content)

        chunks = kb.splitter.split_text(content, lang=lang)
        for i, chunk in enumerate(chunks):
            graph_data = self.extract_graph_from_text(
                chunk,
                source=metadata.get("source", ""),
                page=metadata.get("page", 0),
                chunk_index=i,
            )
            self.save_graph(graph_data)


# 전역 인스턴스
knowledge_graph = KnowledgeGraph()
