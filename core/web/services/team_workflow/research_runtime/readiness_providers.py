"""Real domain readiness providers (T5.1-3).

Each provider queries a single domain authority. RealDomainReadinessContext
delegates here; service_overrides remain unit-test only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def fetch_candidate_stats(
    team_id: str,
    run_id: str,
    *,
    input_snapshot: Mapping[str, Any] | None = None,
) -> Mapping[str, Any] | None:
    """Source Collection authority: candidate/record counts for extraction readiness."""
    snapshot = dict(input_snapshot or {})
    try:
        from core.web.services.team_workflow.source_collection.candidates import (
            list_candidate_store,
        )

        sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
        # Scoped runs must also see candidates stored under the SC run owner
        # project, not only the active project store.
        payload = list_candidate_store(team_id, limit=500, run_id=sc_run_id)
        candidates = [
            item
            for item in list(payload.get("candidates") or [])
            if isinstance(item, dict)
        ]
        scoped = _scope_candidates(candidates, snapshot, run_id)
        record_count = len(scoped)
        if record_count <= 0 and sc_run_id:
            # Fall back to the data_processing record authority for the frozen
            # sourceCollectionRunId. get_source_collection_summary is gated on
            # the *active* research project and raises when the run owner
            # project differs, which silently zeroed scoped runs; the global
            # data_processing run store is the record-count authority.
            from core.web.services import data_processing_service

            status = data_processing_service.get_processing_status(sc_run_id)
            status_summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
            record_count = int(status_summary.get("recordCount") or 0)
        if record_count <= 0:
            return None
        return {
            "record_count": record_count,
            "candidate_count": record_count,
            "teamId": team_id,
            "runId": run_id,
        }
    except Exception:
        return None


def fetch_evidence_cards_stats(
    team_id: str,
    run_id: str,
    *,
    input_snapshot: Mapping[str, Any] | None = None,
) -> Mapping[str, Any] | None:
    """Evidence Store authority: claim evidence cards for relations readiness."""
    snapshot = dict(input_snapshot or {})
    try:
        from core.infrastructure.path_containment import PROJECT_ROOT
        from core.research.evidence import ClaimEvidenceStore

        store = ClaimEvidenceStore(PROJECT_ROOT)
        records = store.list(team_id)
        if not records:
            return None
        scoped = _scope_evidence_records(records, snapshot, run_id)
        if not scoped:
            return None
        missing: list[str] = []
        for item in scoped:
            evidence_id = str(item.get("claimEvidenceId") or item.get("claimId") or "")
            if not str(item.get("quote") or "").strip() or not str(
                item.get("sourceId") or ""
            ).strip():
                if evidence_id:
                    missing.append(evidence_id)
        return {
            "card_count": len(scoped),
            "missing_minimal_fields": missing,
            "teamId": team_id,
            "runId": run_id,
        }
    except Exception:
        return None


def fetch_evidence_graph_stats(
    team_id: str,
    run_id: str,
    *,
    input_snapshot: Mapping[str, Any] | None = None,
) -> Mapping[str, Any] | None:
    """Read graph completeness from the scoped artifact authority only."""
    snapshot = dict(input_snapshot or {})
    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    if not sc_run_id:
        return None
    try:
        from .artifact_readback_registry import (
            load_scoped_artifact_payload,
        )

        graph = load_scoped_artifact_payload(
            "evidence_relation_graph",
            team_id=team_id,
            authority_run_id=sc_run_id,
            workflow_run_id=run_id,
        )
        if not isinstance(graph, dict):
            return None
        nodes = list(graph.get("nodes") or [])
        edges = list(graph.get("edges") or [])
        if not nodes and not edges:
            return None
        missing_links = list(graph.get("missingLinks") or [])
        summary = graph.get("summary") if isinstance(graph.get("summary"), dict) else {}
        missing_link_count = max(
            len(missing_links),
            int(summary.get("missingLinkCount") or 0),
        )
        waiver_count = max(
            int(summary.get("waiverCount") or 0),
            sum(
                1
                for item in missing_links
                if isinstance(item, dict)
                and (
                    bool(item.get("waived"))
                    or str(item.get("status") or "").strip().lower()
                    in {"waived", "accepted"}
                    or isinstance(item.get("waiver"), dict)
                )
            ),
        )
        return {
            "graph_count": 1,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "missing_link_count": missing_link_count,
            "waiver_count": waiver_count,
            "teamId": team_id,
            "runId": run_id,
            "sourceCollectionRunId": sc_run_id,
        }
    except Exception:
        return None


def is_agent_resolvable(agent_id: str) -> bool:
    """Agent Directory authority: agent exists and is not archived."""
    text = str(agent_id or "").strip()
    if not text:
        return False
    try:
        from core.web.services.agent_directory_service import get_agent

        agent = get_agent(text, include_archived=False)
        if not isinstance(agent, dict):
            return False
        status = str(agent.get("status") or agent.get("lifecycleStatus") or "").lower()
        if status in {"archived", "disabled", "deleted"}:
            return False
        return str(agent.get("id") or agent.get("agentId") or "").strip() == text
    except Exception:
        return False


def build_domain_revision_vector(
    team_id: str,
    run_id: str,
    *,
    input_snapshot: Mapping[str, Any] | None = None,
    ledger_store: Any | None = None,
) -> dict[str, str]:
    """Compose a non-empty revision vector from reachable domain authorities."""
    snapshot = dict(input_snapshot or {})
    vector: dict[str, str] = {}

    # Frozen input snapshot itself is a revision anchor.
    snapshot_hash = str(snapshot.get("snapshotHash") or "").strip()
    if snapshot_hash:
        vector["input_snapshot"] = snapshot_hash
    elif snapshot:
        vector["input_snapshot"] = _stable_hash(snapshot)[:32]

    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    try:
        from core.web.services.team_workflow.source_collection.candidates import (
            list_candidate_store,
        )

        # Match fetch_candidate_stats: load broadly (including the SC run
        # owner-project store), then scope to SC/workflow run.
        payload = list_candidate_store(team_id, limit=500, run_id=sc_run_id)
        candidates = [
            item
            for item in list(payload.get("candidates") or [])
            if isinstance(item, dict)
        ]
        scoped_candidates = _scope_candidates(candidates, snapshot, run_id)
        vector["source_collection"] = _stable_hash(
            {
                "teamId": team_id,
                "sourceCollectionRunId": sc_run_id,
                "workflowRunId": run_id,
                "candidateCount": len(scoped_candidates),
                "candidateIds": [
                    str(item.get("candidateId") or item.get("id") or "")
                    for item in scoped_candidates[:20]
                ],
                "workflowId": payload.get("workflowId"),
            }
        )[:32]
    except Exception:
        vector["source_collection"] = _stable_hash(
            {
                "teamId": team_id,
                "sourceCollectionRunId": sc_run_id or "none",
                "workflowRunId": run_id,
            }
        )[:32]

    try:
        from core.infrastructure.path_containment import PROJECT_ROOT
        from core.research.evidence import ClaimEvidenceStore

        evidence = ClaimEvidenceStore(PROJECT_ROOT).list(team_id)
        scoped_evidence = _scope_evidence_records(evidence, snapshot, run_id)
        vector["evidence"] = _stable_hash(
            {
                "teamId": team_id,
                "sourceCollectionRunId": sc_run_id,
                "workflowRunId": run_id,
                "count": len(scoped_evidence),
                "ids": [
                    str(item.get("claimEvidenceId") or item.get("claimId") or "")
                    for item in scoped_evidence[:20]
                ],
            }
        )[:32]
    except Exception:
        vector["evidence"] = _stable_hash(
            {
                "teamId": team_id,
                "workflowRunId": run_id,
                "evidence": "unavailable",
            }
        )[:32]

    if ledger_store is not None:
        try:
            rows = ledger_store.submit(
                lambda uow: uow.repository.execute(
                    "SELECT artifact_kind, sha256, domain_revision "
                    "FROM artifact_receipts WHERE run_id = ? "
                    "ORDER BY created_at_ms DESC LIMIT 50",
                    (run_id,),
                ).fetchall(),
                force_flush=True,
            ).result(timeout=10)
            if rows:
                vector["artifact_receipts"] = _stable_hash(
                    [(str(r[0]), str(r[1]), str(r[2])) for r in rows]
                )[:32]
        except Exception:
            pass

    if not vector:
        vector["workflow_ledger"] = _stable_hash({"teamId": team_id, "runId": run_id})[:32]
    return vector


def _scope_candidates(
    candidates: list[dict[str, Any]],
    snapshot: Mapping[str, Any],
    run_id: str,
) -> list[dict[str, Any]]:
    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    project_id = str(snapshot.get("projectId") or "").strip()
    run_id = str(run_id or "").strip()
    # Without any expected run/project scope, leave the team store untouched.
    if not sc_run_id and not project_id and not run_id:
        return candidates
    scoped: list[dict[str, Any]] = []
    for item in candidates:
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        item_run = str(
            item.get("sourceCollectionRunId")
            or meta.get("sourceCollectionRunId")
            or item.get("runId")
            or ""
        ).strip()
        item_project = str(
            item.get("researchProjectId") or meta.get("researchProjectId") or ""
        ).strip()
        item_workflow = str(
            item.get("workflowRunId") or meta.get("workflowRunId") or ""
        ).strip()
        # Unscoped historical candidates (no SC / workflow run markers) must never
        # unlock or inflate stats for a run that expects SC or workflow scope.
        if (sc_run_id or run_id) and not item_run and not item_workflow:
            continue
        if sc_run_id and item_run and item_run != sc_run_id:
            continue
        if project_id and item_project and item_project != project_id:
            continue
        if item_workflow and item_workflow != run_id:
            continue
        if sc_run_id:
            if item_run != sc_run_id and item_workflow != run_id:
                continue
        elif run_id and item_workflow != run_id:
            continue
        scoped.append(item)
    return scoped


def _scope_evidence_records(
    records: list[Any],
    snapshot: Mapping[str, Any],
    run_id: str,
) -> list[dict[str, Any]]:
    """Scope evidence cards by sourceCollectionRunId / workflowRunId like fetch_*."""
    sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
    scoped: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        item_run = str(item.get("sourceCollectionRunId") or "").strip()
        item_workflow = str(item.get("workflowRunId") or "").strip()
        # Unscoped historical evidence must never unlock a scoped run.
        if (sc_run_id or run_id) and not item_run and not item_workflow:
            continue
        if sc_run_id and item_run and item_run != sc_run_id:
            continue
        if item_workflow and item_workflow != run_id:
            continue
        # Require explicit scope for this workflow or SC run.
        if sc_run_id:
            if item_run != sc_run_id and item_workflow != run_id:
                continue
        elif item_workflow != run_id:
            continue
        scoped.append(item)
    return scoped


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(raw).hexdigest()
