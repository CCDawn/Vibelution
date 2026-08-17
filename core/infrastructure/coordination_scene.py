"""Runtime-scene events for project coordination claim transitions.

The coordination registry writer lives in the Briefbound skill
(`mutate_registry`). That writer optionally loads this module from the
project root and calls `notify_registry_written` / `notify_claim_blocked`.
Diagnostics must never fail registry mutation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.logging import debug as _debug_logger


SCOPE_LOG_LIMIT = 8
TEXT_LOG_LIMIT = 160

_EVENT_BY_STATUS = {
    "ready": ("coordination.claim.claimed", "info", "claimed"),
    "active": ("coordination.claim.claimed", "info", "claimed"),
    "released": ("coordination.claim.released", "info", "released"),
    "completed": ("coordination.claim.released", "info", "released"),
    "blocked": ("coordination.claim.blocked", "warning", "blocked"),
    "expired": ("coordination.claim.expired", "warning", "expired"),
    "yielded": ("coordination.claim.yielded", "info", "yielded"),
}


def notify_registry_written(
    project_root: Path | str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    """Record claim status transitions after a successful registry write."""

    del project_root
    for kind, claim in _iter_claim_transitions(before, after):
        _record_claim_event(kind, claim)


def notify_claim_blocked(
    project_root: Path | str,
    conflicts: list[Any],
    summary: str = "",
) -> None:
    """Record an overlap that blocked claim create/activate/resume."""

    del project_root
    overlapping_claims = []
    overlapping_agents = []
    overlapping_scopes = []
    reasons = []
    for item in conflicts or []:
        if not isinstance(item, dict):
            continue
        claim = item.get("claim") if isinstance(item.get("claim"), dict) else {}
        claim_id = str(claim.get("id") or "").strip()
        agent_id = str(claim.get("agentId") or "").strip()
        if claim_id:
            overlapping_claims.append(claim_id)
        if agent_id:
            overlapping_agents.append(agent_id)
        overlapping_scopes.extend(_safe_scopes(claim.get("scopes")))
        for reason in item.get("reasons") or []:
            text = _truncate_text(reason)
            if text:
                reasons.append(text)
    _record_scene_event(
        "coordination.claim.blocked",
        message=_truncate_text(summary) or "Requested work overlaps an active claim.",
        level="warning",
        outcome="blocked",
        fields={
            "claimId": "",
            "agentId": overlapping_agents[0] if overlapping_agents else "",
            "status": "blocked",
            "overlappingClaimIds": list(dict.fromkeys(overlapping_claims))[:SCOPE_LOG_LIMIT],
            "overlappingAgentIds": list(dict.fromkeys(overlapping_agents))[:SCOPE_LOG_LIMIT],
            "scopes": list(dict.fromkeys(overlapping_scopes))[:SCOPE_LOG_LIMIT],
            "reasons": list(dict.fromkeys(reasons))[:SCOPE_LOG_LIMIT],
        },
    )


def _iter_claim_transitions(
    before: dict[str, Any],
    after: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    before_map = _claim_map(before)
    after_map = _claim_map(after)
    transitions: list[tuple[str, dict[str, Any]]] = []
    for claim_id, claim in after_map.items():
        previous = before_map.get(claim_id)
        status = str(claim.get("status") or "").strip()
        if previous is None:
            if status in _EVENT_BY_STATUS:
                transitions.append((_EVENT_BY_STATUS[status][0], claim))
            continue
        previous_status = str(previous.get("status") or "").strip()
        if previous_status == status:
            continue
        if status in _EVENT_BY_STATUS:
            transitions.append((_EVENT_BY_STATUS[status][0], claim))
    return transitions


def _claim_map(registry: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    claims = registry.get("claims") if isinstance(registry, dict) else None
    if not isinstance(claims, list):
        return {}
    mapped: dict[str, dict[str, Any]] = {}
    for item in claims:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("id") or "").strip()
        if claim_id:
            mapped[claim_id] = item
    return mapped


def _record_claim_event(event_code: str, claim: dict[str, Any]) -> None:
    status = str(claim.get("status") or "").strip()
    _code, level, outcome = _EVENT_BY_STATUS.get(status, (event_code, "info", status or "observed"))
    _record_scene_event(
        event_code or _code,
        message=_claim_message(event_code or _code, claim),
        level=level,
        outcome=outcome,
        fields={
            "claimId": str(claim.get("id") or "").strip(),
            "agentId": str(claim.get("agentId") or "").strip(),
            "laneId": str(claim.get("laneId") or "").strip(),
            "status": status,
            "scopes": _safe_scopes(claim.get("scopes")),
            "task": _truncate_text(claim.get("task")),
            "reason": _truncate_text(claim.get("releaseReason") or claim.get("notes")),
        },
    )


def _claim_message(event_code: str, claim: dict[str, Any]) -> str:
    claim_id = str(claim.get("id") or "").strip() or "claim"
    status = str(claim.get("status") or "").strip() or "updated"
    if event_code.endswith(".blocked"):
        return f"Coordination claim {claim_id} was blocked."
    if event_code.endswith(".expired"):
        return f"Coordination claim {claim_id} expired."
    if event_code.endswith(".yielded"):
        return f"Coordination claim {claim_id} was yielded."
    if event_code.endswith(".released"):
        return f"Coordination claim {claim_id} was {status}."
    return f"Coordination claim {claim_id} is {status}."


def _safe_scopes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    scopes: list[str] = []
    for item in value:
        text = str(item or "").replace("\\", "/").strip()
        if text:
            scopes.append(_truncate_text(text))
        if len(scopes) >= SCOPE_LOG_LIMIT:
            break
    return scopes


def _truncate_text(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) <= TEXT_LOG_LIMIT:
        return text
    return text[:TEXT_LOG_LIMIT] + "..."


def _record_scene_event(
    event_code: str,
    *,
    message: str,
    level: str,
    outcome: str,
    fields: dict[str, Any],
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event_quietly

        record_runtime_scene_event_quietly(
            "coordination",
            "claim",
            event_code,
            message=message,
            level=level,
            outcome=outcome,
            fields=fields,
            lifecycle=True,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics must never fail coordination
        _debug_logger.warning(
            f"runtime scene event record failed (coordination/claim/{event_code}): "
            f"{type(exc).__name__}: {exc}",
            tag="SCENE",
        )
