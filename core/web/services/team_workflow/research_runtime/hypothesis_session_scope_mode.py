"""Frozen rollout mode and side-effect-free shadow evaluation for hypothesis scopes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal, cast

HypothesisSessionScopeMode = Literal["off", "shadow", "on"]
_MODES = frozenset({"off", "shadow", "on"})
HYPOTHESIS_SCOPE_LEGACY_FALLBACK_REASON = (
    "legacy_non_hypothesis_first_without_authoritative_selection"
)


def _run_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    raw_snapshot = value.get("inputSnapshot")
    if isinstance(raw_snapshot, Mapping):
        return dict(raw_snapshot)
    return dict(value)


def _selection_id_from_snapshot(snapshot: Mapping[str, Any]) -> str:
    raw_selection = (
        snapshot.get("hypothesisSelection")
        or snapshot.get("hypothesis_selection")
        or snapshot.get("selection")
    )
    selection = dict(raw_selection) if isinstance(raw_selection, Mapping) else {}
    nested = selection.get("selection")
    if isinstance(nested, Mapping):
        selection = dict(nested)
    return str(
        selection.get("selectionId")
        or snapshot.get("hypothesisSelectionId")
        or snapshot.get("selectionId")
        or ""
    ).strip()


def resolve_hypothesis_scope_activation(
    snapshot_or_record: Mapping[str, Any],
    *,
    chain_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve whether candidate fan-out is applicable to a run.

    This is deliberately a pure decision over the frozen run snapshot and an
    already-read hypothesis chain state.  The node name is not consulted:
    hypothesis-first runs require an authoritative selection, while a
    non-hypothesis-first run without one keeps the legacy node-shared session
    path as an explicitly labelled compatibility fallback.
    """
    snapshot = _run_snapshot(snapshot_or_record)
    raw_chain = chain_state if isinstance(chain_state, Mapping) else {}
    selection_id = _selection_id_from_snapshot(snapshot) or str(
        raw_chain.get("selectionId") or ""
    ).strip()
    try:
        from . import hypothesis_first_chain

        hypothesis_first = hypothesis_first_chain.is_hypothesis_first_snapshot(snapshot)
    except Exception:
        # Older callers may not have the chain module available; preserve the
        # same fail-open marker semantics used by readiness contexts.
        objective = snapshot.get("researchObjectiveContract")
        hypothesis_first = isinstance(objective, Mapping) and objective.get(
            "hypothesisFirst"
        ) is True
    mode = resolve_hypothesis_session_scope_mode(snapshot)
    has_authoritative_selection = bool(selection_id)
    fan_out_enabled = mode != "off" and has_authoritative_selection
    selection_required = mode != "off" and hypothesis_first
    fallback_reason = ""
    if mode != "off" and not has_authoritative_selection and not hypothesis_first:
        fallback_reason = HYPOTHESIS_SCOPE_LEGACY_FALLBACK_REASON
    return {
        "mode": mode,
        "hypothesisFirst": hypothesis_first,
        "selectionId": selection_id,
        "hasAuthoritativeSelection": has_authoritative_selection,
        "fanOutEnabled": fan_out_enabled,
        "selectionRequired": selection_required,
        "fallbackReason": fallback_reason,
    }


def resolve_hypothesis_session_scope_mode(
    snapshot: Mapping[str, Any],
) -> HypothesisSessionScopeMode:
    raw = snapshot.get("workflowSessionScopeV3")
    config = dict(raw) if isinstance(raw, Mapping) else {}
    mode = str(config.get("hypothesis_design") or "off").strip().lower()
    if mode not in _MODES:
        raise ValueError(
            "workflowSessionScopeV3.hypothesis_design must be off, shadow or on"
        )
    return cast(HypothesisSessionScopeMode, mode)


def evaluate_hypothesis_scope_shadow(
    fan_out: Mapping[str, Any],
    *,
    max_parallel: int,
) -> dict[str, Any]:
    """Validate stable candidate scopes without creating sessions/tasks/artifacts."""

    selection_id = str(fan_out.get("selectionId") or "").strip()
    selected = [
        str(item).strip()
        for item in list(fan_out.get("selectedCandidateIds") or [])
        if str(item).strip()
    ]
    if not selection_id or not selected or len(selected) != len(set(selected)):
        raise ValueError("shadow hypothesis scope requires one valid unique selection")
    if max_parallel < 1 or len(selected) > max_parallel:
        raise ValueError("shadow hypothesis scope exceeds maxConcurrency")
    scopes = [
        {
            "kind": "workflow_candidate",
            "selectionId": selection_id,
            "candidateId": candidate_id,
        }
        for candidate_id in selected
    ]
    digest = hashlib.sha256(
        json.dumps(scopes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "mode": "shadow",
        "selectionId": selection_id,
        "candidateCount": len(selected),
        "scopeHash": digest,
    }


__all__ = [
    "HYPOTHESIS_SCOPE_LEGACY_FALLBACK_REASON",
    "HypothesisSessionScopeMode",
    "evaluate_hypothesis_scope_shadow",
    "resolve_hypothesis_scope_activation",
    "resolve_hypothesis_session_scope_mode",
]
