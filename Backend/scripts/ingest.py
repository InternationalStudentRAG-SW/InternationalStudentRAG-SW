#!/usr/bin/env python
"""
초기 데이터 수집 스크립트.
data/documents 폴더의 모든 PDF 문서를 로드하여 ChromaDB에 저장합니다.
"""

import sys
from pathlib import Path

# 부모 디렉토리를 경로에 추가하여 임포트 가능하게 함
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.ingestion import ingester
from app.core.knowledge_base import knowledge_base


def main():
    """지식베이스에 문서 로드."""
    print("문서 수집 시작...")

    # 디렉토리에서 문서 추출
    documents = ingester.extract_from_directory()

    if not documents:
        print("data/documents/ 폴더에 PDF 문서가 없습니다.")
        return

    print(f"{len(documents)}개의 문서를 찾았습니다.")

    # 각 문서를 지식베이스에 추가
    for filename, content in documents:
        print(f"{filename} 지식베이스에 추가 중...")
        try:
            knowledge_base.add_pdf_document(filename, content)
            print(f"  ✓ {filename} 추가 완료")
        except Exception as e:
            print(f"  ✗ {filename} 추가 오류: {e}")

    # 요약 출력
    total_chunks = knowledge_base.get_document_count()
    print(f"\n수집 완료!")
    print(f"데이터베이스의 총 청크: {total_chunks}")


if __name__ == "__main__":
    main()
