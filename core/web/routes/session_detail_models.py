"""Public GET /sessions/{id} contract.

The detail document is large and still evolving. Only `id` is required; extras
such as messages, messageWindow, and projection fields must pass through until
a later field-by-field freeze. Routes must use response_model_exclude_unset=True
so missing optional fields stay absent instead of being filled with defaults.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SessionDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
