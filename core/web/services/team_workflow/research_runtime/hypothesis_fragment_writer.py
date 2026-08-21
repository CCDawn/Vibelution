"""Validate one child-session hypothesis fragment.

The writer deliberately does not inspect or summarize session messages.  It
binds the structured child output to the task context, applies the accepted
knowledge-package allowlist, and returns an immutable hash-bound fragment
envelope.  Persistence can be supplied by the workflow owner once the
artifact-store kind is registered; keeping the sink injectable also makes the
contract safe to use during migration/shadow mode.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any

from core.research.workflow.contracts.hypothesis_fragment import (
    HYPOTHESIS_FRAGMENT_KIND,
    HYPOTHESIS_FRAGMENT_SCHEMA_VERSION,
    HypothesisFragment,
    canonical_fragment_payload,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _task(task_context: Mapping[str, Any]) -> dict[str, Any]:
    value = task_context.get("task")
    return dict(value) if isinstance(value, Mapping) else {}


def _input(task_context: Mapping[str, Any]) -> dict[str, Any]:
    value = task_context.get("hypothesisInput")
    return dict(value) if isinstance(value, Mapping) else {}


def _required_task_value(
    task: Mapping[str, Any], payload: Mapping[str, Any], field: str, *aliases: str
) -> str:
    keys = (field, *aliases)
    task_value = next((_text(task.get(key)) for key in keys if _text(task.get(key))), "")
    payload_value = next(
        (_text(payload.get(key)) for key in keys if _text(payload.get(key))), ""
    )
    if task_value and payload_value and task_value != payload_value:
        raise ValueError(f"Hypothesis fragment {field} does not match bound task scope.")
    value = task_value or payload_value
    if not value:
        raise ValueError(f"Hypothesis fragment is missing bound {field}.")
    return value


def _required_attempt(task: Mapping[str, Any], payload: Mapping[str, Any]) -> int:
    task_value = task.get("sessionAttempt")
    payload_value = payload.get("sessionAttempt")
    if task_value is not None and payload_value is not None and task_value != payload_value:
        raise ValueError("Hypothesis fragment sessionAttempt does not match bound task scope.")
    value = task_value if task_value is not None else payload_value
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("Hypothesis fragment sessionAttempt must be a positive integer.")
    return value


def _bound_payload(task: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.update(
        {
            "schemaVersion": HYPOTHESIS_FRAGMENT_SCHEMA_VERSION,
            "kind": HYPOTHESIS_FRAGMENT_KIND,
            "workflowRunId": _required_task_value(
                task, payload, "workflowRunId", "runId"
            ),
            "workflowNodeId": _required_task_value(
                task, payload, "workflowNodeId", "nodeId"
            ),
            "nodeRunId": _required_task_value(task, payload, "nodeRunId"),
            "selectionId": _required_task_value(task, payload, "selectionId"),
            "candidateId": _required_task_value(task, payload, "candidateId"),
            "sessionId": _required_task_value(task, payload, "sessionId"),
            "sessionAttempt": _required_attempt(task, payload),
            "taskId": _required_task_value(task, payload, "taskId"),
        }
    )
    provenance = result.get("provenance")
    if not isinstance(provenance, Mapping) or not provenance:
        provenance = {
            "source": "child_session",
            "workflowRunId": result["workflowRunId"],
            "workflowNodeId": result["workflowNodeId"],
            "nodeRunId": result["nodeRunId"],
            "selectionId": result["selectionId"],
            "candidateId": result["candidateId"],
            "taskId": result["taskId"],
            "sessionId": result["sessionId"],
            "sessionAttempt": result["sessionAttempt"],
        }
    result["provenance"] = copy.deepcopy(dict(provenance))
    # The writer is authoritative for the digest; a stale model-supplied hash
    # is replaced before the contract parses it.
    return canonical_fragment_payload(result)


def _validate_provenance(fragment: HypothesisFragment) -> None:
    provenance = fragment.provenance
    expected = {
        "workflowRunId": fragment.workflowRunId,
        "workflowNodeId": fragment.workflowNodeId,
        "nodeRunId": fragment.nodeRunId,
        "selectionId": fragment.selectionId,
        "candidateId": fragment.candidateId,
        "sessionId": fragment.sessionId,
        "taskId": fragment.taskId,
    }
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
        supplied = next((_text(provenance.get(key)) for key in keys if _text(provenance.get(key))), "")
        if supplied and supplied != expected[field]:
            raise ValueError(f"Hypothesis fragment provenance does not match {field}.")
    if "sessionAttempt" in provenance and provenance["sessionAttempt"] != fragment.sessionAttempt:
        raise ValueError("Hypothesis fragment provenance does not match sessionAttempt.")


def _allowed_counter_evidence(task_context: Mapping[str, Any]) -> set[str]:
    allowed = _input(task_context).get("allowedEvidenceRefs")
    if not isinstance(allowed, list):
        return set()
    return {
        _text(item)[:200]
        for item in allowed
        if _text(item)[:200]
    }


def build_hypothesis_fragment(
    *, task_context: Mapping[str, Any], payload: Mapping[str, Any]
) -> HypothesisFragment:
    """Bind and validate a fragment without touching a session transcript."""
    task = _task(task_context)
    if not task:
        raise ValueError("Hypothesis fragment requires a bound task.")
    if _text(task.get("workflowNodeId") or task.get("nodeId")) not in {
        "hypothesis_design",
        "hypothesis_fragment",
    }:
        raise ValueError("Hypothesis fragment requires a bound hypothesis_design task.")
    if _input(task_context).get("status") != "ready":
        raise ValueError("Accepted knowledge package is not ready for hypothesis fragment.")
    if not isinstance(payload, Mapping):
        raise TypeError("Hypothesis fragment payload must be an object.")
    bound = _bound_payload(task, payload)
    fragment = HypothesisFragment.from_dict(bound)
    _validate_provenance(fragment)
    allowed = _allowed_counter_evidence(task_context)
    if not fragment.counterEvidenceRefs:
        raise ValueError("Every hypothesis fragment requires counter-evidence references.")
    unknown = sorted(set(fragment.counterEvidenceRefs) - allowed)
    if unknown:
        raise ValueError(
            "Hypothesis fragment counter-evidence references are outside the allowed evidence package: "
            + ", ".join(unknown[:8])
        )
    return fragment


def record_hypothesis_fragment(
    *,
    team_id: str,
    task_context: Mapping[str, Any],
    payload: Mapping[str, Any],
    persist: bool = False,
    artifact_sink: Callable[..., Mapping[str, Any]] | None = None,
    artifact_identity: str = "",
) -> dict[str, Any]:
    """Return a validated fragment envelope and optionally persist via a sink.

    ``persist`` is opt-in because the current artifact-store registry predates
    the new ``hypothesis_fragment`` kind.  A caller that has registered that
    kind supplies ``artifact_sink`` (typically ``put_workflow_artifact``), so
    migration cannot silently write a fragment to the wrong artifact stream.
    """
    fragment = build_hypothesis_fragment(task_context=task_context, payload=payload)
    task = _task(task_context)
    workflow_run_id = fragment.workflowRunId
    source_collection_run_id = _text(task.get("sourceCollectionRunId"))
    default_artifact_ref = (
        f"{HYPOTHESIS_FRAGMENT_KIND}:{fragment.selectionId}:"
        f"{fragment.candidateId}:{fragment.nodeRunId}"
    )
    artifact_ref = _text(artifact_identity) or default_artifact_ref
    artifact: dict[str, Any] = {
        "recordId": artifact_ref,
        "fragmentRef": artifact_ref,
        "kind": HYPOTHESIS_FRAGMENT_KIND,
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_collection_run_id,
        "contentHash": fragment.contentHash,
    }
    if persist:
        if artifact_sink is None:
            raise ValueError(
                "Hypothesis fragment persistence requires an explicit artifact sink."
            )
        stored = artifact_sink(
            team_id,
            kind=HYPOTHESIS_FRAGMENT_KIND,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=source_collection_run_id,
            artifact_identity=artifact_ref,
            payload=fragment.to_dict(),
        )
        if not isinstance(stored, Mapping):
            raise ValueError("Hypothesis fragment artifact sink returned an invalid record.")
        artifact.update(
            {
                "recordId": _text(stored.get("recordId")) or artifact_ref,
                "contentHash": _text(stored.get("contentHash")) or fragment.contentHash,
            }
        )
    return {
        "fragment": fragment.to_dict(),
        "artifact": artifact,
        "scopeBinding": {
            "workflowRunId": fragment.workflowRunId,
            "workflowNodeId": fragment.workflowNodeId,
            "nodeRunId": fragment.nodeRunId,
            "selectionId": fragment.selectionId,
            "candidateId": fragment.candidateId,
            "sessionId": fragment.sessionId,
            "sessionAttempt": fragment.sessionAttempt,
            "taskId": fragment.taskId,
            "source": "bound_hypothesis_child_session",
        },
    }


__all__ = [
    "build_hypothesis_fragment",
    "record_hypothesis_fragment",
]
