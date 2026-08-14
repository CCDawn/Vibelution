"""Protocol-family-neutral adapter surface.

A2A and AG-UI use this contract only in the current delivery. No endpoint is
registered or activated by importing this module.
"""

from __future__ import annotations

from typing import Any, Protocol

from .models import ProtocolAdapterDefinition, ResolvedAgentRoute


class AgentProtocolAdapter(Protocol):
    def describe(self) -> ProtocolAdapterDefinition: ...

    def discover(self, *, principal_ref: str) -> tuple[dict[str, Any], ...]: ...

    def invoke(
        self, *, route: ResolvedAgentRoute, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    def stream(self, *, route: ResolvedAgentRoute, payload: dict[str, Any]) -> Any: ...

    def get_task(self, *, route: ResolvedAgentRoute, task_ref: str) -> dict[str, Any]: ...

    def cancel(self, *, route: ResolvedAgentRoute, task_ref: str) -> dict[str, Any]: ...

    def subscribe(self, *, route: ResolvedAgentRoute, task_ref: str) -> Any: ...

    def close(self) -> None: ...


__all__ = ["AgentProtocolAdapter"]
