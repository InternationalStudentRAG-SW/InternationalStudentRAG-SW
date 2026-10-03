"""
⓪ 라우터 정답 세트 (evaluate/check_router.py가 사용).

라벨
  route    : simple(기본 RAG: 하이브리드+리랭커) / agent(단일 에이전트)
  n_asks   : 요구 단위 개수 (search가 아니면 0)
  depends  : 앞 요구의 답에 따라 달라지는 요구가 있는지
  action   : search / clarify_scope / out_of_scope / no_retrieval
  label_src: compare  = 실제 비교 실험 결과로 정함 (기본 경로가 이기거나 비기면 simple, Adaptive-RAG 방식)
             design   = 설계 기준으로 붙인 라벨 (실험으로 확인 전)
  boundary : 라벨이 애매한 경계 사례 (정확도와 따로 본다)

compare 라벨 근거: evaluate/results/compare_20260930_214543.json (D1~D9, 시도 1회)
  기본 경로 승: D1 D2 D3 D5 D6 D7 / 무승부: D4 D9 / 에이전트 승: D8
시도 1회라 확정이 아니다. compare를 다시 돌리면 이 표도 갱신한다.
"""
from __future__ import annotations

from typing import Dict, List

_GKS_HISTORY = [
    {"role": "user", "content": "저 GKS 장학생이에요. 몇 가지 물어봐도 돼요?"},
    {"role": "assistant", "content": "네, 궁금한 점을 물어보세요."},
]
_DORM_HISTORY = [
    {"role": "user", "content": "기숙사 신청 기간이 언제예요?"},
    {"role": "assistant", "content": "기숙사 신청 기간은 학기별 공지에서 확인할 수 있습니다."},
]

ROUTER_QUESTIONS: List[Dict] = [
    # ── 개발 질문 (compare 라벨) ──────────────────────────────────────────
    {"id": "D1", "question": "한국어학당 수업료가 얼마예요?", "route": "simple", "n_asks": 1, "depends": False,
     "action": "search", "label_src": "compare"},
    {"id": "D2", "question": "동아대학교 2026년 가을학기 지원 기간이 언제예요?", "route": "simple", "n_asks": 1,
     "depends": False, "action": "search", "label_src": "compare"},
    {"id": "D3", "question": "유학생이 받을 수 있는 장학금 종류는 뭐가 있어요?", "route": "simple", "n_asks": 1,
     "depends": False, "action": "search", "label_src": "compare"},
    {"id": "D4", "question": "입학 지원할 때 필요한 서류가 뭐예요?", "route": "simple", "n_asks": 1, "depends": False,
     "action": "search", "label_src": "compare", "note": "무승부 → 더 단순한 경로"},
    {"id": "D5", "question": "기숙사 신청 방법을 알려주세요.", "route": "simple", "n_asks": 1, "depends": False,
     "action": "search", "label_src": "compare"},
    {"id": "D6", "question": "GKS 장학생은 아르바이트할 수 있어?", "route": "simple", "n_asks": 1, "depends": False,
     "action": "search", "label_src": "compare", "note": "GKS는 일반 대상(question_target)이지 사용자 조건 아님"},
    {"id": "D7", "question": "휴학 기간이 끝났는데 복학 안 하면 어떻게 돼요?", "route": "simple", "n_asks": 1,
     "depends": False, "action": "search", "label_src": "compare"},
    {"id": "D8", "question": "저 GKS 장학생인데 아르바이트 해도 돼요? 된다면 어떤 서류를 어디에 내야 해요?",
     "route": "agent", "n_asks": 2, "depends": True, "action": "search", "label_src": "compare"},
    {"id": "D9", "question": "What documents do I need to apply for a student visa?", "route": "simple", "n_asks": 1,
     "depends": False, "action": "search", "label_src": "compare", "note": "무승부 → 더 단순한 경로"},

    # ── 단순: 단일 요구, 조건 없음 (design) ─────────────────────────────────
    {"id": "R01", "question": "기숙사 신청 기간이 언제예요?", "route": "simple", "n_asks": 1, "depends": False,
     "action": "search", "label_src": "design"},
    {"id": "R02", "question": "외국인등록증은 어디서 발급받아요?", "route": "simple", "n_asks": 1, "depends": False,
     "action": "search", "label_src": "design"},
    {"id": "R03", "question": "건강보험 가입은 의무인가요?", "route": "simple", "n_asks": 1, "depends": False,
     "action": "search", "label_src": "design"},
    {"id": "R04", "question": "등록금 얼마예요? 금액이 정확히 궁금해요.", "route": "simple", "n_asks": 1,
     "depends": False, "action": "search", "label_src": "design", "note": "같은 요구를 두 번 말함 → 나누지 않음"},
    {"id": "R05", "question": "How much is the tuition for the Korean language course?", "route": "simple",
     "n_asks": 1, "depends": False, "action": "search", "label_src": "design"},
    {"id": "R06", "question": "Học phí khóa học tiếng Hàn là bao nhiêu?", "route": "simple", "n_asks": 1,
     "depends": False, "action": "search", "label_src": "design"},
    {"id": "R07", "question": "韩国语学堂的学费是多少？", "route": "simple", "n_asks": 1, "depends": False,
     "action": "search", "label_src": "design"},
    {"id": "R08", "question": "입학 서류는 뭐고 어디에 내요?", "route": "simple", "n_asks": 1, "depends": False,
     "action": "search", "label_src": "design", "boundary": True, "note": "서류와 제출처는 한 요구로 묶음"},
    {"id": "R09", "question": "비용은요?", "history": _DORM_HISTORY, "route": "simple", "n_asks": 1,
     "depends": False, "action": "search", "label_src": "design", "note": "후속 질문: 기숙사 비용"},

    # ── 복합: 서로 독립인 요구 여러 개 ─────────────────────────────────────
    {"id": "R10", "question": "한국어학당 수업료랑 가을학기 지원 기간 알려줘", "route": "agent", "n_asks": 2,
     "depends": False, "action": "search", "label_src": "design"},
    {"id": "R11", "question": "기숙사비는 얼마고 신청은 어떻게 해요?", "route": "agent", "n_asks": 2,
     "depends": False, "action": "search", "label_src": "design"},
    {"id": "R12", "question": "When is the application deadline and what documents do I need to submit?",
     "route": "agent", "n_asks": 2, "depends": False, "action": "search", "label_src": "design"},

    # ── 복합: 앞 답에 따라 달라지는 요구 ──────────────────────────────────
    {"id": "R13", "question": "휴학할 수 있어요? 가능하면 신청 절차도 알려주세요.", "route": "agent", "n_asks": 2,
     "depends": True, "action": "search", "label_src": "design"},
    {"id": "R14", "question": "TOPIK 성적이 없으면 입학이 안 되나요? 안 된다면 대신 낼 수 있는 서류가 있어요?",
     "route": "agent", "n_asks": 2, "depends": True, "action": "search", "label_src": "design"},

    # ── 사용자 조건 (본인·다른 사람 사례) ───────────────────────────────────
    {"id": "R15", "question": "저 영어트랙 학부생인데 등록금이 얼마예요?", "route": "agent", "n_asks": 1,
     "depends": False, "action": "search", "label_src": "design", "boundary": True,
     "note": "조건을 밝힌 단일 값 질문. 규칙상 agent"},
    {"id": "R16", "question": "제 친구가 D-4 비자인데 아르바이트 할 수 있어요?", "route": "agent", "n_asks": 1,
     "depends": False, "action": "search", "label_src": "design", "note": "other_person 사례"},
    {"id": "R17", "question": "아르바이트 해도 돼요?", "history": _GKS_HISTORY, "route": "agent", "n_asks": 1,
     "depends": False, "action": "search", "label_src": "design", "note": "조건이 이전 사용자 발언에 있음"},

    # ── 검색하지 않는 행동 ───────────────────────────────────────────────
    {"id": "R18", "question": "안녕하세요!", "route": "simple", "n_asks": 0, "depends": False,
     "action": "no_retrieval", "label_src": "design"},
    {"id": "R19", "question": "부산 해운대 맛집 추천해줘", "route": "simple", "n_asks": 0, "depends": False,
     "action": "out_of_scope", "label_src": "design"},
    {"id": "R20", "question": "서류 알려줘", "route": "agent", "n_asks": 0, "depends": False,
     "action": "clarify_scope", "label_src": "design"},
]


# ── 보류 세트 (held-out): 프롬프트를 고칠 때 보지 않은 질문 ───────────────────
# 출처: 수유니가 만든 노션 '복합 질문 샘플' Q1~Q10 (문서 A~F를 2~4개 결합해야 답이 나옴, 정답·쪽수 포함).
# 모두 복합 질문이므로 route 정답은 agent. 요구 개수·의존 관계는 라벨을 붙이지 않았다(None → 채점 제외, 출력만).
# 이 세트로 점수를 잰 뒤에는 프롬프트를 고쳐도 다시 '보류' 세트로 쓰지 않는다 (새 질문을 더 받아야 함).
_H = dict(route="agent", n_asks=None, depends=None, action="search", label_src="notion_heldout")
HELDOUT_QUESTIONS: List[Dict] = [
    {"id": "H01", "question": "동아대 학부 신입학에 지원하려는데, 한국어 트랙과 영어 트랙의 어학 기준이 각각 뭐야? "
                              "영어 트랙에서 어학 성적을 안 내도 되는 경우도 있어?", "note": "두 문서 비교 (A+B)", **_H},
    {"id": "H02", "question": "한국에 이미 체류 중인 외국인 학생인데, 7월 25일쯤 영어 트랙으로 학부에 지원할 수 있어?",
     "note": "조건 추론 (A+B)", **_H},
    {"id": "H03", "question": "영어 트랙 Global Advanced Integrated Engineering에 합격하면 첫 학기에 내는 등록금은 얼마야? "
                              "한국어 트랙 공학계열이랑 같아? 지원할 때 내는 전형료도 트랙마다 달라?",
     "note": "계산과 교차 검증 (A+B)", **_H},
    {"id": "H04", "question": "동아대 학부에 합격했어. 비자를 받으려면 학교에서 먼저 뭘 받아야 하고, "
                              "비자센터(KVAC)에는 어떤 서류를 내야 해?", "note": "절차 연결 (A+B+C)", **_H},
    {"id": "H05", "question": "동아 한국어학당(D-4)에서 공부하다가 같은 학교 학부에 지원하려고 해. "
                              "잔고증명은 얼마를 내야 하고, 어학원 때 낸 서류를 다시 써도 돼?",
     "note": "조건 비교와 해석 (A+B+D)", **_H},
    {"id": "H06", "question": "남학생이 기숙사에 들어가려고 해. 학부 입학 후 한림생활관과 한국어과정 기숙사 중 "
                              "한 달 기준으로 어느 쪽이 더 싸?", "note": "계산 (A/B+D)", **_H},
    {"id": "H07", "question": "GKS 장학생으로 동아대 학부에 신입학했는데, 첫 학기에 휴학할 수 있어? "
                              "휴학하면 장학금은 어떻게 돼?", "note": "규정 결합 (A+B+E+F)", **_H},
    {"id": "H08", "question": "GKS 학부 장학생도 동아대 근로장학생으로 일할 수 있어? 월 얼마 받고, 성적경고를 받으면 달라져?",
     "note": "규정 결합 (E/F+A/B)", **_H},
    {"id": "H09", "question": "동아대 한국어과정을 듣는 GKS 장학생이 있다고 해보자. 무단결석이 몇 번이면 GKS 경고를 받고, "
                              "한국어과정 다음 급으로 올라가려면 최소 얼마나 출석해야 해? 경고는 몇 번 받으면 자격을 잃어?",
     "note": "규정 결합과 계산 (D+E+F)", **_H},
    {"id": "H10", "question": "비자를 받고 한국에 입국했어. 도착해서 제일 먼저 뭘 해야 하고, 부산에서는 어디로 가? "
                              "건강보험은 어떻게 해야 해?", "note": "절차 결합 (C+D+A+B)", **_H},
]


_S = dict(route="simple", n_asks=1, depends=False, action="search", label_src="pdf_simple_heldout")
HELDOUT_QUESTIONS += [
    {"id": "S01", "question": "동아대 지원서 제출하고 나서 지원 학과나 전공 바꿀 수 있어?", "note": "단일 문서 단순 질문", **_S},
    {"id": "S02", "question": "인문·사회계열 입학하면 첫 학기 수업료가 얼마야?", "note": "단일 문서 단순 질문", **_S},
    {"id": "S03", "question": "한림생활관 승학 1관(여자기숙사) 한 학기 비용이 얼마야?", "note": "단일 문서 단순 질문", **_S},
    {"id": "S04", "question": "TOPIK 4급 갖고 있으면 신입생 장학금은 얼마나 받아?", "note": "단일 문서 단순 질문", **_S},
    {"id": "S05", "question": "입학하고 첫 학기에 휴학할 수 있어?", "note": "단일 문서 단순 질문", **_S},
    {"id": "S06", "question": "What are the office hours for the English track inquiries?", "note": "단일 문서 단순 질문", **_S},
    {"id": "S07", "question": "정부초청장학생(GKS)은 휴학을 합쳐서 최대 얼마나 할 수 있어?", "note": "단일 문서 단순 질문", **_S},
    {"id": "S08", "question": "장학생이 일시출국했다가 돌아오면 며칠 안에 재입국 신고해야 해?", "note": "단일 문서 단순 질문", **_S},
    {"id": "S09", "question": "한국어연수 기간을 연장하면 연수비는 누가 내?", "note": "단일 문서 단순 질문", **_S},
    {"id": "S10", "question": "Is the D-2-1 student visa single entry or multiple entry?", "note": "단일 문서 단순 질문", **_S},
]


# ── 어려운 세트 (hard): 라우터가 헷갈리기 쉬운 질문 (수유니 요청 '빡세게 테스트') ──────
# 라벨은 설계 기준(design). 정답이 애매한 것은 boundary=True 로 점수에서 뺀다.
# 유형: 짧은 단일인데 복합처럼 보임 / 복합인데 한 문장처럼 보임 / 후속질문 / 조건부 / 범위 밖 / 잡담 / 오타·혼합언어
_HD = dict(label_src="design_hard", action="search")
HARD_QUESTIONS: List[Dict] = [
    # (1) 단순인데 복합처럼 보이는 것 (과잉 라우팅 유도)
    {"id": "X01", "question": "한국어 트랙이랑 영어 트랙 중에 서류 접수는 어디가 먼저 시작해?", "route": "simple", "n_asks": 1, "depends": False, "boundary": True, "note": "두 트랙 비교처럼 보임(실제 두 문서 필요 가능)", **_HD},
    {"id": "X02", "question": "수업료랑 입학금 얼마야?", "route": "simple", "n_asks": 2, "depends": False, "boundary": True, "note": "항목 2개지만 같은 표", **_HD},
    {"id": "X03", "question": "GKS 장학생인데 휴학은 몇 번까지 가능해?", "route": "simple", "n_asks": 1, "depends": False, "note": "사용자 조건 1개 + 단일 규정", **_HD},
    {"id": "X04", "question": "TOPIK 4급이고 한국어 트랙 지원할 건데 접수 마감일이 언제야?", "route": "simple", "n_asks": 1, "depends": False, "note": "조건 있지만 답에 영향 적음", "boundary": True, **_HD},
    {"id": "X05", "question": "기숙사 비용이 얼마예요? 승학 캠퍼스 여학생이에요.", "route": "simple", "n_asks": 1, "depends": False, "note": "조건 보충 단일", **_HD},
    {"id": "X06", "question": "비자 신청할 때 수수료가 얼마인지랑 어디서 하는지 알려줘", "route": "simple", "n_asks": 2, "depends": False, "boundary": True, "note": "같은 문서 두 항목", **_HD},
    # (2) 복합인데 한 문장처럼 보이는 것 (놓침 유도)
    {"id": "X07", "question": "영어 트랙 합격하면 비자는 어떻게 받고 기숙사는 언제 신청해?", "route": "agent", "n_asks": 2, "depends": False, "note": "서로 다른 문서(B+C+기숙사)", **_HD},
    {"id": "X08", "question": "GKS 장학생이 한국어과정 중에 휴학하면 연수 기간이랑 장학금은 어떻게 돼?", "route": "agent", "n_asks": 2, "depends": False, "note": "E+D 결합", **_HD},
    {"id": "X09", "question": "입학 전에 잔고증명 내야 한다던데 얼마고, 그걸로 비자도 되는 거야?", "route": "agent", "n_asks": 2, "depends": True, "note": "A/B + C 결합", **_HD},
    {"id": "X10", "question": "영어 트랙 지원 자격이 되는지 모르겠어. 나 TOEFL 70점이고 이미 한국에 살고 있는데 지원 가능해?", "route": "agent", "n_asks": 1, "depends": True, "note": "조건 2개 판단(체류+점수)", **_HD},
    {"id": "X11", "question": "D-4로 한국어학당 다니다 학부 합격하면 비자 바꿔야 돼? 바꾸면 비용은?", "route": "agent", "n_asks": 2, "depends": True, "note": "D+C 의존", **_HD},
    # (3) 후속 질문 (history 의존)
    {"id": "X12", "question": "그럼 영어 트랙은?", "history": [
        {"role": "user", "content": "한국어 트랙 지원 마감일이 언제예요?"},
        {"role": "assistant", "content": "한국어 트랙 접수 기간은 모집요강에서 확인할 수 있습니다."}],
     "route": "simple", "n_asks": 1, "depends": False, "note": "후속 단일", **_HD},
    {"id": "X13", "question": "그거 휴학하면 어떻게 돼?", "history": [
        {"role": "user", "content": "GKS 장학생이 장학금 받는 기간이 얼마나 돼?"},
        {"role": "assistant", "content": "학사과정은 4~6년입니다."}],
     "route": "simple", "n_asks": 1, "depends": False, "boundary": True, "note": "후속인데 규정 결합 가능", **_HD},
    {"id": "X14", "question": "그럼 비용은 대충 얼마나 들어?", "history": [
        {"role": "user", "content": "영어 트랙으로 입학해서 기숙사 살고 비자도 받으려고 해요."},
        {"role": "assistant", "content": "네, 무엇이 궁금하신가요?"}],
     "route": "agent", "n_asks": 3, "depends": False, "boundary": True, "note": "맥락상 복합 비용(등록금+기숙사+비자)", **_HD},
    # (4) 범위 밖 / 잡담 / 정보 부족 (action 판단)
    {"id": "X15", "question": "안녕! 오늘 날씨 좋다", "route": "simple", "n_asks": 0, "depends": False, "action": "no_retrieval", "label_src": "design_hard", "note": "잡담", },
    {"id": "X16", "question": "부산 돼지국밥 맛집 추천해줘", "route": "simple", "n_asks": 0, "depends": False, "action": "out_of_scope", "label_src": "design_hard", "note": "범위 밖"},
    {"id": "X17", "question": "서울대 장학금도 알려줘", "route": "simple", "n_asks": 0, "depends": False, "action": "out_of_scope", "label_src": "design_hard", "note": "다른 학교"},
    {"id": "X18", "question": "장학금", "route": "simple", "n_asks": 1, "depends": False, "boundary": True, "note": "한 단어: 단순 검색 or 되묻기", **_HD},
    # (5) 오타 / 혼합 언어 / 영어
    {"id": "X19", "question": "한림생활관 승학1관 비용 얼마에용?? ㅠㅠ", "route": "simple", "n_asks": 1, "depends": False, "note": "구어체", **_HD},
    {"id": "X20", "question": "Can I work part-time on a D-2 visa and how many hours per week?", "route": "agent", "n_asks": 2, "depends": False, "boundary": True, "note": "허용 + 시간 한도 (같은 규정일 수도)", **_HD},
    {"id": "X21", "question": "What documents do I need for the English track, and is there a TOEFL waiver?", "route": "simple", "n_asks": 2, "depends": False, "boundary": True, "note": "같은 문서 두 질문", **_HD},
    {"id": "X22", "question": "저는 중국에서 왔고 GKS 신입생인데, 먼저 한국어 연수를 1년 해야 하고 TOPIK 3급을 따야 한다던데 못 따면 어떻게 돼?", "route": "simple", "n_asks": 1, "depends": False, "boundary": True, "note": "긴 문장 + 조건, 실제 요구는 1개", **_HD},
    # (6) 가정/조건 분기
    {"id": "X23", "question": "만약 학기 중에 TOPIK 점수를 못 올리면 장학금 잃어? 그러면 등록금은 내가 내야 해?", "route": "agent", "n_asks": 2, "depends": True, "note": "의존: 장학 상실 여부 → 등록금", **_HD},
    {"id": "X24", "question": "친구가 3차 모집에 지원하려는데 해외에서 오는 중이래. 그 친구도 되는 거야?", "route": "simple", "n_asks": 1, "depends": False, "boundary": True, "note": "3차는 국내체류자만 (단일 규정 판단)", **_HD},
]
