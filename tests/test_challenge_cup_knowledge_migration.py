from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import migrate_challenge_cup_knowledge_items as migration


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
        batches.append({"batchId": batch_id, "proposalIds": [proposal_id], "knowledgeBaseId": "kb-challenge"})
        items.append(
            {
                "knowledgeItemId": item_id,
                "knowledgeBaseId": "kb-challenge",
                "proposalId": proposal_id,
                "batchId": batch_id,
                "sourceArtifactIds": [f"artifact-{pack_index}"],
                "centralSourceIds": [f"central-{pack_index}"],
                "title": migration.LEGACY_TITLE,
                "content": content,
                "tags": ["challenge-cup", "candidate-only"],
            }
        )
    source_artifacts = []
    for pack_index in range(5):
        selected = candidates[pack_index * 7 : (pack_index + 1) * 7] if pack_index < 4 else candidates[28:]
        source_artifacts.append(
            {
                "sourceArtifactId": f"artifact-{pack_index}",
                "sourceRef": {
                    "candidateIds": [candidate["candidateId"] for candidate in selected],
                    "sourceTrace": {"sourceCollectionRunId": f"run-{pack_index}"},
                },
            }
        )
    for name, rows in {"proposals": proposals, "batches": batches, "items": items, "audit": [], "source_artifacts": source_artifacts}.items():
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


def _plan(tmp_path: Path, *, migration_id: str = "migration-001") -> dict:
    return migration.build_migration_plan(
        team_id="team-challenge",
        knowledge_base_id="team:team-challenge:kb-challenge",
        migration_id=migration_id,
        operator_agent_id="operator-agent",
        backup_root=tmp_path / f"backup-{migration_id}",
    )


def test_dry_run_requires_exact_five_legacy_packs_and_33_unique_sources(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, source_count=32)
    with pytest.raises(migration.ChallengeCupKnowledgeMigrationError, match="33 unique legacy sources"):
        _plan(tmp_path)


def test_apply_is_atomic_audited_and_idempotent(monkeypatch, tmp_path):
    paths = _seed(monkeypatch, tmp_path)
    plan = _plan(tmp_path)
    assert len(plan["legacyKnowledgeItemIds"]) == 5
    assert len(plan["legacyProposalIds"]) == 5
    assert len(plan["legacyBatchIds"]) == 5
    assert len(plan["sourceCandidateIds"]) == 33

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
    audits = migration._read_jsonl(paths["audit"])
    assert len([row for row in audits if row["action"] == migration.MIGRATION_ACTION]) == 33
    assert len([row for row in audits if row["action"] == migration.TERMINAL_ACTION]) == 1

    second = _plan(tmp_path)
    assert second["status"] == "already_applied"
    assert len(migration._read_jsonl(paths["items"])) == 33


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
