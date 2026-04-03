import os
import re
from pathlib import Path
from typing import List, Tuple
import pdfplumber
import requests
from bs4 import BeautifulSoup
from app.config import settings


class DocumentIngester:
    """PDF 및 웹 소스에서 문서를 수집하고 카테고리를 분류합니다."""

    def __init__(self):
        self.document_path = Path(settings.document_path)
        self.document_path.mkdir(parents=True, exist_ok=True)

    def extract_from_pdf(self, pdf_path: str) -> List[dict]:
        """표 구조와 페이지 메타데이터를 유지하며, 비자 카테고리를 감지하여 추출합니다."""
        documents = []
        filename = os.path.basename(pdf_path)
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                # 🚨 추가: 현재 페이지가 어떤 비자 섹션인지 추적
                current_visa_context = "일반 안내" 

                for page_num, page in enumerate(pdf.pages):
                    # 1. 일반 텍스트 추출
                    text = page.extract_text() or ""
                    
                    # 🚨 추가: 텍스트 내에서 비자 키워드 감지 (카테고리 꼬리표 생성)
                    if "D-2-1" in text or "D-2-2" in text or "D-2-4" in text:
                        current_visa_context = "D-2-1~4 일반 유학 비자"
                    elif "D-2-5" in text:
                        current_visa_context = "D-2-5 연구 유학 비자"
                    elif "D-2-6" in text:
                        current_visa_context = "D-2-6 교환학생 비자"
                    elif "D-2-8" in text:
                        current_visa_context = "D-2-8 방문학생 비자"
                    elif "D-4" in text:
                        current_visa_context = "D-4 한국어연수 비자"

                    # 2. 표(Table) 추출 및 Markdown 변환 (재정증명 등 핵심 정보가 표에 많음)
                    tables = page.extract_tables()
                    table_text = ""
                    if tables:
                        for table in tables:
                            for row in table:
                                # None 값 처리 및 줄바꿈 제거
                                filtered_row = [str(item).replace('\n', ' ') if item else "" for item in row]
                                if any(filtered_row): # 빈 줄 제외
                                    table_text += "| " + " | ".join(filtered_row) + " |\n"
                    
                    # 3. 문맥 정보(카테고리)를 텍스트 맨 앞에 강제로 삽입 (검색 정확도 향상 핵심)
                    combined_content = f"[카테고리: {current_visa_context}]\n{text}\n\n[표 데이터]\n{table_text}"
                    
                    if combined_content.strip():
                        documents.append({
                            "content": combined_content,
                            "metadata": {
                                "source": filename,
                                "page": page_num + 1,
                                "visa_category": current_visa_context # 메타데이터에도 저장
                            }
                        })
                        
            print(f"✅ {filename}: {len(pdf.pages)}페이지 추출 완료 (카테고리 태깅 포함)")
            
        except Exception as e:
            print(f"PDF 추출 오류 {pdf_path}: {e}")
            
        return documents

    def extract_from_directory(self) -> List[Tuple[str, str]]:
        """🚨 추가: 설정된 폴더 내의 모든 PDF 파일을 읽어옵니다. (data_preprocessing.py에서 사용)"""
        all_docs = []
        pdf_files = list(self.document_path.glob("*.pdf"))
        
        for pdf_path in pdf_files:
            # 파일 하나당 모든 페이지 텍스트를 합쳐서 반환 (전처리 확인용)
            pages = self.extract_from_pdf(str(pdf_path))
            full_text = "\n\n".join([p["content"] for p in pages])
            all_docs.append((pdf_path.name, full_text))
            
        return all_docs

    def crawl_web(self, url: str) -> Tuple[str, str]:
        """웹 페이지를 크롤링하고 텍스트를 추출합니다."""
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            for script in soup(["script", "style"]):
                script.decompose()
            text = re.sub(r"\n\s*\n", "\n", soup.get_text()).strip()
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