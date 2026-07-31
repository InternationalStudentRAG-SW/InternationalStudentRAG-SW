# app/core/llm.py

import json

from typing import Optional, Tuple, List, Dict, Any

from langchain_openai import ChatOpenAI

from langchain_core.prompts import PromptTemplate

from langchain_core.output_parsers import StrOutputParser

from app.core.retriever import retriever

from app.config import settings



# 💡 Usefulness 가이드라인(중복 제거, 전제조건 스킵, 다음 여정 유도) 통합 프롬프트

_CONVERSATIONAL_LEADING_TEMPLATE = """귀하는 대한민국 대학교에 재학 중인 외국인 유학생들의 정착과 행정 절차를 돕는 전문가 어시스턴트입니다.



[1] 제공된 유학생 대화 세션 히스토리와 참고 컨텍스트(RAG)를 바탕으로 사용자의 현재 질문에 성실하게 답변하십시오.

[2] 답변을 마친 후, 사용자가 다음에 수행해야 하거나 관심을 가질 만한 '유용한 후속 질문(Useful Follow-up Questions)' 3개를 생성하십시오.



{lang_instruction}

컨텍스트에 관련된 정보가 없으면 "이 질문에 답변할 충분한 정보가 없습니다"라고 말하세요.



---

[대화 세션 히스토리 (최근 내역 우선)]

{session_history}



[참고 컨텍스트 (RAG 문서 추출 내용)]

{context}



[사용자의 현재 질문]

{question}

---



[후속 질문 생성 시 필수 준수 가이드라인 (Usefulness Guidelines)]

1. 중복 제거 (No Redundancy): 사용자의 현재 질문이나 세션 히스토리에 이미 등장했던 내용과 의미상 중복되거나 단순히 유사한 질문은 절대 배제하십시오.

2. 전제조건 스킵 (Skip Prerequisites): 사용자가 이미 수행했거나 알고 있을 것으로 간주되는 기초적인 지식 단계는 건너뛰고, 실질적인 다음 액션 단계의 질문을 생성하십시오.

3. 다음 유저 여정 유도 (Lead Next Journey): 유학생 행정 주기(예: 모집요강 확인 -> 원서접수 -> 서류제출 및 공증 -> 합격확인 -> 비자신청 -> 정착 및 학사운영)에 따라, 다음 단계에 마주하게 될 실무적이고 구체적인 행동을 유도하는 질문을 제안하십시오.



[출력 양식 가이드]

반드시 아래의 엄격한 JSON 형식으로만 결과를 반환해야 하며, 마크다운 코드 블록(```json ```)을 제외한 다른 텍스트는 포함하지 마십시오.



{{

    "answer": "사용자 질문에 대한 최종 답변 내용",

    "suggestions": [

        "가이드라인을 충족하며 사용자가 질문한 언어와 동일한 언어로 작성된 후속 질문 1",

        "동일한 언어로 작성된 후속 질문 2",

        "동일한 언어로 작성된 후속 질문 3"

    ]

}}"""



_LANGUAGE_INSTRUCTIONS = {

    "ko": "한국어로 답변하고, 후속 질문도 한국어로 생성하십시오.",

    "en": "Please answer in English, and generate follow-up questions in English as well.",

    "zh": "请用中文回答，并同样用中文生成后续推荐问题。",

    "es": "Por favor, responda en español y genere también las preguntas de seguimiento en español.",
    
    "vi": "Vui lòng trả lời bằng tiếng Việt và tạo các câu hỏi tiếp theo bằng tiếng Việt.",

    "auto": "사용자가 질문한 언어를 파악하여 반드시 답변과 후속 질문 모두 그 언어로 작성하십시오."

}



class RAGLLM:

    def __init__(self):

        self.llm = ChatOpenAI(

            api_key=settings.openai_api_key,

            model="gpt-4o-mini",

            temperature=0.4,

            max_tokens=2048

        )



    def generate_answer_with_suggestions(

        self,

        question: str,

        context: str,

        lang_instruction: str,

        history: Optional[List[Dict[str, str]]] = None,

    ) -> Tuple[str, List[str]]:

        """내부적으로 대화 세션 히스토리와 가이드라인을 융합하여 JSON 결과물을 파싱하는 코어 파이프라인"""

       

        # FastAPI 세션 히스토리 포맷팅

        history_str = ""

        if history:

            for turn in history[-5:]:

                role = "유저" if turn.get("role") == "user" else "봇"

                history_str += f"- {role}: {turn.get('content')}\n"

        else:

            history_str = "(이전 대화 내역 없음 - 첫 질문)"



        # 안전하게 프롬프트 구성

        prompt_text = _CONVERSATIONAL_LEADING_TEMPLATE.format(

            lang_instruction=lang_instruction,

            session_history=history_str,

            context=context,

            question=question

        )

       

        try:

            # 💡 [교정] 최신 LangChain 스펙에 맞게 .predict() 대신 .invoke()를 사용하고 .content로 텍스트를 가져옵니다.

            response = self.llm.invoke(prompt_text)

            raw_output = response.content

           

            # 마크다운 제어문자 및 공백 제거

            clean_output = raw_output.replace("```json", "").replace("```", "").strip()

            parsed_data = json.loads(clean_output)

           

            answer = parsed_data.get("answer", "답변을 생성하지 못했습니다.")

            suggestions = parsed_data.get("suggestions", [])

        except Exception as e:

            # 💡 [교정] 예외 발생 시 변수 미선언 에러(UnboundLocalError)가 나지 않도록 안전하게 Fallback 구성

            answer = "죄송합니다. 답변을 생성하는 도중 에러가 발생했습니다."

            suggestions = [

                "비자 신청/연장을 위한 필수 서류 목록을 확인해 볼까요?",

                "동아대학교 외국인 전형 장학금 혜택 조건이 궁금하신가요?",

                "학기 중 인턴십이나 아르바이트 신청 절차를 알아볼까요?"

            ]

           

        return answer, suggestions



    def generate_answer_with_language(

        self,

        question: str,

        language: str = "en",

        top_k: int = 3,

        ko_query: Optional[str] = None,

    ) -> Tuple[str, List[dict]]:

        """기존 chat.py 라우터와 100% 규격을 맞추면서 신규 기능까지 우회 정제해 주는 호환성 메서드"""

       

        search_query = ko_query if ko_query else question

        context_str, sources = retriever.retrieve_with_sources(search_query, k=top_k)



        lang_instruction = _LANGUAGE_INSTRUCTIONS.get(

            language, "질문과 같은 언어로 명확하고 유용한 답변을 제공하십시오."

        )



        # 현재 로그인 전이므로 세션 히스토리는 빈 값 [] 전달

        answer, suggestions = self.generate_answer_with_suggestions(

            question=question,

            context=context_str,

            lang_instruction=lang_instruction,

            history=[]

        )



        # 후속 질문 결과를 문자열 하단에 결합

        # if suggestions:
        #     if language == "en":
        #         header = "\n\n💡 **Suggested Follow-up Questions:**\n"
        #     elif language == "zh":
        #         header = "\n\n💡 **推荐的反问问题:**\n"
        #     elif language == "es":
        #         header = "\n\n💡 **Preguntas de seguimiento recomendadas:**\n"
        #     else:
        #         header = "\n\n💡 **추천 후속 질문:**\n"
        #     formatted_suggestions = header + "\n".join([f"{i}. {s}" for i, s in enumerate(suggestions, 1)])
        #     final_answer = answer + formatted_suggestions

        # else:
        #     final_answer = answer

        return answer, sources, suggestions



    def generate_answer(

        self,

        question: str,

        context: Optional[str] = None,

        top_k: int = 3,

    ) -> Tuple[str, List[dict]]:

        """기본형 메소드 구조 호환 유지"""

        if context is None:

            context_str, sources = retriever.retrieve_with_sources(question, k=top_k)

        else:

            context_str = context

            sources = []



        lang_instruction = _LANGUAGE_INSTRUCTIONS.get("ko")

        answer, _ = self.generate_answer_with_suggestions(

            question=question,

            context=context_str,

            lang_instruction=lang_instruction,

            history=[]

        )

        return answer, sources



# chat.py 라우터 인스턴스 이름 바인딩

rag_chain = RAGLLM() 

