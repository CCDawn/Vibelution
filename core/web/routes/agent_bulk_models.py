"""Public contracts for agent bulk archive/purge/config/prompt-template.

These envelopes share a success/skipped/failed summary and still evolve.
Keep required fields to identifiers that exist on every successful shape,
and let extras pass through. Routes must use response_model_exclude_unset=True
so missing optional fields stay absent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AgentBulkActionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = ""
