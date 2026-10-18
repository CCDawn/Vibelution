"""Web-layer singleton for the Agent-scoped personal affairs domain."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from core.agent_plugins.personal_affairs.service import (
    PersonalAffairsError,
    PersonalAffairsNotFoundError,
    PersonalAffairsService,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SERVICE: PersonalAffairsService | None = None
_SERVICE_LOCK = threading.Lock()


def _default_agent_loader(agent_id: str, *, include_archived: bool = False) -> dict[str, Any] | None:
    from .agent_directory_service import get_agent

    return get_agent(agent_id, include_archived=include_archived)


def get_personal_affairs_service() -> PersonalAffairsService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = PersonalAffairsService(
                PROJECT_ROOT,
                agent_loader=_default_agent_loader,
                now_provider=None,
            )
        return _SERVICE


__all__ = [
    "PersonalAffairsError",
    "PersonalAffairsNotFoundError",
    "get_personal_affairs_service",
]
