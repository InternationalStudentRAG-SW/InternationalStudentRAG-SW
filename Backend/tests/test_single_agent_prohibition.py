"""⑤ 금지 규정 검사 테스트 (2026-10-04 본 실험 Q7 오답을 바탕으로, API·DB 호출 없음)."""
import json
from types import SimpleNamespace

from app.core.single_agent import answerer
from app.core.single_agent import checklist_config as cfg
from app.core.single_agent import prohibition_check as pc
from app.core.single_agent.analysis_schema import QuestionAnalysis
from app.core.single_agent.evidence_schema import EvidenceChunk, EvidencePool, RetrievalTag

GKS = "(EN)GKS지침.pdf"
KO = "[동아대]모집요강_한국어트랙.pdf"
GKS_TEXT = ("③ A GKS recipient in a degree program who intends to take a leave of absence during the semester shall be "
            "permitted to do so only under unavoidable circumstances, such as an urgent summons from the recipient's home "
            "country, urgent family matters, or serious personal illness. In such cases, the recipient must submit an "
            "application for a leave of absence along with supporting documents verifying the relevant reason. "
            "④ Leave of absence must be applied for on a semester basis, and the total period of leave of absence shall "
            "not exceed one (1) year.")
KO_TEXT = "- 차. 비자 취득에 문제가 없어야합니다.\n- 카. **입학 후 첫 학기에는 휴학 불가합니다.* *\n- 14 -"
ALLOW_TEXT = "Monthly allowance will not be provided during periods of leave of absence."
SOURCES = {1: GKS, 2: KO, 4: GKS}
TEXTS = {1: GKS_TEXT, 2: KO_TEXT, 4: ALLOW_TEXT}
FACTS = [
    {"ask": "GKS 장학생 첫 학기 휴학 가능 여부", "evidence": 1, "quote": GKS_TEXT[2:200], "verified": True},
    {"ask": "GKS 장학생 첫 학기 휴학 가능 여부", "evidence": 2, "quote": "입학 후 첫 학기에는 휴학 불가합니다.", "verified": True},
    {"ask": "휴학 시 장학금 처리 방법", "evidence": 4, "quote": ALLOW_TEXT, "verified": True},
]


def _issues(answer, facts=FACTS, texts=TEXTS):
    return [i.sentence.strip() for i in pc.find_issues(answer, facts, SOURCES, texts)]


# ── 금지 근거 고르기 ──────────────────────────────────────────────────────

def test_limit_is_not_prohibition():
    assert pc.is_prohibition("입학 후 첫 학기에는 휴학 불가합니다.")
    assert pc.is_prohibition("e-signature not permitted")
    assert not pc.is_prohibition("총 휴학 기간은 1년을 초과할 수 없다")
    assert not pc.is_prohibition("the total period of leave of absence shall not exceed one (1) year")
    assert not pc.is_prohibition("불가피한 사유가 있을 때만 휴학할 수 있다")


# ── 실제 오답 (본 실험 10-04) ─────────────────────────────────────────────

def test_conditional_prohibition_is_flagged():
    """try1: '부득이한 사유가 없으면 첫 학기에 휴학할 수 없다' + 이어지는 신청 절차 문장."""
    a = ("GKS 장학생은 부득이한 사유가 없으면 첫 학기에 휴학할 수 없습니다[1][2]. 부득이한 사유로 휴학하려면 관련 사유를 "
         "증명하는 서류와 함께 휴학 신청서를 제출해야 합니다[1]. 휴학 기간 동안에는 월 생활비가 지급되지 않습니다[4].")
    assert len(_issues(a)) == 2


def test_exception_after_prohibition_is_flagged():
    """try2: 금지 다음 문장에 '그러나 불가피한 사유가 있으면 허용될 수 있다'."""
    a = ("GKS 장학생은 입학 후 첫 학기에는 휴학이 불가합니다[2]. 그러나 불가피한 사유가 있을 경우 휴학이 허용될 수 있습니다[1]. "
         "휴학 기간 동안에는 월별 수당이 지급되지 않습니다[4].")
    assert _issues(a) == ["그러나 불가피한 사유가 있을 경우 휴학이 허용될 수 있습니다[1]."]


def test_uncited_sentence_found_from_evidence_when_not_in_facts():
    """try3: ⑤가 금지 문장을 facts에 옮기지 않았고 첫 문장에 번호도 없음 → 보여준 근거 원문에서 금지 문장을 찾는다."""
    facts = [FACTS[0], FACTS[2]]
    a = ("GKS 장학생은 부득이한 사유가 없으면 첫 학기에 휴학할 수 없습니다. 부득이한 사유가 있을 경우, 관련 서류와 함께 "
         "휴학 신청서를 제출해야 합니다[1]. 휴학 기간 동안에는 장학금 지급이 중단됩니다[4].")
    assert len(_issues(a, facts=facts)) == 2


# ── 문제 삼지 않는 경우 ──────────────────────────────────────────────────

def test_plain_prohibition_passes():
    a = "GKS 장학생은 입학 후 첫 학기에는 휴학할 수 없습니다[2]. 휴학 기간 동안에는 월 생활비가 지급되지 않습니다[4]."
    assert _issues(a) == []


def test_other_situation_stated_passes():
    a = ("입학 후 첫 학기에는 휴학할 수 없습니다[2]. 첫 학기 이후 학기 중에 휴학하려면 부득이한 사유가 있어야 합니다[1]. "
         "휴학 기간에는 월 생활비가 지급되지 않습니다[4].")
    assert _issues(a) == []


def test_rule_before_prohibition_passes():
    """금지를 뒤에서 분명히 밝히고, 앞 문장은 금지 상황을 가리키지 않음 (심판도 맞다고 봄)."""
    a = ("GKS 장학생은 학위 과정에서 불가피한 사유가 있을 경우에만 휴학이 가능합니다[1]. "
         "그러나 동아대학교에서는 입학 후 첫 학기에는 휴학이 불가합니다[2]. 휴학 기간에는 월 생활비가 지급되지 않습니다[4].")
    assert _issues(a) == []


def test_exception_from_same_document_passes():
    sources = {1: KO, 2: KO}
    texts = {1: "첫 학기에는 휴학 불가합니다. 다만 군 입대는 예외로 한다.", 2: "기타"}
    facts = [{"ask": "첫 학기 휴학", "evidence": 1, "quote": "첫 학기에는 휴학 불가합니다.", "verified": True}]
    a = "첫 학기에는 휴학할 수 없습니다[1]. 다만 군 입대는 예외입니다[1]."
    assert pc.find_issues(a, facts, sources, texts) == []


def test_other_ask_is_outside_block():
    """다른 요구(E2 같은 '학기 중 휴학')로 넘어가면 금지 구간이 끝난다."""
    facts = FACTS + [{"ask": "학기 중 휴학 조건", "evidence": 5, "quote": "unavoidable circumstances", "verified": True}]
    sources = {**SOURCES, 5: "다른지침.pdf"}
    a = "입학 후 첫 학기에는 휴학할 수 없습니다[2]. 학기 중 휴학은 부득이한 사유가 있을 때만 가능합니다[5]."
    assert pc.find_issues(a, facts, sources, TEXTS) == []


def test_question_sentence_is_not_flagged():
    a = "입학 후 첫 학기에는 휴학할 수 없습니다[2]. 불가피한 사유가 있는지 알려 주실 수 있나요?"
    assert _issues(a) == []


def test_no_prohibition_in_evidence_means_no_check():
    facts = [FACTS[0]]
    a = "부득이한 사유가 있을 때만 학기 중 휴학이 가능합니다[1]."
    assert pc.find_issues(a, facts, {1: GKS}, {1: GKS_TEXT}) == []


# ── 서버가 직접 고치기 ───────────────────────────────────────────────────

def test_fallback_replaces_with_prohibition_quote():
    a = ("GKS 장학생은 부득이한 사유가 없으면 첫 학기에 휴학할 수 없습니다[1][2]. 부득이한 사유로 휴학하려면 서류와 함께 "
         "휴학 신청서를 제출해야 합니다[1]. 휴학 기간 동안에는 월 생활비가 지급되지 않습니다[4].")
    fixed = pc.fallback_fix(a, pc.find_issues(a, FACTS, SOURCES, TEXTS))
    assert fixed == "입학 후 첫 학기에는 휴학 불가합니다[2]. 휴학 기간 동안에는 월 생활비가 지급되지 않습니다[4]."


def test_fallback_keeps_existing_prohibition_and_drops_connector():
    a = ("GKS 장학생은 불가피한 사유가 있을 경우에만 첫 학기에 휴학할 수 있습니다[1]. "
         "그러나 동아대학교는 입학 후 첫 학기에는 휴학이 불가합니다[2]. 휴학 시에는 장학금이 지급되지 않습니다[4].")
    issues = pc.find_issues(a, FACTS, SOURCES, TEXTS)
    assert len(issues) == 1
    assert pc.fallback_fix(a, issues) == "동아대학교는 입학 후 첫 학기에는 휴학이 불가합니다[2]. 휴학 시에는 장학금이 지급되지 않습니다[4]."


# ── ⑤ write_answer 연결 ──────────────────────────────────────────────────

class FakeClient:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        out = self._outputs.pop(0) if self._outputs else {"answer": "?"}
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20, prompt_tokens_details=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(out, ensure_ascii=False)),
                                                        finish_reason="stop")], usage=usage)


def _setup(monkeypatch):
    pool = EvidencePool()
    tag = RetrievalTag(target_slot_id="rule", search_type="new", query_ko="첫 학기 휴학")
    pool.add(EvidenceChunk(evidence_id=f"{GKS}#p5#c3", source=GKS, page=5, chunk_index=3, text=GKS_TEXT), tag)
    pool.add(EvidenceChunk(evidence_id=f"{KO}#p18#c2", source=KO, page=18, chunk_index=2, text=KO_TEXT), tag)
    monkeypatch.setattr(answerer, "_evidence_order", lambda a, d, p: [f"{GKS}#p5#c3", f"{KO}#p18#c2"])
    monkeypatch.setattr(cfg, "ANSWER_CAVEAT_CHECK", False)
    analysis = QuestionAnalysis(intent_summary="첫 학기 휴학", answer_scope="personal", next_action="search")
    return analysis, pool


FIRST = {"facts": [{"ask": "첫 학기 휴학", "evidence": 2, "quote": "입학 후 첫 학기에는 휴학 불가합니다."},
                   {"ask": "첫 학기 휴학", "evidence": 1, "quote": "shall be permitted to do so only under unavoidable circumstances"}],
         "answer": "GKS 장학생은 부득이한 사유가 없으면 첫 학기에 휴학할 수 없습니다[1][2]."}


def test_write_answer_rewrites_when_prohibition_mixed(monkeypatch):
    analysis, pool = _setup(monkeypatch)
    client = FakeClient([FIRST, {"answer": "GKS 장학생은 입학 후 첫 학기에는 휴학할 수 없습니다[2]."}])
    run = answerer.write_answer("첫 학기 휴학?", "partial_answer", analysis=analysis, pool=pool, client=client, model="fake")
    assert client.calls == 2 and run.rewrites == 1
    assert run.answer == "GKS 장학생은 입학 후 첫 학기에는 휴학할 수 없습니다[2]."
    assert run.prohibition_issues and run.dropped_sentences == []


def test_write_answer_server_fix_when_rewrite_still_mixed(monkeypatch):
    analysis, pool = _setup(monkeypatch)
    client = FakeClient([FIRST, {"answer": FIRST["answer"]}])
    run = answerer.write_answer("첫 학기 휴학?", "partial_answer", analysis=analysis, pool=pool, client=client, model="fake")
    assert client.calls == 2
    assert run.answer == "입학 후 첫 학기에는 휴학 불가합니다[2]."
    assert run.dropped_sentences == [FIRST["answer"]]
    assert [s.page for s in run.sources] == [18]


def test_write_answer_prohibition_check_can_be_disabled(monkeypatch):
    analysis, pool = _setup(monkeypatch)
    monkeypatch.setattr(cfg, "ANSWER_PROHIBITION_CHECK", False)
    client = FakeClient([FIRST])
    run = answerer.write_answer("첫 학기 휴학?", "partial_answer", analysis=analysis, pool=pool, client=client, model="fake")
    assert client.calls == 1 and run.answer == FIRST["answer"]
