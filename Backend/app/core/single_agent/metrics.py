"""Request-local telemetry. SDK calls are not HTTP attempts (the SDK can retry)."""
from typing import List, Optional

from pydantic import BaseModel, Field

METRICS_VERSION = "single-agent-v2"


class LLMCallMetric(BaseModel):
    purpose: str = "main"
    latency_ms: float = 0
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cached_prompt_tokens: Optional[int] = None  # subset of prompt_tokens, never add twice
    error_type: Optional[str] = None


class LLMMetrics(BaseModel):
    calls: List[LLMCallMetric] = Field(default_factory=list)
