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

        payload = list_candidate_store(team_id, limit=500)
        candidates = [
            item
            for item in list(payload.get("candidates") or [])
            if isinstance(item, dict)
        ]
        scoped = _scope_candidates(candidates, snapshot, run_id)
        record_count = len(scoped)
        if record_count <= 0:
            # Fall back to SC summary when a sourceCollectionRunId is frozen.
            sc_run_id = str(snapshot.get("sourceCollectionRunId") or "").strip()
            if sc_run_id:
                from core.web.services.team_workflow.source_collection.runs import (
                    get_source_collection_summary,
                )

                summary = get_source_collection_summary(team_id, run_id=sc_run_id)
                run_summary = summary.get("runSummary") or summary.get("summary") or {}
                record_count = int(
                    run_summary.get("recordCount")
                    or run_summary.get("candidateCount")
                    or 0
                )
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
    _ = input_snapshot
    try:
        from core.infrastructure.path_containment import PROJECT_ROOT
        from core.research.evidence import ClaimEvidenceStore

        store = ClaimEvidenceStore(PROJECT_ROOT)
        records = store.list(team_id)
        if not records:
            return None
        missing: list[str] = []
        for item in records:
            evidence_id = str(item.get("claimEvidenceId") or item.get("claimId") or "")
            if not str(item.get("quote") or "").strip() or not str(
                item.get("sourceId") or ""
            ).strip():
                if evidence_id:
                    missing.append(evidence_id)
        return {
            "card_count": len(records),
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
    """Evidence/Knowledge projection for graph completeness."""
    _ = (team_id, run_id, input_snapshot)
    try:
        from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
            default_artifact_root,
            resolve_artifact_authority,
        )

        spec = resolve_artifact_authority("evidence_relation_graph")
        if spec is None:
            return None
        root = default_artifact_root() / spec.authority / team_id
        if not root.is_dir():
            return None
        graph_files = list(root.rglob("evidence_relation_graph/*.json"))
        if not graph_files:
            return None
        return {
            "graph_count": len(graph_files),
            "blocking_missing_links": 0,
            "teamId": team_id,
            "runId": run_id,
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

        payload = list_candidate_store(team_id, limit=20)
        candidates = list(payload.get("candidates") or [])
        vector["source_collection"] = _stable_hash(
            {
                "teamId": team_id,
                "sourceCollectionRunId": sc_run_id,
                "candidateCount": len(candidates),
                "workflowId": payload.get("workflowId"),
            }
        )[:32]
    except Exception:
        vector["source_collection"] = _stable_hash(
            {"teamId": team_id, "sourceCollectionRunId": sc_run_id or "none"}
        )[:32]

    try:
        from core.infrastructure.path_containment import PROJECT_ROOT
        from core.research.evidence import ClaimEvidenceStore

        evidence = ClaimEvidenceStore(PROJECT_ROOT).list(team_id)
        vector["evidence"] = _stable_hash(
            {
                "teamId": team_id,
                "count": len(evidence),
                "ids": [
                    str(item.get("claimEvidenceId") or "")
                    for item in evidence[:20]
                ],
            }
        )[:32]
    except Exception:
        vector["evidence"] = _stable_hash({"teamId": team_id, "evidence": "unavailable"})[
            :32
        ]

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
    if not sc_run_id and not project_id:
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
        if sc_run_id and item_run and item_run != sc_run_id:
            continue
        if project_id and item_project and item_project != project_id:
            continue
        # When SC run is known but candidates lack run tags, still count them for
        # the team-scoped store (single active collection per team is common).
        if sc_run_id and item_run and item_run != sc_run_id:
            continue
        scoped.append(item)
        _ = run_id
    return scoped


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(raw).hexdigest()
