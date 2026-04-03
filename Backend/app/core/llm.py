# llm.py
from typing import Optional, Tuple, List
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.core.retriever import retriever
from app.config import settings


class RAGLLMChain:
    """RAG를 사용하여 답변을 생성합니다."""

    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=0.0,
            max_tokens=2048
        )

        self.qa_prompt = PromptTemplate(
            input_variables=["context", "question"],
            template="""대학교 관련 질문으로 유학생을 돕는 전문가 어시스턴트입니다.

다음 컨텍스트를 사용하여 질문에 답변하십시오. 컨텍스트에 관련된 정보가 없으면 "이 질문에 답변할 충분한 정보가 없습니다"라고 말하세요.

컨텍스트:
{context}

질문: {question}

질문과 같은 언어로 명확하고 유용한 답변을 제공하십시오."""
        )

        self.qa_chain = self.qa_prompt | self.llm | StrOutputParser()

    def generate_answer(
        self,
        question: str,
        context: Optional[str] = None,
        top_k: int = 3
    ) -> Tuple[str, List[dict]]:
        """
        RAG를 사용하여 답변을 생성합니다.

        Args:
            question: 사용자 질문
            context: 선택 사항인 사전 가져온 컨텍스트
            top_k: 검색할 문서 개수

        Returns:
            (답변, 출처_목록)
        """
        # 컨텍스트가 제공되지 않으면 관련 문서 검색
        if context is None:
            context, sources = retriever.retrieve_with_sources(question, k=top_k)
        else:
            sources = []

        # 답변 생성
        try:
            answer = self.qa_chain.invoke({"context": context, "question": question})
        except Exception as e:
            answer = f"답변 생성 오류: {str(e)}"

        return answer, sources

    def generate_answer_with_language(
        self,
        question: str,
        language: str = "en",
        top_k: int = 3
    ) -> Tuple[str, List[dict]]:
        """
        입력 언어를 존중하여 답변을 생성합니다.

        Args:
            question: 사용자 질문
            language: 감지된 언어 코드 (예: 'en', 'ko')
            top_k: 검색할 문서 개수

        Returns:
            (답변, 출처_목록)
        """
        # 문서 검색
        context, sources = retriever.retrieve_with_sources(question, k=top_k)

        # 언어별 프롬프트 생성
        language_instructions = {
            "en": "영어로 답변해주세요.",
            "ko": "한국어로 답변해주세요.",
            "zh": "중국어로 답변해주세요.",
            "es": "스페인어로 답변해주세요.",
        }

        lang_instruction = language_instructions.get(language, "영어로 답변해주세요.")

        # 언어 지시사항과 함께 답변 생성
        prompt = PromptTemplate(
            input_variables=["context", "question"],
            template=f"""대학교 관련 질문으로 유학생을 돕는 전문가 어시스턴트입니다.

다음 컨텍스트를 사용하여 질문에 답변하십시오. 컨텍스트에 관련된 정보가 없으면 "이 질문에 답변할 충분한 정보가 없습니다"라고 말하세요.
답변을 작성할 때는 반드시 제공된 컨텍스트의 [문서 번호]나 출처를 함께 언급하여 신뢰성을 높여주세요.

{lang_instruction}

컨텍스트:
{{context}}

질문: {{question}}"""
        )

        chain = prompt | self.llm | StrOutputParser()

        try:
            answer = chain.invoke({"context": context, "question": question})
        except Exception as e:
            answer = f"답변 생성 오류: {str(e)}"

        return answer, sources


rag_chain = RAGLLMChain()
