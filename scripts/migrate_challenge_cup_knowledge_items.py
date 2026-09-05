"""Replace the legacy Challenge Cup aggregate knowledge packs with one item per source.

Dry-run is the default.  Apply is intentionally private to this maintenance
command: the product does not expose a general KnowledgeItem deletion API.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.chatroom.store import utc_now_iso
from core.web.services import rag_vector_index_service, team_knowledge_service


LEGACY_TITLE = "神经算法资料入库包"
EXPECTED_LEGACY_COUNT = 5
EXPECTED_SOURCE_COUNT = 33
MIGRATION_ACTION = "challenge_cup.knowledge_items.migrated"
TERMINAL_ACTION = "challenge_cup.knowledge_migration.completed"
DIRECT_INGEST_ACTION = "knowledge.item.direct_ingested"
PURGE_TERMINAL_ACTION = "challenge_cup.legacy_knowledge_purge.completed"
_CANDIDATE_TAGS = {"pending-review", "pending_review", "candidate-only", "candidate_only"}


class ChallengeCupKnowledgeMigrationError(RuntimeError):
    pass


def _stable_id(prefix: str, migration_id: str, source_candidate_id: str) -> str:
    digest = hashlib.sha256(f"{migration_id}\0{source_candidate_id}\0{prefix}".encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _content_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return team_knowledge_service._read_jsonl(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _candidate_title(candidate: dict[str, Any]) -> str:
    return str(candidate.get("title") or candidate.get("sourceUrl") or candidate.get("candidateId") or "").strip()


def _candidate_identity_hash(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    explicit = str(metadata.get("sourceIdentityHash") or "").strip()
    if explicit:
        return explicit
    identity = str(
        metadata.get("sourceIdentityKey")
        or candidate.get("sourceUrl")
        or candidate.get("sourcePath")
        or candidate.get("candidateId")
        or ""
    ).strip()
    return "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _candidate_evidence_level(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    levels = metadata.get("evidenceLevels") if isinstance(metadata.get("evidenceLevels"), list) else []
    return str(
        candidate.get("evidenceLevel")
        or metadata.get("evidenceLevel")
        or (levels[0] if levels else "")
        or candidate.get("qualityStatus")
        or ""
    ).strip()


def _proposal_payload(proposal: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(str(proposal.get("content") or ""))
    except json.JSONDecodeError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _proposal_mentions_candidate(proposal: dict[str, Any], candidate_id: str) -> bool:
    return candidate_id in json.dumps(_proposal_payload(proposal), ensure_ascii=False, sort_keys=True)


def _source_content(proposal: dict[str, Any], candidate: dict[str, Any]) -> str:
    candidate_id = str(candidate.get("candidateId") or "").strip()
    old = _proposal_payload(proposal)
    claims = [
        deepcopy(claim)
        for claim in list(old.get("claims") or [])
        if isinstance(claim, dict)
        and str(claim.get("sourceRef") or claim.get("sourceCandidateId") or "").strip() == candidate_id
    ]
    if not claims:
        claims = [{"claim": str(candidate.get("summary") or _candidate_title(candidate)), "sourceRef": candidate_id}]
    source_url = str(candidate.get("sourceUrl") or "").strip()
    payload = {
        "proposalPayload": {
            "title": _candidate_title(candidate),
            "summary": str(candidate.get("summary") or "").strip(),
        },
        "claims": claims,
        "sourceTrace": {
            "sourceCandidateIds": [candidate_id],
            "sourceUrl": source_url,
        },
        "evidenceRefs": list(candidate.get("evidenceRefs") or []),
        "approvalRequired": True,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _recover_candidate_from_data_record(
    *,
    workspace_root: Path,
    team_id: str,
    candidate_id: str,
    source_collection_run_id: str,
    content_source: dict[str, Any],
    projects_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    run_root = workspace_root / "data_processing" / "runs" / source_collection_run_id
    run_path = run_root / "run.json"
    records_path = run_root / "records.jsonl"
    assignments_path = run_root / "collection_assignments.jsonl"
    if not run_path.is_file() or not records_path.is_file() or not assignments_path.is_file():
        raise ChallengeCupKnowledgeMigrationError(
            f"Source {candidate_id} has no complete authoritative DataRecord run artifacts."
        )

    run = _read_json(run_path)
    if str(run.get("runId") or "").strip() != source_collection_run_id:
        raise ChallengeCupKnowledgeMigrationError(f"Source {candidate_id} DataRecord run identity does not match its lineage.")
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    run_team_id = str(run_scope.get("teamId") or run_metadata.get("teamId") or "").strip()
    research_project_id = str(
        run_scope.get("researchProjectId") or run_metadata.get("researchProjectId") or ""
    ).strip()
    run_question_id = str(run_scope.get("questionId") or run_metadata.get("questionId") or "").strip()
    project = projects_by_id.get(research_project_id) or {}
    project_question_id = str(project.get("challengeQuestionId") or project.get("questionId") or "").strip()
    if run_team_id != team_id or not research_project_id or not project_question_id or run_question_id != project_question_id:
        raise ChallengeCupKnowledgeMigrationError(
            f"Source {candidate_id} DataRecord run has conflicting team, project, or question scope."
        )

    claims = [
        claim
        for claim in list(_proposal_payload(content_source).get("claims") or [])
        if isinstance(claim, dict)
        and str(claim.get("sourceRef") or claim.get("sourceCandidateId") or "").strip() == candidate_id
    ]
    claim_texts = [str(claim.get("claim") or claim.get("fact") or "").strip() for claim in claims]
    if len(claim_texts) != 1 or not claim_texts[0]:
        raise ChallengeCupKnowledgeMigrationError(
            f"Source {candidate_id} requires exactly one legacy claim for DataRecord recovery."
        )
    matching_records = [
        record
        for record in _read_jsonl(records_path)
        if str(record.get("runId") or "").strip() == source_collection_run_id
        and str(record.get("summary") or "").strip() == claim_texts[0]
    ]
    if len(matching_records) != 1:
        raise ChallengeCupKnowledgeMigrationError(
            f"Source {candidate_id} requires one unique matching DataRecord, found {len(matching_records)}."
        )
    record = matching_records[0]
    record_id = str(record.get("recordId") or "").strip()
    title = str(record.get("title") or "").strip()
    source_url = str(record.get("sourceRef") or record.get("rawLocation") or "").strip()
    record_metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    quality_signals = record.get("qualitySignals") if isinstance(record.get("qualitySignals"), dict) else {}
    collection_trace = record.get("collectionTrace") if isinstance(record.get("collectionTrace"), dict) else {}
    source_identity_key = str(
        record_metadata.get("sourceIdentityKey") or quality_signals.get("sourceIdentityKey") or ""
    ).strip()
    source_agent_id = str(
        collection_trace.get("agentId") or record_metadata.get("sourceCollectionStageAgentId") or ""
    ).strip()
    assignment_agent_ids = {
        str(assignment.get("agentId") or "").strip()
        for assignment in _read_jsonl(assignments_path)
        if str(assignment.get("agentId") or "").strip()
    }
    if not record_id or not title or not source_url.startswith("https://") or not source_identity_key:
        raise ChallengeCupKnowledgeMigrationError(
            f"Source {candidate_id} matching DataRecord lacks title, https URL, record identity, or source identity."
        )
    if not source_agent_id or source_agent_id not in assignment_agent_ids:
        raise ChallengeCupKnowledgeMigrationError(
            f"Source {candidate_id} matching DataRecord has no trusted run-assigned source Agent."
        )

    imported_from = {
        "runId": source_collection_run_id,
        "recordId": record_id,
        "profileId": str(run.get("profileId") or "").strip(),
        "sourceType": str(record.get("sourceType") or "").strip(),
        "sourceRef": source_url,
        "title": title,
        "sourceIdentityKey": source_identity_key,
    }
    return {
        "candidateId": candidate_id,
        "candidateType": "source_manifest",
        "teamId": team_id,
        "title": title,
        "summary": claim_texts[0],
        "sourceUrl": source_url,
        "sourcePath": "",
        "sourceKind": str(record.get("sourceType") or "unknown").strip() or "unknown",
        "createdByAgent": source_agent_id,
        "qualityStatus": "source_quality_approved",
        "evidenceRefs": [
            {"type": "data_record", "id": record_id, "label": title},
            {
                "type": "data_processing_run",
                "id": source_collection_run_id,
                "label": str(run.get("title") or source_collection_run_id).strip(),
            },
        ],
        "metadata": {
            "researchProjectId": research_project_id,
            "sourceCollectionRunId": source_collection_run_id,
            "sourceIdentityKey": source_identity_key,
            "sourceRecordId": record_id,
            "importedFromDataRecord": imported_from,
            "migrationRecovery": {
                "sourceCollectionRunId": source_collection_run_id,
                "sourceRecordId": record_id,
            },
        },
        "createdAt": str(record.get("createdAt") or "").strip(),
        "updatedAt": str(record.get("updatedAt") or record.get("createdAt") or "").strip(),
    }


def _knowledge_manager_id(team: dict[str, Any]) -> str:
    matches = [
        str(member.get("agentId") or "").strip()
        for member in list(team.get("members") or [])
        if isinstance(member, dict)
        and str(member.get("roleKey") or member.get("role") or "").strip() == "challenge_cup_knowledge_manager"
        and str(member.get("agentId") or "").strip()
    ]
    if len(matches) != 1:
        raise ChallengeCupKnowledgeMigrationError("Expected exactly one bound challenge_cup_knowledge_manager Agent.")
    return matches[0]


def build_migration_plan(
    *,
    team_id: str,
    knowledge_base_id: str,
    migration_id: str,
    operator_agent_id: str,
    backup_root: Path | None = None,
    legacy_snapshot_root: Path | None = None,
) -> dict[str, Any]:
    required = {
        "teamId": team_id,
        "knowledgeBaseId": knowledge_base_id,
        "migrationId": migration_id,
        "operatorAgentId": operator_agent_id,
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    if missing:
        raise ChallengeCupKnowledgeMigrationError(f"Missing required arguments: {', '.join(missing)}")

    workspace_root = team_knowledge_service._route_team_knowledge_workspace_path(seed=False)
    team_index = _read_json(workspace_root / "teams" / "teams.json")
    team = next(
        (
            row for row in list(team_index.get("teams") or [])
            if isinstance(row, dict) and str(row.get("teamId") or "").strip() == team_id
        ),
        None,
    )
    if team is None:
        raise ChallengeCupKnowledgeMigrationError("Team not found in the read-only team index.")
    reviewer_id = _knowledge_manager_id(team)
    scoped_parts = str(knowledge_base_id or "").split(":", 2)
    raw_requested_base_id = scoped_parts[2] if len(scoped_parts) == 3 else str(knowledge_base_id or "").strip()
    knowledge_root = workspace_root / "teams" / team_id / "knowledge"
    base_state = _read_json(knowledge_root / "knowledge_bases.json")
    base = next(
        (
            row for row in list(base_state.get("knowledgeBases") or [])
            if isinstance(row, dict) and str(row.get("knowledgeBaseId") or "").strip() == raw_requested_base_id
        ),
        None,
    )
    if base is None:
        raise ChallengeCupKnowledgeMigrationError("Knowledge base not found in the read-only knowledge index.")
    if str(base.get("ownerType") or "") != "team" or str(base.get("ownerId") or "") != team_id:
        raise ChallengeCupKnowledgeMigrationError("Knowledge base does not belong to the requested team.")
    raw_base_id = str(base.get("knowledgeBaseId") or "").strip()
    paths = {
        "proposals": knowledge_root / "refinement_proposals.jsonl",
        "batches": knowledge_root / "batches.jsonl",
        "items": knowledge_root / "items.jsonl",
        "audit": knowledge_root / "audit.jsonl",
        "source_artifacts": knowledge_root / "source_artifacts.jsonl",
    }
    proposals = _read_jsonl(paths["proposals"])
    batches = _read_jsonl(paths["batches"])
    items = _read_jsonl(paths["items"])
    audit = _read_jsonl(paths["audit"])
    source_artifacts = _read_jsonl(paths["source_artifacts"])
    live_records = {"proposals": proposals, "batches": batches, "items": items, "audit": audit}

    completed = [
        row for row in audit
        if row.get("action") == TERMINAL_ACTION
        and str((row.get("payload") or {}).get("migrationId") or "") == migration_id
    ]
    if completed:
        replacements = list((completed[-1].get("payload") or {}).get("replacementKnowledgeItemIds") or [])
        current_ids = {str(item.get("knowledgeItemId") or "") for item in items}
        if len(replacements) == EXPECTED_SOURCE_COUNT and set(replacements).issubset(current_ids):
            return {"status": "already_applied", "migrationId": migration_id, "replacementKnowledgeItemIds": replacements}
        raise ChallengeCupKnowledgeMigrationError("Migration audit exists but replacement knowledge is incomplete.")

    resume_from_purge_id = ""
    legacy_snapshot_manifest_hash = ""
    legacy_audit = audit
    snapshot_manifest: dict[str, Any] = {}
    if legacy_snapshot_root is not None:
        snapshot_root = Path(legacy_snapshot_root).resolve()
        required_snapshot_files = {
            "manifest": snapshot_root / "manifest.json",
            "proposals": snapshot_root / "proposals.jsonl",
            "batches": snapshot_root / "batches.jsonl",
            "items": snapshot_root / "items.jsonl",
            "audit": snapshot_root / "audit.jsonl",
        }
        missing_snapshot_files = [name for name, path in required_snapshot_files.items() if not path.is_file()]
        if missing_snapshot_files:
            raise ChallengeCupKnowledgeMigrationError(
                f"Legacy snapshot is incomplete: {', '.join(sorted(missing_snapshot_files))}."
            )
        snapshot_manifest = _read_json(required_snapshot_files["manifest"])
        resume_from_purge_id = str(snapshot_manifest.get("purgeId") or "").strip()
        if (
            snapshot_manifest.get("status") != "ready"
            or str(snapshot_manifest.get("teamId") or "").strip() != team_id
            or str(snapshot_manifest.get("knowledgeBaseId") or "").strip() != raw_base_id
            or not resume_from_purge_id
        ):
            raise ChallengeCupKnowledgeMigrationError("Legacy snapshot is not a matching Challenge Cup purge backup.")
        snapshot_item_ids = {
            str(value or "").strip()
            for value in list(snapshot_manifest.get("legacyKnowledgeItemIds") or [])
            if str(value or "").strip()
        }
        snapshot_batch_ids = {
            str(value or "").strip()
            for value in list(snapshot_manifest.get("legacyBatchIds") or [])
            if str(value or "").strip()
        }
        snapshot_proposal_ids = {
            str(value or "").strip()
            for value in list(snapshot_manifest.get("legacyProposalIds") or [])
            if str(value or "").strip()
        }
        if len(snapshot_item_ids) != EXPECTED_LEGACY_COUNT or len(snapshot_batch_ids) != EXPECTED_LEGACY_COUNT:
            raise ChallengeCupKnowledgeMigrationError("Legacy snapshot does not contain exactly 5 item/batch targets.")
        if (
            snapshot_item_ids & {str(row.get("knowledgeItemId") or "").strip() for row in items}
            or snapshot_batch_ids & {str(row.get("batchId") or "").strip() for row in batches}
            or snapshot_proposal_ids & {str(row.get("proposalId") or "").strip() for row in proposals}
        ):
            raise ChallengeCupKnowledgeMigrationError("Legacy purge targets are still present in the live knowledge store.")
        matching_purge_audits = [
            row for row in audit
            if row.get("action") == PURGE_TERMINAL_ACTION
            and str((row.get("payload") or {}).get("purgeId") or "").strip() == resume_from_purge_id
            and set((row.get("payload") or {}).get("removedKnowledgeItemIds") or []) == snapshot_item_ids
            and set((row.get("payload") or {}).get("removedBatchIds") or []) == snapshot_batch_ids
            and set((row.get("payload") or {}).get("removedProposalIds") or []) == snapshot_proposal_ids
        ]
        if len(matching_purge_audits) != 1:
            raise ChallengeCupKnowledgeMigrationError("Post-purge migration requires one matching completed purge audit.")
        proposals = _read_jsonl(required_snapshot_files["proposals"])
        batches = _read_jsonl(required_snapshot_files["batches"])
        items = _read_jsonl(required_snapshot_files["items"])
        legacy_audit = _read_jsonl(required_snapshot_files["audit"])
        legacy_snapshot_manifest_hash = _content_hash(snapshot_manifest)

    legacy_items = [
        item for item in items
        if str(item.get("knowledgeBaseId") or "") == raw_base_id
        and not str(item.get("sourceCandidateId") or "").strip()
        and not str(item.get("lifecycleStatus") or "").strip()
    ]
    if len(legacy_items) != EXPECTED_LEGACY_COUNT:
        raise ChallengeCupKnowledgeMigrationError(
            f"Expected exactly {EXPECTED_LEGACY_COUNT} legacy items, found {len(legacy_items)}."
        )
    legacy_item_ids = {str(item.get("knowledgeItemId") or "").strip() for item in legacy_items}
    legacy_batch_ids = {str(item.get("batchId") or "").strip() for item in legacy_items}
    legacy_batches = [row for row in batches if str(row.get("batchId") or "").strip() in legacy_batch_ids]
    legacy_proposal_ids = {
        str(proposal_id or "").strip()
        for row in legacy_batches
        for proposal_id in list(row.get("proposalIds") or [])
        if str(proposal_id or "").strip()
    }
    legacy_proposals = [row for row in proposals if str(row.get("proposalId") or "").strip() in legacy_proposal_ids]
    if len(legacy_batch_ids) != EXPECTED_LEGACY_COUNT or len(legacy_batches) != EXPECTED_LEGACY_COUNT:
        raise ChallengeCupKnowledgeMigrationError("Legacy item-to-batch mapping is not exactly 5 unique batches.")
    if len(legacy_proposals) != len(legacy_proposal_ids):
        raise ChallengeCupKnowledgeMigrationError(
            "One or more legacy batch proposal records are missing or duplicated "
            f"(found {len(legacy_proposal_ids)} ids and {len(legacy_proposals)} records)."
        )
    if resume_from_purge_id:
        if set(snapshot_manifest.get("legacyKnowledgeItemIds") or []) != legacy_item_ids:
            raise ChallengeCupKnowledgeMigrationError("Legacy snapshot item records do not match its purge manifest.")
        if set(snapshot_manifest.get("legacyBatchIds") or []) != legacy_batch_ids:
            raise ChallengeCupKnowledgeMigrationError("Legacy snapshot batch records do not match its purge manifest.")
        if set(snapshot_manifest.get("legacyProposalIds") or []) != legacy_proposal_ids:
            raise ChallengeCupKnowledgeMigrationError("Legacy snapshot proposal records do not match its purge manifest.")
        expected_hashes = {
            str(row.get("knowledgeItemId") or "").strip(): str(row.get("contentHash") or "").strip()
            for row in list(snapshot_manifest.get("lineageRows") or [])
            if isinstance(row, dict) and str(row.get("knowledgeItemId") or "").strip()
        }
        if len(expected_hashes) != EXPECTED_LEGACY_COUNT or any(
            expected_hashes.get(str(item.get("knowledgeItemId") or "").strip()) != _content_hash(item)
            for item in legacy_items
        ):
            raise ChallengeCupKnowledgeMigrationError("Legacy snapshot item hashes do not match its purge manifest.")

    artifacts_by_id: dict[str, dict[str, Any]] = {}
    for artifact in source_artifacts:
        artifact_id = str(artifact.get("sourceArtifactId") or "").strip()
        if not artifact_id:
            continue
        if artifact_id in artifacts_by_id:
            raise ChallengeCupKnowledgeMigrationError(f"Source artifact {artifact_id} is duplicated.")
        artifacts_by_id[artifact_id] = artifact
    proposals_by_id = {
        str(proposal.get("proposalId") or "").strip(): proposal
        for proposal in legacy_proposals
    }
    batches_by_id = {
        str(batch.get("batchId") or "").strip(): batch
        for batch in legacy_batches
    }
    source_origins: dict[str, dict[str, str]] = {}
    legacy_lineage_by_item_id: dict[str, dict[str, Any]] = {}
    direct_ingested_batch_ids: list[str] = []
    for old_item in legacy_items:
        old_item_id = str(old_item.get("knowledgeItemId") or "").strip()
        batch_id = str(old_item.get("batchId") or "").strip()
        old_batch = batches_by_id.get(batch_id)
        if old_batch is None:
            raise ChallengeCupKnowledgeMigrationError(f"Legacy item {old_item_id} has no unique batch.")
        artifact_ids = [str(value or "").strip() for value in list(old_item.get("sourceArtifactIds") or []) if str(value or "").strip()]
        if len(artifact_ids) != 1 or artifact_ids[0] not in artifacts_by_id:
            raise ChallengeCupKnowledgeMigrationError("Each legacy item must reference exactly one retained source artifact.")
        artifact = artifacts_by_id[artifact_ids[0]]
        batch_artifact_ids = [
            str(value or "").strip()
            for value in list(old_batch.get("sourceArtifactIds") or [])
            if str(value or "").strip()
        ]
        if batch_artifact_ids != artifact_ids:
            raise ChallengeCupKnowledgeMigrationError(
                f"Legacy item {old_item_id}, batch {batch_id}, and source artifact mapping is not unique."
            )
        source_ref = artifact.get("sourceRef") if isinstance(artifact.get("sourceRef"), dict) else {}
        item_central_ids = [
            str(value or "").strip()
            for value in list(old_item.get("centralSourceIds") or [])
            if str(value or "").strip()
        ]
        batch_central_ids = [
            str(value or "").strip()
            for value in list(old_batch.get("centralSourceIds") or [])
            if str(value or "").strip()
        ]
        artifact_central_id = str(artifact.get("centralSourceId") or source_ref.get("centralSourceId") or "").strip()
        if len(item_central_ids) != 1 or batch_central_ids != item_central_ids or artifact_central_id != item_central_ids[0]:
            raise ChallengeCupKnowledgeMigrationError(
                f"Legacy item {old_item_id}, batch {batch_id}, and central source mapping is not unique."
            )
        proposal_ids = [
            str(value or "").strip()
            for value in list(old_batch.get("proposalIds") or [])
            if str(value or "").strip()
        ]
        direct_audits = [
            row for row in legacy_audit
            if row.get("action") == DIRECT_INGEST_ACTION
            and str((row.get("payload") or {}).get("teamId") or "").strip() == team_id
            and str((row.get("payload") or {}).get("knowledgeBaseId") or "").strip() == raw_base_id
            and str((row.get("payload") or {}).get("batchId") or "").strip() == batch_id
            and str((row.get("payload") or {}).get("knowledgeItemId") or "").strip() == old_item_id
        ]
        if len(proposal_ids) == 1:
            if direct_audits:
                raise ChallengeCupKnowledgeMigrationError(
                    f"Legacy batch {batch_id} has conflicting proposal-backed and direct-ingest lineage."
                )
            old_proposal = proposals_by_id.get(proposal_ids[0])
            if old_proposal is None:
                raise ChallengeCupKnowledgeMigrationError(f"Legacy batch {batch_id} has no unique proposal record.")
            proposal_artifact_ids = [
                str(value or "").strip()
                for value in list(old_proposal.get("sourceArtifactIds") or [])
                if str(value or "").strip()
            ]
            proposal_central_ids = [
                str(value or "").strip()
                for value in list(old_proposal.get("centralSourceIds") or [])
                if str(value or "").strip()
            ]
            if proposal_artifact_ids != artifact_ids or proposal_central_ids != item_central_ids:
                raise ChallengeCupKnowledgeMigrationError(
                    f"Legacy proposal {proposal_ids[0]} does not match its item source lineage."
                )
            ingestion_mode = "proposal_backed"
            old_proposal_id: str | None = proposal_ids[0]
            content_source = old_proposal
        elif not proposal_ids:
            if len(direct_audits) != 1 or str((direct_audits[0].get("payload") or {}).get("proposalId") or "").strip():
                raise ChallengeCupKnowledgeMigrationError(
                    f"Legacy batch {batch_id} must have exactly one direct-ingest audit with no proposal."
                )
            ingestion_mode = "direct_ingested"
            old_proposal_id = None
            content_source = old_item
            direct_ingested_batch_ids.append(batch_id)
        else:
            raise ChallengeCupKnowledgeMigrationError(f"Legacy batch {batch_id} has more than one proposal.")
        legacy_lineage_by_item_id[old_item_id] = {
            "batch": old_batch,
            "contentSource": content_source,
            "legacyIngestionMode": ingestion_mode,
            "oldProposalId": old_proposal_id,
            "sourceArtifactId": artifact_ids[0],
            "centralSourceId": item_central_ids[0],
        }
        trace = source_ref.get("sourceTrace") if isinstance(source_ref.get("sourceTrace"), dict) else {}
        run_id = str(trace.get("sourceCollectionRunId") or "").strip()
        candidate_ids = [str(value or "").strip() for value in list(source_ref.get("candidateIds") or trace.get("sourceCandidateIds") or []) if str(value or "").strip()]
        if not run_id or not candidate_ids:
            raise ChallengeCupKnowledgeMigrationError(f"Legacy source artifact {artifact_ids[0]} has incomplete source-run lineage.")
        for candidate_id in candidate_ids:
            if candidate_id in source_origins:
                raise ChallengeCupKnowledgeMigrationError(f"Source {candidate_id} occurs in more than one legacy artifact.")
            source_origins[candidate_id] = {
                "sourceCollectionRunId": run_id,
                "sourceArtifactId": artifact_ids[0],
                "oldKnowledgeItemId": old_item_id,
            }
    if len(source_origins) != EXPECTED_SOURCE_COUNT:
        raise ChallengeCupKnowledgeMigrationError(
            f"Expected exactly {EXPECTED_SOURCE_COUNT} unique legacy sources, found {len(source_origins)}."
        )
    projects_root = workspace_root / "teams" / team_id / "research_projects"
    projects_state = _read_json(projects_root / "index.json")
    projects_by_id = {
        str(project.get("projectId") or "").strip(): project
        for project in list(projects_state.get("projects") or [])
        if isinstance(project, dict) and str(project.get("projectId") or "").strip()
    }
    candidates_by_id: dict[str, dict[str, Any]] = {}
    for candidate_store_path in sorted(projects_root.glob("*/workspace/candidate_store/index.json")):
        candidate_store = _read_json(candidate_store_path)
        for candidate in list(candidate_store.get("candidates") or []):
            candidate_id = str(candidate.get("candidateId") or "").strip() if isinstance(candidate, dict) else ""
            if candidate_id in source_origins:
                candidates_by_id[candidate_id] = candidate
    missing_candidates = sorted(set(source_origins) - set(candidates_by_id))
    recovered_candidate_ids: list[str] = []
    unrecoverable_candidates: list[str] = []
    first_recovery_error: ChallengeCupKnowledgeMigrationError | None = None
    for candidate_id in missing_candidates:
        origin = source_origins[candidate_id]
        lineage = legacy_lineage_by_item_id[origin["oldKnowledgeItemId"]]
        try:
            candidates_by_id[candidate_id] = _recover_candidate_from_data_record(
                workspace_root=workspace_root,
                team_id=team_id,
                candidate_id=candidate_id,
                source_collection_run_id=origin["sourceCollectionRunId"],
                content_source=lineage["contentSource"],
                projects_by_id=projects_by_id,
            )
            recovered_candidate_ids.append(candidate_id)
        except ChallengeCupKnowledgeMigrationError as exc:
            unrecoverable_candidates.append(candidate_id)
            first_recovery_error = first_recovery_error or exc
    if unrecoverable_candidates:
        if len(unrecoverable_candidates) == 1 and first_recovery_error is not None:
            raise first_recovery_error
        raise ChallengeCupKnowledgeMigrationError(
            "Authoritative source candidates are missing and cannot be recovered from unique DataRecords "
            f"({len(unrecoverable_candidates)}): {', '.join(unrecoverable_candidates)}."
        )
    member_ids = {
        str(member.get("agentId") or "").strip()
        for member in list(team.get("members") or [])
        if isinstance(member, dict) and str(member.get("agentId") or "").strip()
    }
    source_rows: list[dict[str, Any]] = []
    now = utc_now_iso()
    for candidate_id, candidate in sorted(candidates_by_id.items()):
        origin = source_origins[candidate_id]
        old_item = next(item for item in legacy_items if item.get("knowledgeItemId") == origin["oldKnowledgeItemId"])
        lineage = legacy_lineage_by_item_id[origin["oldKnowledgeItemId"]]
        old_batch = lineage["batch"]
        proposer_id = str(candidate.get("createdByAgent") or "").strip()
        if proposer_id not in member_ids:
            raise ChallengeCupKnowledgeMigrationError(f"Source {candidate_id} has no trusted team Agent proposer.")
        if proposer_id == reviewer_id:
            raise ChallengeCupKnowledgeMigrationError(f"Source {candidate_id} proposer equals the required reviewer.")
        content_source = lineage["contentSource"]
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        research_project_id = str(metadata.get("researchProjectId") or "").strip()
        if not research_project_id:
            raise ChallengeCupKnowledgeMigrationError(f"Source {candidate_id} is missing researchProjectId.")
        project = projects_by_id.get(research_project_id) or {}
        question_id = str(project.get("challengeQuestionId") or project.get("questionId") or "").strip()
        if not question_id:
            raise ChallengeCupKnowledgeMigrationError(f"Project {research_project_id} is missing its Challenge Cup question binding.")
        source_collection_run_id = origin["sourceCollectionRunId"]
        proposal_id = _stable_id("kprop-migrated", migration_id, candidate_id)
        batch_id = _stable_id("kbatch-migrated", migration_id, candidate_id)
        item_id = _stable_id("kitem-migrated", migration_id, candidate_id)
        content = _source_content(content_source, candidate)
        scope = {
            "requiredReviewerAgentId": reviewer_id,
            "researchProjectId": research_project_id,
            "questionId": question_id,
            "sourceCollectionRunId": source_collection_run_id,
            "sourceCandidateId": candidate_id,
            "sourceIdentityHash": _candidate_identity_hash(candidate),
            "evidenceLevel": _candidate_evidence_level(candidate),
        }
        new_proposal = deepcopy(content_source) if lineage["legacyIngestionMode"] == "proposal_backed" else {
            "targetKnowledgeBaseId": raw_base_id,
            "sourceArtifactIds": [lineage["sourceArtifactId"]],
            "centralSourceIds": [lineage["centralSourceId"]],
            "tags": list(old_item.get("tags") or []),
        }
        new_proposal.update(
            {
                "proposalId": proposal_id,
                "proposedByAgentId": proposer_id,
                **scope,
                "status": "applied",
                "title": _candidate_title(candidate),
                "summary": str(candidate.get("summary") or "").strip(),
                "content": content,
                "tags": [tag for tag in list(content_source.get("tags") or []) if str(tag).lower() not in _CANDIDATE_TAGS],
                "createdAt": now,
                "updatedAt": now,
                "reviewedAt": now,
                "reviewedByAgentId": reviewer_id,
                "resolutionNote": f"Migrated by {migration_id}",
                "batchId": batch_id,
                "knowledgeItemIds": [item_id],
            }
        )
        new_batch = deepcopy(old_batch)
        new_batch.update({"batchId": batch_id, "proposalIds": [proposal_id], "reviewedByAgentId": reviewer_id, "appliedAt": now})
        new_item = deepcopy(old_item)
        new_item.update(
            {
                "knowledgeItemId": item_id,
                "proposalId": proposal_id,
                "batchId": batch_id,
                **scope,
                "title": _candidate_title(candidate),
                "summary": str(candidate.get("summary") or "").strip(),
                "content": content,
                "tags": [tag for tag in list(old_item.get("tags") or []) if str(tag).lower() not in _CANDIDATE_TAGS],
                "lifecycleStatus": "applied",
                "createdAt": now,
                "updatedAt": now,
            }
        )
        source_rows.append(
            {
                "sourceCandidateId": candidate_id,
                "sourceRecovery": (
                    deepcopy(metadata.get("migrationRecovery"))
                    if isinstance(metadata.get("migrationRecovery"), dict)
                    else None
                ),
                "oldKnowledgeItemId": str(old_item.get("knowledgeItemId") or ""),
                "oldContentHash": _content_hash(old_item),
                "oldProposalId": lineage["oldProposalId"],
                "legacyIngestionMode": lineage["legacyIngestionMode"],
                "proposal": new_proposal,
                "batch": new_batch,
                "item": new_item,
            }
        )

    replacement_ids = [row["item"]["knowledgeItemId"] for row in source_rows]
    if len(source_rows) != EXPECTED_SOURCE_COUNT or len(set(replacement_ids)) != EXPECTED_SOURCE_COUNT:
        raise ChallengeCupKnowledgeMigrationError("Replacement plan is not exactly 33 unique KnowledgeItems.")
    backup_path = Path(backup_root) if backup_root else paths["items"].parent / "migration_backups" / migration_id
    manifest_hash = _content_hash(
        {
            "migrationId": migration_id,
            "resumeFromPurgeId": resume_from_purge_id,
            "legacySnapshotManifestHash": legacy_snapshot_manifest_hash,
            "legacy": [
                {
                    "knowledgeItemId": item_id,
                    "batchId": str(next(item for item in legacy_items if item.get("knowledgeItemId") == item_id).get("batchId") or ""),
                    "proposalId": legacy_lineage_by_item_id[item_id]["oldProposalId"],
                    "legacyIngestionMode": legacy_lineage_by_item_id[item_id]["legacyIngestionMode"],
                    "contentHash": _content_hash(next(item for item in legacy_items if item.get("knowledgeItemId") == item_id)),
                }
                for item_id in sorted(legacy_item_ids)
            ],
            "sources": sorted(candidates_by_id),
            "recoveredSources": sorted(recovered_candidate_ids),
            "replacements": replacement_ids,
            "scopes": sorted(
                {
                    (row["item"]["researchProjectId"], row["item"]["questionId"], row["item"]["sourceCollectionRunId"])
                    for row in source_rows
                }
            ),
        }
    )
    return {
        "status": "ready",
        "mode": "dry-run",
        "migrationId": migration_id,
        "resumeFromPurgeId": resume_from_purge_id,
        "operatorAgentId": operator_agent_id,
        "reviewerAgentId": reviewer_id,
        "teamId": team_id,
        "knowledgeBaseId": raw_base_id,
        "researchScopes": [
            {"researchProjectId": project_id, "questionId": qid, "sourceCollectionRunId": run_id}
            for project_id, qid, run_id in sorted(
                {
                    (row["item"]["researchProjectId"], row["item"]["questionId"], row["item"]["sourceCollectionRunId"])
                    for row in source_rows
                }
            )
        ],
        "legacyKnowledgeItemIds": sorted(legacy_item_ids),
        "legacyBatchIds": sorted(legacy_batch_ids),
        "legacyProposalIds": sorted(legacy_proposal_ids),
        "directIngestedBatchIds": sorted(direct_ingested_batch_ids),
        "sourceCandidateIds": sorted(candidates_by_id),
        "recoveredSourceCandidateIds": sorted(recovered_candidate_ids),
        "replacementKnowledgeItemIds": replacement_ids,
        "manifestHash": manifest_hash,
        "backupPath": str(backup_path.resolve()),
        "paths": paths,
        "records": live_records,
        "sourceRows": source_rows,
    }


def _backup(plan: dict[str, Any]) -> None:
    backup = Path(plan["backupPath"])
    if backup.exists():
        raise ChallengeCupKnowledgeMigrationError(f"Backup path already exists: {backup}")
    backup.mkdir(parents=True)
    for name, path in plan["paths"].items():
        source = Path(path)
        if source.exists():
            shutil.copy2(source, backup / f"{name}.jsonl")
    vector_root = rag_vector_index_service._index_root()
    if vector_root.exists():
        shutil.copytree(vector_root, backup / "vector_index")
    (backup / "manifest.json").write_text(
        json.dumps({key: value for key, value in plan.items() if key not in {"records", "sourceRows", "paths"}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _restore(plan: dict[str, Any]) -> None:
    backup = Path(plan["backupPath"])
    for name, path in plan["paths"].items():
        target = Path(path)
        saved = backup / f"{name}.jsonl"
        if saved.exists():
            shutil.copy2(saved, target)
        elif target.exists():
            target.unlink()
    vector_root = rag_vector_index_service._index_root()
    saved_vector = backup / "vector_index"
    if vector_root.exists():
        shutil.rmtree(vector_root)
    if saved_vector.exists():
        shutil.copytree(saved_vector, vector_root)


def apply_migration(
    plan: dict[str, Any],
    *,
    maintenance_window_confirmed: bool,
    expected_manifest_hash: str,
) -> dict[str, Any]:
    if plan.get("status") == "already_applied":
        return plan
    if not maintenance_window_confirmed:
        raise ChallengeCupKnowledgeMigrationError("Apply requires an explicit maintenance-window confirmation.")
    if not expected_manifest_hash or expected_manifest_hash != plan.get("manifestHash"):
        raise ChallengeCupKnowledgeMigrationError("Apply requires the matching fresh dry-run manifest hash.")
    _backup(plan)
    try:
        old = plan["records"]
        old_item_ids = set(plan["legacyKnowledgeItemIds"])
        old_batch_ids = set(plan["legacyBatchIds"])
        old_proposal_ids = set(plan["legacyProposalIds"])
        new_proposals = [row["proposal"] for row in plan["sourceRows"]]
        new_batches = [row["batch"] for row in plan["sourceRows"]]
        new_items = [row["item"] for row in plan["sourceRows"]]
        if len(new_items) != EXPECTED_SOURCE_COUNT or len({row["sourceCandidateId"] for row in new_items}) != EXPECTED_SOURCE_COUNT:
            raise ChallengeCupKnowledgeMigrationError("Replacement validation failed before legacy deletion.")
        proposals = [row for row in old["proposals"] if str(row.get("proposalId") or "") not in old_proposal_ids] + new_proposals
        batches = [row for row in old["batches"] if str(row.get("batchId") or "") not in old_batch_ids] + new_batches
        items = [row for row in old["items"] if str(row.get("knowledgeItemId") or "") not in old_item_ids] + new_items
        audit = list(old["audit"])
        now = utc_now_iso()
        for row in plan["sourceRows"]:
            audit.append(
                {
                    "auditId": _stable_id("kaudit-migrated", plan["migrationId"], row["sourceCandidateId"]),
                    "action": MIGRATION_ACTION,
                    "actorAgentId": plan["operatorAgentId"],
                    "createdAt": now,
                    "payload": {
                        "migrationId": plan["migrationId"],
                        "oldKnowledgeItemId": row["oldKnowledgeItemId"],
                        "oldContentHash": row["oldContentHash"],
                        "oldProposalId": row["oldProposalId"],
                        "legacyIngestionMode": row["legacyIngestionMode"],
                        "replacementKnowledgeItemId": row["item"]["knowledgeItemId"],
                        "sourceCandidateId": row["sourceCandidateId"],
                        "sourceRecovery": row["sourceRecovery"],
                        "operatorAgentId": plan["operatorAgentId"],
                    },
                }
            )
        audit.append(
            {
                "auditId": _stable_id("kaudit-completed", plan["migrationId"], "terminal"),
                "action": TERMINAL_ACTION,
                "actorAgentId": plan["operatorAgentId"],
                "createdAt": now,
                "payload": {
                    "migrationId": plan["migrationId"],
                    "legacyKnowledgeItemIds": plan["legacyKnowledgeItemIds"],
                    "replacementKnowledgeItemIds": plan["replacementKnowledgeItemIds"],
                    "operatorAgentId": plan["operatorAgentId"],
                },
            }
        )
        team_knowledge_service._write_jsonl(plan["paths"]["proposals"], proposals)
        team_knowledge_service._write_jsonl(plan["paths"]["batches"], batches)
        team_knowledge_service._write_jsonl(plan["paths"]["items"], items)
        team_knowledge_service._write_jsonl(plan["paths"]["audit"], audit)
        old_vector_records = [
            record
            for record in rag_vector_index_service._load_all_index_records()
            if str(record.get("knowledgeItemId") or "") in old_item_ids
        ]
        for record in old_vector_records:
            record_path = rag_vector_index_service._item_record_path(
                rag_vector_index_service._record_id_for_record(record)
            )
            if record_path.exists():
                record_path.unlink()
        rag_vector_index_service._write_index_summary(rag_vector_index_service._load_all_index_records())
    except Exception:
        _restore(plan)
        raise
    return {
        "status": "applied",
        "migrationId": plan["migrationId"],
        "backupPath": plan["backupPath"],
        "removedKnowledgeItemIds": plan["legacyKnowledgeItemIds"],
        "replacementKnowledgeItemIds": plan["replacementKnowledgeItemIds"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--migration-id", required=True)
    parser.add_argument("--operator-agent-id", required=True)
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument(
        "--legacy-snapshot-root",
        type=Path,
        help="Resume from a completed Challenge Cup purge backup without restoring the legacy live records.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--maintenance-window-confirmed", action="store_true")
    parser.add_argument("--expected-manifest-hash", default="")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        plan = build_migration_plan(
            team_id=args.team_id,
            knowledge_base_id=args.knowledge_base_id,
            migration_id=args.migration_id,
            operator_agent_id=args.operator_agent_id,
            backup_root=args.backup_root,
            legacy_snapshot_root=args.legacy_snapshot_root,
        )
        result = apply_migration(
            plan,
            maintenance_window_confirmed=args.maintenance_window_confirmed,
            expected_manifest_hash=args.expected_manifest_hash,
        ) if args.apply else {
            key: value for key, value in plan.items() if key not in {"records", "sourceRows", "paths"}
        }
    except ChallengeCupKnowledgeMigrationError as exc:
        print(json.dumps({"status": "blocked", "mode": "apply" if args.apply else "dry-run", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
