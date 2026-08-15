"""Public contracts for memory JSON routes.

Overview, graph, item, and cleanup envelopes still evolve. Dual-shape
endpoints only require identifiers that exist on every successful shape.
Routes must use response_model_exclude_unset=True so missing optional
fields stay absent instead of being filled with defaults.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MemoryRouteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
