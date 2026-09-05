from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import migrate_challenge_cup_knowledge_items as migration
from scripts import purge_challenge_cup_legacy_knowledge as purge


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _seed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, source_count: int = 33) -> dict[str, Path]:
    workspace = tmp_path / "workspace"
    knowledge_root = workspace / "teams" / "team-challenge" / "knowledge"
    paths = {
        "proposals": knowledge_root / "refinement_proposals.jsonl",
        **{name: knowledge_root / f"{name}.jsonl" for name in ("batches", "items", "audit", "source_artifacts")},
    }
    candidates = []
    proposals = []
    batches = []
    items = []
    audit = []
    direct_ingested_pack_indexes = {1, 2, 3}
    for index in range(source_count):
        candidates.append(
            {
                "candidateId": f"source-{index:02d}",
                "title": f"真实来源 {index:02d}",
                "summary": f"来源 {index:02d} 的多条证据。",
                "sourceUrl": f"https://example.test/{index:02d}",
                "createdByAgent": "source-agent",
                "qualityStatus": "approved",
                "metadata": {"evidenceLevel": "peer_reviewed", "researchProjectId": f"project-{index // 7}"},
            }
        )
    for pack_index in range(5):
        selected = candidates[pack_index * 7 : (pack_index + 1) * 7] if pack_index < 4 else candidates[28:]
        proposal_id = f"old-proposal-{pack_index}"
        batch_id = f"old-batch-{pack_index}"
        item_id = f"old-item-{pack_index}"
        content = json.dumps(
            {
                "claims": [
                    {"claim": f"{candidate['candidateId']} claim A", "sourceRef": candidate["candidateId"]}
                    for candidate in selected
                ],
                "sourceTrace": {"sourceCandidateIds": [candidate["candidateId"] for candidate in selected]},
            },
            ensure_ascii=False,
        )
        if pack_index not in direct_ingested_pack_indexes:
            proposals.append(
                {
                    "proposalId": proposal_id,
                    "targetKnowledgeBaseId": "kb-challenge",
                    "sourceArtifactIds": [f"artifact-{pack_index}"],
                    "centralSourceIds": [f"central-{pack_index}"],
                    "title": migration.LEGACY_TITLE,
                    "content": content,
                    "tags": ["challenge-cup", "pending-review"],
                    "batchId": batch_id,
                }
            )
        batches.append(
            {
                "batchId": batch_id,
                "proposalIds": [] if pack_index in direct_ingested_pack_indexes else [proposal_id],
                "knowledgeBaseId": "kb-challenge",
                "sourceArtifactIds": [f"artifact-{pack_index}"],
                "centralSourceIds": [f"central-{pack_index}"],
            }
        )
        items.append(
            {
                "knowledgeItemId": item_id,
                "knowledgeBaseId": "kb-challenge",
                "proposalId": None,
                "batchId": batch_id,
                "sourceArtifactIds": [f"artifact-{pack_index}"],
                "centralSourceIds": [f"central-{pack_index}"],
                "title": migration.LEGACY_TITLE,
                "content": content,
                "tags": ["challenge-cup", "candidate-only"],
            }
        )
        if pack_index in direct_ingested_pack_indexes:
            audit.append(
                {
                    "auditId": f"old-direct-audit-{pack_index}",
                    "action": "knowledge.item.direct_ingested",
                    "payload": {
                        "teamId": "team-challenge",
                        "knowledgeBaseId": "kb-challenge",
                        "batchId": batch_id,
                        "knowledgeItemId": item_id,
                        "proposalId": None,
                    },
                }
            )
    source_artifacts = []
    for pack_index in range(5):
        selected = candidates[pack_index * 7 : (pack_index + 1) * 7] if pack_index < 4 else candidates[28:]
        source_artifacts.append(
            {
                "sourceArtifactId": f"artifact-{pack_index}",
                "centralSourceId": f"central-{pack_index}",
                "sourceRef": {
                    "centralSourceId": f"central-{pack_index}",
                    "candidateIds": [candidate["candidateId"] for candidate in selected],
                    "sourceTrace": {"sourceCollectionRunId": f"run-{pack_index}"},
                },
            }
        )
    for name, rows in {"proposals": proposals, "batches": batches, "items": items, "audit": audit, "source_artifacts": source_artifacts}.items():
        _write_jsonl(paths[name], rows)

    team = {
        "teamId": "team-challenge",
        "members": [
            {"agentId": "source-agent", "role": "source_ingestor"},
            {"agentId": "knowledge-manager", "role": "challenge_cup_knowledge_manager"},
        ],
    }
    (workspace / "teams").mkdir(parents=True, exist_ok=True)
    (workspace / "teams" / "teams.json").write_text(json.dumps({"teams": [team]}), encoding="utf-8")
    knowledge_root.mkdir(parents=True, exist_ok=True)
    (knowledge_root / "knowledge_bases.json").write_text(
        json.dumps({"knowledgeBases": [{"knowledgeBaseId": "kb-challenge", "ownerType": "team", "ownerId": "team-challenge"}]}),
        encoding="utf-8",
    )
    projects_root = workspace / "teams" / "team-challenge" / "research_projects"
    projects = [
        {"projectId": f"project-{index}", "challengeQuestionId": f"SCI-{index:03d}"}
        for index in range(5)
    ]
    projects_root.mkdir(parents=True, exist_ok=True)
    (projects_root / "index.json").write_text(json.dumps({"projects": projects}), encoding="utf-8")
    for index in range(5):
        store_path = projects_root / f"project-{index}" / "workspace" / "candidate_store" / "index.json"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        selected = [candidate for candidate in candidates if int(candidate["candidateId"].rsplit("-", 1)[-1]) // 7 == index]
        store_path.write_text(json.dumps({"candidates": selected}), encoding="utf-8")
    monkeypatch.setattr(migration.team_knowledge_service, "_route_team_knowledge_workspace_path", lambda seed=False: workspace)
    vector_root = tmp_path / "vector"
    (vector_root / "items").mkdir(parents=True)
    for index in range(5):
        (vector_root / "items" / f"old-item-{index}.json").write_text(
            json.dumps({"knowledgeItemId": f"old-item-{index}"}), encoding="utf-8"
        )
    monkeypatch.setattr(migration.rag_vector_index_service, "_index_root", lambda: vector_root)
    monkeypatch.setattr(
        migration.rag_vector_index_service,
        "_item_record_path",
        lambda item_id: vector_root / "items" / f"{item_id}.json",
    )
    return paths


def _plan(
    tmp_path: Path,
    *,
    migration_id: str = "migration-001",
    legacy_snapshot_root: Path | None = None,
) -> dict:
    return migration.build_migration_plan(
        team_id="team-challenge",
        knowledge_base_id="team:team-challenge:kb-challenge",
        migration_id=migration_id,
        operator_agent_id="operator-agent",
        backup_root=tmp_path / f"backup-{migration_id}",
        legacy_snapshot_root=legacy_snapshot_root,
    )


def _purge_plan(tmp_path: Path, *, purge_id: str = "purge-001") -> dict:
    return purge.build_purge_plan(
        team_id="team-challenge",
        knowledge_base_id="team:team-challenge:kb-challenge",
        purge_id=purge_id,
        operator_agent_id="operator-agent",
        backup_root=tmp_path / f"backup-{purge_id}",
    )


def test_dry_run_requires_exact_five_legacy_packs_and_33_unique_sources(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, source_count=32)
    with pytest.raises(migration.ChallengeCupKnowledgeMigrationError, match="33 unique legacy sources"):
        _plan(tmp_path)


def test_apply_is_atomic_audited_and_idempotent(monkeypatch, tmp_path):
    paths = _seed(monkeypatch, tmp_path)
    plan = _plan(tmp_path)
    assert len(plan["legacyKnowledgeItemIds"]) == 5
    assert len(plan["legacyProposalIds"]) == 2
    assert len(plan["legacyBatchIds"]) == 5
    assert plan["directIngestedBatchIds"] == ["old-batch-1", "old-batch-2", "old-batch-3"]
    assert len(plan["sourceCandidateIds"]) == 33
    assert {row["legacyIngestionMode"] for row in plan["sourceRows"]} == {"proposal_backed", "direct_ingested"}
    assert all(
        row["oldProposalId"] is None
        for row in plan["sourceRows"]
        if row["legacyIngestionMode"] == "direct_ingested"
    )

    result = migration.apply_migration(
        plan,
        maintenance_window_confirmed=True,
        expected_manifest_hash=plan["manifestHash"],
    )
    assert result["status"] == "applied"
    items = migration._read_jsonl(paths["items"])
    assert len(items) == 33
    assert len({item["sourceCandidateId"] for item in items}) == 33
    assert all(item["lifecycleStatus"] == "applied" for item in items)
    assert all("candidate-only" not in item["tags"] and "pending-review" not in item["tags"] for item in items)
    assert all(item["requiredReviewerAgentId"] == "knowledge-manager" for item in items)
    assert all(item["title"].startswith("真实来源") for item in items)
    proposals = migration._read_jsonl(paths["proposals"])
    assert len(proposals) == 33
    assert all("candidate-only" not in row["tags"] and "pending-review" not in row["tags"] for row in proposals)
    audits = migration._read_jsonl(paths["audit"])
    migration_audits = [row for row in audits if row["action"] == migration.MIGRATION_ACTION]
    assert len(migration_audits) == 33
    assert {row["payload"]["legacyIngestionMode"] for row in migration_audits} == {
        "proposal_backed",
        "direct_ingested",
    }
    assert all(
        row["payload"]["oldProposalId"] is None
        for row in migration_audits
        if row["payload"]["legacyIngestionMode"] == "direct_ingested"
    )
    assert len([row for row in audits if row["action"] == migration.TERMINAL_ACTION]) == 1

    second = _plan(tmp_path)
    assert second["status"] == "already_applied"
    assert len(migration._read_jsonl(paths["items"])) == 33


def test_migration_can_resume_from_completed_purge_backup_without_reviving_legacy_items(monkeypatch, tmp_path):
    paths = _seed(monkeypatch, tmp_path)
    purge_plan = _purge_plan(tmp_path, purge_id="purge-before-migration")
    purge.apply_purge(
        purge_plan,
        maintenance_window_confirmed=True,
        expected_manifest_hash=purge_plan["manifestHash"],
    )
    assert migration._read_jsonl(paths["items"]) == []
    assert migration._read_jsonl(paths["batches"]) == []
    assert migration._read_jsonl(paths["proposals"]) == []

    plan = _plan(
        tmp_path,
        migration_id="migration-after-purge",
        legacy_snapshot_root=Path(purge_plan["backupPath"]),
    )
    assert plan["resumeFromPurgeId"] == "purge-before-migration"
    assert len(plan["sourceCandidateIds"]) == 33

    migration.apply_migration(
        plan,
        maintenance_window_confirmed=True,
        expected_manifest_hash=plan["manifestHash"],
    )
    assert len(migration._read_jsonl(paths["items"])) == 33
    assert len(migration._read_jsonl(paths["batches"])) == 33
    assert len(migration._read_jsonl(paths["proposals"])) == 33
    audits = migration._read_jsonl(paths["audit"])
    assert len([row for row in audits if row["action"] == purge.TERMINAL_ACTION]) == 1
    assert len([row for row in audits if row["action"] == migration.TERMINAL_ACTION]) == 1


def test_post_purge_resume_requires_matching_completed_purge_audit(monkeypatch, tmp_path):
    paths = _seed(monkeypatch, tmp_path)
    purge_plan = _purge_plan(tmp_path, purge_id="purge-without-live-audit")
    purge.apply_purge(
        purge_plan,
        maintenance_window_confirmed=True,
        expected_manifest_hash=purge_plan["manifestHash"],
    )
    audits = [row for row in migration._read_jsonl(paths["audit"]) if row["action"] != purge.TERMINAL_ACTION]
    _write_jsonl(paths["audit"], audits)

    with pytest.raises(migration.ChallengeCupKnowledgeMigrationError, match="matching completed purge audit"):
        _plan(tmp_path, legacy_snapshot_root=Path(purge_plan["backupPath"]))


def test_post_purge_resume_restores_empty_live_store_when_write_is_interrupted(monkeypatch, tmp_path):
    paths = _seed(monkeypatch, tmp_path)
    purge_plan = _purge_plan(tmp_path, purge_id="purge-before-interruption")
    purge.apply_purge(
        purge_plan,
        maintenance_window_confirmed=True,
        expected_manifest_hash=purge_plan["manifestHash"],
    )
    before = {name: path.read_bytes() for name, path in paths.items()}
    plan = _plan(
        tmp_path,
        migration_id="migration-post-purge-failure",
        legacy_snapshot_root=Path(purge_plan["backupPath"]),
    )
    real_write = migration.team_knowledge_service._write_jsonl
    calls = 0

    def interrupted(path, rows):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated post-purge interruption")
        return real_write(path, rows)

    monkeypatch.setattr(migration.team_knowledge_service, "_write_jsonl", interrupted)
    with pytest.raises(OSError, match="simulated post-purge interruption"):
        migration.apply_migration(
            plan,
            maintenance_window_confirmed=True,
            expected_manifest_hash=plan["manifestHash"],
        )
    assert {name: path.read_bytes() for name, path in paths.items()} == before


def test_apply_restores_all_files_when_write_is_interrupted(monkeypatch, tmp_path):
    paths = _seed(monkeypatch, tmp_path)
    before = {name: path.read_bytes() for name, path in paths.items()}
    plan = _plan(tmp_path, migration_id="migration-failure")
    real_write = migration.team_knowledge_service._write_jsonl
    calls = 0

    def interrupted(path, rows):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated interruption")
        return real_write(path, rows)

    monkeypatch.setattr(migration.team_knowledge_service, "_write_jsonl", interrupted)
    with pytest.raises(OSError, match="simulated interruption"):
        migration.apply_migration(
            plan,
            maintenance_window_confirmed=True,
            expected_manifest_hash=plan["manifestHash"],
        )
    assert {name: path.read_bytes() for name, path in paths.items()} == before


@pytest.mark.parametrize("audit_fault", ["missing", "duplicate"])
def test_dry_run_rejects_direct_ingested_batch_without_unique_audit(monkeypatch, tmp_path, audit_fault):
    paths = _seed(monkeypatch, tmp_path)
    audit = migration._read_jsonl(paths["audit"])
    broken = audit[:-1] if audit_fault == "missing" else audit + [dict(audit[-1], auditId="duplicate-direct-audit")]
    _write_jsonl(paths["audit"], broken)

    with pytest.raises(migration.ChallengeCupKnowledgeMigrationError, match="one direct-ingest audit"):
        _plan(tmp_path)


def test_dry_run_rejects_conflicting_central_source_mapping(monkeypatch, tmp_path):
    paths = _seed(monkeypatch, tmp_path)
    batches = migration._read_jsonl(paths["batches"])
    batches[1]["centralSourceIds"] = ["wrong-central-source"]
    _write_jsonl(paths["batches"], batches)

    with pytest.raises(migration.ChallengeCupKnowledgeMigrationError, match="central source mapping is not unique"):
        _plan(tmp_path)


def test_dry_run_reports_every_missing_authoritative_candidate(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    store_path = (
        workspace
        / "teams"
        / "team-challenge"
        / "research_projects"
        / "project-0"
        / "workspace"
        / "candidate_store"
        / "index.json"
    )
    store = json.loads(store_path.read_text(encoding="utf-8"))
    store["candidates"] = store["candidates"][2:]
    store_path.write_text(json.dumps(store), encoding="utf-8")

    with pytest.raises(
        migration.ChallengeCupKnowledgeMigrationError,
        match=r"missing and cannot be recovered from unique DataRecords \(2\): source-00, source-01",
    ):
        _plan(tmp_path)


def test_dry_run_recovers_missing_candidate_from_unique_authoritative_data_record(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    store_path = (
        workspace
        / "teams"
        / "team-challenge"
        / "research_projects"
        / "project-0"
        / "workspace"
        / "candidate_store"
        / "index.json"
    )
    store = json.loads(store_path.read_text(encoding="utf-8"))
    store["candidates"] = [candidate for candidate in store["candidates"] if candidate["candidateId"] != "source-00"]
    store_path.write_text(json.dumps(store), encoding="utf-8")

    run_root = workspace / "data_processing" / "runs" / "run-0"
    run_root.mkdir(parents=True)
    (run_root / "run.json").write_text(
        json.dumps(
            {
                "runId": "run-0",
                "profileId": "generic_document_processing",
                "title": "Authoritative source run",
                "scope": {
                    "teamId": "team-challenge",
                    "researchProjectId": "project-0",
                    "questionId": "SCI-000",
                },
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        run_root / "records.jsonl",
        [
            {
                "recordId": "record-source-00",
                "runId": "run-0",
                "title": "恢复的真实来源 00",
                "summary": "source-00 claim A",
                "sourceRef": "https://example.test/recovered-00",
                "rawLocation": "https://example.test/recovered-00",
                "sourceType": "paper",
                "status": "ready_for_review",
                "collectionTrace": {"agentId": "source-agent", "agentRole": "source_finder"},
                "metadata": {"sourceIdentityKey": "url:https://example.test/recovered-00"},
                "qualitySignals": {"sourceIdentityKey": "url:https://example.test/recovered-00"},
            }
        ],
    )
    _write_jsonl(
        run_root / "collection_assignments.jsonl",
        [{"assignmentId": "assignment-00", "agentId": "source-agent", "agentRole": "source_finder"}],
    )

    plan = _plan(tmp_path)

    assert plan["recoveredSourceCandidateIds"] == ["source-00"]
    recovered = next(row for row in plan["sourceRows"] if row["sourceCandidateId"] == "source-00")
    assert recovered["sourceRecovery"] == {
        "sourceCollectionRunId": "run-0",
        "sourceRecordId": "record-source-00",
    }
    assert recovered["item"]["title"] == "恢复的真实来源 00"
    assert recovered["item"]["sourceIdentityHash"] == "sha256:" + hashlib.sha256(
        b"url:https://example.test/recovered-00"
    ).hexdigest()
    assert recovered["item"]["evidenceLevel"] == "source_quality_approved"
    assert recovered["proposal"]["proposedByAgentId"] == "source-agent"


def test_dry_run_rejects_ambiguous_data_record_recovery(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path)
    workspace = tmp_path / "workspace"
    store_path = (
        workspace
        / "teams"
        / "team-challenge"
        / "research_projects"
        / "project-0"
        / "workspace"
        / "candidate_store"
        / "index.json"
    )
    store = json.loads(store_path.read_text(encoding="utf-8"))
    store["candidates"] = [candidate for candidate in store["candidates"] if candidate["candidateId"] != "source-00"]
    store_path.write_text(json.dumps(store), encoding="utf-8")
    run_root = workspace / "data_processing" / "runs" / "run-0"
    run_root.mkdir(parents=True)
    (run_root / "run.json").write_text(
        json.dumps(
            {
                "runId": "run-0",
                "scope": {
                    "teamId": "team-challenge",
                    "researchProjectId": "project-0",
                    "questionId": "SCI-000",
                },
            }
        ),
        encoding="utf-8",
    )
    duplicate = {
        "runId": "run-0",
        "title": "Ambiguous source",
        "summary": "source-00 claim A",
        "sourceRef": "https://example.test/ambiguous",
        "sourceType": "paper",
        "status": "ready_for_review",
        "collectionTrace": {"agentId": "source-agent"},
        "metadata": {"sourceIdentityKey": "url:https://example.test/ambiguous"},
    }
    _write_jsonl(
        run_root / "records.jsonl",
        [dict(duplicate, recordId="record-a"), dict(duplicate, recordId="record-b")],
    )
    _write_jsonl(run_root / "collection_assignments.jsonl", [{"agentId": "source-agent"}])

    with pytest.raises(migration.ChallengeCupKnowledgeMigrationError, match="unique matching DataRecord"):
        _plan(tmp_path)


def test_legacy_purge_removes_only_searchable_records_and_is_idempotent(monkeypatch, tmp_path):
    paths = _seed(monkeypatch, tmp_path)
    proposals = migration._read_jsonl(paths["proposals"])
    batches = migration._read_jsonl(paths["batches"])
    items = migration._read_jsonl(paths["items"])
    proposals.append({"proposalId": "keep-proposal", "title": "保留"})
    batches.append({"batchId": "keep-batch", "proposalIds": ["keep-proposal"]})
    items.append(
        {
            "knowledgeItemId": "keep-item",
            "knowledgeBaseId": "kb-challenge",
            "sourceCandidateId": "keep-source",
            "lifecycleStatus": "applied",
            "batchId": "keep-batch",
        }
    )
    _write_jsonl(paths["proposals"], proposals)
    _write_jsonl(paths["batches"], batches)
    _write_jsonl(paths["items"], items)
    source_artifacts_before = paths["source_artifacts"].read_bytes()

    plan = _purge_plan(tmp_path)
    assert plan["legacyKnowledgeItemIds"] == [f"old-item-{index}" for index in range(5)]
    assert plan["legacyBatchIds"] == [f"old-batch-{index}" for index in range(5)]
    assert plan["legacyProposalIds"] == ["old-proposal-0", "old-proposal-4"]
    assert plan["directIngestedBatchIds"] == ["old-batch-1", "old-batch-2", "old-batch-3"]
    assert len(plan["sourceCandidateIds"]) == 33

    result = purge.apply_purge(
        plan,
        maintenance_window_confirmed=True,
        expected_manifest_hash=plan["manifestHash"],
    )
    assert result["status"] == "applied"
    assert [row["knowledgeItemId"] for row in migration._read_jsonl(paths["items"])] == ["keep-item"]
    assert [row["batchId"] for row in migration._read_jsonl(paths["batches"])] == ["keep-batch"]
    assert [row["proposalId"] for row in migration._read_jsonl(paths["proposals"])] == ["keep-proposal"]
    assert paths["source_artifacts"].read_bytes() == source_artifacts_before
    audits = migration._read_jsonl(paths["audit"])
    assert len([row for row in audits if row["action"] == purge.PURGE_ACTION]) == 1
    assert len([row for row in audits if row["action"] == purge.TERMINAL_ACTION]) == 1
    assert Path(plan["backupPath"], "manifest.json").exists()
    assert not any((tmp_path / "vector" / "items").glob("old-item-*.json"))

    second = _purge_plan(tmp_path)
    assert second["status"] == "already_applied"


def test_legacy_purge_restores_files_and_vector_index_on_interruption(monkeypatch, tmp_path):
    paths = _seed(monkeypatch, tmp_path)
    before = {name: path.read_bytes() for name, path in paths.items()}
    vector_before = {
        path.name: path.read_bytes()
        for path in (tmp_path / "vector" / "items").glob("*.json")
    }
    plan = _purge_plan(tmp_path, purge_id="purge-failure")
    real_write = purge.team_knowledge_service._write_jsonl
    calls = 0

    def interrupted(path, rows):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated purge interruption")
        return real_write(path, rows)

    monkeypatch.setattr(purge.team_knowledge_service, "_write_jsonl", interrupted)
    with pytest.raises(OSError, match="simulated purge interruption"):
        purge.apply_purge(
            plan,
            maintenance_window_confirmed=True,
            expected_manifest_hash=plan["manifestHash"],
        )
    assert {name: path.read_bytes() for name, path in paths.items()} == before
    assert {
        path.name: path.read_bytes()
        for path in (tmp_path / "vector" / "items").glob("*.json")
    } == vector_before


def test_legacy_purge_rejects_target_count_drift(monkeypatch, tmp_path):
    paths = _seed(monkeypatch, tmp_path)
    _write_jsonl(paths["items"], migration._read_jsonl(paths["items"])[:-1])

    with pytest.raises(purge.ChallengeCupKnowledgePurgeError, match="exactly 5 legacy items"):
        _purge_plan(tmp_path)
