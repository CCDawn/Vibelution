"""Remove the five legacy Challenge Cup knowledge packs without replacing them.

Dry-run is the default. This command is deliberately specific to the observed
Challenge Cup legacy shape and does not expose a general KnowledgeItem delete API.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.chatroom.store import utc_now_iso
from core.web.services import rag_vector_index_service, team_knowledge_service
from scripts import migrate_challenge_cup_knowledge_items as migration

EXPECTED_ITEM_COUNT = 5
EXPECTED_BATCH_COUNT = 5
EXPECTED_PROPOSAL_COUNT = 2
EXPECTED_DIRECT_INGEST_COUNT = 3
EXPECTED_SOURCE_COUNT = 33
PURGE_ACTION = "challenge_cup.legacy_knowledge.purged"
TERMINAL_ACTION = "challenge_cup.legacy_knowledge_purge.completed"


class ChallengeCupKnowledgePurgeError(RuntimeError):
    pass


def _string_list(value: Any) -> list[str]:
    return [str(item or "").strip() for item in list(value or []) if str(item or "").strip()]


def _unique_records(rows: list[dict[str, Any]], key: str, ids: set[str], label: str) -> list[dict[str, Any]]:
    selected = [row for row in rows if str(row.get(key) or "").strip() in ids]
    selected_ids = [str(row.get(key) or "").strip() for row in selected]
    if len(selected) != len(ids) or len(set(selected_ids)) != len(ids):
        raise ChallengeCupKnowledgePurgeError(f"Legacy {label} records are missing or duplicated.")
    return selected


def build_purge_plan(
    *,
    team_id: str,
    knowledge_base_id: str,
    purge_id: str,
    operator_agent_id: str,
    backup_root: Path | None = None,
) -> dict[str, Any]:
    required = {
        "teamId": team_id,
        "knowledgeBaseId": knowledge_base_id,
        "purgeId": purge_id,
        "operatorAgentId": operator_agent_id,
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    if missing:
        raise ChallengeCupKnowledgePurgeError(f"Missing required arguments: {', '.join(missing)}")

    workspace_root = team_knowledge_service._route_team_knowledge_workspace_path(seed=False)
    team_index = migration._read_json(workspace_root / "teams" / "teams.json")
    team = next(
        (
            row
            for row in list(team_index.get("teams") or [])
            if isinstance(row, dict) and str(row.get("teamId") or "").strip() == team_id
        ),
        None,
    )
    if team is None:
        raise ChallengeCupKnowledgePurgeError("Team not found in the read-only team index.")

    scoped_parts = str(knowledge_base_id or "").split(":", 2)
    requested_base_id = scoped_parts[2] if len(scoped_parts) == 3 else str(knowledge_base_id or "").strip()
    knowledge_root = workspace_root / "teams" / team_id / "knowledge"
    base_state = migration._read_json(knowledge_root / "knowledge_bases.json")
    base = next(
        (
            row
            for row in list(base_state.get("knowledgeBases") or [])
            if isinstance(row, dict) and str(row.get("knowledgeBaseId") or "").strip() == requested_base_id
        ),
        None,
    )
    if base is None:
        raise ChallengeCupKnowledgePurgeError("Knowledge base not found in the read-only knowledge index.")
    if str(base.get("ownerType") or "") != "team" or str(base.get("ownerId") or "") != team_id:
        raise ChallengeCupKnowledgePurgeError("Knowledge base does not belong to the requested team.")
    raw_base_id = str(base.get("knowledgeBaseId") or "").strip()

    paths = {
        "proposals": knowledge_root / "refinement_proposals.jsonl",
        "batches": knowledge_root / "batches.jsonl",
        "items": knowledge_root / "items.jsonl",
        "audit": knowledge_root / "audit.jsonl",
        "source_artifacts": knowledge_root / "source_artifacts.jsonl",
    }
    records = {name: migration._read_jsonl(path) for name, path in paths.items()}
    completed = [
        row
        for row in records["audit"]
        if row.get("action") == TERMINAL_ACTION
        and str((row.get("payload") or {}).get("purgeId") or "").strip() == purge_id
    ]
    if completed:
        payload = completed[-1].get("payload") or {}
        item_ids = set(_string_list(payload.get("removedKnowledgeItemIds")))
        batch_ids = set(_string_list(payload.get("removedBatchIds")))
        proposal_ids = set(_string_list(payload.get("removedProposalIds")))
        current_item_ids = {str(row.get("knowledgeItemId") or "").strip() for row in records["items"]}
        current_batch_ids = {str(row.get("batchId") or "").strip() for row in records["batches"]}
        current_proposal_ids = {str(row.get("proposalId") or "").strip() for row in records["proposals"]}
        if item_ids.isdisjoint(current_item_ids) and batch_ids.isdisjoint(current_batch_ids) and proposal_ids.isdisjoint(current_proposal_ids):
            return {
                "status": "already_applied",
                "purgeId": purge_id,
                "removedKnowledgeItemIds": sorted(item_ids),
                "removedBatchIds": sorted(batch_ids),
                "removedProposalIds": sorted(proposal_ids),
            }
        raise ChallengeCupKnowledgePurgeError("Purge audit exists but one or more legacy records remain.")

    legacy_items = [
        row
        for row in records["items"]
        if str(row.get("knowledgeBaseId") or "").strip() == raw_base_id
        and not str(row.get("sourceCandidateId") or "").strip()
        and not str(row.get("lifecycleStatus") or "").strip()
    ]
    if len(legacy_items) != EXPECTED_ITEM_COUNT:
        raise ChallengeCupKnowledgePurgeError(
            f"Expected exactly {EXPECTED_ITEM_COUNT} legacy items, found {len(legacy_items)}."
        )
    item_ids = {str(row.get("knowledgeItemId") or "").strip() for row in legacy_items}
    batch_ids = {str(row.get("batchId") or "").strip() for row in legacy_items}
    if len(item_ids) != EXPECTED_ITEM_COUNT or len(batch_ids) != EXPECTED_BATCH_COUNT:
        raise ChallengeCupKnowledgePurgeError("Legacy items do not map to exactly 5 unique item and batch IDs.")
    legacy_batches = _unique_records(records["batches"], "batchId", batch_ids, "batch")
    batches_by_id = {str(row.get("batchId") or "").strip(): row for row in legacy_batches}
    proposal_ids = {
        proposal_id
        for batch in legacy_batches
        for proposal_id in _string_list(batch.get("proposalIds"))
    }
    if len(proposal_ids) != EXPECTED_PROPOSAL_COUNT:
        raise ChallengeCupKnowledgePurgeError(
            f"Expected exactly {EXPECTED_PROPOSAL_COUNT} legacy proposals, found {len(proposal_ids)}."
        )
    legacy_proposals = _unique_records(records["proposals"], "proposalId", proposal_ids, "proposal")
    proposals_by_id = {str(row.get("proposalId") or "").strip(): row for row in legacy_proposals}

    artifacts_by_id: dict[str, dict[str, Any]] = {}
    for artifact in records["source_artifacts"]:
        artifact_id = str(artifact.get("sourceArtifactId") or "").strip()
        if not artifact_id:
            continue
        if artifact_id in artifacts_by_id:
            raise ChallengeCupKnowledgePurgeError(f"Source artifact {artifact_id} is duplicated.")
        artifacts_by_id[artifact_id] = artifact

    direct_batch_ids: list[str] = []
    source_candidate_ids: set[str] = set()
    retained_artifact_ids: set[str] = set()
    retained_central_source_ids: set[str] = set()
    lineage_rows: list[dict[str, Any]] = []
    for item in legacy_items:
        item_id = str(item.get("knowledgeItemId") or "").strip()
        batch_id = str(item.get("batchId") or "").strip()
        batch = batches_by_id[batch_id]
        artifact_ids = _string_list(item.get("sourceArtifactIds"))
        central_source_ids = _string_list(item.get("centralSourceIds"))
        if len(artifact_ids) != 1 or len(central_source_ids) != 1:
            raise ChallengeCupKnowledgePurgeError(f"Legacy item {item_id} does not have one retained source lineage.")
        artifact = artifacts_by_id.get(artifact_ids[0])
        if artifact is None:
            raise ChallengeCupKnowledgePurgeError(f"Legacy item {item_id} source artifact is missing.")
        source_ref = artifact.get("sourceRef") if isinstance(artifact.get("sourceRef"), dict) else {}
        artifact_central_id = str(artifact.get("centralSourceId") or source_ref.get("centralSourceId") or "").strip()
        if (
            _string_list(batch.get("sourceArtifactIds")) != artifact_ids
            or _string_list(batch.get("centralSourceIds")) != central_source_ids
            or artifact_central_id != central_source_ids[0]
        ):
            raise ChallengeCupKnowledgePurgeError(f"Legacy item {item_id} source lineage is inconsistent.")
        batch_proposal_ids = _string_list(batch.get("proposalIds"))
        direct_audits = [
            row
            for row in records["audit"]
            if row.get("action") == migration.DIRECT_INGEST_ACTION
            and str((row.get("payload") or {}).get("teamId") or "").strip() == team_id
            and str((row.get("payload") or {}).get("knowledgeBaseId") or "").strip() == raw_base_id
            and str((row.get("payload") or {}).get("batchId") or "").strip() == batch_id
            and str((row.get("payload") or {}).get("knowledgeItemId") or "").strip() == item_id
        ]
        if not batch_proposal_ids:
            if len(direct_audits) != 1 or str((direct_audits[0].get("payload") or {}).get("proposalId") or "").strip():
                raise ChallengeCupKnowledgePurgeError(
                    f"Legacy batch {batch_id} must have exactly one direct-ingest audit with no proposal."
                )
            ingestion_mode = "direct_ingested"
            proposal_id: str | None = None
            direct_batch_ids.append(batch_id)
        elif len(batch_proposal_ids) == 1 and not direct_audits:
            proposal_id = batch_proposal_ids[0]
            proposal = proposals_by_id.get(proposal_id)
            if proposal is None:
                raise ChallengeCupKnowledgePurgeError(f"Legacy proposal {proposal_id} is missing.")
            if (
                _string_list(proposal.get("sourceArtifactIds")) != artifact_ids
                or _string_list(proposal.get("centralSourceIds")) != central_source_ids
            ):
                raise ChallengeCupKnowledgePurgeError(f"Legacy proposal {proposal_id} source lineage is inconsistent.")
            ingestion_mode = "proposal_backed"
        else:
            raise ChallengeCupKnowledgePurgeError(f"Legacy batch {batch_id} has ambiguous ingestion lineage.")
        candidate_ids = _string_list(source_ref.get("candidateIds") or (source_ref.get("sourceTrace") or {}).get("sourceCandidateIds"))
        if not candidate_ids or source_candidate_ids.intersection(candidate_ids):
            raise ChallengeCupKnowledgePurgeError(f"Legacy item {item_id} has missing or duplicated source candidates.")
        source_candidate_ids.update(candidate_ids)
        retained_artifact_ids.add(artifact_ids[0])
        retained_central_source_ids.add(central_source_ids[0])
        lineage_rows.append(
            {
                "knowledgeItemId": item_id,
                "batchId": batch_id,
                "proposalId": proposal_id,
                "legacyIngestionMode": ingestion_mode,
                "sourceArtifactId": artifact_ids[0],
                "centralSourceId": central_source_ids[0],
                "contentHash": migration._content_hash(item),
            }
        )
    if len(direct_batch_ids) != EXPECTED_DIRECT_INGEST_COUNT:
        raise ChallengeCupKnowledgePurgeError(
            f"Expected exactly {EXPECTED_DIRECT_INGEST_COUNT} direct-ingested batches, found {len(direct_batch_ids)}."
        )
    if len(source_candidate_ids) != EXPECTED_SOURCE_COUNT:
        raise ChallengeCupKnowledgePurgeError(
            f"Expected exactly {EXPECTED_SOURCE_COUNT} unique source candidates, found {len(source_candidate_ids)}."
        )

    backup_path = Path(backup_root) if backup_root else knowledge_root / "migration_backups" / purge_id
    manifest_hash = migration._content_hash(
        {
            "purgeId": purge_id,
            "lineage": sorted(lineage_rows, key=lambda row: row["knowledgeItemId"]),
            "sourceCandidateIds": sorted(source_candidate_ids),
            "retainedSourceArtifactIds": sorted(retained_artifact_ids),
            "retainedCentralSourceIds": sorted(retained_central_source_ids),
        }
    )
    return {
        "status": "ready",
        "mode": "dry-run",
        "purgeId": purge_id,
        "operatorAgentId": operator_agent_id,
        "teamId": team_id,
        "knowledgeBaseId": raw_base_id,
        "legacyKnowledgeItemIds": sorted(item_ids),
        "legacyBatchIds": sorted(batch_ids),
        "legacyProposalIds": sorted(proposal_ids),
        "directIngestedBatchIds": sorted(direct_batch_ids),
        "sourceCandidateIds": sorted(source_candidate_ids),
        "retainedSourceArtifactIds": sorted(retained_artifact_ids),
        "retainedCentralSourceIds": sorted(retained_central_source_ids),
        "manifestHash": manifest_hash,
        "backupPath": str(backup_path.resolve()),
        "paths": paths,
        "records": records,
        "lineageRows": lineage_rows,
    }


def apply_purge(
    plan: dict[str, Any],
    *,
    maintenance_window_confirmed: bool,
    expected_manifest_hash: str,
) -> dict[str, Any]:
    if plan.get("status") == "already_applied":
        return plan
    if not maintenance_window_confirmed:
        raise ChallengeCupKnowledgePurgeError("Apply requires an explicit maintenance-window confirmation.")
    if not expected_manifest_hash or expected_manifest_hash != plan.get("manifestHash"):
        raise ChallengeCupKnowledgePurgeError("Apply requires the matching fresh dry-run manifest hash.")
    migration._backup(plan)
    try:
        old = plan["records"]
        item_ids = set(plan["legacyKnowledgeItemIds"])
        batch_ids = set(plan["legacyBatchIds"])
        proposal_ids = set(plan["legacyProposalIds"])
        proposals = [row for row in old["proposals"] if str(row.get("proposalId") or "").strip() not in proposal_ids]
        batches = [row for row in old["batches"] if str(row.get("batchId") or "").strip() not in batch_ids]
        items = [row for row in old["items"] if str(row.get("knowledgeItemId") or "").strip() not in item_ids]
        now = utc_now_iso()
        audit = list(old["audit"])
        audit.append(
            {
                "auditId": migration._stable_id("kaudit-purge", plan["purgeId"], "legacy-records"),
                "action": PURGE_ACTION,
                "actorAgentId": plan["operatorAgentId"],
                "createdAt": now,
                "payload": {
                    "purgeId": plan["purgeId"],
                    "removedKnowledgeItemIds": plan["legacyKnowledgeItemIds"],
                    "removedBatchIds": plan["legacyBatchIds"],
                    "removedProposalIds": plan["legacyProposalIds"],
                    "retainedSourceArtifactIds": plan["retainedSourceArtifactIds"],
                    "retainedCentralSourceIds": plan["retainedCentralSourceIds"],
                    "lineage": plan["lineageRows"],
                    "operatorAgentId": plan["operatorAgentId"],
                },
            }
        )
        audit.append(
            {
                "auditId": migration._stable_id("kaudit-purge-completed", plan["purgeId"], "terminal"),
                "action": TERMINAL_ACTION,
                "actorAgentId": plan["operatorAgentId"],
                "createdAt": now,
                "payload": {
                    "purgeId": plan["purgeId"],
                    "removedKnowledgeItemIds": plan["legacyKnowledgeItemIds"],
                    "removedBatchIds": plan["legacyBatchIds"],
                    "removedProposalIds": plan["legacyProposalIds"],
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
            if str(record.get("knowledgeItemId") or "").strip() in item_ids
        ]
        for record in old_vector_records:
            record_path = rag_vector_index_service._item_record_path(
                rag_vector_index_service._record_id_for_record(record)
            )
            if record_path.exists():
                record_path.unlink()
        rag_vector_index_service._write_index_summary(rag_vector_index_service._load_all_index_records())
    except Exception:
        migration._restore(plan)
        raise
    return {
        "status": "applied",
        "purgeId": plan["purgeId"],
        "backupPath": plan["backupPath"],
        "removedKnowledgeItemIds": plan["legacyKnowledgeItemIds"],
        "removedBatchIds": plan["legacyBatchIds"],
        "removedProposalIds": plan["legacyProposalIds"],
        "retainedSourceArtifactIds": plan["retainedSourceArtifactIds"],
        "retainedCentralSourceIds": plan["retainedCentralSourceIds"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--purge-id", required=True)
    parser.add_argument("--operator-agent-id", required=True)
    parser.add_argument("--backup-root", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--maintenance-window-confirmed", action="store_true")
    parser.add_argument("--expected-manifest-hash", default="")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        plan = build_purge_plan(
            team_id=args.team_id,
            knowledge_base_id=args.knowledge_base_id,
            purge_id=args.purge_id,
            operator_agent_id=args.operator_agent_id,
            backup_root=args.backup_root,
        )
        result = (
            apply_purge(
                plan,
                maintenance_window_confirmed=args.maintenance_window_confirmed,
                expected_manifest_hash=args.expected_manifest_hash,
            )
            if args.apply
            else {key: value for key, value in plan.items() if key not in {"records", "lineageRows", "paths"}}
        )
    except ChallengeCupKnowledgePurgeError as exc:
        print(
            json.dumps(
                {"status": "blocked", "mode": "apply" if args.apply else "dry-run", "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
