"""Canonical Artifact kind → Domain Store read-back registry (T5.1-2).

Ledger receipts only store refs; this module is the sole read-back path for
production RealDomainPorts. Authority is the real Source Collection candidate
store, ClaimEvidenceStore, and SC graph records — never data/domain_artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from core.web.services.team_workflow.research_runtime.domain_ports import ArtifactReadBack
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
    canonical_sha256,
)

Authority = Literal[
    "source_collection",
    "evidence",
    "knowledge",
    "experiment",
    "promotion",
    "result_package",
    "workflow_system",
]


@dataclass(frozen=True)
class ArtifactAuthoritySpec:
    kind: str
    authority: Authority


ARTIFACT_AUTHORITY: dict[str, ArtifactAuthoritySpec] = {
    "problem_understanding": ArtifactAuthoritySpec("problem_understanding", "workflow_system"),
    "dimension_reviews": ArtifactAuthoritySpec("dimension_reviews", "experiment"),
    "feedback_iterations": ArtifactAuthoritySpec("feedback_iterations", "workflow_system"),
    "candidate_screening": ArtifactAuthoritySpec("candidate_screening", "workflow_system"),
    "core_hypothesis_coherence": ArtifactAuthoritySpec(
        "core_hypothesis_coherence", "workflow_system"
    ),
    "source_candidate_batch": ArtifactAuthoritySpec("source_candidate_batch", "source_collection"),
    "evidence_card_batch": ArtifactAuthoritySpec("evidence_card_batch", "source_collection"),
    "evidence_relation_graph": ArtifactAuthoritySpec("evidence_relation_graph", "evidence"),
    "knowledge_package_draft": ArtifactAuthoritySpec("knowledge_package_draft", "knowledge"),
    "knowledge_package": ArtifactAuthoritySpec("knowledge_package", "knowledge"),
    "hypothesis_set": ArtifactAuthoritySpec("hypothesis_set", "experiment"),
    "research_plan": ArtifactAuthoritySpec("research_plan", "experiment"),
    "stage1_research_plan": ArtifactAuthoritySpec(
        "stage1_research_plan", "workflow_system"
    ),
    "competition_alignment": ArtifactAuthoritySpec(
        "competition_alignment", "workflow_system"
    ),
    "stage_one_completion_manifest": ArtifactAuthoritySpec(
        "stage_one_completion_manifest", "workflow_system"
    ),
    "protocol_draft": ArtifactAuthoritySpec("protocol_draft", "experiment"),
    "protocol_review_report": ArtifactAuthoritySpec("protocol_review_report", "experiment"),
    "frozen_protocol": ArtifactAuthoritySpec("frozen_protocol", "experiment"),
    "smoke_evidence": ArtifactAuthoritySpec("smoke_evidence", "experiment"),
    "smoke_release": ArtifactAuthoritySpec("smoke_release", "experiment"),
    "run_artifacts": ArtifactAuthoritySpec("run_artifacts", "experiment"),
    "evaluation_report": ArtifactAuthoritySpec("evaluation_report", "experiment"),
    "iteration_decision": ArtifactAuthoritySpec("iteration_decision", "experiment"),
    "version_governance_record": ArtifactAuthoritySpec(
        "version_governance_record", "experiment"
    ),
    "promotion_proposal": ArtifactAuthoritySpec("promotion_proposal", "promotion"),
    "research_result_package": ArtifactAuthoritySpec(
        "research_result_package", "result_package"
    ),
    "delivery_orchestration_result": ArtifactAuthoritySpec(
        "delivery_orchestration_result", "workflow_system"
    ),
}


def resolve_artifact_authority(kind: str) -> ArtifactAuthoritySpec | None:
    return ARTIFACT_AUTHORITY.get(str(kind or "").strip())


def required_artifact_kinds(
    node_id: str,
    *,
    definition: Any,
) -> tuple[str, ...]:
    """Return produced kinds from the caller's already-pinned definition."""
    node = next(
        (
            item
            for item in definition.nodes
            if item.nodeId == node_id
        ),
        None,
    )
    if node is None:
        return ()
    return tuple(node.producesArtifactKinds)


def build_canonical_ref(
    *,
    kind: str,
    team_id: str,
    authority_run_id: str,
    content_hash: str,
) -> str:
    return f"{kind}://{team_id}/{authority_run_id}/{content_hash}"


def parse_canonical_ref(canonical_ref: str) -> dict[str, str] | None:
    text = str(canonical_ref or "").strip()
    if "://" not in text:
        # Legacy short form kind:prefix — not addressable without store lookup.
        if ":" in text:
            kind, identity = text.split(":", 1)
            if resolve_artifact_authority(kind) is None:
                return None
            return {"kind": kind, "identity": identity, "legacy": "1"}
        return None
    kind, rest = text.split("://", 1)
    if resolve_artifact_authority(kind) is None:
        return None
    parts = [p for p in rest.split("/") if p]
    if len(parts) < 3:
        return None
    team_id, authority_run_id, content_hash = parts[0], parts[1], parts[2]
    if len(content_hash) < 16:
        return None
    return {
        "kind": kind,
        "teamId": team_id,
        "authorityRunId": authority_run_id,
        "contentHash": content_hash,
    }


def materialize_domain_artifact(
    *,
    kind: str,
    payload: dict[str, Any],
    team_id: str,
    authority_run_id: str,
    root: Path | None = None,
    schema_version: str = "1.0.0",
) -> dict[str, str]:
    """Forbidden: parallel domain_artifacts store must not be written in production."""
    _ = (kind, payload, team_id, authority_run_id, root, schema_version)
    raise RuntimeError("parallel domain_artifacts store is forbidden")


def _scope_ids(item: dict[str, Any]) -> dict[str, str]:
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
    graph = meta.get("graph") if isinstance(meta.get("graph"), dict) else {}
    graph_summary = graph.get("summary") if isinstance(graph.get("summary"), dict) else {}
    return {
        "teamId": str(item.get("teamId") or "").strip(),
        "sourceCollectionRunId": str(
            item.get("sourceCollectionRunId")
            or meta.get("sourceCollectionRunId")
            or summary.get("sourceCollectionRunId")
            or graph_summary.get("sourceCollectionRunId")
            or ""
        ).strip(),
        "workflowRunId": str(
            item.get("workflowRunId")
            or meta.get("workflowRunId")
            or summary.get("workflowRunId")
            or ""
        ).strip(),
        "researchProjectId": str(
            item.get("researchProjectId") or meta.get("researchProjectId") or ""
        ).strip(),
    }


def _matches_collect_scope(
    item: dict[str, Any],
    *,
    team_id: str,
    source_collection_run_id: str,
    workflow_run_id: str,
) -> bool:
    ids = _scope_ids(item)
    if ids["teamId"] and ids["teamId"] != team_id:
        return False
    sc = ids["sourceCollectionRunId"]
    wf = ids["workflowRunId"]
    # Unscoped historical records must never be counted for a run.
    if not sc and not wf:
        return False
    if source_collection_run_id and sc and sc != source_collection_run_id:
        return False
    if workflow_run_id and wf and wf != workflow_run_id:
        return False
    matched = False
    if source_collection_run_id and sc == source_collection_run_id:
        matched = True
    if workflow_run_id and wf == workflow_run_id:
        matched = True
    return matched


def _matches_authority_scope(
    item: dict[str, Any],
    *,
    team_id: str,
    authority_run_id: str,
) -> bool:
    ids = _scope_ids(item)
    if ids["teamId"] and ids["teamId"] != team_id:
        return False
    sc = ids["sourceCollectionRunId"]
    wf = ids["workflowRunId"]
    if not sc and not wf:
        return False
    return authority_run_id in {sc, wf}


def _records_pass_strict_scope(
    records: list[dict[str, Any]],
    *,
    team_id: str,
    authority_run_id: str,
) -> bool:
    for item in records:
        ids = _scope_ids(item)
        if ids["teamId"] and ids["teamId"] != team_id:
            return False
        sc = ids["sourceCollectionRunId"]
        wf = ids["workflowRunId"]
        if sc and sc != authority_run_id and wf != authority_run_id:
            return False
        if wf and wf != authority_run_id and sc != authority_run_id:
            return False
        if not sc and not wf:
            return False
        if authority_run_id not in {sc, wf}:
            return False
    return True


def _load_scoped_candidates(
    *,
    team_id: str,
    authority_run_id: str,
    workflow_run_id: str = "",
) -> list[dict[str, Any]] | None:
    from core.web.services.team_workflow.source_collection.candidates import (
        list_candidate_store,
    )

    try:
        payload = list_candidate_store(team_id, limit=500, run_id=authority_run_id)
    except Exception:
        return None
    candidates = [
        item
        for item in list(payload.get("candidates") or [])
        if isinstance(item, dict)
        and str(item.get("candidateType") or "") != "candidate_graph"
        and _matches_collect_scope(
            item,
            team_id=team_id,
            source_collection_run_id=authority_run_id,
            workflow_run_id=workflow_run_id,
        )
    ]
    if not _records_pass_strict_scope(
        candidates, team_id=team_id, authority_run_id=authority_run_id
    ):
        return None
    return sorted(
        candidates,
        key=lambda item: str(item.get("candidateId") or item.get("sourceUrl") or ""),
    )


def _load_scoped_evidence(
    *,
    team_id: str,
    authority_run_id: str,
    workflow_run_id: str = "",
) -> list[dict[str, Any]] | None:
    from core.infrastructure.path_containment import PROJECT_ROOT
    from core.research.evidence import ClaimEvidenceStore

    try:
        records = ClaimEvidenceStore(PROJECT_ROOT).list(team_id)
    except Exception:
        return None
    scoped = [
        item
        for item in records
        if isinstance(item, dict)
        and _matches_collect_scope(
            item,
            team_id=team_id,
            source_collection_run_id=authority_run_id,
            workflow_run_id=workflow_run_id,
        )
    ]
    if not scoped:
        return None
    if not _records_pass_strict_scope(
        scoped, team_id=team_id, authority_run_id=authority_run_id
    ):
        return None
    return sorted(
        scoped,
        key=lambda item: str(item.get("claimEvidenceId") or item.get("claimId") or ""),
    )


def _load_scoped_relation_graph(
    *,
    team_id: str,
    authority_run_id: str,
    workflow_run_id: str = "",
) -> dict[str, Any]:
    from core.web.services.team_workflow.source_collection.candidates import (
        list_candidate_store,
    )

    empty = {
        "nodes": [],
        "edges": [],
        "summary": {
            "teamId": team_id,
            "sourceCollectionRunId": authority_run_id,
            "workflowRunId": workflow_run_id,
        },
        "teamId": team_id,
        "sourceCollectionRunId": authority_run_id,
        "workflowRunId": workflow_run_id,
    }
    try:
        payload = list_candidate_store(
            team_id,
            candidate_type="candidate_graph",
            limit=500,
            run_id=authority_run_id,
        )
    except Exception:
        # Fall back to SC summary metrics when the graph store is unavailable.
        try:
            from core.web.services.team_workflow.source_collection.runs import (
                get_source_collection_summary,
            )

            summary = get_source_collection_summary(team_id, run_id=authority_run_id)
            run_summary = summary.get("runSummary") or summary.get("summary") or {}
            node_count = int(run_summary.get("graphNodeCount") or 0)
            if node_count <= 0:
                return empty
            empty["summary"]["graphNodeCount"] = node_count
            empty["summary"]["from"] = "source_collection_summary"
            return empty
        except Exception:
            return empty

    graphs = [
        item
        for item in list(payload.get("candidates") or [])
        if isinstance(item, dict)
        and _matches_collect_scope(
            item,
            team_id=team_id,
            source_collection_run_id=authority_run_id,
            workflow_run_id=workflow_run_id,
        )
    ]
    if not graphs:
        return empty
    if not _records_pass_strict_scope(
        graphs, team_id=team_id, authority_run_id=authority_run_id
    ):
        return empty
    latest = max(
        graphs,
        key=lambda item: (
            str(item.get("updatedAt") or ""),
            str(item.get("createdAt") or ""),
            str(item.get("candidateId") or ""),
        ),
    )
    meta = latest.get("metadata") if isinstance(latest.get("metadata"), dict) else {}
    graph = meta.get("graph") if isinstance(meta.get("graph"), dict) else {}
    if not graph:
        return empty
    return {
        "nodes": list(graph.get("nodes") or []),
        "edges": list(graph.get("edges") or []),
        "missingLinks": list(graph.get("missingLinks") or []),
        "summary": dict(graph.get("summary") or {}),
        "teamId": team_id,
        "sourceCollectionRunId": authority_run_id,
        "workflowRunId": workflow_run_id,
        "candidateGraphId": str(latest.get("candidateId") or ""),
    }


def load_scoped_artifact_payload(
    kind: str,
    *,
    team_id: str,
    authority_run_id: str,
    workflow_run_id: str = "",
    content_hash: str = "",
    record_id: str = "",
) -> dict[str, Any] | None:
    """Load a deterministic scoped payload for hashing / read-back.

    Returns None when the kind is unknown, unwired to a store authority, or
    store records violate team/run scope.  ``record_id`` optionally pins the
    read to one immutable artifact identity (e.g. the Ledger-authoritative
    node attempt) instead of the latest record in scope.
    """
    normalized_kind = str(kind or "").strip()
    if resolve_artifact_authority(normalized_kind) is None:
        return None
    normalized_team = str(team_id or "").strip()
    normalized_authority = str(authority_run_id or "").strip()
    normalized_workflow = str(workflow_run_id or "").strip()
    if not normalized_team or not normalized_authority:
        return None

    if normalized_kind == "source_candidate_batch":
        candidates = _load_scoped_candidates(
            team_id=normalized_team,
            authority_run_id=normalized_authority,
            workflow_run_id=normalized_workflow,
        )
        if candidates is None:
            return None
        # Hash envelope keys stay authority-stable so collect/read hashes match
        # even when workflow_run_id is only used as a filter.
        return {
            "teamId": normalized_team,
            "sourceCollectionRunId": normalized_authority,
            "candidates": candidates,
            "candidateCount": len(candidates),
        }

    if normalized_kind == "evidence_card_batch":
        cards = _load_scoped_evidence(
            team_id=normalized_team,
            authority_run_id=normalized_authority,
            workflow_run_id=normalized_workflow,
        )
        if cards is None:
            return None
        return {
            "teamId": normalized_team,
            "sourceCollectionRunId": normalized_authority,
            "evidenceCards": cards,
            "cardCount": len(cards),
        }

    if normalized_kind == "evidence_relation_graph":
        graph = _load_scoped_relation_graph(
            team_id=normalized_team,
            authority_run_id=normalized_authority,
            workflow_run_id=normalized_workflow,
        )
        return {
            "teamId": normalized_team,
            "sourceCollectionRunId": normalized_authority,
            "nodes": list(graph.get("nodes") or []),
            "edges": list(graph.get("edges") or []),
            "missingLinks": list(graph.get("missingLinks") or []),
            "summary": dict(graph.get("summary") or {}),
            "candidateGraphId": str(graph.get("candidateGraphId") or ""),
        }

    if normalized_kind == "knowledge_package_draft":
        from .knowledge_artifact_authority import load_knowledge_package_draft_payload

        return load_knowledge_package_draft_payload(
            team_id=normalized_team,
            authority_run_id=normalized_authority,
            workflow_run_id=normalized_workflow,
            content_hash=content_hash,
        )

    if normalized_kind == "knowledge_package":
        from .knowledge_artifact_authority import load_knowledge_package_payload

        return load_knowledge_package_payload(
            team_id=normalized_team,
            authority_run_id=normalized_authority,
            workflow_run_id=normalized_workflow,
            content_hash=content_hash,
        )

    # Experiment / result-package / smoke kinds: formal workflow_artifact_store.
    if normalized_kind in {
        "run_artifacts",
        "research_result_package",
        "smoke_evidence",
        "smoke_release",
        "frozen_protocol",
        "evaluation_report",
        "hypothesis_set",
        "research_plan",
        "stage1_research_plan",
        "competition_alignment",
        "stage_one_completion_manifest",
        "protocol_draft",
        "protocol_review_report",
        "iteration_decision",
        "version_governance_record",
        "delivery_orchestration_result",
        "problem_understanding",
        "dimension_reviews",
        "feedback_iterations",
        "candidate_screening",
        "core_hypothesis_coherence",
    }:
        from .workflow_artifact_store import load_workflow_artifact_payload

        return load_workflow_artifact_payload(
            normalized_kind,
            team_id=normalized_team,
            authority_run_id=normalized_authority,
            workflow_run_id=normalized_workflow,
            content_hash=content_hash,
            record_id=record_id,
        )

    # Other kinds are not yet wired to a production store authority.
    # Never invent empty records / hashes for unwired kinds — that would make
    # forged or missing team/run refs look like successful read-back.
    return None


def read_domain_artifact(
    canonical_ref: str,
    *,
    root: Path | None = None,
) -> ArtifactReadBack | None:
    """Read-back from the unique domain authority for the artifact kind."""
    _ = root  # parallel file store is forbidden; root is ignored
    parsed = parse_canonical_ref(canonical_ref)
    if parsed is None:
        return None
    if parsed.get("legacy") == "1":
        return None
    kind = parsed["kind"]
    team_id = parsed["teamId"]
    authority_run_id = parsed["authorityRunId"]
    content_hash = parsed["contentHash"]
    payload = load_scoped_artifact_payload(
        kind,
        team_id=team_id,
        authority_run_id=authority_run_id,
        workflow_run_id="",
        content_hash=content_hash,
    )
    if payload is None:
        return None
    # Extra forge guard: every record in the payload must match ref team/run.
    records: list[dict[str, Any]] = []
    if kind == "source_candidate_batch":
        records = [item for item in list(payload.get("candidates") or []) if isinstance(item, dict)]
    elif kind == "evidence_card_batch":
        records = [
            item for item in list(payload.get("evidenceCards") or []) if isinstance(item, dict)
        ]
    if records and not _records_pass_strict_scope(
        records, team_id=team_id, authority_run_id=authority_run_id
    ):
        return None
    recomputed = canonical_sha256(payload)
    if recomputed != content_hash:
        return None
    schema_version = "1.0.0"
    domain_revision = canonical_sha256(
        {
            "kind": kind,
            "teamId": team_id,
            "authorityRunId": authority_run_id,
            "contentHash": content_hash,
            "schemaVersion": schema_version,
        }
    )[:32]
    return ArtifactReadBack(
        canonical_ref=build_canonical_ref(
            kind=kind,
            team_id=team_id,
            authority_run_id=authority_run_id,
            content_hash=content_hash,
        ),
        version=schema_version,
        content_hash=content_hash,
        domain_revision=domain_revision,
    )
