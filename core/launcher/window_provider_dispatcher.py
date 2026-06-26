from __future__ import annotations

from typing import Any, Callable


WindowActionWriter = Callable[[str, dict[str, Any]], dict[str, Any]]


class WindowProviderDispatcher:
    def __init__(self, *, provider: str, desktop_action_writer: WindowActionWriter, edge_provider: Any) -> None:
        self.provider = provider or "none"
        self.desktop_action_writer = desktop_action_writer
        self.edge_provider = edge_provider

    def open_workbench(self, *, reason: str) -> dict[str, Any]:
        if self.provider == "electron":
            return self.desktop_action_writer("open_workbench", {"reason": reason})
        if self.provider == "edge_app":
            return self.edge_provider.open_workbench(reason=reason)
        return {"ok": False, "provider": "none", "reason": "window_provider_unavailable"}

    def focus_workbench(self, *, reason: str) -> dict[str, Any]:
        if self.provider == "electron":
            return self.desktop_action_writer("focus_workbench", {"reason": reason})
        if self.provider == "edge_app":
            return self.edge_provider.focus_workbench(reason=reason)
        return {"ok": False, "provider": "none", "reason": "window_provider_unavailable"}
