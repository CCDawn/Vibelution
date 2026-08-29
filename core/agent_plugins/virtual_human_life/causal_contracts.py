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
    "reflectionProposals": "reflections/proposals.jsonl",
    "memoryReinforcements": "memory/reinforcement_receipts.jsonl",
    "memoryReconciliations": "memory/reconciliation_receipts.jsonl",
    "environmentFacts": "environment/facts.jsonl",
    "locationMovements": "environment/location_movements.jsonl",
    "calendarEvents": "calendar/events.jsonl",
    "rhythmProfile": "rhythms/state.json",
    "worldCatalog": "world/catalog.json",
    "artifactReceipts": "artifacts/receipts.jsonl",
    "socialCircle": "social/npcs.json",
    "expressionRules": "expression/rules.json",
    "embodimentConfig": "embodiment/config.json",
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
        {
            "sliceId": "reflection-timeline-and-environment",
            "sourcePaths": [
                "dreaming.py",
                "self_timeline.py",
                "daily_state.py",
                "tests/test_environment_change_proactive.py",
                "tests/test_detail_model_location.py",
            ],
            "adaptationBoundary": (
                "Adapt source-backed reflection, history-only timeline disclosure, "
                "environment provenance, and non-instant location transitions; dream "
                "material never becomes external fact and elapsed plans never become history."
            ),
            "verification": (
                "reflection rejection, fact supersession, timed movement, memory provenance, "
                "and injected-clock cross-midnight tests"
            ),
        },
        {
            "sliceId": "calendar-and-chronotype",
            "sourcePaths": [
                "calendar_contracts.py",
                "calendar_observer.py",
                "chronotype.py",
                "daily_review.py",
            ],
            "adaptationBoundary": (
                "Adapt durable calendar constraints, recurrence/exception expansion, "
                "conflict evidence, and conservative chronotype learning; daily Schedule "
                "continues to own execution and one unusual night cannot rewrite the profile."
            ),
            "verification": (
                "recurrence, exception, cancellation, conflict, cross-midnight, and "
                "repeated-evidence chronotype tests with injected time"
            ),
        },
        {
            "sliceId": "interests-world-and-local-feed",
            "sourcePaths": [
                "reading_archive.py",
                "news_exploration.py",
                "creative.py",
                "place_cognitive_map.py",
                "photo_reference_catalog.py",
                "photo_wardrobe_decision.py",
            ],
            "adaptationBoundary": (
                "Adapt outcome-backed reading/news/creative progress, stable familiar-place "
                "and important-item catalogs, plus local artifact receipts; omit AstrBot "
                "platform publishing, user-profile storage, and asset assumptions."
            ),
            "verification": (
                "failed/planned outcome gate, idempotent place visits, source-backed items, "
                "stable NPC profiles, and read-only life-feed projection tests"
            ),
        },
        {
            "sliceId": "expression-and-embodiment-boundaries",
            "sourcePaths": [
                "busy_reply_gate.py",
                "segmented_message.py",
                "reaction_expression.py",
            ],
            "adaptationBoundary": (
                "Adapt explainable condition/priority selection and explicit asset preference "
                "boundaries; do not delay native real-time chat, expose process messages, "
                "or bundle third-party character, voice, GLB, or Live2D assets."
            ),
            "verification": (
                "rule-priority explanation, unauthorized-asset fallback, provider failure, "
                "and native text-chat continuity tests"
            ),
        },
    ],
    "referenceOnlySources": [
        {
            "name": "Graphiti",
            "sourceCommit": "c18d6778184c55e3be28f5ae3e5821930b361d47",
            "boundary": "fact validity and supersession semantics only; no graph database",
        },
        {
            "name": "LangMem",
            "sourceCommit": "29cbe41e58528f92e9efa773c12e15c47be3808c",
            "boundary": "memory proposal lifecycle only; no LangGraph memory runtime",
        },
        {
            "name": "Parlant",
            "sourceCommit": "ea737442b8ae65854a842542e544fbe7e6144bad",
            "boundary": "condition, priority, dependency, and explanation only",
        },
        {
            "name": "Voyager",
            "sourceCommit": "55e45a880755d0c8c66ca7fb5fe7962ac8974f89",
            "boundary": "curriculum and verified skill progress only",
        },
        {
            "name": "SOTOPIA",
            "sourceCommit": "a0aaafb440e570e5e61b7c44a44e5e417c545383",
            "boundary": "lightweight social-profile evaluation concepts only",
        },
        {
            "name": "TalkingHead",
            "sourceCommit": "eed58d198076a7e1e825f804802921c4d3804d46",
            "boundary": "optional provider shape only; assets require separate authorization",
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
