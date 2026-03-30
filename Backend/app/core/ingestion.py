import os
import re
from pathlib import Path
from typing import List, Tuple
import pdfplumber
import requests
from bs4 import BeautifulSoup
from app.config import settings


class DocumentIngester:
    """PDF 및 웹 소스에서 문서를 수집합니다."""

    def __init__(self):
        self.document_path = Path(settings.document_path)
        self.document_path.mkdir(parents=True, exist_ok=True)

    def extract_from_pdf(self, pdf_path: str) -> List[str]:
        """PDF 파일에서 텍스트를 추출합니다."""
        pages_content = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        pages_content.append(f"--- 페이지 {page_num + 1} ---\n{text}")
        except Exception as e:
            print(f"PDF 추출 오류 {pdf_path}: {e}")
        return pages_content

    def extract_from_directory(self) -> List[Tuple[str, str]]:
        """문서 디렉토리의 모든 PDF 파일에서 텍스트를 추출합니다."""
        documents = []
        pdf_files = list(self.document_path.glob("*.pdf"))

        for pdf_file in pdf_files:
            print(f"처리 중 {pdf_file.name}...")
            pages = self.extract_from_pdf(str(pdf_file))
            full_text = "\n".join(pages)
            documents.append((pdf_file.name, full_text))

        return documents

    def crawl_web(self, url: str) -> Tuple[str, str]:
        """웹 페이지를 크롤링하고 텍스트를 추출합니다."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, "html.parser")

            # 스크립트 및 스타일 태그 제거
            for script in soup(["script", "style"]):
                script.decompose()

            text = soup.get_text()
            # 공백 정리
            text = re.sub(r"\n\s*\n", "\n", text)
            text = text.strip()

            return url, text
        except Exception as e:
            print(f"웹 크롤링 오류 {url}: {e}")
            return url, ""

    def save_document(self, filename: str, content: str) -> Path:
        """문서 콘텐츠를 파일로 저장합니다."""
        file_path = self.document_path / filename
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return file_path


ingester = DocumentIngester()
