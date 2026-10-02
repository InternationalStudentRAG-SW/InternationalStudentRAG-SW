"""
질문 분석·근거 검증 체크리스트 설정 (docs/single_agent 체크리스트 v1, 2026-09-28 개정 기준).

이 파일에는 '정적 규칙'만 둔다.
- 규정 수치(TOPIK 등급, 금액, 기한 등)는 넣지 않는다. 수치는 문서 근거로만 관리한다.
- 질문별 실행 상태(칸 상태, 근거, 사용자 조건)는 analysis_schema.py의 모델로 따로 관리한다.

구성
- DOC_SLOTS      : 문서 칸 정의 (여러 유형이 같은 의미의 칸을 공유하면 같은 ID를 쓴다)
- PROFILES       : 질문 유형 T1~T6 (답의 모양, 예시, 문서 칸별 기본 필수도, 사용자 칸 후보)
- USER_FIELDS    : 사용자 칸 후보와 활성화 조건
- 선택지 목록     : 필수도, 칸 상태, 답변 범위, 조건 대상, ①의 다음 행동
"""
from __future__ import annotations

from typing import Dict, List

CHECKLIST_VERSION = "v1-2026-09-28"

# ── 선택지 ────────────────────────────────────────────────────────────────

REQUIREMENTS = {
    "required": "필수",
    "conditional": "조건부 필수",
    "optional": "선택",
}

# 조건부 필수 칸의 발동 여부
ACTIVATION_STATES = {
    "triggered": "발동 확인 (질문이 명시적으로 요구함)",
    "unresolved": "발동 미확인 (문서 확인 후 결정)",
    "not_triggered": "발동 안 함",
}

DOC_SLOT_STATUSES = {
    "unchecked": "미확인",
    "supported": "근거 확보",
    "partial": "일부 확보",
    "missing": "검색 후 미확보",
    "conflicting": "충돌",
    "not_applicable": "적용 안 됨",
    "unavailable_in_corpus": "보유 자료로 확인 불가",
}

USER_SLOT_STATUSES = {
    "confirmed": "확인됨",
    "unknown": "미확인",
    "ambiguous": "모호함",
    "not_required": "불필요",
}

ANSWER_SCOPES = {
    "general": "일반 규정 문의",
    "personal": "사용자 본인의 개인별 결론 요청",
    "third_party": "다른 사람(친구 등) 사례 문의",
}

CONDITION_SUBJECTS = {
    "user_self": "사용자 본인",
    "question_target": "질문 속 대상 (사용자 본인이라는 증거 아님)",
    "other_person": "다른 사람 사례",
}

CONDITION_STATUSES = {
    "confirmed": "확인됨",
    "ambiguous": "모호함",
}

# ① 질문 분석이 고를 수 있는 다음 행동
ANALYSIS_ACTIONS = {
    "search": "문서 검색부터 시작",
    "clarify_scope": "요청 범위가 너무 넓어 최초 검색을 정할 수 없음 → 요청 대상만 좁히는 질문",
    "out_of_scope": "서비스 범위 밖 (동아대 유학생 생활·행정과 무관)",
    "no_retrieval": "검색이 필요 없는 발화 (인사, 감사 등)",
}

MAX_SUBQUERIES = 3        # 질문 1개당 하위 질문(신규 검색) 최대 개수
MAX_SEARCH_CALLS = 6      # 신규 검색 + 원문 확장을 합친 전체 검색 호출 한도
MAX_CONTEXT_EXPANSIONS = 3  # 원문 확장 최대 횟수

# 칸 하나에 쓸 수 있는 검색 횟수 (한 칸이 전체 예산을 독식하지 않게)
MAX_NEW_SEARCHES_PER_SLOT = 2  # 신규 검색 2번에도 missing이면 더 검색하지 않음 (status는 missing 유지 → 부분 답변)
MAX_EXPANSIONS_PER_SLOT = 2    # 원문 확장 2번에도 partial이면 더 확장하지 않음 (partial로 답변)

# ③ 근거 검색 (초기값이며 평가로 조정한다)
SEARCH_TOP_K = 7          # 신규 검색 1회당 돌려받을 청크 수 (기본 top_k 10보다 줄여 ④ 입력을 제한)
EXPAND_WINDOW = 1         # 원문 확장 때 앵커 앞·뒤로 가져올 청크 수
TOOL_MAX_RETRIES = 1      # 검색 도구 오류 시 재시도 횟수. 끝내 실패하면 예산·칸별 상한에서 차감하지 않는다

# ④ 충분성 검증 (초기값이며 평가로 조정한다)
VERIFY_MAX_CHUNKS = 20      # 판정 프롬프트에 넣을 청크 상한 (이미 칸에 연결된 청크 → 이번 라운드 새 청크 순)
MAX_CLARIFY_FIELDS = 2      # 한 번에 되물을 사용자 칸 최대 수 (체크리스트 4.2절)
MAX_NO_PROGRESS_ROUNDS = 2  # 연속으로 새 근거가 없던 검색이 이만큼이면 더 검색하지 않음 (체크리스트 7절)
# 전체 흐름 (pipeline.py, 초기값이며 평가로 조정한다)
MAX_VERIFY_ROUNDS = 3        # ②③④ 라운드 최대 횟수 (④ LLM 호출 비용이 커서 검색 예산보다 먼저 제한)
AUTO_EXPAND_FIRST_ROUND = True  # 첫 바퀴 신규 검색 뒤 1순위 청크 앞뒤를 바로 확장 (LLM 없음, dev 풀 수집과 같은 방식)
ANSWER_MAX_EVIDENCE = 12     # ⑤ 프롬프트에 넣을 근거 청크 상한
ANSWER_CHUNK_CHARS = 900     # ⑤ 프롬프트에 넣을 청크 본문 길이 상한
MIN_QUOTE_CHARS = 4         # 근거 인용의 최소 길이 (text_match 정규화 후 글자 수). 너무 짧은 인용은 아무 청크에나 맞으므로 거부

# ④가 LLM에게 허용하는 칸 상태. unavailable_in_corpus는 자료 범위표로만 정하므로 ④가 쓰지 않는다(2.1절).
VERIFIABLE_STATUSES = {"supported", "partial", "missing", "conflicting", "not_applicable"}
EARLY_STOP_ON_CORE = True   # 핵심 칸이 모두 supported이고 남은 미해결 칸이 전부 부수 칸이면 검색을 멈추고 답한다
# 질문 유형별 핵심·부수 칸. 표에 없는 유형(조건·예외가 답을 바꾸는 T2~T6)은 조기 종료하지 않는다
EARLY_STOP_SLOTS = {
    "T1": {"core": ("requested_value", "applicable_scope"), "aux": ("reference_time", "variation_notes", "extra_info")},
}
RESOLVED_STATUSES = {"supported", "not_applicable"}   # 답변에 필요한 확인이 끝난 상태

# ④가 고르는 다음 행동 (서버 규칙으로 결정, 체크리스트 2.4절)
VERIFY_ACTIONS = {
    "answer": "완결 답변",
    "answer_by_condition": "조건별 일반 안내 (개인별 결론은 확정하지 않음)",
    "ask_clarification": "개인별 결론을 바꾸는 사용자 조건만 확인",
    "continue_search": "② 검색 계획으로 돌아가 재검색·원문 확장",
    "partial_answer": "확인된 내용·미확인 항목·이유를 구분한 부분 답변",
    "no_evidence": "사용할 근거가 없음 → 확인 불가 안내",
}

# ② 검색 계획이 문서 칸 status를 보고 다음 행동을 정할 때 쓰는 분류.
# (체크리스트 v1 2.1절 문서 칸 상태 기준)
NEEDS_EXPAND_STATUSES = {"partial"}
NEEDS_NEW_SEARCH_STATUSES = {"unchecked", "missing", "conflicting"}
NO_SEARCH_NEEDED_STATUSES = {"supported", "not_applicable", "unavailable_in_corpus"}

# partial 판정이 다음 검색 행동으로 이어지도록 하는 구조화된 부족 유형.
# continuation만 인접 청크를 읽고, 다른 조항·범위·충돌 문제는 새 검색으로 전환한다.
MISSING_KINDS = {"continuation", "different_section", "scope_gap", "conflict", "unknown"}
MISSING_KINDS_REQUIRING_NEW_SEARCH = {"different_section", "scope_gap", "conflict"}

# ── 문서 칸 정의 ──────────────────────────────────────────────────────────

DOC_SLOTS: Dict[str, Dict[str, str]] = {
    # 공통
    "applicable_scope": {
        "label": "적용 범위",
        "criterion": "값·규정이 어느 대상(과정·트랙·차수·GKS/일반 학생·시점)에 해당하는지 확인. 전체 공통이면 그 범위를 기록",
    },
    "extra_info": {
        "label": "추가 안내",
        "criterion": "질문 해결에 직접 도움이 되는 출처 있는 보완 정보만",
    },
    # T1 단순 사실
    "requested_value": {
        "label": "요청한 값",
        "criterion": "질문한 항목의 값이 명시됨. 금액은 통화·산정 단위, 기간은 시작·종료 또는 기준 사건까지",
    },
    "reference_time": {
        "label": "기준 시점",
        "criterion": "시점에 따라 달라지는 값이면 적용 학년도·학기·시행 시점을 확인",
    },
    "variation_notes": {
        "label": "조건별 차이·변동 단서",
        "criterion": "값을 바꾸거나 현재 값으로 단정하지 못하게 하는 주석(변동 가능 등)",
    },
    # T2 목록·종류
    "requested_list": {
        "label": "요청 범위의 목록",
        "criterion": "관련 표·목록·주석과 이어지는 부분까지 확인. 보유 자료 범위를 넘어 '모든 종류'라고 단정하지 않음",
    },
    "item_eligibility": {
        "label": "항목별 대상·제외 조건",
        "criterion": "목록 포함/제외를 결정하는 조건",
    },
    "item_details": {
        "label": "항목별 설명·금액",
        "criterion": "항목마다 설명·금액 (사용자가 요구하면 필수로 승격)",
    },
    # T3 서류
    "requested_documents": {
        "label": "요청한 서류·기본 목록",
        "criterion": "전체 서류 질문이면 대상별 목록의 끝과 주석까지. 특정 서류 질문이면 그 서류 정보만",
    },
    "conditional_documents": {
        "label": "조건별 추가·대체 서류",
        "criterion": "입학 구분·재정 주체·발급 상황 등에 따른 추가/대체 요건",
    },
    "format_validity": {
        "label": "형식·유효기간",
        "criterion": "인증·번역·원본/사본·발급일 요건. 숫자는 실제 조항에서만",
    },
    "country_exceptions": {
        "label": "국가·발급지별 예외",
        "criterion": "문서에 적용 갈래가 있을 때만. 국적·발급국·신청국을 혼동하지 않음",
    },
    "submission_method": {
        "label": "제출 방법·기한·장소",
        "criterion": "온라인/우편, 마감일, 제출처",
    },
    # T4 절차
    "step_sequence": {
        "label": "단계 순서",
        "criterion": "요청 범위에서 시작·중간·완료 단계가 연결됨. 문서에 없는 단계를 상식으로 추가하지 않음",
    },
    "application_channel": {
        "label": "신청처·방법",
        "criterion": "어디에 어떤 방법으로 진행하는지",
    },
    "prerequisites": {
        "label": "선행 요건",
        "criterion": "절차 시작에 필요한 자격·서류·사전 승인",
    },
    "deadline": {
        "label": "기한",
        "criterion": "기한이 요구되거나 적용되면 확인. 못 찾았다고 '기한 없음'으로 처리하지 않음",
    },
    "approval_exceptions": {
        "label": "승인·신고·예외",
        "criterion": "순서나 완료 여부를 바꾸는 승인·신고·예외",
    },
    # T5 자격·허용·의무
    "rule": {
        "label": "원칙",
        "criterion": "허용·금지·의무·자격의 기본 규정",
    },
    "conditions_limits": {
        "label": "허용 조건·한도",
        "criterion": "원칙에 붙은 조건·한도 전체. 금지만 명시된 규정에 한도를 지어내지 않음",
    },
    "exceptions_related": {
        "label": "예외·관련 조항 점검",
        "criterion": "본문과 연결된 '다만'·'단'·준용 조항을 검토하고 확인 범위를 남김",
    },
    "approval_reporting": {
        "label": "승인·신고 절차",
        "criterion": "승인·신고가 허용의 전제이면 가능 여부만 묻더라도 포함",
    },
    # T6 결과·제재·구제
    "event_trigger": {
        "label": "질문한 사건·사유",
        "criterion": "어떤 사건이 결과를 일으키는지. 특정 사건 질문에 무관한 전체 사유를 요구하지 않음",
    },
    "full_reason_list": {
        "label": "사유 전체 목록",
        "criterion": "'어떤 경우에 ~?'처럼 전체 사유를 요청할 때 목록·주석 끝까지",
    },
    "consequence": {
        "label": "결과·조치",
        "criterion": "해당 사건에 연결되는 결과와 필요한 조건",
    },
    "exceptions_remedies": {
        "label": "예외·구제·기한",
        "criterion": "결과를 바꾸는 예외, 요청된 이의신청·환불·복구 방법과 기한",
    },
}

# ── 질문 유형 ─────────────────────────────────────────────────────────────
# doc_slots: [(slot_id, 기본 필수도)]

PROFILES: Dict[str, Dict] = {
    "T1": {
        "name": "단순 사실",
        "answer_shape": "금액, 날짜, 기간, 장소, 연락처 등 특정 값",
        "examples": [
            "한국어학당 수업료가 얼마예요?",
            "가을학기 지원 기간이 언제예요?",
            "국제교류 담당 부서 연락처는?",
        ],
        "doc_slots": [
            ("requested_value", "required"),
            ("applicable_scope", "required"),
            ("reference_time", "conditional"),
            ("variation_notes", "conditional"),
            ("extra_info", "optional"),
        ],
        "user_field_candidates": ["application_term", "program", "track"],
    },
    "T2": {
        "name": "목록·종류",
        "answer_shape": "제도·시설·전공 등 항목의 목록",
        "examples": [
            "유학생 장학금 종류는?",
            "학생 비자 종류는?",
            "기숙사 시설에는 무엇이 있나요?",
        ],
        "doc_slots": [
            ("requested_list", "required"),
            ("applicable_scope", "required"),
            ("item_eligibility", "conditional"),
            ("item_details", "optional"),
        ],
        "user_field_candidates": ["track", "program", "student_status", "admission_type"],
    },
    "T3": {
        "name": "서류",
        "answer_shape": "제출 서류 또는 특정 서류의 준비 요건",
        "examples": [
            "입학 지원 서류가 뭐예요?",
            "재정 증명은 어떻게 준비하나요?",
            "번역공증이 필요한가요?",
        ],
        "doc_slots": [
            ("requested_documents", "required"),
            ("conditional_documents", "conditional"),
            ("format_validity", "conditional"),
            ("country_exceptions", "conditional"),
            ("submission_method", "optional"),
        ],
        "user_field_candidates": [
            "admission_type", "program", "track", "application_country",
            "nationality", "document_issuing_country",
        ],
    },
    "T4": {
        "name": "절차",
        "answer_shape": "목적을 달성하기 위한 행동 순서",
        "examples": [
            "입학 지원은 어떻게 하나요?",
            "등록금 납부 방법은?",
            "기숙사 신청 절차는?",
        ],
        "doc_slots": [
            ("step_sequence", "required"),
            ("application_channel", "required"),
            ("prerequisites", "conditional"),
            ("deadline", "conditional"),
            ("approval_exceptions", "conditional"),
            ("extra_info", "optional"),
        ],
        "user_field_candidates": [
            "program", "student_status", "gks_status", "current_location", "request_reason",
        ],
    },
    "T5": {
        "name": "자격·허용·의무",
        "answer_shape": "가능/불가능, 대상 자격, 해야 하는지와 그 조건",
        "examples": [
            "GKS 장학생은 아르바이트할 수 있나요?",
            "휴학할 수 있나요?",
            "보험 가입이 의무인가요?",
        ],
        "doc_slots": [
            ("rule", "required"),
            ("applicable_scope", "required"),
            ("conditions_limits", "conditional"),
            ("exceptions_related", "required"),
            ("approval_reporting", "conditional"),
        ],
        "user_field_candidates": [
            "gks_status", "program", "gks_stage", "degree_level",
            "current_semester", "activity_timing", "request_reason",
        ],
    },
    "T6": {
        "name": "결과·제재·구제",
        "answer_shape": "특정 행동·상황의 결과, 제재 사유 또는 구제 방법",
        "examples": [
            "비자가 거부되면 환불되나요?",
            "휴학 후 복학하지 않으면?",
            "GKS 장학생이 경고받는 경우는?",
        ],
        "doc_slots": [
            ("event_trigger", "required"),
            ("full_reason_list", "conditional"),
            ("consequence", "required"),
            ("applicable_scope", "required"),
            ("exceptions_remedies", "conditional"),
        ],
        "user_field_candidates": [
            "gks_status", "program", "degree_level", "request_reason", "activity_timing",
        ],
    },
}

# ── 사용자 칸 후보 ────────────────────────────────────────────────────────

USER_FIELDS: Dict[str, Dict[str, str]] = {
    "program": {
        "label": "교육 과정",
        "values": "어학연수 / 학부 / 대학원",
        "activation": "해당 문서에서 과정별 규정이 다름",
    },
    "admission_type": {
        "label": "입학 구분",
        "values": "신입 / 편입",
        "activation": "입학 요건·서류 등이 달라짐",
    },
    "transfer_year": {
        "label": "편입 학년",
        "values": "2학년 / 3학년",
        "activation": "편입 질문이며 학년에 따라 적용 내용이 달라짐",
    },
    "student_status": {
        "label": "학생 상태",
        "values": "지원 예정 / 합격 / 재학 / 휴학",
        "activation": "같은 제도의 적용 조건이 상태별로 다름",
    },
    "track": {
        "label": "수업 트랙",
        "values": "한국어 / 영어",
        "activation": "모집요강·비용·자격 등의 기준이 다름",
    },
    "gks_status": {
        "label": "GKS 여부",
        "values": "예 / 아니오",
        "activation": "해당 사례에 GKS 규정을 적용할지 결정해야 함",
    },
    "gks_stage": {
        "label": "GKS 단계",
        "values": "한국어연수 / 학위과정",
        "activation": "GKS 규정이 단계별로 다름",
    },
    "degree_level": {
        "label": "학위 수준",
        "values": "학사 / 석사 / 박사",
        "activation": "해당 조항이 학위 수준별로 다름",
    },
    "application_term": {
        "label": "지원 학년도·학기·차수",
        "values": "사용자가 지정한 값",
        "activation": "모집 기간·대상·요건이 달라짐",
    },
    "current_semester": {
        "label": "재학 학기",
        "values": "첫 학기 등",
        "activation": "관련 규정의 적용 여부가 달라짐",
    },
    "activity_timing": {
        "label": "활동·신청 시점",
        "values": "학기 전 / 학기 중 / 방학 / 특정 날짜",
        "activation": "해당 조항이 시점별로 다름",
    },
    "current_location": {
        "label": "현재 체류 위치",
        "values": "국내 / 해외 (필요 시 국가)",
        "activation": "문서가 현재 체류 위치를 조건으로 함",
    },
    "application_country": {
        "label": "신청 국가·기관",
        "values": "실제 신청할 국가·기관",
        "activation": "관할에 따라 서류·비용·절차가 다름",
    },
    "nationality": {
        "label": "국적",
        "values": "사용자가 직접 말한 값만",
        "activation": "문서에 국적별 적용 규정이 있음",
    },
    "document_issuing_country": {
        "label": "서류 발급국·발급 기관",
        "values": "사용자가 직접 말한 값만",
        "activation": "학력 인증 등의 요건이 발급국·기관에 따라 다름",
    },
    "request_reason": {
        "label": "신청 사유·현재 진행 단계",
        "values": "질문 해결에 필요한 최소 정보",
        "activation": "문서가 그 사유·단계에 따라 답을 달리함",
    },
}


# ── 도우미 ───────────────────────────────────────────────────────────────

def slots_for_types(type_ids: List[str]) -> Dict[str, str]:
    """선택된 유형들의 문서 칸 합집합 {slot_id: 기본 필수도}. 같은 칸은 더 강한 필수도를 쓴다."""
    rank = {"required": 2, "conditional": 1, "optional": 0}
    merged: Dict[str, str] = {}
    for t in type_ids:
        for slot_id, req in PROFILES[t]["doc_slots"]:
            if slot_id not in merged or rank[req] > rank[merged[slot_id]]:
                merged[slot_id] = req
    return merged


def _validate_config() -> None:
    """설정 자체의 오타를 import 시점에 잡는다."""
    for t, p in PROFILES.items():
        for slot_id, req in p["doc_slots"]:
            assert slot_id in DOC_SLOTS, f"{t}: 정의되지 않은 문서 칸 {slot_id}"
            assert req in REQUIREMENTS, f"{t}: 잘못된 필수도 {req}"
        for f in p["user_field_candidates"]:
            assert f in USER_FIELDS, f"{t}: 정의되지 않은 사용자 칸 {f}"


_validate_config()


# ── 문서별 기본 적용 대상 (④ 청크 메모에 서버가 합침, branching.py) ─────────────
# LLM이 청크 메모에 적용 대상을 빠뜨리거나 표기를 바꿔도(예: "Korean Language Course" / "어학연수")
# 문서 단위로 확실한 대상은 서버가 채운다. match는 파일 이름(source)의 부분 문자열(정규화 후 비교).
# aliases: 사용자 질문에 이 표현이 있으면 이미 그 대상을 가리킨 것으로 보고 그 사용자 칸은 갈래·대상 한정에서 뺀다.
# 문서가 추가·교체되면 이 표를 함께 고친다.
DOC_SCOPES = [
    {"match": "모집요강_한국어트랙", "field_id": "track", "value": "한국어트랙",
     "aliases": ["한국어트랙", "한국어 트랙", "Korean track", "Korean-taught"]},
    {"match": "English+Track", "field_id": "track", "value": "영어트랙",
     "aliases": ["영어트랙", "영어 트랙", "English track", "English-taught"]},
    {"match": "정부초청+외국인+장학생", "field_id": "gks_status", "value": "GKS 장학생",
     "aliases": ["GKS", "정부초청", "Global Korea Scholarship", "government scholarship"]},
    {"match": "Korean+Language+Course", "field_id": "program", "value": "어학연수",
     "aliases": ["어학당", "어학연수", "한국어 연수", "한국어연수", "언어교육원", "Korean Language Course",
                 "language course", "language program", "language institute"]},
]
