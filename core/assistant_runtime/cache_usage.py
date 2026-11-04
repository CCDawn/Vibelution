"""Bounded, read-only projection of the native assistant's usage ledger."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


Count = Annotated[int, Field(ge=0, le=9_007_199_254_740_991)]
Identity = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,160}$")]
MissingReason = Literal["", "not_called", "provider_cache_usage_missing", "partial_provider_cache_usage"]


class _UsageNumbers(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    inputTokens: Count
    cachedInputTokens: Count
    cacheReadInputTokens: Count
    cacheCreationInputTokens: Count
    uncachedInputTokens: Count
    outputTokens: Count
    reasoningOutputTokens: Count
    totalTokens: Count
    latencyMs: Count
    cacheHitRate: float = Field(ge=0, le=1)
    cacheUsageObserved: bool
    cacheUsageMissingReason: MissingReason


class AssistantUsageSample(_UsageNumbers):
    source: Literal["provider_usage", "estimated", "missing", "not_called"]


class AssistantUsageRollup(_UsageNumbers):
    callCount: Count
    observedCallCount: Count
    estimatedCallCount: Count
    missingCallCount: Count
    notCalledCount: Count
    cacheObservedInputTokens: Count
    cacheObservedCallCount: Count
    cacheUnobservedCallCount: Count
    cacheUsageComplete: bool


class AssistantUsageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sessionId: Identity
    agentId: Identity
    sessionTokenUsage: AssistantUsageRollup
    lastTokenUsage: AssistantUsageSample


def read_usage_summary(*, project_root: Path, session_id: str, agent_id: str) -> dict:
    """Use the writer's frozen root and select no global or diagnostic fields."""
    from core.llm import usage_ledger

    if usage_ledger.PROJECT_ROOT != project_root:
        raise ValueError("usage_owner_mismatch")
    summary = usage_ledger.build_usage_summary(
        scope="session_agent", session_id=session_id, agent_id=agent_id, project_root=project_root,
    )
    last = summary["lastTokenUsage"]
    if last.get("sessionId", session_id) != session_id or last.get("agentId", agent_id) != agent_id:
        raise ValueError("usage_identity_mismatch")
    # Ledger samples also contain provider metadata and diagnostic identifiers.
    # Only the closed numeric/cache projection is allowed across this bridge.
    sample = {key: last[key] for key in _UsageNumbers.model_fields if key != "latencyMs"}
    sample["latencyMs"] = last.get("latencyMs", 0)
    sample["source"] = last["source"]
    sample["cacheUsageMissingReason"] = (
        "" if last["cacheUsageObserved"] else "not_called" if last["source"] == "not_called"
        else "provider_cache_usage_missing"
    )
    rollup = summary["sessionTokenUsage"]
    return AssistantUsageSummary.model_validate({
        "sessionId": session_id, "agentId": agent_id,
        "sessionTokenUsage": {key: rollup[key] for key in AssistantUsageRollup.model_fields},
        "lastTokenUsage": sample,
    }).model_dump()
