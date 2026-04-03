from app.core.knowledge_base import knowledge_base

def check_db_content():
    # 1. 저장된 전체 데이터 가져오기
    data = knowledge_base.vector_store.get()
    
    print(f"=== VectorDB 상태 확인 ===")
    
    if not data['ids']:
        print("DB가 비어 있습니다. 동기화 코드를 먼저 실행하세요.")
        return

    # 2. 저장된 파일 목록(Source) 추출
    sources = set(m['source'] for m in data['metadatas'])
    
    print(f"📍 저장된 총 청크 수: {len(data['ids'])}개")
    print(f"📄 학습된 파일 목록:")
    for src in sources:
        # 해당 파일의 페이지 수 계산
        pages = [m['page'] for m in data['metadatas'] if m['source'] == src]
        print(f"   - {src} (총 {max(pages)}페이지 분량)")

    # 3. 데이터 샘플 확인 (첫 번째 조각)
    print(f"\n🔍 데이터 샘플 (첫 번째 청크):")
    print(f"내용: {data['documents'][0][:100]}...")
    print(f"메타데이터: {data['metadatas'][0]}")

if __name__ == "__main__":
    check_db_content()