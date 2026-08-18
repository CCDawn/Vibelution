"""Working-layer experiment outcome graph (prescribed ontology, no graph DB).

P0 authority lives on the experiment plan as ``outcomeGraph``. Registration
writes edges in the same ``_WORKFLOW_LOCK`` as smoke/full-run results.
Official KnowledgeItem sync is out of scope.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA_VERSION = 1
ONTOLOGY = "prescribed_only"
NODE_KINDS = {"experiment_run", "claim", "protocol"}
RELATIONS = {"tests", "supports", "falsifies", "duplicates"}
OUTCOMES = {"passed", "failed", "blocked"}
MAX_NEGATIVE = 8
MAX_SUCCESS = 8
_EXPLICIT_REJECT_MARKERS = (
    "否定",
    "证伪",
    "不成立",
    "falsif",
    "reject",
    "contradict",
    "refute",
)


def claim_id_for_hypothesis(text: str) -> str:
    normalized = " ".join(str(text or "").lower().split())
    if not normalized:
        return ""
    return f"claim-{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:12]}"


def plan_has_outcome_graph(plan: dict[str, Any] | None) -> bool:
    graph = (plan or {}).get("outcomeGraph")
    if not isinstance(graph, dict):
        return False
    edges = [item for item in list(graph.get("edges") or []) if isinstance(item, dict)]
    return bool(edges)


def empty_outcome_graph() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ontology": ONTOLOGY,
        "nodes": [],
        "edges": [],
    }


def normalize_outcome_graph(value: Any) -> dict[str, Any]:
    graph = value if isinstance(value, dict) else {}
    nodes = [item for item in list(graph.get("nodes") or []) if isinstance(item, dict)]
    edges = [item for item in list(graph.get("edges") or []) if isinstance(item, dict)]
    return {
        "schemaVersion": int(graph.get("schemaVersion") or SCHEMA_VERSION),
        "ontology": str(graph.get("ontology") or ONTOLOGY),
        "nodes": nodes,
        "edges": edges,
    }


def current_edges(graph: dict[str, Any] | None) -> list[dict[str, Any]]:
    normalized = normalize_outcome_graph(graph)
    return [
        edge
        for edge in normalized["edges"]
        if str(edge.get("validUntil") or "").strip() == ""
        and str(edge.get("relation") or "") in RELATIONS
    ]


def run_node_id(result: dict[str, Any]) -> str:
    result_id = _result_id(result)
    return f"run:{result_id}" if result_id else ""


def merge_registered_result(
    plan: dict[str, Any],
    result: dict[str, Any],
    *,
    extra: dict[str, Any] | None = None,
    peer_plans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge a smoke/full-run result into ``plan['outcomeGraph']``. Mutates plan."""
    graph = normalize_outcome_graph(plan.get("outcomeGraph"))
    delta = build_outcome_graph_delta(plan, result, extra=extra)
    _apply_delta(graph, delta)
    _attach_cross_plan_duplicates(
        graph,
        plan,
        result,
        signature=str(delta.get("experimentSignature") or ""),
        occurred_at=str(delta.get("occurredAt") or ""),
        peer_plans=peer_plans or [],
    )
    _prune_to_result_window(graph, plan)
    plan["outcomeGraph"] = graph
    return graph


def build_outcome_graph_delta(
    plan: dict[str, Any],
    result: dict[str, Any],
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra_payload = extra if isinstance(extra, dict) else {}
    hypotheses = _plan_hypotheses(plan)
    claim_ids: list[str] = []
    for text in hypotheses:
        claim_id = claim_id_for_hypothesis(text)
        if claim_id and claim_id not in claim_ids:
            claim_ids.append(claim_id)
    claim_id = claim_ids[0] if claim_ids else ""
    hypothesis_by_claim = {
        claim_id_for_hypothesis(text): text for text in hypotheses if claim_id_for_hypothesis(text)
    }
    protocol_id = _protocol_id(plan)
    run_id = run_node_id(result)
    occurred_at = str(result.get("recordedAt") or extra_payload.get("recordedAt") or "")
    signature = _experiment_signature(plan)
    status = str(result.get("status") or "").strip().lower()
    outcome = _outcome_for_status(status)
    interpretation = _interpretation(result, extra_payload, status)
    failed_gates = _failed_gates(plan, extra_payload, outcome)
    evidence_refs = _result_evidence_refs(result)
    nodes = []
    if run_id:
        nodes.append(
            {
                "nodeId": run_id,
                "nodeKind": "experiment_run",
                "ref": {
                    "planId": str(plan.get("planId") or ""),
                    "resultId": _result_id(result),
                },
                "summary": interpretation,
                "outcome": outcome,
                "occurredAt": occurred_at,
            }
        )
    for claim_item_id in claim_ids:
        nodes.append(
            {
                "nodeId": claim_item_id,
                "nodeKind": "claim",
                "ref": {"claimId": claim_item_id, "planId": str(plan.get("planId") or "")},
                "summary": hypothesis_by_claim.get(claim_item_id, ""),
            }
        )
    if protocol_id:
        nodes.append(
            {
                "nodeId": protocol_id,
                "nodeKind": "protocol",
                "ref": {"protocolRef": protocol_id, "planId": str(plan.get("planId") or "")},
                "summary": str(plan.get("title") or protocol_id),
            }
        )
    edges: list[dict[str, Any]] = []
    if run_id and claim_ids:
        for claim_item_id in claim_ids:
            edges.append(
                _edge(
                    relation="tests",
                    from_id=run_id,
                    to_id=claim_item_id,
                    occurred_at=occurred_at,
                    produced_by=_result_id(result),
                    interpretation=interpretation,
                    failed_gates=failed_gates if outcome == "failed" else [],
                    evidence_refs=evidence_refs,
                    signature=signature,
                )
            )
        if protocol_id:
            edges.append(
                _edge(
                    relation="tests",
                    from_id=run_id,
                    to_id=protocol_id,
                    occurred_at=occurred_at,
                    produced_by=_result_id(result),
                    interpretation=interpretation,
                    failed_gates=[],
                    evidence_refs=evidence_refs,
                    signature=signature,
                )
            )
        if outcome == "passed":
            for claim_item_id in claim_ids:
                edges.append(
                    _edge(
                        relation="supports",
                        from_id=run_id,
                        to_id=claim_item_id,
                        occurred_at=occurred_at,
                        produced_by=_result_id(result),
                        interpretation=interpretation,
                        failed_gates=[],
                        evidence_refs=evidence_refs,
                        signature=signature,
                    )
                )
        elif outcome == "failed":
            for claim_item_id in claim_ids:
                edges.append(
                    _edge(
                        relation="falsifies",
                        from_id=run_id,
                        to_id=claim_item_id,
                        occurred_at=occurred_at,
                        produced_by=_result_id(result),
                        interpretation=interpretation,
                        failed_gates=failed_gates,
                        evidence_refs=evidence_refs,
                        signature=signature,
                    )
                )
    return {
        "nodes": nodes,
        "edges": edges,
        "experimentSignature": signature,
        "occurredAt": occurred_at,
        "claimId": claim_id,
        "claimIds": claim_ids,
        "runId": run_id,
        "outcome": outcome,
    }


def record_duplicate_block(
    plan: dict[str, Any],
    *,
    occurred_at: str,
    signature: str = "",
    prior_run_id: str = "",
) -> dict[str, Any]:
    """Write a blocked run + duplicates edge without inventing a result record."""
    graph = normalize_outcome_graph(plan.get("outcomeGraph"))
    resolved_signature = signature or _experiment_signature(plan)
    digest = hashlib.sha256(f"{occurred_at}|{resolved_signature}".encode("utf-8")).hexdigest()[:12]
    blocked_id = f"run:dup:{digest}"
    graph["nodes"] = _upsert_nodes(
        graph["nodes"],
        [
            {
                "nodeId": blocked_id,
                "nodeKind": "experiment_run",
                "ref": {"planId": str(plan.get("planId") or ""), "resultId": ""},
                "summary": "Duplicate experiment signature blocked.",
                "outcome": "blocked",
                "occurredAt": occurred_at,
            }
        ],
    )
    target = prior_run_id or _latest_run_node_id(graph)
    if target and target != blocked_id:
        graph["edges"].append(
            _edge(
                relation="duplicates",
                from_id=blocked_id,
                to_id=target,
                occurred_at=occurred_at,
                produced_by="",
                interpretation="Same experimentSignature blocked from re-suggestion.",
                failed_gates=[],
                evidence_refs=[],
                signature=resolved_signature,
            )
        )
    plan["outcomeGraph"] = graph
    return graph


def project_outcome_memory(plans: list[dict[str, Any]]) -> dict[str, Any]:
    negatives: list[dict[str, Any]] = []
    successes: list[dict[str, Any]] = []
    forbidden: list[dict[str, Any]] = []
    graph_plan_ids: list[str] = []
    for plan in plans:
        if not plan_has_outcome_graph(plan):
            continue
        plan_id = str(plan.get("planId") or "")
        graph_plan_ids.append(plan_id)
        graph = normalize_outcome_graph(plan.get("outcomeGraph"))
        live = current_edges(graph)
        nodes_by_id = {str(node.get("nodeId") or ""): node for node in graph["nodes"]}
        signature = _experiment_signature(plan)
        for edge in live:
            relation = str(edge.get("relation") or "")
            if relation == "falsifies":
                negatives.append(_negative_from_edge(plan, edge, nodes_by_id, signature))
                forbidden.append(_forbidden_from_edge(plan, edge, signature, reason=str(edge.get("interpretation") or "")))
            elif relation == "supports":
                successes.append(_success_from_edge(plan, edge))
            elif relation == "duplicates":
                forbidden.append(
                    _forbidden_from_edge(
                        plan,
                        edge,
                        str(edge.get("experimentSignature") or signature),
                        reason=str(edge.get("interpretation") or "duplicate signature"),
                    )
                )
    negatives.sort(key=lambda item: str(item.get("validFrom") or ""))
    successes.sort(key=lambda item: str(item.get("recordedAt") or item.get("resultId") or ""))
    return {
        "usedGraph": bool(graph_plan_ids),
        "graphPlanIds": graph_plan_ids,
        "negativeExperiments": negatives[-MAX_NEGATIVE:],
        "priorSuccessfulRuns": successes[-MAX_SUCCESS:],
        "forbiddenDuplicateExperiments": _dedupe_forbidden(forbidden),
    }


def apply_graph_claim_flags(item: dict[str, Any], plan: dict[str, Any]) -> None:
    """Overlay working-layer edges onto a claim_map row. Does not grant qualified."""
    claim_id = str(item.get("claimId") or "")
    live = [
        edge
        for edge in current_edges(plan.get("outcomeGraph"))
        if str(edge.get("toId") or "") == claim_id
    ]
    for edge in live:
        relation = str(edge.get("relation") or "")
        refs = [ref for ref in list(edge.get("evidenceRefs") or []) if isinstance(ref, dict)]
        if relation == "supports":
            item["supportEvidenceRefs"] = _merge_refs(item.get("supportEvidenceRefs") or [], refs)
        elif relation == "falsifies":
            item["_unsupported"] = True
            item["counterEvidenceRefs"] = _merge_refs(item.get("counterEvidenceRefs") or [], refs)
            if _explicitly_rejects(edge):
                item["_explicitlyRejected"] = True


def build_working_outcome_overlay(plans: list[dict[str, Any]]) -> dict[str, Any]:
    """Read-only overlay of working-layer run nodes/edges. Does not touch candidate_only."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    for plan in plans:
        graph = normalize_outcome_graph(plan.get("outcomeGraph"))
        for node in graph["nodes"]:
            node_id = str(node.get("nodeId") or "")
            if not node_id or node_id in seen_nodes:
                continue
            seen_nodes.add(node_id)
            nodes.append(node)
        edges.extend(graph["edges"])
    return {"schemaVersion": SCHEMA_VERSION, "graphKind": "working_outcome", "nodes": nodes, "edges": edges}


def _apply_delta(graph: dict[str, Any], delta: dict[str, Any]) -> None:
    claim_ids = [str(item) for item in list(delta.get("claimIds") or []) if str(item)]
    if not claim_ids:
        claim_id = str(delta.get("claimId") or "")
        claim_ids = [claim_id] if claim_id else []
    outcome = str(delta.get("outcome") or "")
    graph["nodes"] = _upsert_nodes(graph["nodes"], list(delta.get("nodes") or []))
    if claim_ids and outcome in {"passed", "failed"}:
        close_relation = "falsifies" if outcome == "passed" else "supports"
        incoming_by_claim: dict[str, dict[str, Any]] = {}
        for item in list(delta.get("edges") or []):
            relation = str(item.get("relation") or "")
            if relation in {"supports", "falsifies"}:
                incoming_by_claim.setdefault(str(item.get("toId") or ""), item)
        for edge in graph["edges"]:
            to_id = str(edge.get("toId") or "")
            if (
                to_id in claim_ids
                and str(edge.get("relation") or "") == close_relation
                and str(edge.get("validUntil") or "").strip() == ""
            ):
                incoming = incoming_by_claim.get(to_id, {})
                edge["validUntil"] = str(delta.get("occurredAt") or "")
                edge["supersededByEdgeId"] = str(incoming.get("edgeId") or "")
    for edge in list(delta.get("edges") or []):
        graph["edges"].append(edge)


def _attach_cross_plan_duplicates(
    graph: dict[str, Any],
    plan: dict[str, Any],
    result: dict[str, Any],
    *,
    signature: str,
    occurred_at: str,
    peer_plans: list[dict[str, Any]],
) -> None:
    if not signature:
        return
    this_run = run_node_id(result)
    if not this_run:
        return
    seen_targets: set[str] = set()
    for other in peer_plans:
        if not isinstance(other, dict):
            continue
        if str(other.get("planId") or "") == str(plan.get("planId") or ""):
            continue
        other_signature = _experiment_signature(other)
        if other_signature != signature:
            continue
        target = ""
        if plan_has_outcome_graph(other):
            for edge in current_edges(other.get("outcomeGraph")):
                if str(edge.get("experimentSignature") or "") == signature:
                    target = str(edge.get("fromId") or "")
                    if target:
                        break
        if not target:
            target = run_node_id(_active_result(other))
        if not target or target == this_run or target in seen_targets:
            continue
        seen_targets.add(target)
        graph["edges"].append(
            _edge(
                relation="duplicates",
                from_id=this_run,
                to_id=target,
                occurred_at=occurred_at,
                produced_by=_result_id(result),
                interpretation="Same experimentSignature as a prior plan.",
                failed_gates=[],
                evidence_refs=_result_evidence_refs(result),
                signature=signature,
            )
        )


def _prune_to_result_window(graph: dict[str, Any], plan: dict[str, Any]) -> None:
    keep_result_ids = _result_window_ids(plan)
    if not keep_result_ids:
        return
    keep_run_ids = {f"run:{result_id}" for result_id in keep_result_ids}
    keep_run_ids.update(
        str(node.get("nodeId") or "")
        for node in graph["nodes"]
        if str(node.get("nodeKind") or "") == "experiment_run"
        and str(node.get("outcome") or "") == "blocked"
    )
    graph["edges"] = [
        edge
        for edge in graph["edges"]
        if str(edge.get("fromId") or "") in keep_run_ids
        or (
            str(edge.get("relation") or "") == "duplicates"
            and str(edge.get("fromId") or "").startswith("run:dup:")
        )
    ]
    referenced = {str(edge.get("fromId") or "") for edge in graph["edges"]}
    referenced.update(str(edge.get("toId") or "") for edge in graph["edges"])
    graph["nodes"] = [
        node
        for node in graph["nodes"]
        if str(node.get("nodeKind") or "") != "experiment_run"
        or str(node.get("nodeId") or "") in referenced
    ]


def _edge(
    *,
    relation: str,
    from_id: str,
    to_id: str,
    occurred_at: str,
    produced_by: str,
    interpretation: str,
    failed_gates: list[str],
    evidence_refs: list[dict[str, str]],
    signature: str,
) -> dict[str, Any]:
    digest = hashlib.sha256(
        f"{relation}|{from_id}|{to_id}|{produced_by}|{occurred_at}".encode("utf-8")
    ).hexdigest()[:12]
    return {
        "edgeId": f"edge-{digest}",
        "relation": relation,
        "fromId": from_id,
        "toId": to_id,
        "edgeState": "working_only",
        "validFrom": occurred_at,
        "validUntil": "",
        "supersededByEdgeId": "",
        "producedByEpisodeId": produced_by,
        "interpretation": interpretation,
        "failedGates": list(failed_gates),
        "evidenceRefs": list(evidence_refs),
        "experimentSignature": signature,
    }


def _upsert_nodes(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(node.get("nodeId") or ""): node for node in existing if str(node.get("nodeId") or "")}
    for node in incoming:
        node_id = str(node.get("nodeId") or "")
        if not node_id:
            continue
        by_id[node_id] = node
    return list(by_id.values())


def _outcome_for_status(status: str) -> str:
    if status == "passed":
        return "passed"
    if status == "blocked":
        return "blocked"
    return "failed"


def _interpretation(result: dict[str, Any], extra: dict[str, Any], status: str) -> str:
    text = _text(
        extra.get("interpretation")
        or result.get("interpretation")
        or result.get("notes")
        or result.get("delta")
        or extra.get("notes")
        or f"Experiment ended with {status or 'unknown'}.",
        600,
    )
    return text or f"Experiment ended with {status or 'unknown'}."


def _failed_gates(plan: dict[str, Any], extra: dict[str, Any], outcome: str) -> list[str]:
    if outcome != "failed":
        return []
    explicit = extra.get("failedGates")
    if isinstance(explicit, (list, tuple)):
        gates = [_text(item, 360) for item in explicit if _text(item, 360)]
        if gates:
            return gates[:8]
    contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
    decision = contract.get("decisionContract") if isinstance(contract.get("decisionContract"), dict) else {}
    gates = [_text(item, 360) for item in list(decision.get("failureCriteria") or []) if _text(item, 360)]
    return gates[:8] or ["failed"]


def _explicitly_rejects(edge: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            str(edge.get("interpretation") or ""),
            " ".join(str(item) for item in list(edge.get("failedGates") or [])),
        ]
    ).lower()
    return any(marker in haystack for marker in _EXPLICIT_REJECT_MARKERS)


def _plan_hypothesis(plan: dict[str, Any]) -> str:
    hypotheses = _plan_hypotheses(plan)
    return hypotheses[0] if hypotheses else ""


def _plan_hypotheses(plan: dict[str, Any]) -> list[str]:
    """Every selected hypothesis text; one claim node is written per entry."""
    selected = [item for item in list(plan.get("selectedHypotheses") or []) if isinstance(item, dict)]
    texts: list[str] = []
    for item in selected:
        text = _text(item.get("hypothesis"), 800)
        if text and claim_id_for_hypothesis(text) not in {claim_id_for_hypothesis(row) for row in texts}:
            texts.append(text)
    if texts:
        return texts
    contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
    fallback = _text(contract.get("researchQuestion"), 800)
    return [fallback] if fallback else []


def _protocol_id(plan: dict[str, Any]) -> str:
    contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
    for key in ("protocolId", "designId"):
        value = _text(contract.get(key), 160)
        if value:
            return value
    experiment_plan = plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
    value = _text(experiment_plan.get("protocolId"), 160)
    if value:
        return value
    plan_id = str(plan.get("planId") or "").strip()
    return f"protocol:{plan_id}" if plan_id else ""


def _experiment_signature(plan: dict[str, Any]) -> str:
    contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
    method_config = contract.get("methodConfig") if isinstance(contract.get("methodConfig"), dict) else {}
    keys = (
        "candidateMaskedLossWeight",
        "candidateLossMaskMode",
        "candidateMechanism",
        "candidateMaskSize",
    )
    changed = {key: method_config[key] for key in keys if key in method_config}
    payload = {
        "researchQuestion": _text(contract.get("researchQuestion"), 600).lower(),
        "hypothesisCandidateIds": sorted(_text_list(plan.get("hypothesisCandidateIds"), limit=16)),
        "changedVariable": changed,
        "constraints": _text_list(contract.get("constraints"), limit=12, max_length=240),
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _result_id(result: dict[str, Any]) -> str:
    return str(
        result.get("fullRunResultId")
        or result.get("smokeResultId")
        or result.get("evidenceId")
        or result.get("resultId")
        or ""
    )


def _result_evidence_refs(result: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    result_id = _result_id(result)
    if result_id:
        refs.append({"type": "experiment_result", "id": result_id})
    log_ref = _text(result.get("logRef"), 500)
    if log_ref:
        refs.append({"type": "experiment_log", "id": log_ref})
    result_path = _text(result.get("resultPath"), 500)
    if result_path:
        refs.append({"type": "experiment_artifact", "id": result_path})
    return refs[:6]


def _find_result(plan: dict[str, Any], result_id: str) -> dict[str, Any]:
    if not result_id:
        return {}
    for key in ("smokeResults", "fullRunResults"):
        for item in list(plan.get(key) or []):
            if isinstance(item, dict) and _result_id(item) == result_id:
                return item
    return _active_result(plan) if _result_id(_active_result(plan)) == result_id else {}


def _active_result(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    for key in ("activeFullRunResult", "activeSmokeResult"):
        value = plan.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _result_window_ids(plan: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("smokeResults", "fullRunResults"):
        for item in list(plan.get(key) or []):
            if not isinstance(item, dict):
                continue
            result_id = _result_id(item)
            if result_id:
                ids.add(result_id)
    return ids


def _latest_run_node_id(graph: dict[str, Any]) -> str:
    runs = [
        node
        for node in graph["nodes"]
        if str(node.get("nodeKind") or "") == "experiment_run" and str(node.get("outcome") or "") != "blocked"
    ]
    if not runs:
        return ""
    runs.sort(key=lambda item: str(item.get("occurredAt") or ""))
    return str(runs[-1].get("nodeId") or "")


def _negative_from_edge(
    plan: dict[str, Any],
    edge: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
    signature: str,
) -> dict[str, Any]:
    run = nodes_by_id.get(str(edge.get("fromId") or ""), {})
    result_id = str((run.get("ref") or {}).get("resultId") or edge.get("producedByEpisodeId") or "")
    contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
    method_config = contract.get("methodConfig") if isinstance(contract.get("methodConfig"), dict) else {}
    keys = (
        "candidateMaskedLossWeight",
        "candidateLossMaskMode",
        "candidateMechanism",
        "candidateMaskSize",
    )
    result = _find_result(plan, result_id)
    try:
        revision = max(0, int(contract.get("revision") or 0))
    except (TypeError, ValueError):
        revision = 0
    return {
        "planId": str(plan.get("planId") or ""),
        "revision": revision,
        "title": _text(plan.get("title"), 240),
        "status": str(plan.get("status") or "failed"),
        "hypothesis": _plan_hypothesis(plan),
        "changedVariable": {key: method_config[key] for key in keys if key in method_config},
        "fixedControls": _text_list(contract.get("constraints"), limit=12, max_length=360),
        "result": {
            "resultId": result_id,
            "status": str(result.get("status") or "failed"),
            "metricValue": _text(result.get("metricValue"), 240),
            "delta": _text(result.get("delta"), 360),
        },
        "failedGates": [_text(item, 360) for item in list(edge.get("failedGates") or []) if _text(item, 360)][:8],
        "interpretation": _text(edge.get("interpretation"), 600),
        "retestPolicy": "blocked_without_new_evidence_or_changed_assumption",
        "evidenceRefs": [ref for ref in list(edge.get("evidenceRefs") or []) if isinstance(ref, dict)][:6],
        "supersededBy": "",
        "candidateIds": _text_list(plan.get("hypothesisCandidateIds"), limit=16),
        "experimentSignature": str(edge.get("experimentSignature") or signature),
        "validFrom": str(edge.get("validFrom") or ""),
    }


def _success_from_edge(plan: dict[str, Any], edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "planId": str(plan.get("planId") or ""),
        "resultId": str(edge.get("producedByEpisodeId") or ""),
        "recordedAt": str(edge.get("validFrom") or ""),
        "candidateIds": _text_list(plan.get("hypothesisCandidateIds"), limit=16),
        "evidenceRefs": [ref for ref in list(edge.get("evidenceRefs") or []) if isinstance(ref, dict)][:6],
    }


def _forbidden_from_edge(
    plan: dict[str, Any],
    edge: dict[str, Any],
    signature: str,
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "planId": str(plan.get("planId") or ""),
        "experimentSignature": signature,
        "candidateIds": _text_list(plan.get("hypothesisCandidateIds"), limit=16),
        "reason": _text(reason, 600),
        "defaultAction": "exclude_from_suggestions",
        "retestPolicy": "blocked_without_new_evidence_or_changed_assumption",
        "evidenceRefs": [ref for ref in list(edge.get("evidenceRefs") or []) if isinstance(ref, dict)][:6],
    }


def _dedupe_forbidden(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in rows:
        key = (str(item.get("planId") or ""), str(item.get("experimentSignature") or ""))
        if key in seen:
            continue
        if not item.get("candidateIds") and not item.get("experimentSignature"):
            continue
        seen.add(key)
        result.append(item)
    return result


def _merge_refs(existing: list[dict[str, str]], incoming: list[dict[str, str]]) -> list[dict[str, str]]:
    merged = list(existing)
    seen = {(str(item.get("type") or ""), str(item.get("id") or "")) for item in merged}
    for item in incoming:
        key = (str(item.get("type") or ""), str(item.get("id") or ""))
        if not key[1] or key in seen:
            continue
        merged.append({"type": key[0], "id": key[1]})
        seen.add(key)
        if len(merged) >= 8:
            break
    return merged


def _text(value: Any, max_length: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_length]


def _text_list(value: Any, *, limit: int, max_length: int = 160) -> list[str]:
    if isinstance(value, str):
        rows = [value]
    elif isinstance(value, (list, tuple, set)):
        rows = list(value)
    else:
        rows = []
    result: list[str] = []
    for row in rows:
        text = _text(row, max_length)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result
