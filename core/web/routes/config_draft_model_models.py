"""Public contracts for config draft model and LLM probe JSON routes.

Workspace-shaped writes reuse ConfigWorkspaceResponse. Test and discovery
envelopes still evolve, so only fields that exist on every successful shape
are required. Routes must use response_model_exclude_unset=True so missing
optional fields stay absent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ConfigLlmTestResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool = False


class ConfigModelDiscoveryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
