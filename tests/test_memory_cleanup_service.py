import sqlite3
from pathlib import Path

import pytest

from core.web.services import (
    agent_directory_service,
    chat_room_service,
    memory_cleanup_service,
    memory_service,
    rag_vector_index_service,
    team_knowledge_service,
    team_service,
)


@pytest.fixture()
def cleanup_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    for service in (
        agent_directory_service,
        chat_room_service,
        memory_cleanup_service,
        memory_service,
        team_knowledge_service,
        team_service,
    ):
        monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memory_cleanup_service, "record_runtime_scene_event", lambda *args, **kwargs: None)
    return tmp_path


def _write(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _promote_source_to_item(env: dict) -> dict:
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "cleanup test source"},
        original_content="Cleanup source file content.",
        original_filename="cleanup-source.txt",
        title="Cleanup source",
        actor_agent_id=env["member"]["agentId"],
    )
    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        env["team"]["teamId"],
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )
    source_artifact = team_knowledge_service.create_source_artifact_from_central_source(
        env["base"]["knowledgeBaseId"],
        reviewed["centralSource"]["centralSourceId"],
        actor_agent_id=env["member"]["agentId"],
        title="Cleanup artifact",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source_artifact["sourceArtifactId"]],
        proposed_by_agent_id=env["member"]["agentId"],
        title="Cleanup formal item",
        summary="Cleanup should remove this reviewed item.",
        content="This item should be hard-deleted from the owner KB and vector metadata.",
    )
    return team_knowledge_service.review_refinement_proposal(
        env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )["item"]


def _knowledge_env() -> dict:
    lead = agent_directory_service.create_agent_instance(display_name="Cleanup Lead")
    member = agent_directory_service.create_agent_instance(display_name="Cleanup Member")
    team = team_service.create_team(
        name="Cleanup Team",
        members=[
            {"agentId": lead["agentId"], "role": "lead"},
            {"agentId": member["agentId"], "role": "member"},
        ],
    )
    base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Cleanup Base",
        actor_agent_id=lead["agentId"],
        acl={"grants": {"review": [lead["agentId"]]}},
    )
    return {"lead": lead, "member": member, "team": team, "base": base}


def test_memory_cleanup_global_runtime_memory_preserves_non_memory_database_tables(cleanup_project: Path):
    db_file = cleanup_project / "workspace" / "agent_brain.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE LongTermMemory (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT)")
        conn.execute("CREATE TABLE GitCommit (commit_sha TEXT PRIMARY KEY, subject TEXT)")
        conn.execute("INSERT INTO LongTermMemory (content) VALUES ('delete me')")
        conn.execute("INSERT INTO GitCommit (commit_sha, subject) VALUES ('abc123', 'keep me')")
    memory_file = _write(cleanup_project / "workspace" / "memory" / "memory.json", '{"noise":true}')
    state_memory = _write(cleanup_project / "workspace" / "prompts" / "STATE_MEMORY.md", "state memory")
    dynamic_prompt = _write(cleanup_project / "workspace" / "prompts" / "DYNAMIC.md", "dynamic")

    preview = memory_cleanup_service.preview_memory_cleanup([{"targetType": "global_runtime_memory"}])

    assert preview["hardDelete"] is True
    assert preview["totals"]["databaseRowCount"] == 1
    assert preview["confirmationPhrase"] == memory_cleanup_service.CONFIRMATION_PHRASE

    result = memory_cleanup_service.execute_memory_cleanup(
        [{"targetType": "global_runtime_memory"}],
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
    )

    assert result["totals"]["targetCount"] == 1
    assert not memory_file.exists()
    assert state_memory.exists()
    assert state_memory.read_text(encoding="utf-8") == ""
    assert dynamic_prompt.exists()
    with sqlite3.connect(str(db_file)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM LongTermMemory").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM GitCommit").fetchone()[0] == 1
    assert (cleanup_project / "logs" / "memory_cleanup" / "memory_cleanup_audit.jsonl").exists()


def test_memory_cleanup_sqlite_compact_reclaims_free_pages_without_deleting_rows(cleanup_project: Path):
    db_file = cleanup_project / "workspace" / "agent_brain.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE GitCommit (commit_sha TEXT PRIMARY KEY, subject TEXT)")
        conn.executemany(
            "INSERT INTO GitCommit (commit_sha, subject) VALUES (?, ?)",
            [(f"sha-{index}", "x" * 4096) for index in range(600)],
        )
        conn.execute("DELETE FROM GitCommit WHERE commit_sha != 'sha-0'")
        conn.commit()

    preview = memory_cleanup_service.preview_memory_cleanup([{"targetType": "sqlite_database_compact"}])

    assert preview["totals"]["rowCount"] == 0
    assert preview["totals"]["databaseRowCount"] == 0
    assert preview["totals"]["byteCount"] > 0
    assert preview["targets"][0]["paths"][0]["kind"] == "database_compact"

    result = memory_cleanup_service.execute_memory_cleanup(
        [{"targetType": "sqlite_database_compact"}],
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
    )

    assert result["totals"]["byteCount"] > 0
    with sqlite3.connect(str(db_file)) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA freelist_count").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM GitCommit").fetchone()[0] == 1


def test_memory_cleanup_maintenance_artifacts_delete_noise_without_touching_protected_state(cleanup_project: Path):
    project_memory = _write(cleanup_project / ".docs" / "project-memory" / "memory.json", '{"keep":true}')
    current_team_run = _write(
        cleanup_project / "workspace" / "teams" / "research-team" / "source_collection_runs" / "current" / "records.jsonl",
        "{}\n",
    )
    cleanup_paths = [
        cleanup_project / "workspace" / "evaluation" / "chat_candidates" / "noise.json",
        cleanup_project / "workspace" / "sessions" / "session-a" / "logs" / "conversation.jsonl",
        cleanup_project / "log_info" / "debug.log",
        cleanup_project / "logs" / "runtime_scenes" / "scene-a" / "timeline.jsonl",
        cleanup_project / "workspace" / "teams" / "research-team" / "archives" / "old-run" / "records.jsonl",
    ]
    for path in cleanup_paths:
        _write(path, "noise")
    targets = [
        {"targetType": "evaluation_artifacts"},
        {"targetType": "session_artifacts"},
        {"targetType": "legacy_log_info"},
        {"targetType": "runtime_scene_logs"},
        {"targetType": "team_archive_artifacts"},
    ]

    preview = memory_cleanup_service.preview_memory_cleanup(targets)

    assert preview["totals"]["targetCount"] == 5
    assert preview["totals"]["fileCount"] == 5
    assert any(target["warnings"] for target in preview["targets"])

    result = memory_cleanup_service.execute_memory_cleanup(
        targets,
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
    )

    assert result["totals"]["fileCount"] == 5
    for path in cleanup_paths:
        assert not path.exists()
    assert project_memory.exists()
    assert current_team_run.exists()


def test_memory_cleanup_knowledge_base_removes_owner_records_and_vector_metadata(cleanup_project: Path):
    env = _knowledge_env()
    reviewed_item = _promote_source_to_item(env)
    indexable_item = next(
        item
        for item in rag_vector_index_service.list_indexable_knowledge_items(internal=True)
        if item["knowledgeItemId"] == reviewed_item["knowledgeItemId"]
    )
    rag_vector_index_service.write_index_record(indexable_item, embedding_provider="test", embedding_model="cleanup-v1")
    scoped_id = env["base"]["scopedKnowledgeBaseId"]
    central_registry = cleanup_project / "workspace" / "knowledge" / "sources" / "registry" / "source_registry.jsonl"

    preview = memory_cleanup_service.preview_memory_cleanup(
        [{"targetType": "knowledge_base", "knowledgeBaseId": scoped_id}]
    )

    assert preview["totals"]["knowledgeBaseCount"] == 1
    assert preview["totals"]["knowledgeItemCount"] == 1
    assert preview["totals"]["vectorRecordCount"] == 1
    assert central_registry.exists()

    result = memory_cleanup_service.execute_memory_cleanup(
        [{"targetType": "knowledge_base", "knowledgeBaseId": scoped_id}],
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
    )

    assert result["totals"]["vectorRecordCount"] == 1
    assert central_registry.exists()
    owner = {"ownerType": "team", "ownerId": env["team"]["teamId"]}
    assert team_knowledge_service._load_bases_state_for_owner(owner)["knowledgeBases"] == []
    assert team_knowledge_service._read_jsonl(team_knowledge_service._items_path_for_owner(owner)) == []
    assert team_knowledge_service._read_jsonl(team_knowledge_service._source_artifacts_path_for_owner(owner)) == []
    assert rag_vector_index_service._load_all_index_records() == []


def test_memory_cleanup_agent_private_memory_and_policy_reset(cleanup_project: Path):
    agent = agent_directory_service.create_agent_instance(display_name="Cleanup Agent")
    memory_file = _write(cleanup_project / "workspace" / "agents" / agent["agentId"] / "memory" / "scratch.md", "delete")

    result = memory_cleanup_service.execute_memory_cleanup(
        [
            {"targetType": "agent_private_memory", "agentId": agent["agentId"]},
            {"targetType": "agent_memory_policy", "agentId": agent["agentId"]},
        ],
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
    )

    assert result["totals"]["targetCount"] == 2
    assert result["totals"]["memoryPolicyResetCount"] == 1
    assert not memory_file.exists()
    refreshed = agent_directory_service.get_agent(agent["agentId"])
    assert refreshed is not None
    assert refreshed["workspacePath"] == f"workspace/agents/{agent['agentId']}"
    assert refreshed["memoryPolicyId"]


def test_memory_cleanup_execute_requires_exact_confirmation(cleanup_project: Path):
    with pytest.raises(memory_cleanup_service.MemoryCleanupError):
        memory_cleanup_service.execute_memory_cleanup(
            [{"targetType": "global_runtime_memory"}],
            confirmation_phrase="delete",
        )
