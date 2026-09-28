"""
① 질문 분석 확인용 시나리오 (개발용 질문).

체크리스트 v1 10절 '구현 전 최소 확인 시나리오'와 few-shot 질문에서 골랐다.
프롬프트·체크리스트를 고치면서 계속 보는 질문이므로 최종 평가용이 아니다 (v1 8.2절).

expect에 쓸 수 있는 키
  primary_type          : 대표 유형 (예: "T5")
  primary_type_in       : 허용되는 대표 유형 목록
  additional_includes   : 추가 유형에 반드시 있어야 할 것
  additional_excludes   : 추가 유형에 있으면 안 되는 것
  next_action           : 다음 행동
  answer_scope          : 답변 범위
  condition             : {"field_id": ..., "subject": ...(선택), "value_contains": ...(선택)} 조건이 있어야 함
  no_condition          : 이 칸의 조건이 있으면 안 됨 (예: 언어로 국적 추정 금지)
  inactive_slots        : 활성화되면 안 되는 문서 칸 (좁은 질문에 전체 체크리스트 강제 금지)
  active_slots          : 활성화되어야 하는 문서 칸
"""

SCENARIOS = [
    {
        "id": "S01",
        "title": "단순 사실: 수업료만 묻는데 서류·절차를 요구하지 않는가",
        "question": "한국어학당 수업료가 얼마예요?",
        "expect": {
            "primary_type": "T1",
            "additional_excludes": ["T3", "T4"],
            "next_action": "search",
        },
    },
    {
        "id": "S02",
        "title": "일반 규정 문의: 개인 조건을 먼저 요구하지 않고 검색하는가",
        "question": "GKS 장학생은 아르바이트할 수 있어?",
        "expect": {
            "primary_type": "T5",
            "next_action": "search",
            "answer_scope": "general",
            "condition": {"field_id": "gks_status", "subject": "question_target"},
        },
    },
    {
        "id": "S03",
        "title": "복합 질문: 허용 + 서류 + 제출처를 함께 잡는가",
        "question": "저 GKS 장학생인데 아르바이트 해도 돼요? 된다면 어떤 서류를 어디에 내야 해요?",
        "expect": {
            "primary_type": "T5",
            "additional_includes": ["T3"],
            "next_action": "search",
            "answer_scope": "personal",
            "condition": {"field_id": "gks_status", "subject": "user_self"},
            "active_slots": ["submission_method"],
        },
    },
    {
        "id": "S04",
        "title": "서류 질문: 국적을 추정하거나 먼저 묻지 않는가",
        "question": "입학 지원할 때 필요한 서류가 뭐예요?",
        "expect": {
            "primary_type": "T3",
            "next_action": "search",
            "no_condition": ["nationality"],
        },
    },
    {
        "id": "S05",
        "title": "'증명서' 단어에 끌려 전체 서류 목록으로 가지 않는가",
        "question": "결핵 증명서는 언제 내요?",
        "expect": {
            "primary_type": "T1",
            "next_action": "search",
        },
    },
    {
        "id": "S06",
        "title": "친구 사례: 사용자 본인 조건으로 저장하지 않는가",
        "question": "친구가 GKS 장학생인데 학기 중에 본국에 잠깐 다녀와도 된대?",
        "expect": {
            "primary_type": "T5",
            "answer_scope": "third_party",
            "condition": {"field_id": "gks_status", "subject": "other_person"},
        },
    },
    {
        "id": "S07",
        "title": "되묻기에 대한 답: 이전 대화와 연결해 조건을 뽑는가",
        "history": [
            {"role": "user", "content": "GKS 장학생은 휴학할 수 있어?"},
            {"role": "assistant", "content": "GKS 장학생의 휴학은 과정과 시점에 따라 규정이 다릅니다. 현재 한국어연수 과정인가요, 학위과정인가요? 그리고 학기 시작 전인가요, 학기 중인가요?"},
        ],
        "question": "저는 학위과정이고 학기 중에 쉬고 싶어요.",
        "expect": {
            "primary_type": "T5",
            "next_action": "search",
            "condition": {"field_id": "gks_stage", "subject": "user_self", "value_contains": "학위"},
        },
    },
    {
        "id": "S08",
        "title": "영어 질문: 언어로 국적을 추정하지 않는가",
        "question": "Can GKS scholars work part-time?",
        "expect": {
            "primary_type": "T5",
            "next_action": "search",
            "no_condition": ["nationality"],
        },
    },
    {
        "id": "S09",
        "title": "베트남어 질문: 언어로 국적을 추정하지 않는가",
        "question": "Học phí khóa tiếng Hàn là bao nhiêu?",
        "expect": {
            "primary_type": "T1",
            "next_action": "search",
            "no_condition": ["nationality"],
        },
    },
    {
        "id": "S10",
        "title": "결과 질문",
        "question": "휴학 기간이 끝났는데 복학 안 하면 어떻게 돼요?",
        "expect": {
            "primary_type": "T6",
            "next_action": "search",
        },
    },
    {
        "id": "S11",
        "title": "목록 질문",
        "question": "유학생이 받을 수 있는 장학금 종류는 뭐가 있어요?",
        "expect": {
            "primary_type": "T2",
            "next_action": "search",
        },
    },
    {
        "id": "S12",
        "title": "절차 질문",
        "question": "외국인등록증은 어떻게 발급받나요?",
        "expect": {
            "primary_type": "T4",
            "next_action": "search",
        },
    },
    {
        "id": "S13",
        "title": "요청 대상이 불분명: 요청 범위만 좁히는 질문을 하는가",
        "question": "서류 알려줘",
        "expect": {
            "next_action": "clarify_scope",
        },
    },
    {
        "id": "S14",
        "title": "인사: 검색하지 않는가",
        "question": "안녕하세요!",
        "expect": {
            "next_action": "no_retrieval",
        },
    },
    {
        "id": "S15",
        "title": "서비스 범위 밖",
        "question": "부산 맛집 추천해줘",
        "expect": {
            "next_action": "out_of_scope",
        },
    },
]
