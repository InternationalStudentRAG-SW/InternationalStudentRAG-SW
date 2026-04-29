# [요약] A Hybrid Approach to Information Retrieval and Answer Generation for Regulatory Texts

---

## 정보 검색 시스템(information retrieval systems)

1. 검색 성능 향상 파이프라인
    1. Expand contractions(축약어 확장): `e.g., don’t → do not`으로 확장
    2. Normalization(정규화): 모든 텍스트 소문자화, 영숫자 제외 문자 제거
    3. Space removal(공백 제거): 불필요한 공백 제거
    4. Preserve legal format(법률 형식 유지): 법률 문서에 중요한 특수 문자 유지
        1. **참조 번호 보존**: "Rule 7.3.4"나 "DocumentID 11"처럼 점(`.`)으로 연결된 조항 번호가 단순한 구두점으로 인식되어 삭제되지 않도록 보호
        2. **특수 기호 유지**: 법률 문서에서 항목을 구분하는 괄호 `()`, 하이픈 `-`, 또는 조항 기호 등이 검색 키워드로서의 가치를 가질 때 이를 남겨두는 것
        3. **의미적 일관성**: 규제 텍스트는 용어가 매우 전문적이고 미세한 차이로 의무 사항이 달라지기 때문에, 정규화 과정에서 이런 구조적 정보가 사라지면 검색 정확도가 크게 떨어질 수 있음
    5. Stopwords(불용어): *nltk & scikit-learn* 세트를 이용해 불용어 제거
        
        <aside>
        🙋🏻‍♀️
        
        **stopword**: 자연어 처리 부문에서 사용되는 용어로, **문장의 의미를 전달하는 데에 거의 기여를 하지 않는, 자주 등장하지만 불필요한 단어**를 의미함.
        
        </aside>
        
    6. Stemming(어간 추출): Snowball Stemmer을 적용하여 어간 추출
        
        <aside>
        🙋🏻‍♀️
        
        **stemming**: 자연어 처리 부문에서 사용되는 용어로, **단어의 변형된 형태(예: 굴절, 파생)에서 접사(접두사, 접미사)를 제거하고 어간(Stem)을 분리해 내는 과정**을 의미함.
        
        </aside>
        
    7. Tokenization(토큰화): unigrams, bi-grams 생성
        
        <aside>
        🙋🏻‍♀️
        
        **tokenization**: 자연어 처리 부문에서 사용되는 용어로, **긴 데이터를 의미 있는 최소 단위(토큰, Token)로 분할하는 과정**을 의미함.
        
        </aside>
        
2. 접근 방식 구현
    1. BM25(Baseline(기준모델): k = 15, b = 0.75로 구성
    2. Semantic Retriever(의미 기반 검색): 의미론적 일치에 대해서만 Leveraged the fine-tuned model(미세 조정된 모델 활용)
    3. Hybrid System(하이브리드 시스템): BM25 + Leveraged the fine-tuned model → 아래의 식을 사용해 집계된 점수 계산
        
        $Score = \alpha \space \cdot \space Semantic \space Score \space + \space (1 \space - \alpha) \space \cdot \space Lexical \space Score$
        
        - $\alpha$(가중치) $\space = \space 0.65$ 로 설정: 의미론적 매칭 + 어휘 검색에 높은 가중치 주기 위함
        - Semantic Score(Vector Search System Score)
        - Lexical Score(Keyword Search System Score)
3. result
    
    ![정보 검색 시스템 간의 성능 비교](../assets/images/paper_hybrid_01.png)
    
    정보 검색 시스템 간의 성능 비교
    

## 답변 생성(Answer Generation)

1. RAG 프레임워크와 모델 선택
    1. 사용된 모델: Azure OpenAI의 **GPT-3.5 Turbo**, **GPT-4o Mini**, Groq API를 통한 **Llama 3.1**
    2. 최종 선택된 모델: **GPT-3.5 Turbo** (가장 높은 성능(RePASs 점수 0.57))
2. 데이터 필터링
    1. **상위 10개 추출**: 하이브리드 검색 시스템을 통해 질문과 가장 관련 있는 구절을 최대 10개까지 첨부
    2. **최소 점수제:** 관련성 점수가 **0.72 이상**인 구절만 답변 생성의 근거로 사용
    3. **점수 급락 차단:** 만약 다음 구절의 점수가 이전 구절보다 **0.1 이상 낮아지면**, 정보의 일관성을 위해 그 지점에서 데이터 수집을 중단
3. 시스템 프롬프트(System Prompt) 설계
    1. AI에게 "너는 규제 준수 도우미야"라는 역할을 명확히 부여
    2. **출처 준수:** 제공된 구절 이외의 외부 지식은 절대 사용하지 말 것.
    3. **우선순위:** 검색 엔진이 준 순서대로 정보의 중요도를 판단할 것.
    4. **정확성:** 모든 의무 사항과 통찰을 완전히 통합하고, 답변 내에서 모순이 없도록 할 것.
    
    > **프롬프트 내용:**
    “As a regulatory compliance assistant. Provide
    a **complete**, **coherent**, and **correct**
    response to the given question by synthesizing the
    information from the provided passages. Your
    answer should **fully integrate all relevant obli-
    gations, practices, and insights**, and directly
    address the question. The passages are presented
    in order of relevance, so **prioritize the infor-
    mation accordingly** and ensure consistency in
    your response, avoiding any contradictions. Ad-
    ditionally, reference **specific regulations and
    key compliance requirements** outlined in the
    regulatory content to support your answer. **Do
    not use any extraneous or external knowledge**
    outside of the provided passages when crafting
    your response.”
    > 
4. 답변 품질 측정: **RePASs(Regulatory Passage Answer Stability Score) 지표**
    1. **함의 점수 (Entailment Score, $E_s$):** 생성된 답변의 문장들이 실제 검색된 구절에 의해 뒷받침되는지 측정
    2. **모순 점수 (Contradiction Score, $C_s$):** 답변 중에 원문과 반대되는 내용이 있는지 확인
    3. **의무 범위 점수 (Obligation Coverage Score, $OC_s$):** 원문에 나온 중요한 행정적/법적 의무 사항들을 빠짐없이 담았는지 체크
        
        ![답변 품질 측정](../assets/images/paper_hybrid_02.png)
