from langdetect import detect, detect_langs, LangDetectException


class LanguageDetector:
    """입력 텍스트의 언어를 감지합니다."""

    # 주요 유학생 언어를 지원하기 위한 언어 코드 매핑
    LANGUAGE_MAP = {
        'en': '영어',
        'ko': '한국어',
        'zh-cn': '중국어(간체)',
        'zh-tw': '중국어(번체)',
        'zh': '중국어',
        'ja': '일본어',
        'es': '스페인어',
        'fr': '프랑스어',
        'de': '독일어',
        'ru': '러시아어',
        'ar': '아랍어',
        'pt': '포르투갈어',
        'vi': '베트남어',
        'th': '태국어',
    }

    @staticmethod
    def detect(text: str, min_length: int = 10) -> str:
        """
        텍스트의 언어를 감지합니다.

        Args:
            text: 감지할 텍스트
            min_length: 감지를 위한 최소 텍스트 길이

        Returns:
            언어 코드 (예: 'en', 'ko')
        """
        if not text or len(text.strip()) < min_length:
            return 'en'  # 기본값: 영어

        try:
            lang = detect(text)
            return lang.lower()
        except LangDetectException:
            return 'en'  # 오류 시 기본값: 영어

    @staticmethod
    def detect_with_probabilities(text: str) -> dict:
        """
        확률과 함께 언어를 감지합니다.

        Returns:
            {'language': 코드, 'probabilities': {...}}
        """
        if not text or len(text.strip()) < 10:
            return {
                'language': 'en',
                'probabilities': {'en': 1.0}
            }

        try:
            results = detect_langs(text)
            probabilities = {str(r).split(':')[0]: float(str(r).split(':')[1])
                           for r in results}
            detected_lang = max(probabilities, key=probabilities.get)

            return {
                'language': detected_lang,
                'probabilities': probabilities
            }
        except LangDetectException:
            return {
                'language': 'en',
                'probabilities': {'en': 1.0}
            }

    @staticmethod
    def get_language_name(lang_code: str) -> str:
        """언어 코드의 친화적인 이름을 반환합니다."""
        return LanguageDetector.LANGUAGE_MAP.get(lang_code, '알 수 없음')


detector = LanguageDetector()
