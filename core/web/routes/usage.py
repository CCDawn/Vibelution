"""Token usage summary routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from core.llm.usage_ledger import build_usage_summary


router = APIRouter(tags=["usage"])


@router.get("/usage/summary")
def usage_summary(
    scope: str = Query("global", pattern="^(global|session|agent|model)$"),
    sessionId: str = "",
    agentId: str = "",
    provider: str = "",
    model: str = "",
) -> dict[str, Any]:
    normalized_scope = str(scope or "global").strip().lower()
    session_id = str(sessionId or "").strip()
    agent_id = str(agentId or "").strip()
    provider_id = str(provider or "").strip()
    model_id = str(model or "").strip()
    if normalized_scope == "session" and not session_id:
        raise HTTPException(status_code=400, detail="sessionId is required when scope=session")
    if normalized_scope == "agent" and not agent_id:
        raise HTTPException(status_code=400, detail="agentId is required when scope=agent")
    if normalized_scope == "model" and not (provider_id or model_id):
        raise HTTPException(status_code=400, detail="provider or model is required when scope=model")
    summary = build_usage_summary(
        scope=normalized_scope,
        session_id=session_id,
        agent_id=agent_id,
        provider=provider_id,
        model=model_id,
    )
    summary.setdefault("updatedAt", _utcnow())
    summary.setdefault("breakdowns", {"models": [], "providers": [], "sources": []})
    return summary


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
