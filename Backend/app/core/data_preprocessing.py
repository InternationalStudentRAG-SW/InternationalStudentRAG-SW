import re
import contractions
import nltk
import os
from konlpy.tag import Okt
from nltk.corpus import stopwords
from nltk.stem import SnowballStemmer
from nltk.tokenize import word_tokenize
from langdetect import detect, DetectorFactory

from app.core.ingestion import ingester

# NLTK 필수 데이터 다운로드
nltk.download('punkt')
nltk.download('stopwords')
nltk.download('punkt_tab')

# 언어 감지 결과의 일관성을 위해 시드 고정
DetectorFactory.seed = 0

class HybridPipeline:
    """논문 기반의 7단계 텍스트 전처리 파이프라인 클래스"""
    
    def __init__(self):
        # 한국어 형태소 분석기(Okt) / 영어 어근 추출기(Snowball) 초기화
        self.okt = Okt()
        self.en_stemmer = SnowballStemmer("english")
        self.en_stopwords = set(stopwords.words('english'))
        
        # 한국어 불용어 리스트
        self.ko_stopwords = {'은', '는', '이', '가', '을', '를', '의', '에', '와', '과', '항', '제'}

    def clean_step(self, text):
        # 1~4단계: 텍스트 정제 및 특수 형식 보존
        # 1. Expand contractions
        text = contractions.fix(text)
        
        # 2. Normalization (소문자 변환)
        text = text.lower()
        
        # 4. Preserve legal format (숫자, 마침표, 하이픈, 괄호 등 규정 형식 보존)
        text = re.sub(r'[^a-z0-9가-힣\s\.\-\(\)]', ' ', text)
        
        # 3. Space removal (불필요한 공백 및 줄바꿈 정리)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
        
    def tokenize_step(self, text):
        # 5~7단계: 언어 감지 -> 토큰화 및 N-grams 생성
        try:
            lang = detect(text)
        except:
            lang = 'en'

        temp_tokens = [] # 임시로 토큰을 담을 리스트

        if lang == 'ko':
            # --- 한국어 처리 로직 ---
            nouns = self.okt.nouns(text) 
            # 불용어 제거 및 2글자 이상만 남기기
            temp_tokens = [t for t in nouns if t not in self.ko_stopwords and len(t) > 1]
        else:
            # --- 영어 처리 로직 ---
            words = word_tokenize(text)
            # 불용어 제거 및 어근 추출(Stemming)
            temp_tokens = [self.en_stemmer.stem(t) for t in words if t not in self.en_stopwords]

        # [핵심!] 기호만 있는 토큰(--, -, 1 등)을 완전히 제거하는 필터링
        # 알파벳이나 한글이 최소 하나는 포함된 토큰만 남깁니다.
        base_tokens = [t for t in temp_tokens if re.search(r'[a-z가-힣]', t)]

        # 7. Tokenization 확장: Unigrams + Bigrams 생성
        bigrams = [" ".join(pair) for pair in zip(base_tokens, base_tokens[1:])]
        
        return base_tokens + bigrams

    def run_pipeline(self, text):
        # 정제부터 토큰화까지 전 과정을 순차적으로 실행
        cleaned_text = self.clean_step(text)
        final_tokens = self.tokenize_step(cleaned_text)
        return final_tokens

def process_all_documents():
    # DATA/documents 폴더 내의 모든 PDF를 처리하는 메인 로직
    pipeline = HybridPipeline()
    
    print("📂 PDF 텍스트 추출 및 전처리를 시작합니다...")
    documents = ingester.extract_from_directory()
    
    if not documents:
        print("⚠️ 처리할 PDF 파일이 없습니다. 경로 설정을 확인해 주세요.")
        return None

    all_processed_data = []

    for filename, full_text in documents:
        print(f"\n--- [{filename}] 처리 중 ---")
        
        # 파이프라인 첨부
        processed_tokens = pipeline.run_pipeline(full_text)
        
        all_processed_data.append({
            "filename": filename,
            "tokens": processed_tokens
        })
        
        print(f"✅ 완료: {len(processed_tokens)}개의 토큰이 생성되었습니다.")
        print(f"💡 샘플 토큰: {processed_tokens[:10]}")

    return all_processed_data

if __name__ == "__main__":
    results = process_all_documents()
    if results:
        print("\n✨ 모든 문서의 전처리가 성공적으로 끝났습니다")