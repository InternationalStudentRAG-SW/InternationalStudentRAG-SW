"""
ChromaDB에 저장된 청크들을 읽어 Neo4j 지식그래프를 구축하는 스크립트.
임베딩은 이미 완료된 ChromaDB를 재사용하고, 그래프만 새로 구축한다.
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.core.knowledge_base import knowledge_base
from app.core.knowledge_graph import knowledge_graph

MAX_WORKERS = 10  # 동시 GPT 호출 수


def process_chunk(args):
    idx, total, doc = args
    meta = doc["metadata"]
    source = meta.get("source", "")
    page = meta.get("page", 0)
    chunk_index = meta.get("chunk_index", 0)

    try:
        graph_data = knowledge_graph.extract_graph_from_text(
            doc["content"],
            source=source,
            page=page,
            chunk_index=chunk_index,
        )
        knowledge_graph.save_graph(graph_data)
        entity_count = len(graph_data["entities"])
        print(f"  [{idx+1}/{total}] {source} p{page}-c{chunk_index}: 엔티티 {entity_count}개")
        return True
    except Exception as e:
        print(f"  [{idx+1}/{total}] {source} p{page}-c{chunk_index}: 오류 - {e}")
        return False


def build_graph_from_chroma():
    docs = knowledge_base.get_all_documents()
    total = len(docs)
    print(f"총 {total}개 청크 병렬 처리 시작 (동시 {MAX_WORKERS}개)")
    start = time.time()

    args = [(i, total, doc) for i, doc in enumerate(docs)]
    success, failed = 0, 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_chunk, arg): arg for arg in args}
        for future in as_completed(futures):
            if future.result():
                success += 1
            else:
                failed += 1

    elapsed = time.time() - start
    print(f"\n완료 — 성공: {success}, 실패: {failed}, 총: {total}, 소요시간: {elapsed:.1f}초")


if __name__ == "__main__":
    build_graph_from_chroma()
