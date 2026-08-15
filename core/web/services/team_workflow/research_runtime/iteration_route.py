"""Pick the real successor after iteration_decision / version_governance.

``successor_map()`` lists every legal edge. Adapter/graph workers used to take
``successors[0]``, which is always ``controlled_run`` after iteration_decision.
STOP / promote / rollback must go to ``version_governance``.
"""

from __future__ import annotations

import json
from typing import Any

from core.research.workflow.challenge_cup_runtime import successor_map
from core.research.workflow.iteration_decisions import (
    IterationDecisionError,
    IterationDecisionKind,
    parse_decision_kind,
    route_target_for_decision,
)


def routed_successors(node_id: str, branch_decision: str | None) -> tuple[str, ...]:
    """Return the single routed successor, or () when the decision is unknown."""
    if node_id == "iteration_decision":
        raw = str(branch_decision or "").strip()
        if not raw:
            return ()
        try:
            target = route_target_for_decision(raw)
        except IterationDecisionError:
            return ()
        return (target,) if target else ()
    if node_id == "version_governance":
        raw = str(branch_decision or "").strip()
        if not raw:
            return ()
        try:
            kind = parse_decision_kind(raw)
        except IterationDecisionError:
            return ()
        if kind is IterationDecisionKind.PROMOTE_CANDIDATE:
            return ("candidate_promotion",)
        if kind in {
            IterationDecisionKind.STOP,
            IterationDecisionKind.ROLLBACK_CANDIDATE,
        }:
            return ("result_package",)
        return ()
    return successor_map().get(node_id, ())


def branch_decision_from_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("decisionKind") or payload.get("kind") or "").strip()


def branch_decision_from_run(run: Any) -> str:
    """Read decisionKind from the persisted iteration_decision artifact."""
    if run is None:
        return ""
    snapshot: dict[str, Any] = {}
    raw = getattr(run, "input_snapshot_json", None) or ""
    if raw:
        try:
            loaded = json.loads(raw)
        except (TypeError, ValueError):
            loaded = {}
        if isinstance(loaded, dict):
            snapshot = loaded
    team_id = str(getattr(run, "team_id", "") or snapshot.get("teamId") or "").strip()
    run_id = str(getattr(run, "run_id", "") or "").strip()
    authority = str(snapshot.get("sourceCollectionRunId") or run_id).strip()
    if not team_id or not run_id or not authority:
        return ""
    from .workflow_artifact_store import load_workflow_artifact_payload

    envelope = load_workflow_artifact_payload(
        "iteration_decision",
        team_id=team_id,
        authority_run_id=authority,
        workflow_run_id=run_id,
    )
    if envelope is None:
        # Compact restore can freeze a sourceCollectionRunId that no longer
        # matches the jsonl row. Readiness already heals that; routing must too.
        from .real_readiness_context import _readiness_artifact_envelope

        envelope = _readiness_artifact_envelope(
            "iteration_decision",
            team_id=team_id,
            run_id=run_id,
            authority_run_id=authority,
        )
    body = envelope.get("payload") if isinstance(envelope, dict) else envelope
    return branch_decision_from_payload(body)
