#!/usr/bin/env python
"""
증분 업데이트 기능 구현 (26.04.03)
- DB에 없는 새 파일만 추가 학습 (비용 및 시간 절감)
- 폴더에서 삭제된 파일은 DB에서도 자동 삭제
- PDF 레이아웃 보존 및 페이지별 메타데이터 저장 유지
"""

import sys
import os
from pathlib import Path

# 프로젝트 루트 디렉토리를 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.ingestion import ingester
from app.core.knowledge_base import knowledge_base
from app.config import settings

def main():
    """지식베이스에 변경된 문서만 반영하여 로드."""
    print("지식베이스 동기화를 시작합니다.")

    # 1. 실제 폴더 내 PDF 파일 목록 (Set으로 변환하여 비교 용이하게 함)
    pdf_path = Path(settings.document_path)
    current_pdf_files = {f.name: f for f in pdf_path.glob("*.pdf")}
    current_filenames = set(current_pdf_files.keys())

    # 2. 현재 DB에 저장된 파일 목록 가져오기 (메타데이터 활용) -> 전체 초기화 대신, DB에 이미 등록된 파일명을 확인
    try:
        # ChromaDB에서 모든 메타데이터를 가져와 저장된 'source' 목록 추출
        existing_data = knowledge_base.vector_store.get()
        if existing_data and existing_data['metadatas']:
            existing_filenames = set(m['source'] for m in existing_data['metadatas'])
        else:
            existing_filenames = set()
    except Exception as e:
        print(f"기존 DB 정보를 가져오는 데 실패했습니다: {e}")
        existing_filenames = set()

    # 3. 폴더에는 없는데 DB에만 남아있는 파일 제거
    deleted_files = existing_filenames - current_filenames
    for old_file in deleted_files:
        print(f"🗑️  DB에서 삭제된 파일 제거 중: {old_file}")
        try:
            knowledge_base.vector_store.delete(where={"source": old_file})
        except Exception as e:
            print(f"  ❌ {old_file} 삭제 중 오류: {e}")

    # 4. DB에 없는 새로운 파일만 골라내기
    new_filenames = current_filenames - existing_filenames
    
    if not new_filenames and not deleted_files:
        print("모든 문서가 최신 상태입니다. 추가할 파일이 없습니다.")
    else:
        print(f"📂 새 파일 {len(new_filenames)}개 추가, 삭제 파일 {len(deleted_files)}개 반영 시작.")

    for filename in new_filenames:
        pdf_file = current_pdf_files[filename]
        print(f"\n--- [{filename}] 신규 학습 시작 ---")
        try:
            # 표 구조 보존 및 페이지별 추출
            pages_data = ingester.extract_from_pdf(str(pdf_file))

            if not pages_data:
                print(f"  ⚠️ {filename}: 추출된 내용이 없습니다.")
                continue

            # 페이지별로 DB 추가
            for page in pages_data:
                knowledge_base.add_document(
                    content=page["content"],
                    metadata=page["metadata"]
                )
            
            print(f"  {filename}: 저장 완료")

        except Exception as e:
            print(f"  {filename} 처리 중 오류 발생: {e}")

    # 5. 최종 결과 요약
    try:
        total_chunks = knowledge_base.get_document_count()
        print(f"\n 동기화 완료!")
        print(f" 현재 지식베이스 내 총 청크 수: {total_chunks}")
    except:
        print("\n 프로세스가 종료되었습니다.")

if __name__ == "__main__":
    main()