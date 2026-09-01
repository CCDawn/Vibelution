"""Deterministic fan-in from candidate fragments to a hypothesis-set payload."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from core.research.workflow.contracts._canonical import sha256_hex
from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.hypothesis_fragment import HypothesisFragment


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        converted = value.to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _selection_fields(selection: Any) -> dict[str, Any]:
    value = _mapping(selection)
    nested = value.get("selection")
    if isinstance(nested, Mapping):
        value = dict(nested)
    return value


def _scope_value(scope: Mapping[str, Any], *keys: str) -> str:
    return next((_text(scope.get(key)) for key in keys if _text(scope.get(key))), "")


def _required_scope(scope: Mapping[str, Any], field: str, *aliases: str) -> str:
    value = _scope_value(scope, field, *aliases)
    if not value:
        raise ValueError(f"Hypothesis fragment aggregation scope is missing {field}.")
    return value


def _candidate_ids(selection: Mapping[str, Any]) -> tuple[str, ...]:
    raw = selection.get("selectedCandidateIds")
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValueError("Hypothesis fragment aggregation selection is missing selected candidates.")
    ids = tuple(_text(item) for item in raw)
    if any(not item for item in ids):
        raise ValueError("Hypothesis fragment aggregation selection contains an empty candidate.")
    if len(set(ids)) != len(ids):
        raise ValueError("Hypothesis fragment aggregation selection candidate IDs must be unique.")
    return ids


def _fragment_payload(value: Any) -> Mapping[str, Any] | HypothesisFragment:
    if isinstance(value, HypothesisFragment):
        return value
    item = _mapping(value)
    nested = item.get("fragment")
    if isinstance(nested, Mapping):
        return nested
    nested = item.get("payload")
    if isinstance(nested, Mapping) and (
        nested.get("kind") == "hypothesis_fragment"
        or nested.get("candidateId")
    ):
        return nested
    return item


def _provenance_matches(
    fragment: HypothesisFragment,
    expected: Mapping[str, str],
) -> bool:
    provenance = fragment.provenance
    aliases = {
        "workflowRunId": ("workflowRunId", "runId"),
        "workflowNodeId": ("workflowNodeId", "nodeId"),
        "nodeRunId": ("nodeRunId",),
        "selectionId": ("selectionId",),
        "candidateId": ("candidateId",),
        "sessionId": ("sessionId",),
        "taskId": ("taskId",),
    }
    for field, keys in aliases.items():
        supplied = _scope_value(provenance, *keys)
        if supplied and supplied != expected[field]:
            return False
    attempt = provenance.get("sessionAttempt")
    return not (
        attempt is not None
        and expected.get("sessionAttempt") is not None
        and attempt != expected["sessionAttempt"]
    )


def _candidate_scope_binding(
    scope: Mapping[str, Any], candidate_id: str
) -> dict[str, Any]:
    """Read optional per-candidate task/session bindings from a node scope."""
    for key in (
        "candidateScopes",
        "candidateScope",
        "candidateBindings",
        "bindings",
        "scopedSessions",
    ):
        value = scope.get(key)
        if isinstance(value, Mapping):
            item = value.get(candidate_id)
            if isinstance(item, Mapping):
                return dict(item)
            # ``scopedSessions`` is also commonly represented as an array.
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping) and _text(
                    item.get("candidateId")
                ) == candidate_id:
                    return dict(item)
    return {}


def _binding_mismatch(
    fragment: HypothesisFragment,
    binding: Mapping[str, Any],
) -> str:
    expected_task = _text(binding.get("taskId") or binding.get("task"))
    expected_session = _text(binding.get("sessionId") or binding.get("session"))
    if expected_task and fragment.taskId != expected_task:
        return "taskId"
    if expected_session and fragment.sessionId != expected_session:
        return "sessionId"
    expected_attempt = binding.get("sessionAttempt")
    if expected_attempt is not None and fragment.sessionAttempt != expected_attempt:
        return "sessionAttempt"
    return ""


def _fragment_ref(fragment: HypothesisFragment) -> str:
    supplied = _text(fragment.provenance.get("artifactRef"))
    # Mirrors the writer's artifact identity, which is attempt-scoped so a
    # retry-improved fragment never collides with its superseded attempt.
    return supplied or (
        f"hypothesis_fragment:{fragment.selectionId}:"
        f"{fragment.candidateId}:{fragment.nodeRunId}:"
        f"{fragment.sessionAttempt}"
    )


def aggregate_hypothesis_fragments(
    selection: Mapping[str, Any] | Any,
    fragments: Iterable[Any],
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    """Fan-in exactly one valid fragment per selected candidate.

    Input order is intentionally ignored.  Selection order is the sole order
    used for both the candidate list and provenance anchors, making replay and
    content hashes stable across concurrent completion order.

    When the scope does not pin ``sessionAttempt``, a candidate may supply one
    fragment per retry attempt; the latest attempt wins and superseded
    fragments stay as history.  Fragments sharing one candidate and attempt
    remain a duplicate error.
    """
    selection_payload = _selection_fields(selection)
    selection_id = _text(selection_payload.get("selectionId"))
    if not selection_id:
        raise ValueError("Hypothesis fragment aggregation selectionId is required.")
    selected = _candidate_ids(selection_payload)
    scope_payload = _mapping(scope)
    requested_attempt = scope_payload.get("sessionAttempt")
    if requested_attempt is not None and (
        isinstance(requested_attempt, bool)
        or not isinstance(requested_attempt, int)
        or requested_attempt < 1
    ):
        raise ValueError("Hypothesis fragment aggregation sessionAttempt must be positive.")
    expected = {
        "workflowRunId": _required_scope(scope_payload, "workflowRunId", "runId"),
        "workflowNodeId": _required_scope(scope_payload, "workflowNodeId", "nodeId"),
        "nodeRunId": _required_scope(scope_payload, "nodeRunId"),
        "selectionId": selection_id,
        "sessionAttempt": requested_attempt,
    }
    selected_scope_id = _text(scope_payload.get("selectionId"))
    if selected_scope_id and selected_scope_id != selection_id:
        raise ValueError("Hypothesis fragment aggregation selection scope mismatch.")

    # Candidate/task/session are checked per fragment so provenance cannot
    # smuggle a sibling scope through.
    parsed: dict[str, HypothesisFragment] = {}
    selected_set = set(selected)
    for raw in fragments:
        try:
            item = raw if isinstance(raw, HypothesisFragment) else HypothesisFragment.from_dict(_fragment_payload(raw))
        except (ContractValidationError, TypeError, ValueError) as exc:
            raise ValueError(f"Hypothesis fragment is invalid: {exc}") from exc
        if (
            item.workflowRunId != expected["workflowRunId"]
            or item.workflowNodeId != expected["workflowNodeId"]
            or item.nodeRunId != expected["nodeRunId"]
            or item.selectionId != expected["selectionId"]
            or (
                expected["sessionAttempt"] is not None
                and item.sessionAttempt != expected["sessionAttempt"]
            )
        ):
            raise ValueError(
                "Hypothesis fragment scope mismatch for candidate " + item.candidateId
            )
        if item.candidateId not in selected_set:
            raise ValueError(
                "Hypothesis fragment candidate is outside the selection: "
                + item.candidateId
            )
        binding = _candidate_scope_binding(scope_payload, item.candidateId)
        mismatch = _binding_mismatch(item, binding)
        if mismatch:
            raise ValueError(
                "Hypothesis fragment scope mismatch for candidate "
                + item.candidateId
                + ": "
                + mismatch
            )
        candidate_expected = {
            **expected,
            "candidateId": item.candidateId,
            "sessionId": item.sessionId,
            "taskId": item.taskId,
        }
        if not _provenance_matches(item, candidate_expected):
            raise ValueError(
                "Hypothesis fragment provenance scope mismatch for candidate "
                + item.candidateId
            )
        existing = parsed.get(item.candidateId)
        if existing is not None:
            # A formal retry keeps the superseded attempt's fragment as
            # history.  Unless the scope pins one attempt, the latest
            # attempt wins and older fragments are ignored; two fragments
            # on the same attempt are still a genuine duplicate.
            if item.sessionAttempt == existing.sessionAttempt:
                raise ValueError(
                    "duplicate hypothesis fragment for candidate " + item.candidateId
                )
            if item.sessionAttempt < existing.sessionAttempt:
                continue
        parsed[item.candidateId] = item
    missing = [candidate_id for candidate_id in selected if candidate_id not in parsed]
    if missing:
        raise ValueError("missing hypothesis fragment for candidate(s): " + ", ".join(missing))

    fragment_list = [parsed[candidate_id] for candidate_id in selected]
    fragment_refs = [_fragment_ref(item) for item in fragment_list]
    if len(set(fragment_refs)) != len(fragment_refs):
        raise ValueError("Duplicate hypothesis fragment artifact references are not allowed.")
    anchors = [
        {
            "candidateId": item.candidateId,
            "sessionId": item.sessionId,
            "sessionAttempt": item.sessionAttempt,
            "taskId": item.taskId,
            "fragmentRef": _fragment_ref(item),
            "contentHash": item.contentHash,
        }
        for item in fragment_list
    ]
    candidates = [
        {
            "candidateId": item.candidateId,
            "claim": item.statement,
            "scores": copy.deepcopy(item.scores),
            "counterEvidenceRefs": list(item.counterEvidenceRefs),
            "derivedFromCandidateIds": [],
            "status": "draft",
            "reviewRef": _fragment_ref(item),
        }
        for item in fragment_list
    ]
    candidate_details = {
        item.candidateId: {
            "statement": item.statement,
            "mechanism": item.mechanism,
            "novelty_basis": item.novelty_basis,
            "predictions": list(item.predictions),
            "falsificationCriteria": list(item.falsificationCriteria),
            "evidenceRefs": list(item.evidenceRefs),
            "counterEvidenceRefs": list(item.counterEvidenceRefs),
            "boundary_conditions": list(item.boundary_conditions),
            "contentHash": item.contentHash,
        }
        for item in fragment_list
    }
    run_id = expected["workflowRunId"]
    payload: dict[str, Any] = {
        "portfolioId": _text(selection_payload.get("portfolioId"))
        or f"portfolio:{run_id}:{selection_id}",
        "runId": run_id,
        "maxCandidates": int(selection_payload.get("maxCandidates") or len(selected)),
        "maxEvolutionRounds": int(scope_payload.get("maxEvolutionRounds") or 1),
        "currentEvolutionRound": int(scope_payload.get("currentEvolutionRound") or 1),
        "candidates": candidates,
        "selectionId": selection_id,
        "fragmentRefs": fragment_refs,
        "aggregationMode": "all_required_ordered",
        "candidateSessionAnchors": anchors,
        "candidateDetails": candidate_details,
        "provenance": {
            "source": "hypothesis_fragment_fan_in",
            "workflowRunId": expected["workflowRunId"],
            "workflowNodeId": expected["workflowNodeId"],
            "nodeRunId": expected["nodeRunId"],
            "selectionId": selection_id,
            "selectedCandidateIds": list(selected),
            "fragmentRefs": fragment_refs,
        },
    }
    if payload["maxCandidates"] < len(selected):
        raise ValueError("Aggregated hypothesis candidate count exceeds maxCandidates.")
    if payload["currentEvolutionRound"] < 1 or payload["currentEvolutionRound"] > payload["maxEvolutionRounds"]:
        raise ValueError("Aggregated hypothesis evolution round is outside its limit.")
    payload["contentHash"] = sha256_hex(payload)
    return copy.deepcopy(payload)


__all__ = ["aggregate_hypothesis_fragments"]
