"""Companion-only source classification; elapsed time is never execution proof."""

from collections.abc import Mapping
from typing import Any


def _receipt_ids(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and 0 < len(value) <= 32
        and all(
            isinstance(item, str) and 0 < len(item.strip()) <= 256 for item in value
        )
    )


def event_provenance(event: Mapping[str, Any]) -> str:
    outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
    if (
        event.get("simulatedAfterRestart")
        or outcome.get("kind") == "deterministic_simulation"
    ):
        return "simulation"
    evidence = outcome.get("evidence")
    if (
        outcome.get("kind") == "verified_tool_outcome"
        and isinstance(evidence, Mapping)
        and evidence.get("kind") == "native_tool_execution"
        and str(evidence.get("sessionId") or "").strip()
        and str(evidence.get("turnId") or "").strip()
        and _receipt_ids(evidence.get("toolCallIds"))
        and _receipt_ids(evidence.get("receiptEventIds"))
    ):
        return "verified_action"
    if outcome.get("kind") in {"character_report", "world_experience"}:
        return "character_report"
    return "unknown"


def is_verified_experience(event: Mapping[str, Any]) -> bool:
    outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
    return (
        event.get("kind") == "activity_completed"
        and outcome.get("status") == "succeeded"
        and event_provenance(event) == "verified_action"
    )
