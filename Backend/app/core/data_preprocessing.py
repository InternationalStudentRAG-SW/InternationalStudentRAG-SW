# import re
# import json 
# import contractions
# import nltk
# import os
# from pathlib import Path  # 🚨 추가: 폴더 경로 탐색을 위해 필요합니다
# from konlpy.tag import Okt
# from nltk.corpus import stopwords
# from nltk.stem import SnowballStemmer
# from nltk.tokenize import word_tokenize
# from langdetect import detect, DetectorFactory

# from app.core.ingestion import ingester
# from app.config import settings  # 🚨 추가: 문서가 저장된 폴더 경로를 가져오기 위함

# # NLTK 필수 데이터 다운로드
# nltk.download('punkt')
# nltk.download('stopwords')
# nltk.download('punkt_tab')

# # 언어 감지 결과의 일관성을 위해 시드 고정
# DetectorFactory.seed = 0

# class HybridPipeline:
#     """논문 기반의 7단계 텍스트 전처리 파이프라인 클래스"""
    
#     def __init__(self):
#         # 한국어 형태소 분석기(Okt) / 영어 어근 추출기(Snowball) 초기화
#         self.okt = Okt()
#         self.en_stemmer = SnowballStemmer("english")
#         self.en_stopwords = set(stopwords.words('english'))
        
#         # 한국어 불용어 리스트
#         self.ko_stopwords = {'은', '는', '이', '가', '을', '를', '의', '에', '와', '과', '항', '제',
#                             '및', '등', '관련', '대하여', '경우', '내용', '위하여', '따라', '명'}

#     def clean_step(self, text):
#         # 1~4단계: 텍스트 정제 및 특수 형식 보존
#         # 1. Expand contractions
#         text = contractions.fix(text)
        
#         # 2. Normalization (소문자 변환)
#         text = text.lower()
        
#         # 4. Preserve legal format (숫자, 마침표, 하이픈, 괄호 등 규정 형식 보존)
#         text = re.sub(r'[^a-z0-9가-힣\s\.\-\(\)]', ' ', text)
        
#         # 3. Space removal (불필요한 공백 및 줄바꿈 정리)
#         text = re.sub(r'\s+', ' ', text).strip()
#         return text
        
#     def tokenize_step(self, text):
#         # 5~7단계: 한글/영어/숫자 동시 추출
#         temp_tokens = []
        
#         pos_tags = self.okt.pos(text)
        
#         for word, tag in pos_tags:
#             # 1. 한국어 명사일 경우
#             if tag == 'Noun':
#                 if word not in self.ko_stopwords and len(word) > 1:
#                     temp_tokens.append(word)
            
#             # 2. 영어일 경우 (소문자 변환 + 불용어 제거 + 어근 추출)
#             elif tag == 'Alpha':
#                 word_lower = word.lower()
#                 if word_lower not in self.en_stopwords:
#                     temp_tokens.append(self.en_stemmer.stem(word_lower))
            
#             # 3. 숫자일 경우 (D-2-5 같은 비자 코드를 살리기 위해 필수!)
#             elif tag == 'Number':
#                 temp_tokens.append(word)

#         # 기호만 있는 토큰(--, -, 1 등)을 제거하는 필터링
#         base_tokens = [t for t in temp_tokens if re.search(r'[a-z0-9가-힣]', t)]

#         # 7. Tokenization 확장: Unigrams + Bigrams 생성
#         bigrams = [" ".join(pair) for pair in zip(base_tokens, base_tokens[1:])]
        
#         return base_tokens + bigrams

#     def run_pipeline(self, text):
#         # 정제부터 토큰화까지 전 과정을 순차적으로 실행
#         cleaned_text = self.clean_step(text)
#         final_tokens = self.tokenize_step(cleaned_text)
#         return final_tokens

# def process_all_documents():
#     # DATA/documents 폴더 내의 모든 PDF를 처리하는 메인 로직
#     pipeline = HybridPipeline()
    
#     print("📂 PDF 텍스트 추출 및 전처리를 시작합니다...")
    
#     # settings.py에 정의된 문서 폴더 경로를 가져옵니다.
#     doc_dir = Path(settings.document_path)
    
#     if not doc_dir.exists():
#         print(f"⚠️ {doc_dir} 폴더가 존재하지 않습니다. 경로를 확인해 주세요.")
#         return None

#     all_processed_data = []

#     # 폴더 안의 모든 .pdf 파일을 하나씩 찾아서 반복합니다.
#     for pdf_file in doc_dir.glob("*.pdf"):
#         filename = pdf_file.name
#         print(f"\n--- [{filename}] 처리 중 ---")
        
#         # ingester의 기존 함수를 사용해 PDF 추출 (페이지별 딕셔너리 리스트 반환)
#         extracted_pages = ingester.extract_from_pdf(str(pdf_file))
        
#         # 페이지별로 나뉜 텍스트를 하나의 거대한 문자열로 합치기
#         full_text = "\n".join([page["content"] for page in extracted_pages])
        
#         # 파이프라인 적용
#         processed_tokens = pipeline.run_pipeline(full_text)
        
#         all_processed_data.append({
#             "filename": filename,
#             "tokens": processed_tokens
#         })
        
#         print(f"✅ 완료: {len(processed_tokens)}개의 토큰이 생성되었습니다.")
#         print(f"💡 샘플 토큰: {processed_tokens[:10]}")

#     return all_processed_data

# if __name__ == "__main__":
#     results = process_all_documents()
#     if results:
#         output_filename = "preprocessed_tokens_check.json"
        
#         with open(output_filename, "w", encoding="utf-8") as f:
#             json.dump(results, f, ensure_ascii=False, indent=4)
            
#         print("\n=======================================================")
#         print(f"✨ 모든 문서의 전처리가 성공적으로 끝났습니다!")
#         print(f"📁 현재 폴더에 '{output_filename}' 파일이 생성되었습니다.")
#         print("해당 파일을 열어서 'd', '2', '5', 'visa' 등의 토큰이 잘 살아있는지 확인해 보세요!")
#         print("=======================================================")