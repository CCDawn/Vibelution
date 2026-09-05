"""Read a run's receipt-bound evidence graph from its canonical domain store."""
from __future__ import annotations

from typing import Any

from . import artifact_readback_registry as artifacts
from .node_command_adapter import NodeCommandUnavailable


def _bound_graph(record: dict[str, Any]) -> dict[str, Any] | None:
    refs = [ref for ref in (record.get("artifactSummary") or {}).get("refs", [])
            if ref.get("kind") == "evidence_relation_graph" and ref.get("materialized")]
    if not refs:
        return None
    # A changed or missing current graph must not fall back to an older receipt.
    ref = max(refs, key=lambda item: int(item.get("verifiedAtMs") or 0))
    parsed = artifacts.parse_canonical_ref(str(ref.get("canonicalRef") or ""))
    run_id = str(record.get("runId") or "").strip()
    team_id = str(record.get("teamId") or "").strip()
    if (not parsed or not run_id or not team_id
            or parsed["kind"] != "evidence_relation_graph"
            or parsed["teamId"] != team_id
            or parsed["contentHash"] != ref.get("sha256")):
        return None
    graph = artifacts.load_scoped_artifact_payload(
        "evidence_relation_graph", team_id=team_id,
        authority_run_id=parsed["authorityRunId"], workflow_run_id=run_id,
        content_hash=parsed["contentHash"],
    )
    if graph is None or artifacts.canonical_sha256(graph) != parsed["contentHash"]:
        return None
    return {**graph, "runId": run_id, "source": "canonical_artifact",
            "canonicalRef": ref["canonicalRef"]}


def evidence_graph_availability(record: dict[str, Any]) -> tuple[bool, str]:
    if _bound_graph(record) is not None:
        return True, ""
    return False, "当前运行尚无可核验的证据关系数据：需绑定正式产物回执且内容与回执一致"


def project_evidence_graph(record: dict[str, Any]) -> dict[str, Any]:
    graph = _bound_graph(record)
    if graph is None:
        raise NodeCommandUnavailable(
            "当前运行尚无可核验的证据关系数据：需绑定正式产物回执且内容与回执一致",
            code="no_evidence_graph_data",
        )
    return graph
