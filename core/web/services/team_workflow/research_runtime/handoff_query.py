"""Read-only Handoff list and provenance detail projections."""

from __future__ import annotations

from typing import Any


class HandoffQueryError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def list_handoffs(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": record["runId"],
        "teamId": record["teamId"],
        "runVersion": record["runVersion"],
        "handoffs": [dict(item) for item in record.get("handoffs") or []],
    }


def get_handoff_detail(
    record: dict[str, Any],
    handoff_id: str,
) -> dict[str, Any]:
    handoff = next(
        (
            dict(item)
            for item in record.get("handoffs") or []
            if str(item.get("handoffId") or "") == handoff_id
        ),
        None,
    )
    if handoff is None:
        raise HandoffQueryError(
            f"Unknown handoffId: {handoff_id}",
            code="unknown_handoff",
        )
    node_runs = list(record.get("nodeRuns") or [])
    manifests = list(record.get("artifactManifests") or [])
    artifact_ids = {
        str(item.get("artifactId") or "")
        for item in handoff.get("outputArtifactRefs") or []
    }
    human_task_id = str(handoff.get("humanTaskId") or "")
    return {
        "runId": record["runId"],
        "teamId": record["teamId"],
        "runVersion": record["runVersion"],
        "handoff": handoff,
        "fromNodeRun": next(
            (
                dict(item)
                for item in node_runs
                if item.get("nodeRunId") == handoff.get("fromNodeRunId")
            ),
            None,
        ),
        "toNodeRun": next(
            (
                dict(item)
                for item in node_runs
                if item.get("nodeRunId") == handoff.get("toNodeRunId")
            ),
            None,
        ),
        "humanTask": next(
            (
                dict(item)
                for item in record.get("humanTasks") or []
                if human_task_id and item.get("taskId") == human_task_id
            ),
            None,
        ),
        "artifactManifests": [
            dict(item)
            for item in manifests
            if str(item.get("artifactId") or "") in artifact_ids
        ],
    }
