"""Causal-life storage and provenance contracts.

The Vibelution plugin remains the sole runtime owner.  The upstream receipt is
metadata for a small, permission-backed adaptation; it is not a dependency or
an alternate Agent/Session/Memory authority.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

CAUSAL_SCHEMA_VERSION = 1
CAUSAL_LEDGER_PATHS = {
    "drives": "drives/state.json",
    "driveEvents": "drives/events.jsonl",
    "affectEpisodes": "affect/episodes.jsonl",
    "affectProjection": "affect/state.json",
    "relationshipEvents": "relationships/events.jsonl",
    "relationshipProjection": "relationships.json",
    "proactiveCandidates": "proactive/candidates.jsonl",
    "openLoops": "conversation/open_loops.jsonl",
}

_UPSTREAM_REUSE_RECEIPT: dict[str, Any] = {
    "schemaVersion": 1,
    "sourceRepo": "https://github.com/menglimi/astrbot_plugin_private_companion",
    "sourceCommit": "85cc366ee6e1ccf08b357e8b9e396c3abb842ff4",
    "permissionBasis": "user_confirmed_upstream_permission_2026-08-29",
    "publicationBoundary": "requires_separate_attribution_and_distribution_confirmation",
    "runtimeDependency": False,
    "adaptationBoundary": (
        "Reuse bounded domain policies and test ideas only; Vibelution keeps Agent, "
        "Session, Memory, ToolPolicy, workspace, lifecycle, delivery, and VUI authority."
    ),
    "slices": [
        {
            "sliceId": "proactive-candidate-policy",
            "sourcePaths": [
                "proactive_engine.py",
                "proactive.py",
                "proactive_message.py",
            ],
            "adaptationBoundary": (
                "Adapt candidate windows, score factors, duplicate suppression, "
                "unanswered backoff, and send-time recheck into the existing "
                "Vibelution proactive Turn transaction."
            ),
            "verification": "deterministic candidate-policy and delivery-boundary tests",
        },
        {
            "sliceId": "affect-afterglow",
            "sourcePaths": [
                "domains/affect/emotion_event_contract.py",
                "domains/affect/emotion_event_ledger.py",
                "domains/affect/affect_modulation.py",
            ],
            "adaptationBoundary": (
                "Adapt source-addressed emotion episodes and bounded recovery; do "
                "not reuse platform identity roles or prompt/runtime ownership."
            ),
            "verification": "event idempotency and accelerated recovery replay tests",
        },
        {
            "sliceId": "relationship-ledger",
            "sourcePaths": [
                "relationship_ledger.py",
                "relationship_event_policy.py",
                "relationship_policy.py",
            ],
            "adaptationBoundary": (
                "Adapt bounded event deltas, stage hysteresis, decay, and repair into "
                "Agent-scoped ledgers; omit AstrBot private/group role semantics."
            ),
            "verification": "daily caps, stage lag, decay, repair, and replay tests",
        },
        {
            "sliceId": "life-drives-and-open-loops",
            "sourcePaths": ["daily_state.py", "user_memory.py", "self_timeline.py"],
            "adaptationBoundary": (
                "Adapt outcome-backed goal/skill progress and open-loop lifecycle; "
                "do not import the upstream user-profile store or self-timeline as memory SSOT."
            ),
            "verification": "outcome gate, dedupe, expiry, and schedule-link tests",
        },
    ],
}


def authorized_reuse_receipt() -> dict[str, Any]:
    """Return a copy so callers cannot mutate the process-level receipt."""

    return deepcopy(_UPSTREAM_REUSE_RECEIPT)


__all__ = [
    "CAUSAL_LEDGER_PATHS",
    "CAUSAL_SCHEMA_VERSION",
    "authorized_reuse_receipt",
]
