from typing import Optional, Tuple, List
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.core.retriever import retriever
from app.config import settings


_SIMPLE_PROMPT = (
    "대학교 관련 질문으로 유학생을 돕는 전문가 어시스턴트입니다.\n\n"
    "다음 컨텍스트를 사용하여 질문에 답변하십시오. "
    "컨텍스트에 관련된 정보가 없으면 '이 질문에 답변할 충분한 정보가 없습니다'라고 말하세요.\n\n"
    "컨텍스트:\n{context}\n\n"
    "질문: {question}\n\n"
    "질문과 같은 언어로 명확하고 유용한 답변을 제공하십시오."
)

_LANGUAGE_INSTRUCTIONS = {
    "ko":   "한국어로 답변해주세요.",
    "en":   "영어로 답변해주세요.",
    "zh":   "중국어로 답변해주세요.",
    "es":   "스페인어로 답변해주세요.",
    "auto": (
        "사용자가 질문한 언어를 파악하여 반드시 그 언어로 답변하세요. "
        "컨텍스트가 한국어여도 영어 질문이면 영어로, 중국어 질문이면 중국어로 답변해야 합니다."
    ),
}

_LANG_PROMPT_TEMPLATE = (
    "대학교 관련 질문으로 유학생을 돕는 전문가 어시스턴트입니다.\n\n"
    "다음 컨텍스트를 사용하여 질문에 답변하십시오. "
    "컨텍스트에 관련된 정보가 없으면 '이 질문에 답변할 충분한 정보가 없습니다'라고 말하세요.\n"
    "답변을 작성할 때는 반드시 제공된 컨텍스트의 (출처: PDF파일명) 형식으로 출처를 함께 언급하여 신뢰성을 높여주세요.\n\n"
    "{lang_instruction}\n\n"
    "컨텍스트:\n{{context}}\n\n"
    "질문: {{question}}"
)


class RAGLLMChain:

    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=0.0,
            max_tokens=2048,
        )
        self.qa_prompt = PromptTemplate(
            input_variables=["context", "question"],
            template=_SIMPLE_PROMPT,
        )
        self.qa_chain = self.qa_prompt | self.llm | StrOutputParser()

    def generate_answer(
        self,
        question: str,
        context: Optional[str] = None,
        top_k: int = 3,
    ) -> Tuple[str, List[dict]]:
        if context is None:
            context, sources = retriever.retrieve_with_sources(question, k=top_k)
        else:
            sources = []

        try:
            answer = self.qa_chain.invoke({"context": context, "question": question})
        except Exception as e:
            answer = f"답변 생성 오류: {str(e)}"

        return answer, sources

    def generate_answer_with_language(
        self,
        question: str,
        language: str = "en",
        top_k: int = 3,
        ko_query: Optional[str] = None,
    ) -> Tuple[str, List[dict]]:
        context, sources = retriever.retrieve_with_sources(
            question, k=top_k, ko_query=ko_query
        )

        lang_instruction = _LANGUAGE_INSTRUCTIONS.get(
            language, "질문과 같은 언어로 답변해주세요."
        )

        prompt = PromptTemplate(
            input_variables=["context", "question"],
            template=_LANG_PROMPT_TEMPLATE.format(lang_instruction=lang_instruction),
        )
        chain = prompt | self.llm | StrOutputParser()

        try:
            answer = chain.invoke({"context": context, "question": question})
        except Exception as e:
            answer = f"답변 생성 오류: {str(e)}"

        return answer, sources


rag_chain = RAGLLMChain()
