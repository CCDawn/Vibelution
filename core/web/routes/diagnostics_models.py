"""Public contracts for health diagnostics JSON routes.

Known status envelope fields stay explicit for OpenAPI. Helper and finding
payloads still evolve, so extras pass through. Routes must use
response_model_exclude_unset=True.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HealthDiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = ""
    summary: str = ""
