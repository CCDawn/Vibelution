"""Evidence graph projection for workflow runs (read-only).

The workflow graph records artifact REFS (hash:...) rather than graph content,
so the concrete graph is projected from the run's evidence facts:

- primary: `langGraph.artifacts.evidence_relation_graph` when the graph stored
  an actual dict (future-proof for graph-produced projections);
- fallback: research-loop evidenceRecords for the run's research project
  (loops index), the same source the legacy graph panel consumed.

This module never writes. Missing data raises NodeCommandUnavailable so the
frontend shows an honest reason instead of an empty graph.
"""

from __future__ import annotations

import json
from typing import Any

from .node_command_adapter import NodeCommandUnavailable


def _artifact_refs(record: dict[str, Any]) -> dict[str, Any]:
    return dict((record.get("langGraph") or {}).get("artifacts") or {})


def evidence_graph_availability(record: dict[str, Any]) -> tuple[bool, str]:
    raw = _artifact_refs(record).get("evidence_relation_graph")
    if isinstance(raw, dict) and raw:
        return True, ""
    if _loop_evidence_for_project(record):
        return True, ""
    return False, "尚无证据关系数据：先完成证据卡与关系图产出"


def _loop_evidence_for_project(record: dict[str, Any]) -> list[dict[str, Any]]:
    team_id = str(record.get("teamId") or "").strip()
    project_id = str(record.get("projectId") or "").strip()
    if not team_id or not project_id:
        return []
    try:
        from core.web.services import team_workflow_orchestration_service as s

        index_path = s.resolve_team_program_root(team_id) / "research_loops" / "index.json"
        if not index_path.exists():
            return []
        loops = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return []
    records: list[dict[str, Any]] = []
    for loop in loops if isinstance(loops, list) else []:
        if not isinstance(loop, dict):
            continue
        if str(loop.get("researchProjectId") or "") != project_id:
            continue
        for item in list(loop.get("evidenceRecords") or [])[:200]:
            if isinstance(item, dict):
                records.append(item)
    return records


def _evidence_id(item: dict[str, Any]) -> str:
    return str(item.get("evidenceId") or item.get("resultId") or "").strip()


def _evidence_claim(item: dict[str, Any]) -> str:
    value = str(item.get("claim") or item.get("summary") or "").strip()
    return value[:240]


def _evidence_source(item: dict[str, Any]) -> str:
    value = str(
        item.get("source")
        or item.get("sourceId")
        or item.get("knowledgeId")
        or ""
    ).strip()
    return value[:160]


def _project_from_loop_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()

    def add_node(node_id: str, node_type: str, props: dict[str, Any]) -> None:
        if node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        nodes.append({"id": node_id, "type": node_type, **props})

    def add_edge(source: str, target: str, kind: str) -> None:
        key = (source, target, kind)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"source": source, "target": target, "kind": kind})

    for item in records:
        evidence_id = _evidence_id(item)
        if not evidence_id:
            continue
        claim = _evidence_claim(item)
        source = _evidence_source(item)
        add_node(
            f"evidence:{evidence_id}",
            "evidence",
            {
                "evidenceId": evidence_id,
                "claim": claim,
                "evidenceType": str(item.get("evidenceType") or ""),
                "status": str(item.get("status") or ""),
            },
        )
        if source:
            add_node(f"source:{source}", "source", {"title": source})
            add_edge(f"source:{source}", f"evidence:{evidence_id}", "supports")
        if claim:
            claim_id = f"claim:{evidence_id}"
            add_node(claim_id, "claim", {"claim": claim})
            add_edge(f"evidence:{evidence_id}", claim_id, "derives")

    return {"nodes": nodes, "edges": edges}


def project_evidence_graph(record: dict[str, Any]) -> dict[str, Any]:
    """Return the evidence graph DTO for a run (raise when no facts exist)."""
    artifacts = _artifact_refs(record)
    raw = artifacts.get("evidence_relation_graph")
    if isinstance(raw, dict) and raw:
        graph = {
            **raw,
            "runId": str(record.get("runId") or ""),
        }
        graph.setdefault("nodes", [])
        graph.setdefault("edges", [])
        return graph

    records = _loop_evidence_for_project(record)
    if not records:
        raise NodeCommandUnavailable(
            "尚无证据关系数据：先完成证据卡与关系图产出",
            code="no_evidence_graph_data",
        )
    return {
        "runId": str(record.get("runId") or ""),
        "source": "research_loop_evidence_records",
        **(_project_from_loop_records(records)),
    }
