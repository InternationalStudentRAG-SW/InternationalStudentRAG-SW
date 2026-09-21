import json
from typing import List, Dict
from neo4j import GraphDatabase
from openai import OpenAI
from app.config import settings

_EXTRACT_PROMPT = """다음 텍스트에서 유학생 관련 핵심 엔티티와 관계를 추출하세요.

엔티티 유형: 비자, 서류, 기관, 절차, 자격요건, 기간, 비용, 언어시험
관계 유형: 필요서류, 제출기관, 소요기간, 비용, 자격요건, 다음절차, 관련항목

반드시 아래 JSON 형식으로만 응답하세요:
{
  "entities": [
    {"name": "엔티티명", "type": "엔티티유형"}
  ],
  "relations": [
    {"from": "출발엔티티명", "relation": "관계유형", "to": "도착엔티티명"}
  ]
}

텍스트:
"""


class KnowledgeGraph:
    """Neo4j 기반 지식그래프 관리."""

    def __init__(self):
        self._driver = None
        self._client = OpenAI(api_key=settings.openai_api_key)
        # TODO: 지식그래프 고도화 후 아래 주석 해제
        # 비활성화 원인: search_simple CONTAINS 매칭이 너무 광범위하여
        # 키워드당 수천 개 엔티티/관계 반환 → LLM 토큰 초과로 답변 생성 실패
        # self._enabled = bool(settings.neo4j_uri)
        self._enabled = False

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

    # ── 엔티티/관계 추출 ────────────────────────────────────────────────

    def extract_graph_from_text(
        self, text: str, source: str, page: int, chunk_index: int
    ) -> Dict:
        """GPT로 텍스트에서 엔티티/관계 추출."""
        try:
            response = self._client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": "유학생 행정 문서 분석 전문가입니다. JSON만 응답합니다."},
                    {"role": "user", "content": _EXTRACT_PROMPT + text[:1500]},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            result = json.loads(response.choices[0].message.content)
            return {
                "entities": result.get("entities", []),
                "relations": result.get("relations", []),
                "source": source,
                "page": page,
                "chunk_index": chunk_index,
            }
        except Exception as e:
            print(f"[KG] 추출 오류 ({source} p{page} c{chunk_index}): {e}")
            return {"entities": [], "relations": [], "source": source, "page": page, "chunk_index": chunk_index}

    # ── Neo4j CRUD ───────────────────────────────────────────────────────

    def save_graph(self, graph_data: Dict) -> None:
        """추출된 엔티티/관계를 Neo4j에 저장."""
        if not self._enabled:
            return
        source = graph_data["source"]
        page = graph_data["page"]
        chunk_index = graph_data["chunk_index"]

        with self._get_driver().session() as session:
            # 엔티티 저장 (MERGE: 중복 방지)
            for entity in graph_data["entities"]:
                session.run(
                    """
                    MERGE (e:Entity {name: $name})
                    SET e.type = $type
                    WITH e
                    MERGE (c:Chunk {source: $source, page: $page, chunk_index: $chunk_index})
                    MERGE (e)-[:MENTIONED_IN]->(c)
                    """,
                    name=entity["name"],
                    type=entity["type"],
                    source=source,
                    page=page,
                    chunk_index=chunk_index,
                )

            # 관계 저장
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

    # ── 그래프 탐색 (에이전트 tool_graph용) ─────────────────────────────

    def search_simple(self, query: str) -> Dict:
        """
        query와 이름이 유사한 엔티티를 찾고 연결된 관계/청크 반환.
        반환: {entities, relations, chunks: [{source, page, chunk_index}]}
        """
        if not self._enabled:
            return {"entities": [], "relations": [], "chunks": []}

        with self._get_driver().session() as session:
            result = session.run(
                """
                MATCH (e:Entity)
                WHERE toLower(e.name) CONTAINS toLower($term)
                WITH e LIMIT 5
                OPTIONAL MATCH (e)-[r:RELATES]->(related:Entity)
                OPTIONAL MATCH (e)<-[r2:RELATES]-(incoming:Entity)
                OPTIONAL MATCH (e)-[:MENTIONED_IN]->(c:Chunk)
                RETURN e, r, related, r2, incoming, c
                """,
                term=query,
            )
            entities, relations, chunks = {}, [], {}
            for record in result:
                e = record["e"]
                entities[e["name"]] = {"name": e["name"], "type": e.get("type", "")}

                if record["related"]:
                    related = record["related"]
                    entities[related["name"]] = {"name": related["name"], "type": related.get("type", "")}
                    relations.append({
                        "from": e["name"],
                        "relation": record["r"]["type"] if record["r"] else "",
                        "to": related["name"],
                    })
                if record["incoming"]:
                    incoming = record["incoming"]
                    entities[incoming["name"]] = {"name": incoming["name"], "type": incoming.get("type", "")}
                    relations.append({
                        "from": incoming["name"],
                        "relation": record["r2"]["type"] if record["r2"] else "",
                        "to": e["name"],
                    })
                if record["c"]:
                    c = record["c"]
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


# 전역 인스턴스
knowledge_graph = KnowledgeGraph()
