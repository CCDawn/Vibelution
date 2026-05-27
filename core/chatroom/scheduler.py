"""Extensible chat room speaker scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ChatRoomScheduler(Protocol):
    """Choose the participant order for one chat room round."""

    mode: str
    status: str
    label: str

    def select_speakers(
        self,
        participants: list[dict[str, Any]],
        *,
        topic: str,
        history: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return the speakers for this round."""


@dataclass(frozen=True)
class RoundRobinScheduler:
    mode: str = "round_robin"
    status: str = "ready"
    label: str = "Round robin"

    def select_speakers(
        self,
        participants: list[dict[str, Any]],
        *,
        topic: str,
        history: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        limit = _positive_int(config.get("maxSpeakers") or config.get("max_speakers"))
        enabled = [item for item in participants if item.get("enabled", True)]
        if limit > 0:
            return enabled[:limit]
        return enabled


@dataclass(frozen=True)
class PlannedScheduler:
    mode: str
    label: str
    status: str = "planned"

    def select_speakers(
        self,
        participants: list[dict[str, Any]],
        *,
        topic: str,
        history: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        raise RuntimeError(f"Chat room mode {self.mode} is not ready.")


class SchedulerRegistry:
    """Small registry so future discussion modes do not rewrite orchestration."""

    def __init__(self, schedulers: list[ChatRoomScheduler] | None = None) -> None:
        self._schedulers: dict[str, ChatRoomScheduler] = {}
        for scheduler in schedulers or []:
            self.register(scheduler)

    def register(self, scheduler: ChatRoomScheduler) -> None:
        mode = str(getattr(scheduler, "mode", "") or "").strip().lower()
        if not mode:
            raise ValueError("Chat room scheduler mode is required.")
        self._schedulers[mode] = scheduler

    def get(self, mode: str) -> ChatRoomScheduler | None:
        return self._schedulers.get(str(mode or "").strip().lower())

    def list_modes(self) -> list[dict[str, str]]:
        return [
            {
                "id": scheduler.mode,
                "label": scheduler.label,
                "status": scheduler.status,
            }
            for scheduler in self._schedulers.values()
        ]


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


_REGISTRY = SchedulerRegistry(
    [
        RoundRobinScheduler(),
        PlannedScheduler(mode="opportunistic", label="Opportunistic"),
    ]
)


def get_scheduler_registry() -> SchedulerRegistry:
    return _REGISTRY
