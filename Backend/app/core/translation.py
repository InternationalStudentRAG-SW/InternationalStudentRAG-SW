from deep_translator import GoogleTranslator

class QueryTranslator:
    def __init__(self):
        # source='auto'로 설정하면 입력 언어를 자동으로 감지합니다.
        self.translator = GoogleTranslator(source='auto', target='ko')

    def combine_ko_en(self, user_query):
        """
        사용자의 질문을 분석하여 외국어일 경우 한국어로 번역하고, 
        논문 [cite: 101, 112]의 전략처럼 검색 범위를 넓히기 위해 [원문 + 번역문]을 반환합니다.
        """
        try:
            # 텍스트 번역 실행
            translated = self.translator.translate(user_query)
            
            # 번역 결과가 입력값과 같다면(이미 한국어거나 번역이 필요 없는 경우) 원문만 반환
            if translated.strip().lower() == user_query.strip().lower():
                return user_query
            
            # 검색 성능 향상을 위해 원문과 한국어 번역본을 합침 (Hybrid Lexical Coverage)
            combined_query = f"{user_query} {translated}"
            return combined_query
            
        except Exception as e:
            print(f"⚠️ 번역 중 오류 발생: {e}")
            return user_query


# ---------------------------------------------------------------------------------
# 테스트 코드: 이 파일을 직접 실행할 때만 작동함.
if __name__ == "__main__":
    translator = QueryTranslator()
    
    # 테스트 케이스 1: 영어 질문
    test_query_en = "What documents are required for a D-2 visa extension?"
    result_en = translator.combine_ko_en(test_query_en)
    print(f"\n[Test 1 - English]")
    print(f"입력: {test_query_en}")
    print(f"결과: {result_en}")

    # 테스트 케이스 2: 한국어 질문 (번역이 필요 없는 경우)
    test_query_ko = "비자 연장 서류 알려줘"
    result_ko = translator.combine_ko_en(test_query_ko)
    print(f"\n[Test 2 - Korean]")
    print(f"입력: {test_query_ko}")
    print(f"결과: {result_ko}")

    # 테스트 케이스 3: 기타 외국어 (예: 베트남어 유학생 가정)
    test_query_vi = "Làm thế nào để gia hạn visa?"
    result_vi = translator.combine_ko_en(test_query_vi)
    print(f"\n[Test 3 - Vietnamese]")
    print(f"입력: {test_query_vi}")
    print(f"결과: {result_vi}")