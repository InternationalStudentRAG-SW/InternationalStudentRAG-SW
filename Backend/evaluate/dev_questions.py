"""
단일 에이전트 개발용 질문 세트 (체크리스트 8.2절의 '개발·회귀 테스트' 질문).

few-shot 예시와 ① 개발 시나리오에서 골랐다. 프롬프트·체크리스트를 고치면서 계속 보는 질문이므로
최종 평가에는 쓰지 않는다. RAGAS 평가 30문항(qa_dataset_cache*.json)과 비슷한 질문이 섞여 있어서,
단일 에이전트의 최종 평가는 이 세트·few-shot·RAGAS 30문항과 겹치지 않는 새 질문으로 해야 한다.

check  : 이 질문으로 무엇을 확인하려는지
gold   : 정답 초안 (status="draft"면 팀의 원문 확인 전). 2026-09-29 수집한 첫 바퀴 풀 기준.
  round1.slots        : {칸: [허용 상태]}  첫 바퀴 풀만 보고 ④가 내야 할 상태 (적은 칸만 채점)
  round1.must_cite    : {칸: [[청크 ID 후보, ...], ...]}  묶음마다 하나 이상 인용해야 함 (번역본·중복 청크는 같은 묶음)
  round1.must_not_cite: {칸: [청크 ID]}  이 칸의 근거로 쓰면 안 되는 청크 (다른 대상·다른 제도)
  round1.user_fields  : 문서상 답이 갈려 활성화돼야 하는 사용자 칸
  round1.next_action  : 허용되는 ④ 다음 행동
  final               : 루프가 끝났을 때 기대하는 답의 모양·핵심 사실, 첫 풀 밖에 있는 필요한 청크
  notes               : 원문 대조 중 발견한 점, 팀 확인이 필요한 점
"""

KLC = "English_2026-2027+Korean+Language+Course.pdf"
KOT = "[동아대]2026학년도+후기+학부+외국인+신(편)입학+특별전형+모집요강_한국어트랙.pdf"
ENT = "[Dong-A+univ]2026+FALL+Admission+Guidelines_English+track+for+the+Undergraduates_English+Track.pdf"
GE = "(EN)정부초청+외국인+장학생+학사+운영+지침(2026.3.1.개정).pdf"
GK = "(KO)정부초청+외국인+장학생+학사+운영+지침(2026.3.1.개정).pdf"
SIK = "Study in KOREA! 한국 유학 가이드.pdf"


def c(src, page, idx):
    return f"{src}#p{page}#c{idx}"


DEV_QUESTIONS = [
    {"id": "D1", "type": "T1", "question": "한국어학당 수업료가 얼마예요?",
     "check": "표 안의 값, 통화·산정 단위, 표가 청크에서 잘리는지 (partial/cut_at)",
     "gold": {
         "status": "draft",
         "round1": {
             "slots": {"requested_value": ["supported"], "applicable_scope": ["supported"]},
             "must_cite": {"requested_value": [[c(KLC, 2, 1), c(KLC, 2, 2)]],
                           "applicable_scope": [[c(KLC, 2, 1), c(KLC, 2, 2)]]},
             "must_not_cite": {"requested_value": [c(KOT, 19, 6), c(KOT, 20, 2), c(KOT, 20, 3), c(GE, 3, 0)]},
             "user_fields": [],
             "next_action": ["answer", "continue_search"],
         },
         "final": {"mode": "answer",
                   "key_facts": ["1,300,000 KRW per semester (한 학기 10주, 연 4학기)",
                                 "전형료 50,000원은 환불 불가"],
                   "outside_pool": []},
         "notes": [
             "검색 1순위가 학부 장학금 표(수업료 %)였고 정답 청크는 2위. 1순위를 앵커로 한 확장은 헛돌았음",
             "학부 등록금(p19#c6)·장학금 비율·GKS 50% 부담(p3#c0)을 어학당 수업료로 쓰면 오답",
             "기준 시점: 청크 본문에 연도가 없고 파일명만 2026-2027. reference_time을 어떻게 볼지 팀 결정 필요",
         ]}},
    {"id": "D2", "type": "T1", "question": "동아대학교 2026년 가을학기 지원 기간이 언제예요?",
     "check": "날짜, 기준 시점, 한국어·영어 트랙 갈래",
     "gold": {
         "status": "draft",
         "round1": {
             "slots": {"requested_value": ["supported"], "applicable_scope": ["supported", "partial"]},
             "must_cite": {"requested_value": [[c(KOT, 5, 0)], [c(ENT, 5, 0)]],
                           "variation_notes": [[c(KOT, 5, 1)]]},
             "must_not_cite": {},
             "user_fields": ["track"],
             "next_action": ["answer_by_condition", "answer"],
         },
         "final": {"mode": "answer_by_condition",
                   "key_facts": ["한국어트랙: 1차 2026.4.1~4.14, 2차 6.15~6.21, 3차 7.23~7.29 (3차는 국내 체류자만)",
                                 "영어트랙: 1차 2026.4.1~4.14, 2차 6.15~6.21",
                                 "전형 일정은 변동될 수 있음 (국제교류과 홈페이지 공지)"],
                   "outside_pool": []},
         "notes": [
             "[팀 확인] '가을학기'를 학부 후기 입학으로 볼지, 어학당 2학기(8/31 시작, 지원 5.18~7.03)도 포함할지. 초안은 학부 기준",
         ]}},
    {"id": "D3", "type": "T2", "question": "유학생이 받을 수 있는 장학금 종류는 뭐가 있어요?",
     "check": "여러 청크·문서에 흩어진 목록, '모든 종류' 단정 금지",
     "gold": {
         "status": "draft",
         "round1": {
             "slots": {"requested_list": ["partial"]},
             "must_cite": {"requested_list": [[c(KOT, 20, 2)], [c(KOT, 20, 5)], [c(KOT, 21, 0)]]},
             "must_not_cite": {"requested_list": [c(KOT, 22, 2), c(GK, 2, 0)]},
             "user_fields": [],
             "next_action": ["continue_search"],
         },
         "final": {"mode": "answer (보유 자료 범위 명시)",
                   "key_facts": ["신입생: 외국인우수신입생 A~E, DAU 외국인우수신입생 A~D, 동아특화분야 우수장학금 Ⅰ·Ⅱ",
                                 "재학생: 외국인 성적우수 A~D, 근로장학금, TOPIK 장학금",
                                 "영어트랙은 별도 장학금 (English Track Freshman Scholarship A~D)"],
                   "outside_pool": [c(KOT, 20, 6), c(ENT, 14, 8), c(ENT, 14, 9)]},
         "notes": [
             "동아특화분야 우수장학금 Ⅱ가 p20#c6에 있는데 첫 풀에 없음 → 목록이 끊긴 전형적인 partial (cut_at p20#c5)",
             "영어트랙 모집요강의 장학금(p14)은 한국어 검색어로 안 잡힘",
             "유학생 지원 프로그램(p22#c2)·GKS 적용 대상(p2#c0)은 장학금 종류가 아님",
         ]}},
    {"id": "D4", "type": "T3", "question": "입학 지원할 때 필요한 서류가 뭐예요?",
     "check": "페이지를 넘어가는 서류 목록, 조건별 추가 서류, 신입/편입 갈래",
     "gold": {
         "status": "draft",
         "round1": {
             "slots": {"requested_documents": ["partial"]},
             "must_cite": {"requested_documents": [[c(KOT, 13, 1)], [c(KOT, 13, 2)]]},
             "must_not_cite": {"requested_documents": [c(SIK, 3, 5), c(SIK, 5, 5)]},
             "user_fields": ["admission_type"],
             "next_action": ["continue_search"],
         },
         "final": {"mode": "answer_by_condition",
                   "key_facts": ["필수 13종 (6·7번 전적대학 서류는 편입만)",
                                 "재정 주체가 본인이 아니면 재정보증확인서·수입증명·재직증명 추가",
                                 "한국어·영어 외 언어 서류는 번역공증"],
                   "outside_pool": [c(KOT, 13, 3), c(KOT, 14, 1)]},
         "notes": [
             "필수서류 표가 p13#c2의 8번에서 끊김 → 9~13번은 p13#c3 (cut_at p13#c2)",
             "Study in KOREA의 비자 서류는 입학 지원 서류가 아님",
             "[① 문제] ①이 conditional_documents·format_validity·country_exceptions를 not_triggered(비활성)로 둠. "
             "문서를 보기 전이라 발동 여부를 알 수 없으므로 unresolved여야 함(체크리스트 1.2절)",
             "[팀 확인] 영어트랙 서류도 함께 안내할지",
         ]}},
    {"id": "D5", "type": "T4", "question": "기숙사 신청 방법을 알려주세요.",
     "check": "자료에 절차가 없는 경우('추후 공지'). 절차를 지어내지 않고 partial_answer/no_evidence로 가는지",
     "gold": {
         "status": "draft",
         "round1": {
             "slots": {"step_sequence": ["partial", "missing"]},
             "must_cite": {},
             "must_not_cite": {"step_sequence": [c(ENT, 5, 4), c(KOT, 13, 1)],
                               "application_channel": [c(ENT, 5, 4), c(ENT, 5, 0)]},
             "user_fields": [],
             "next_action": ["continue_search"],
         },
         "final": {"mode": "answer_by_condition (학부/어학당) 또는 partial_answer",
                   "key_facts": ["학부(한국어·영어트랙): 합격자 대상 추후 공지, 기숙사 홈페이지 hanlim.donga.ac.kr",
                                 "어학당: 최종 합격 후 입국해서 기숙사 신청서 작성·기숙사비 납부"],
                   "outside_pool": [c(KLC, 4, 8), c(ENT, 16, 1)]},
         "notes": [
             "[중요] 체크리스트 5.2절은 '기숙사 신청 = 추후 공지뿐'이라고 했지만, 어학당 자료 p4#c8에 신청 절차가 있음. "
             "첫 검색(한국어 검색어)이 영어 청크를 못 찾은 것",
             "입학 지원 절차(ENT p5#c4)를 기숙사 절차로 쓰면 오답",
         ]}},
    {"id": "D6", "type": "T5", "question": "GKS 장학생은 아르바이트할 수 있어?",
     "check": "기준선. 학위과정/한국어연수 갈래, 예외 조항, 20시간·방학 한정",
     "gold": {
         "status": "draft",
         "round1": {
             "slots": {"rule": ["supported"], "applicable_scope": ["supported"],
                       "conditions_limits": ["supported", "partial"], "exceptions_related": ["supported", "partial"],
                       "approval_reporting": ["supported"]},
             "must_cite": {"rule": [[c(GE, 10, 3)], [c(GE, 11, 0)]],
                           "applicable_scope": [[c(GE, 10, 3)], [c(GE, 11, 0)]],
                           "conditions_limits": [[c(GE, 10, 3)], [c(GE, 10, 4)]],
                           "exceptions_related": [[c(GE, 11, 2), c(GE, 11, 3)], [c(GE, 11, 4), c(GE, 11, 3)]],
                           "approval_reporting": [[c(GE, 11, 0)], [c(GE, 10, 4)]]},
             "must_not_cite": {"*": [c(GK, 10, 1)]},
             "user_fields": ["gks_stage"],
             "next_action": ["answer_by_condition", "continue_search"],
         },
         "final": {"mode": "answer_by_condition (gks_stage)",
                   "key_facts": ["공통: 법무부 시간제 취업 요건 충족, 전공 학업 우선",
                                 "한국어연수: 6개월 이수 후, 방학 중에만, 연수기관장 사전 승인 + 법무부 사전 허가. "
                                 "진학 TOPIK 취득 시 학기 중 주 20시간 이내",
                                 "학위과정: 총장 승인 시에만 (성적·출석·지도교수 의견 고려)",
                                 "성적경고 받으면 원칙적으로 3(E) 활동 불가, 경고 1회 등 요건 충족 시 예외, 2회면 예외 없음"],
                   "outside_pool": [c(GE, 11, 1)]},
         "notes": [
             "이번 풀에는 예외 요건 A~C 전체(p11#c3)가 있음 (오전 live 풀과 다름: 검색어가 조금 달랐음)",
             "허용 활동 목록 A·B(교내 근로, 연구)는 p11#c1에 있고 첫 풀에 없음 → conditions_limits는 partial도 허용",
             "KO p10#c1은 동문 조사·시행일 등 잡음",
         ]}},
    {"id": "D7", "type": "T6", "question": "휴학 기간이 끝났는데 복학 안 하면 어떻게 돼요?",
     "check": "결과·제재, GKS 지침인지 학칙인지 적용 범위",
     "gold": {
         "status": "draft",
         "round1": {
             "slots": {"event_trigger": ["supported"], "consequence": ["supported"],
                       "applicable_scope": ["partial", "supported"]},
             "must_cite": {"event_trigger": [[c(GK, 7, 0)]], "consequence": [[c(GK, 6, 1)]]},
             "must_not_cite": {"consequence": [c(KOT, 18, 1), c(GE, 7, 3)]},
             "user_fields": ["gks_status"],
             "next_action": ["continue_search", "partial_answer", "answer_by_condition"],
         },
         "final": {"mode": "partial_answer (GKS 한정 안내 + 일반 학생 기준은 보유 자료 없음)",
                   "key_facts": ["GKS 장학생: 휴학 종료 후 정당한 사유 없이 복학원서 미제출 → 장학생 자격상실 (제19조 5호)",
                                 "복학 신고는 휴학 종료 1개월 전까지 (제13조)",
                                 "GKS가 아닌 학생의 기준은 학칙 사항이며 현재 자료에 없음 (제23조 준용 규정)"],
                   "outside_pool": []},
         "notes": [
             "[중요] 근거가 모두 GKS 지침. 질문은 GKS를 말하지 않았으므로(general) 일반 학생 규정처럼 답하면 안 됨 (체크리스트 5.3절 2항)",
             "자격상실 조항 제목(제19조)은 p6#c1 끝에, 해당 호(5호)는 p7#c0에 있음 → 두 청크를 같이 봐야 결과가 확정됨",
             "첫 학기 휴학 불가(KOT p18#c1)·경고 사유(GE p7#c3)는 이 사건의 결과가 아님",
         ]}},
    {"id": "D8", "type": "T5+T3+T4", "question": "저 GKS 장학생인데 아르바이트 해도 돼요? 된다면 어떤 서류를 어디에 내야 해요?",
     "check": "복합 질문, 본인 사례(personal) → 갈리는 조건이 있으면 ask_clarification",
     "gold": {
         "status": "draft",
         "round1": {
             "slots": {"rule": ["supported"], "requested_documents": ["missing", "unchecked"]},
             "must_cite": {"rule": [[c(GE, 10, 3)], [c(GE, 11, 0)]]},
             "must_not_cite": {"requested_documents": [c(GE, 3, 1), c(GE, 6, 2)],
                               "submission_method": [c(GE, 3, 1), c(GE, 6, 2)]},
             "user_fields": ["gks_stage"],
             "next_action": ["continue_search"],
         },
         "final": {"mode": "ask_clarification (gks_stage) 후 답변, 서류 목록은 보유 자료로 확인 불가",
                   "key_facts": ["승인 주체: 학위과정은 총장, 한국어연수는 연수기관장 + 법무부",
                                 "시간제 취업 허가 서류 목록은 현재 자료에 없음 (출입국·학교 확인 필요)"],
                   "outside_pool": []},
         "notes": [
             "결석 서류(GE p3#c1)·일시출국 승인(GE p6#c2)을 아르바이트 서류로 쓰면 오답",
             "[① 문제] 추가 유형 T4 때문에 step_sequence·application_channel 등이 필수로 추가돼 칸이 16개. "
             "'어디에 내?'는 T3 submission_method로 충분할 수 있음 → 검색 예산 낭비 가능",
         ]}},
    {"id": "D9", "type": "T3", "question": "What documents do I need to apply for a student visa?",
     "check": "영어 질문, 관할이 제한된 비자 자료(체크리스트 5.3절)",
     "gold": {
         "status": "draft",
         "round1": {
             "slots": {"requested_documents": ["supported", "partial"]},
             "must_cite": {"requested_documents": [[c(KLC, 4, 1)], [c(KLC, 4, 2)]]},
             "must_not_cite": {"requested_documents": [c(KLC, 3, 7)]},
             "user_fields": ["program"],
             "next_action": ["answer_by_condition", "continue_search", "partial_answer"],
         },
         "final": {"mode": "answer_by_condition (어학연수 D-4 / 학위 D-2) + 관할 한정 안내",
                   "key_facts": ["D-4(어학연수): 사증발급신청서, 여권 사본, 사진, 수수료, 입학허가서·수업료 확인서, 최종학교 졸업증명, "
                                 "재정능력 입증(연 USD 8,000 이상), 잔고증명(KRW 8,000,000 이상), 결핵검사 확인서",
                                 "D-2 서류 목록은 KVAC 헤이그(네덜란드) 신청 기준 자료뿐 → 다른 국가 신청자에게 그대로 안내하면 안 됨"],
                   "outside_pool": []},
         "notes": [
             "Study in KOREA 자료는 'KVAC THE HAGUE 2024'(p1#c3), 네덜란드 거주 조건·유로 금액 → 체크리스트 5.3절 1항 사례로 확인됨",
             "어학당 입학 지원 서류(KLC p3#c7)는 비자 서류가 아님",
             "[① 문제] D4와 같이 conditional_documents를 not_triggered로 둠 (결핵·재정 증명은 조건부 서류)",
         ]}},
]
