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
class OpportunisticScheduler:
    mode: str = "opportunistic"
    status: str = "ready"
    label: str = "Opportunistic"

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
        priority_ids = _string_list(
            config.get("priorityParticipantIds")
            or config.get("priority_participant_ids")
            or config.get("speakerOrder")
            or config.get("speaker_order")
        )
        priority_sessions = _string_list(
            config.get("prioritySessionIds")
            or config.get("priority_session_ids")
        )
        priority_agents = _string_list(
            config.get("priorityAgentIds")
            or config.get("priority_agent_ids")
        )
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate_id in priority_ids + priority_sessions + priority_agents:
            participant = _find_participant(enabled, candidate_id)
            if participant is None:
                continue
            participant_id = str(participant.get("participantId") or "").strip()
            if not participant_id or participant_id in seen:
                continue
            seen.add(participant_id)
            selected.append(participant)
        for participant in enabled:
            participant_id = str(participant.get("participantId") or "").strip()
            if not participant_id or participant_id in seen:
                continue
            seen.add(participant_id)
            selected.append(participant)
        if limit > 0:
            return selected[:limit]
        return selected


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


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        values = []
    return [str(item or "").strip() for item in values if str(item or "").strip()]


def _find_participant(participants: list[dict[str, Any]], candidate_id: str) -> dict[str, Any] | None:
    normalized = str(candidate_id or "").strip()
    if not normalized:
        return None
    for participant in participants:
        keys = (
            participant.get("participantId"),
            participant.get("sessionId"),
            participant.get("directSessionId"),
            participant.get("agentId"),
            participant.get("agentCode"),
        )
        if any(str(key or "").strip() == normalized for key in keys):
            return participant
    return None


_REGISTRY = SchedulerRegistry(
    [
        RoundRobinScheduler(),
        OpportunisticScheduler(),
    ]
)


def get_scheduler_registry() -> SchedulerRegistry:
    return _REGISTRY
