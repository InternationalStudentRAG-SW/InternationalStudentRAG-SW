import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from app.config import settings


class QueryLogger:
    """질문, 답변 및 출처를 JSON 파일에 로깅합니다."""

    def __init__(self):
        self.log_dir = Path(settings.log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log_query(
        self,
        question: str,
        answer: str,
        language: Optional[str] = None,
        sources: Optional[List[dict]] = None
    ) -> Path:
        """
        쿼리와 답변을 로깅합니다.

        Args:
            question: 사용자의 질문
            answer: 생성된 답변
            language: 감지된 언어
            sources: 출처 문서 목록

        Returns:
            로그 파일 경로
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "answer": answer,
            "language": language or "unknown",
            "sources": sources or [],
        }

        # 일일 로그 파일 생성
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self.log_dir / f"queries_{today}.jsonl"

        # 로그 파일에 추가
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"쿼리 로깅 오류: {e}")

        return log_file

    def log_document_upload(
        self,
        filename: str,
        status: str,
        chunks_created: int = 0,
        error: Optional[str] = None
    ) -> Path:
        """
        문서 업로드 이벤트를 로깅합니다.

        Args:
            filename: 업로드된 파일의 이름
            status: 상태 ('success' 또는 'error')
            chunks_created: 생성된 청크 개수
            error: 상태가 'error'인 경우 오류 메시지

        Returns:
            로그 파일 경로
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": "document_upload",
            "filename": filename,
            "status": status,
            "chunks_created": chunks_created,
            "error": error,
        }

        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self.log_dir / f"uploads_{today}.jsonl"

        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"업로드 로깅 오류: {e}")

        return log_file

    def get_daily_stats(self, date: str) -> dict:
        """
        특정 날짜의 통계를 가져옵니다.

        Args:
            date: 'YYYY-MM-DD' 형식의 날짜

        Returns:
            쿼리 통계가 포함된 딕셔너리
        """
        query_file = self.log_dir / f"queries_{date}.jsonl"

        stats = {
            "date": date,
            "total_queries": 0,
            "languages": {},
            "average_sources": 0,
        }

        if not query_file.exists():
            return stats

        try:
            queries = []
            with open(query_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        queries.append(json.loads(line))

            stats["total_queries"] = len(queries)

            # 언어 카운팅
            for query in queries:
                lang = query.get("language", "unknown")
                stats["languages"][lang] = stats["languages"].get(lang, 0) + 1

            # 평균 출처
            if queries:
                total_sources = sum(len(q.get("sources", [])) for q in queries)
                stats["average_sources"] = total_sources / len(queries)

        except Exception as e:
            print(f"통계 읽기 오류: {e}")

        return stats

    def export_logs(self, output_file: str, date_from: Optional[str] = None, date_to: Optional[str] = None):
        """
        로그를 파일로 내보냅니다.

        Args:
            output_file: 출력 파일 경로
            date_from: 시작 날짜 (YYYY-MM-DD)
            date_to: 종료 날짜 (YYYY-MM-DD)
        """
        entries = []

        try:
            log_files = sorted(self.log_dir.glob("queries_*.jsonl"))

            for log_file in log_files:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            entries.append(json.loads(line))

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)

        except Exception as e:
            print(f"로그 내보내기 오류: {e}")


# 전역 로거 인스턴스
logger = QueryLogger()


def log_query(
    question: str,
    answer: str,
    language: Optional[str] = None,
    sources: Optional[List[dict]] = None
):
    """쿼리를 로깅하는 편의 함수입니다."""
    logger.log_query(question, answer, language, sources)


def log_document_upload(
    filename: str,
    status: str,
    chunks_created: int = 0,
    error: Optional[str] = None
):
    """문서 업로드를 로깅하는 편의 함수입니다."""
    logger.log_document_upload(filename, status, chunks_created, error)
