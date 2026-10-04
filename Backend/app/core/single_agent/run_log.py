"""
실서비스 실행 기록 (AGENT_RUN_LOG=true일 때).

  logs/agent_runs/<시각>_<id>.json : 에이전트 경로로 간 질문 1개의 전체 기록
      질문·언어·한국어 질의, ⓪ 라우터 판단, ①~⑤ 단계별 출력(PipelineRun 전체: 칸·검색어·검색 결과·
      근거 풀·판정·답변·시간·토큰)과 프론트로 보낸 최종 답·출처
  logs/routes.jsonl                : AGENT_ROUTING=auto일 때 모든 질문의 라우터 판단 1줄씩
      (simple로 간 질문도 남아서, 놓친 복합 질문을 나중에 찾을 수 있다)

보기: python -m evaluate.show_agent_run            # 가장 최근 기록
      python -m evaluate.show_agent_run <파일> --full

기록 실패는 서비스에 영향을 주지 않는다 (예외를 삼키고 None).
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

RUNS_SUBDIR = "agent_runs"
ROUTES_FILE = "routes.jsonl"


def _settings():
    from app.config import settings
    return settings


def enabled() -> bool:
    try:
        return bool(getattr(_settings(), "agent_run_log", False))
    except Exception:
        return False


def log_dir() -> str:
    try:
        return getattr(_settings(), "log_dir", "./logs") or "./logs"
    except Exception:
        return "./logs"


def save_agent_run(record: Dict[str, Any], base_dir: Optional[str] = None) -> Optional[str]:
    """record를 logs/agent_runs/에 JSON으로 저장하고 경로를 돌려준다."""
    try:
        d = os.path.join(base_dir or log_dir(), RUNS_SUBDIR)
        os.makedirs(d, exist_ok=True)
        now = datetime.now()
        rid = uuid.uuid4().hex[:6]
        path = os.path.join(d, f"{now:%Y%m%d_%H%M%S}_{rid}.json")
        record = {"saved_at": now.isoformat(timespec="seconds"), "run_id": rid, **record}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2, default=str)
        logger.info("agent run saved: %s", path)
        return path
    except Exception as e:
        logger.warning("agent run log failed: %s", e)
        return None


def append_route(entry: Dict[str, Any], base_dir: Optional[str] = None) -> None:
    """라우터 판단 1건을 logs/routes.jsonl에 덧붙인다."""
    try:
        d = base_dir or log_dir()
        os.makedirs(d, exist_ok=True)
        entry = {"at": datetime.now().isoformat(timespec="seconds"), **entry}
        with open(os.path.join(d, ROUTES_FILE), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logger.warning("route log failed: %s", e)
