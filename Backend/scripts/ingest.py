#!/usr/bin/env python
"""
고도화된 데이터 수집 스크립트.
- 논문 기반 하이브리드 검색 지원 (Vector + BM25)
- PDF 레이아웃(표/리스트) 보존 및 페이지별 메타데이터 저장
"""

import sys
import os
from pathlib import Path

# 프로젝트 루트 디렉토리를 경로에 추가하여 app 패키지를 찾을 수 있게 함
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.ingestion import ingester
from app.core.knowledge_base import knowledge_base
from app.config import settings

def main():
    """지식베이스에 고도화된 방식으로 문서 로드."""
    print("🚀 [하이브리드 RAG] 문서 수집 및 지식베이스 구축을 시작합니다...")

    # 1. 설정된 경로에서 PDF 파일 목록 확보
    pdf_path = Path(settings.document_path)
    pdf_files = list(pdf_path.glob("*.pdf"))

    if not pdf_files:
        print(f"⚠️ {settings.document_path} 폴더에 PDF 문서가 없습니다.")
        return

    print(f"📂 총 {len(pdf_files)}개의 문서를 발견했습니다.")

    for pdf_file in pdf_files:
        print(f"\n--- [{pdf_file.name}] 처리 시작 ---")
        try:
            # 2. PDF 추출 (수정된 ingester 사용: 표 구조 보존 및 페이지별 dict 반환)
            # 반환 형식: [{"content": "...", "metadata": {"source": "...", "page": 1}}, ...]
            pages_data = ingester.extract_from_pdf(str(pdf_file))

            if not pages_data:
                print(f"  ⚠️ {pdf_file.name}: 추출된 내용이 없습니다.")
                continue

            # 3. 페이지별로 지식베이스에 추가
            for page in pages_data:
                # [중요] knowledge_base.add_document 내부에서 
                # 벡터 임베딩과 BM25 토큰화가 동시에 이루어져야 합니다.
                knowledge_base.add_document(
                    content=page["content"],
                    metadata=page["metadata"]
                )
            
            print(f"  ✅ {pdf_file.name}: 총 {len(pages_data)} 페이지 저장 완료")

        except Exception as e:
            # 에러 발생 시 파일명과 함께 상세 원인 출력
            print(f"  ❌ {pdf_file.name} 처리 중 오류 발생: {e}")

    # 4. 최종 결과 요약
    # 데이터베이스에 저장된 총 청크(조각) 수를 확인합니다.
    try:
        total_chunks = knowledge_base.get_document_count()
        print(f"\n✨ 수집 완료!")
        print(f"📊 현재 지식베이스 내 총 청크 수: {total_chunks}")
    except:
        print("\n✨ 수집 프로세스가 종료되었습니다.")

if __name__ == "__main__":
    main()