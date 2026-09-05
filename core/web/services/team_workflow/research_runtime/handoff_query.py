"""Read-only Handoff list and provenance detail projections."""

from __future__ import annotations

from typing import Any

from . import artifact_readback_registry as artifacts


def _knowledge_packages(record: dict[str, Any], handoff: dict[str, Any]) -> list[dict[str, Any]]:
    """Read only the drafts bound to this handoff, retaining their independent status."""
    result = []
    for ref in handoff.get("outputArtifactRefs") or []:
        if ref.get("kind") != "knowledge_package_draft":
            continue
        reading: dict[str, Any] = {"artifactId": ref.get("artifactId", ""), "status": "unavailable"}
        result.append(reading)
        parsed = artifacts.parse_canonical_ref(str(ref.get("uri") or ""))
        if (not parsed or parsed["kind"] != "knowledge_package_draft"
                or parsed["teamId"] != record["teamId"]
                or parsed["contentHash"] != ref.get("contentHash")):
            continue
        payload = artifacts.load_scoped_artifact_payload(
            "knowledge_package_draft", team_id=record["teamId"],
            authority_run_id=parsed["authorityRunId"], workflow_run_id=record["runId"],
            content_hash=parsed["contentHash"],
        )
        if payload is None or artifacts.canonical_sha256(payload) != parsed["contentHash"]:
            continue
        draft = payload.get("draft") or {}
        proposal = draft.get("proposalPayload") or {}
        text = lambda value: value if isinstance(value, str) else ""
        reading.update(
            status="available", title=text(proposal.get("title")),
            summary=text(proposal.get("summary")), content=text(proposal.get("content")),
            sourceUrl=text((draft.get("sourceTrace") or {}).get("sourceUrl")),
            riskSummary=text(draft.get("riskSummary")),
            uncertainties=[item for item in draft.get("uncertainty", []) if isinstance(item, str)],
        )
    return result


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
        "knowledgePackages": _knowledge_packages(record, handoff),
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
