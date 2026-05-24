import os
import re
import unicodedata
from pathlib import Path
from typing import List
import fitz          # PyMuPDF
import pymupdf4llm
from app.config import settings

class DocumentIngester:
    """PDF에서 문서를 수집합니다."""

    def __init__(self):
        self.document_path = Path(settings.document_path)
        self.document_path.mkdir(parents=True, exist_ok=True)
        
    def normalize_text(self, text: str) -> str:
        """PDF 추출 텍스트 정규화 (인코딩 수정 + 노이즈 제거)."""
        # 한국어 자모 분리 복구 (NFD → NFC) 다른 언어에 대해서도 무해함 
        text = unicodedata.normalize("NFC", text)
        # 소프트 하이픈 줄바꿈 제거: "단어-\n계속" → "단어계속"
        text = re.sub(r"-\n", "", text)
        # PDF 제어문자 제거 (폼피드 \x0c 등), 일반 whitespace 보존
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        # 3개 이상 연속 개행 → 2개로 정리
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 줄 끝 공백 제거
        text = re.sub(r"[ \t]+\n", "\n", text)
        return text.strip()

    def detect_language(self, text: str) -> str:
        """페이지 언어 감지. 텍스트가 너무 짧으면 'unknown' 반환."""
        from langdetect import detect, LangDetectException
        sample = text[:500].strip()
        if len(sample) < 20:
            return "unknown"
        try:
            return detect(sample)
        except LangDetectException:
            return "unknown"

    def extract_from_pdf(self, pdf_path: str) -> List[dict]:
        """pymupdf4llm으로 PDF를 마크다운 추출 (표 인라인 포함, 정규화, 언어 감지)."""
        documents = []
        try:
<<<<<<< Updated upstream
            doc = fitz.open(pdf_path)
            for page_num in range(len(doc)):
                md_text = pymupdf4llm.to_markdown(doc, pages=[page_num])
                if not md_text.strip():
                    continue
                if len(md_text.strip()) < 50:
                    print(f"  ⚠️  p{page_num + 1}: 텍스트 부족 — OCR 미지원 (스킵)")
                    continue
                normalized = self.normalize_text(md_text)
                lang = self.detect_language(normalized)
                documents.append({
                    "content": normalized,
                    "metadata": {
                        "source": os.path.basename(pdf_path),
                        "page": page_num + 1,
                        "lang": lang,
                    }
                })
            doc.close()
        except Exception as e:
            print(f"PDF 추출 오류 ({pdf_path}): {e}")
        return documents



ingester = DocumentIngester()


def sync_documents() -> None:
    """DATA/documents 폴더와 ChromaDB를 증분 동기화."""
    from app.core.knowledge_base import knowledge_base  # 순환 import 방지

    current_pdfs = {f.name: f for f in ingester.document_path.glob("*.pdf")}
    existing_data = knowledge_base.vector_store.get()
    existing_filenames = {m["source"] for m in existing_data["metadatas"] if m}

    # 폴더에서 삭제된 파일 → DB 제거
    for filename in existing_filenames - set(current_pdfs):
        knowledge_base.vector_store.delete(where={"source": filename})
        print(f"[삭제] {filename}")

    # DB에 없는 신규 파일 → 추가
    new_files = set(current_pdfs) - existing_filenames
    if not new_files and not (existing_filenames - set(current_pdfs)):
        print("모든 문서가 최신 상태입니다.")
    else:
        print(f"신규 {len(new_files)}개 추가 시작")

    for filename in new_files:
        pages = ingester.extract_from_pdf(str(current_pdfs[filename]))
        if not pages:
            print(f"  ⚠️  {filename}: 추출 내용 없음")
            continue
        for page in pages:
            knowledge_base.add_document(page["content"], page["metadata"])
        print(f"[추가] {filename} — {len(pages)} 페이지")

    total = knowledge_base.get_document_count()
    print(f"동기화 완료 — 총 청크: {total}")


if __name__ == "__main__":
    sync_documents()
=======
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    
                    tables = page.extract_tables()
                    table_text = ""
                    if tables:
                        for table in tables:
                            for row in table:
                                filtered_row = [item.replace('\n', ' ') if item else "" for item in row]
                                table_text += "| " + " | ".join(filtered_row) + " |\n"
                    
                    combined_content = f"{text}\n\n[Tables]\n{table_text}"
                    
                    if combined_content.strip():
                        documents.append({
                            "content": combined_content,
                            "metadata": {
                                "source": os.path.basename(pdf_path),
                                "page": page_num + 1
                            }
                        })
        except Exception as e:
            logger.error(f"PDF 추출 오류 {pdf_path}: {e}")
            
        return documents

    def inspect_parsing(self, pdf_path: str) -> None:
        """PDF의 표 파싱 결과를 콘솔에 출력합니다."""
        logger.info(f"=== 표 파싱 검사 시작: {os.path.basename(pdf_path)} ===")

        try:
            with pdfplumber.open(pdf_path) as pdf:
                logger.info(f"총 페이지 수: {len(pdf.pages)}")

                for page_num, page in enumerate(pdf.pages, start=1):
                    tables = page.extract_tables()

                    if not tables:
                        continue  # 표 없는 페이지는 스킵

                    logger.info(f"\n--- [Page {page_num}] 표 {len(tables)}개 ---")
                    for t_idx, table in enumerate(tables, start=1):
                        col_count = max(len(row) for row in table) if table else 0
                        logger.info(f"  표 #{t_idx}: {len(table)}행 x {col_count}열")
                        for r_idx, row in enumerate(table):
                            cleaned = [cell.replace('\n', ' ') if cell else "" for cell in row]
                            logger.info(f"    행 {r_idx+1}: {cleaned}")

        except Exception as e:
            logger.error(f"파싱 검사 오류 {pdf_path}: {e}")

        logger.info(f"\n=== 파싱 검사 완료 ===")

    def crawl_web(self, url: str) -> Tuple[str, str]:
        """웹 페이지를 크롤링하고 텍스트를 추출합니다."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, "html.parser")

            for script in soup(["script", "style"]):
                script.decompose()

            text = soup.get_text()
            text = re.sub(r"\n\s*\n", "\n", text)
            text = text.strip()

            return url, text
        except Exception as e:
            logger.error(f"웹 크롤링 오류 {url}: {e}")
            return url, ""

    def save_document(self, filename: str, content: str) -> Path:
        """문서 콘텐츠를 파일로 저장합니다."""
        file_path = self.document_path / filename
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return file_path


ingester = DocumentIngester()
>>>>>>> Stashed changes
