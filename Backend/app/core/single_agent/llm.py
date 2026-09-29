"""
①②④ 공통 LLM 호출 (JSON 모드).

  get_client()     : OpenAI 클라이언트 (처음 쓸 때 만들고 모든 단계가 공유)
  model_for(stage) : 단계별 모델. ④("verify")는 settings.verify_model이 있으면 그것, 없으면 openai_model
  run_json_loop()  : 호출 → 파싱 → 형식이 틀리면 오류를 알려주고 다시 만들게 함 (최대 MAX_ATTEMPTS번)

오류 처리
  - API 오류(네트워크, rate limit 등)는 형식 재시도와 별개로 API_RETRIES번 다시 호출한다.
    끝내 실패하면 run.error에 'LLM 호출 실패'를 적는다.
  - 출력이 max_tokens에서 잘렸으면(finish_reason == "length") 오류에 그 사실을 적고,
    다음 시도는 max_tokens를 TRUNCATION_TOKEN_FACTOR배로 늘리고 더 짧게 쓰라고 알린다.
  - 파싱은 됐지만 다시 만들어야 하는 경우(예: 중복 검색어)는 parse가 RetryWith를 던진다.

run 인자는 AnalysisRun / SearchPlanRun / VerificationRun 중 하나다.
attempts, error, warnings는 공통이고, prompt_tokens·completion_tokens·raw_output·raw_outputs는 있으면 채운다.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple

MAX_ATTEMPTS = 2              # 최초 1회 + 형식 오류·RetryWith 재시도 1회
API_RETRIES = 1               # API 오류 시 추가 호출 횟수 (형식 재시도 횟수와 별개)
API_RETRY_WAIT_S = 1.0        # API 재시도 전 대기
TRUNCATION_TOKEN_FACTOR = 2   # 출력이 잘렸을 때 다음 시도의 max_tokens 배수


class RetryWith(Exception):
    """
    파싱은 됐지만 다시 만들게 할 때 parse가 던진다.
    feedback은 LLM에게 보낼 메시지, value는 끝내 못 고쳤을 때 돌려줄 값, warning은 run.warnings에 남길 문장.
    """

    def __init__(self, feedback: str, value: Any = None, warning: str = ""):
        super().__init__(feedback)
        self.feedback = feedback
        self.value = value
        self.warning = warning


_client = None


def get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        from app.config import settings
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def model_for(stage: str) -> str:
    """stage: "analyze" / "plan" / "verify"."""
    from app.config import settings
    if stage == "verify" and (getattr(settings, "verify_model", "") or "").strip():
        return settings.verify_model.strip()
    return settings.openai_model


def _create(run, client, kwargs: Dict) -> Tuple[Any, Optional[Exception]]:
    last: Optional[Exception] = None
    for n in range(1 + API_RETRIES):
        try:
            return client.chat.completions.create(**kwargs), None
        except Exception as e:  # 네트워크·API 오류
            last = e
            if n < API_RETRIES:
                run.warnings.append(f"[API 재시도] {type(e).__name__}: {str(e)[:200]}")
                if API_RETRY_WAIT_S > 0:
                    time.sleep(API_RETRY_WAIT_S)
    return None, last


def run_json_loop(
    run,
    client,
    model: str,
    messages: List[Dict],
    parse: Callable[[str], Any],
    temperature: float,
    max_tokens: int,
    format_hint: str,
) -> Tuple[Any, bool]:
    """
    반환: (값, 성공 여부)
      - (값, True)   : parse 성공
      - (값, False)  : RetryWith를 끝내 못 고침 → 마지막 RetryWith.value
      - (None, False): API 실패 또는 형식 오류가 계속됨 → run.error에 이유
    parse는 형식이 틀리면 ValueError(json.JSONDecodeError, pydantic ValidationError 포함)를 던진다.
    """
    messages = list(messages)
    fallback: Any = None
    tokens = max_tokens
    for _ in range(MAX_ATTEMPTS):
        run.attempts += 1
        resp, err = _create(run, client, dict(
            model=model, messages=messages, temperature=temperature, max_tokens=tokens,
            response_format={"type": "json_object"},
        ))
        if resp is None:
            run.error = f"LLM 호출 실패 ({1 + API_RETRIES}회 시도): {type(err).__name__}: {err}"
            return fallback, False

        usage = getattr(resp, "usage", None)
        if usage is not None and hasattr(run, "prompt_tokens"):
            run.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            run.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
        choice = resp.choices[0]
        raw = choice.message.content or ""
        if hasattr(run, "raw_output"):
            run.raw_output = raw
        if hasattr(run, "raw_outputs"):
            run.raw_outputs.append(raw)
        truncated = getattr(choice, "finish_reason", None) == "length"

        try:
            value = parse(raw)
        except RetryWith as e:
            run.error = None
            fallback = e.value
            if e.warning:
                run.warnings.append(e.warning)
            messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": e.feedback}]
            continue
        except ValueError as e:
            msg = f"형식 오류: {type(e).__name__}: {str(e)[:500]}"
            if truncated:
                msg = f"출력이 max_tokens({tokens})에서 잘림 → {msg}"
                tokens *= TRUNCATION_TOKEN_FACTOR
                feedback = f"출력이 길이 제한에서 잘렸습니다. 설명(value·reason 등)을 더 짧게 줄여 {format_hint}"
            else:
                feedback = f"출력 형식 오류입니다: {msg}\n{format_hint}"
            run.error = msg
            messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": feedback}]
            continue

        run.error = None
        return value, True
    return fallback, False
