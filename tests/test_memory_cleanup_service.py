import sqlite3
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from core.web.services.team_knowledge import semantic as knowledge_semantic_service

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
def cleanup_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
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
    with memory_cleanup_service._CLEANUP_OPERATION_LOCK:
        memory_cleanup_service._PREVIEW_GRANTS.clear()
    yield tmp_path
    with memory_cleanup_service._CLEANUP_OPERATION_LOCK:
        memory_cleanup_service._PREVIEW_GRANTS.clear()


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


def _promote_agent_source_to_item(agent_id: str, knowledge_base_id: str) -> dict:
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "agent",
        agent_id,
        source_type="agent_authored",
        source_ref={"note": "private cleanup race test"},
        original_content="Private Agent knowledge must not retain an orphan vector after cleanup.",
        original_filename="private-cleanup-source.txt",
        title="Private cleanup source",
        actor_agent_id=agent_id,
    )
    reviewed = team_knowledge_service.review_owner_inbox_source(
        "agent",
        agent_id,
        inbox_source["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=agent_id,
    )
    source_artifact = team_knowledge_service.create_source_artifact_from_central_source(
        knowledge_base_id,
        reviewed["centralSource"]["centralSourceId"],
        actor_agent_id=agent_id,
        title="Private cleanup source",
    )
    proposal = team_knowledge_service.create_refinement_proposal(
        knowledge_base_id,
        source_artifact_ids=[source_artifact["sourceArtifactId"]],
        proposed_by_agent_id=agent_id,
        title="Private cleanup race item",
        content="Private Agent knowledge must not retain an orphan vector after cleanup.",
    )
    return team_knowledge_service.review_refinement_proposal(
        knowledge_base_id,
        proposal["proposalId"],
        status="approved",
        reviewed_by_agent_id=agent_id,
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
        preview_token=preview["previewToken"],
    )

    assert result["totals"]["targetCount"] == 1
    assert not memory_file.exists()
    assert state_memory.exists()
    assert state_memory.read_text(encoding="utf-8") == ""
    assert dynamic_prompt.exists()
    with sqlite3.connect(str(db_file)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM LongTermMemory").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM GitCommit").fetchone()[0] == 1
    audit_path = cleanup_project / "logs" / "memory_cleanup" / "memory_cleanup_audit.jsonl"
    assert audit_path.exists()
    assert preview["previewToken"] not in audit_path.read_text(encoding="utf-8")


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
        preview_token=preview["previewToken"],
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
        preview_token=preview["previewToken"],
    )

    assert result["totals"]["fileCount"] == 5
    for path in cleanup_paths:
        assert not path.exists()
    assert project_memory.exists()
    assert current_team_run.exists()


def test_memory_cleanup_knowledge_base_removes_only_selected_base_records_and_vectors(cleanup_project: Path):
    env = _knowledge_env()
    reviewed_item = _promote_source_to_item(env)
    preserved_base = team_knowledge_service.create_knowledge_base(
        env["team"]["teamId"],
        name="Preserved Base",
        actor_agent_id=env["lead"]["agentId"],
    )
    preserved_item = _promote_source_to_item({**env, "base": preserved_base})
    indexable_items = {
        item["knowledgeItemId"]: item
        for item in rag_vector_index_service.list_indexable_knowledge_items(internal=True)
    }
    for item_id in (reviewed_item["knowledgeItemId"], preserved_item["knowledgeItemId"]):
        rag_vector_index_service.write_index_record(
            indexable_items[item_id],
            embedding_provider="test",
            embedding_model="cleanup-v1",
            chunks=[{"start": 0, "end": 1, "vector": [1.0, 0.0]}],
        )
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
        preview_token=preview["previewToken"],
    )

    assert result["totals"]["vectorRecordCount"] == 1
    assert central_registry.exists()
    owner = {"ownerType": "team", "ownerId": env["team"]["teamId"]}
    remaining_bases = team_knowledge_service._load_bases_state_for_owner(owner)["knowledgeBases"]
    remaining_items = team_knowledge_service._read_jsonl(team_knowledge_service._items_path_for_owner(owner))
    assert [base["knowledgeBaseId"] for base in remaining_bases] == [preserved_base["knowledgeBaseId"]]
    assert [item["knowledgeItemId"] for item in remaining_items] == [preserved_item["knowledgeItemId"]]
    assert [record["knowledgeItemId"] for record in rag_vector_index_service._load_all_index_records()] == [
        preserved_item["knowledgeItemId"]
    ]


def test_memory_cleanup_private_knowledge_base_still_hard_deletes_only_its_owner_rows(cleanup_project: Path):
    agent = agent_directory_service.create_agent_instance(display_name="Private Knowledge Owner")
    base = team_knowledge_service.create_agent_knowledge_base(
        agent["agentId"],
        name="Private Base",
        actor_agent_id=agent["agentId"],
    )
    target = {
        "targetType": "knowledge_base",
        "ownerType": "agent",
        "ownerId": agent["agentId"],
        "knowledgeBaseId": base["knowledgeBaseId"],
    }

    preview = memory_cleanup_service.preview_memory_cleanup([target])
    result = memory_cleanup_service.execute_memory_cleanup(
        [target],
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
        preview_token=preview["previewToken"],
    )

    assert result["outcome"] == "succeeded"
    owner = {"ownerType": "agent", "ownerId": agent["agentId"]}
    assert team_knowledge_service._load_bases_state_for_owner(owner)["knowledgeBases"] == []
    assert team_knowledge_service._read_jsonl(team_knowledge_service._items_path_for_owner(owner)) == []
    assert rag_vector_index_service._load_all_index_records() == []


@pytest.mark.parametrize("target_type", ["knowledge_base", "agent_formal_knowledge", "team_knowledge"])
def test_memory_cleanup_waits_for_inflight_semantic_publish_then_removes_its_vector(
    cleanup_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_type: str,
):
    sync_reviewed_item = knowledge_semantic_service.sync_reviewed_item
    monkeypatch.setattr(knowledge_semantic_service, "sync_reviewed_item", lambda *args, **kwargs: {"status": "unavailable"})
    if target_type == "agent_formal_knowledge":
        publisher_agent = agent_directory_service.create_agent_instance(display_name="Private Cleanup Publisher")
        base = team_knowledge_service.create_agent_knowledge_base(
            publisher_agent["agentId"],
            name="Private Cleanup Base",
            actor_agent_id=publisher_agent["agentId"],
        )
        reviewed_item = _promote_agent_source_to_item(publisher_agent["agentId"], base["knowledgeBaseId"])
        owner = {"ownerType": "agent", "ownerId": publisher_agent["agentId"]}
        target = {"targetType": target_type, "agentId": publisher_agent["agentId"]}
    else:
        env = _knowledge_env()
        base = env["base"]
        publisher_agent = env["lead"]
        reviewed_item = _promote_source_to_item(env)
        owner = {"ownerType": "team", "ownerId": env["team"]["teamId"]}
        if target_type == "team_knowledge":
            target = {"targetType": target_type, "teamId": env["team"]["teamId"]}
        else:
            target = {
                "targetType": target_type,
                "knowledgeBaseId": base.get("scopedKnowledgeBaseId") or base["knowledgeBaseId"],
            }
    monkeypatch.setattr(knowledge_semantic_service, "sync_reviewed_item", sync_reviewed_item)
    indexable_item = next(
        item
        for item in rag_vector_index_service.list_indexable_knowledge_items(internal=True)
        if item["knowledgeItemId"] == reviewed_item["knowledgeItemId"]
    )
    rag_vector_index_service.write_index_record(
        indexable_item,
        embedding_provider="test",
        embedding_model="cleanup-v1",
        chunks=[{"start": 0, "end": 1, "vector": [1.0, 0.0]}],
    )
    preview = memory_cleanup_service.preview_memory_cleanup([target])
    assert preview["totals"]["vectorRecordCount"] == 1

    monkeypatch.setattr(knowledge_semantic_service, "DEFAULT_EMBEDDING_DIMENSION", 2)
    monkeypatch.setattr(
        knowledge_semantic_service.embeddings,
        "readiness",
        lambda **_: {"status": "ready", "cached": True},
    )
    monkeypatch.setattr(
        knowledge_semantic_service.embeddings,
        "encode",
        lambda texts, **_: [[1.0, 0.0] for _ in texts],
    )

    publish_write_entered = threading.Event()
    allow_publish_write = threading.Event()
    cleanup_lock_attempted = threading.Event()
    cleanup_started = threading.Event()
    cleanup_thread_id: int | None = None
    original_write_index_record = rag_vector_index_service.write_index_record

    def block_publish_after_canonical_validation(item, **kwargs):
        publish_write_entered.set()
        if not allow_publish_write.wait(timeout=5):
            raise TimeoutError("test did not release the paused semantic publisher")
        return original_write_index_record(item, **kwargs)

    underlying_knowledge_lock = team_knowledge_service._LOCK

    class CleanupObservedRLock:
        def acquire(self, *args, **kwargs):
            if threading.get_ident() == cleanup_thread_id:
                cleanup_lock_attempted.set()
            return underlying_knowledge_lock.acquire(*args, **kwargs)

        def release(self):
            return underlying_knowledge_lock.release()

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.release()
            return False

    monkeypatch.setattr(rag_vector_index_service, "write_index_record", block_publish_after_canonical_validation)
    monkeypatch.setattr(team_knowledge_service, "_LOCK", CleanupObservedRLock())

    def run_cleanup():
        nonlocal cleanup_thread_id
        cleanup_thread_id = threading.get_ident()
        cleanup_started.set()
        return memory_cleanup_service.execute_memory_cleanup(
            [target],
            confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
            preview_token=preview["previewToken"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        publisher = pool.submit(
            knowledge_semantic_service.sync_reviewed_item,
            base["knowledgeBaseId"],
            reviewed_item,
            agent_id=publisher_agent["agentId"],
        )
        cleanup = None
        try:
            write_started = publish_write_entered.wait(timeout=5)
            assert write_started, (
                "publisher did not reach post-validation vector write; "
                f"error={publisher.exception(timeout=0) if publisher.done() else 'still running'}"
            )
            cleanup = pool.submit(run_cleanup)
            assert cleanup_started.wait(timeout=5)
            assert cleanup_lock_attempted.wait(timeout=5), "cleanup did not attempt the canonical knowledge lock"
            assert not cleanup.done(), "cleanup passed the publisher while it held the canonical lock"
        finally:
            allow_publish_write.set()

        publish_result = publisher.result(timeout=5)
        cleanup_result = cleanup.result(timeout=5) if cleanup is not None else {}

    assert publish_result == {"status": "indexed", "embeddingModel": knowledge_semantic_service.embeddings.DEFAULT_MODEL_NAME}
    assert cleanup_result["outcome"] == "succeeded"
    assert team_knowledge_service._read_jsonl(team_knowledge_service._items_path_for_owner(owner)) == []
    assert rag_vector_index_service._load_all_index_records() == []


def test_global_runtime_memory_cleanup_preserves_formal_knowledge_and_its_vector(
    cleanup_project: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    env = _knowledge_env()
    monkeypatch.setattr(knowledge_semantic_service, "sync_reviewed_item", lambda *args, **kwargs: {"status": "unavailable"})
    reviewed_item = _promote_source_to_item(env)
    indexable_item = next(
        item
        for item in rag_vector_index_service.list_indexable_knowledge_items(internal=True)
        if item["knowledgeItemId"] == reviewed_item["knowledgeItemId"]
    )
    rag_vector_index_service.write_index_record(
        indexable_item,
        embedding_provider="test",
        embedding_model="cleanup-v1",
        chunks=[{"start": 0, "end": 1, "vector": [1.0, 0.0]}],
    )
    runtime_memory_file = _write(cleanup_project / "workspace" / "memory" / "runtime.md", "runtime memory")
    owner = {"ownerType": "team", "ownerId": env["team"]["teamId"]}
    item_path = team_knowledge_service._items_path_for_owner(owner)

    preview = memory_cleanup_service.preview_memory_cleanup([{"targetType": "global_runtime_memory"}])
    result = memory_cleanup_service.execute_memory_cleanup(
        [{"targetType": "global_runtime_memory"}],
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
        preview_token=preview["previewToken"],
    )

    assert result["outcome"] == "succeeded"
    assert not runtime_memory_file.exists()
    assert [item["knowledgeItemId"] for item in team_knowledge_service._read_jsonl(item_path)] == [
        reviewed_item["knowledgeItemId"]
    ]
    assert [record["knowledgeItemId"] for record in rag_vector_index_service._load_all_index_records()] == [
        reviewed_item["knowledgeItemId"]
    ]


def test_memory_cleanup_agent_private_memory_and_policy_reset(cleanup_project: Path):
    agent = agent_directory_service.create_agent_instance(display_name="Cleanup Agent")
    memory_file = _write(cleanup_project / "workspace" / "agents" / agent["agentId"] / "memory" / "scratch.md", "delete")
    targets = [
        {"targetType": "agent_private_memory", "agentId": agent["agentId"]},
        {"targetType": "agent_memory_policy", "agentId": agent["agentId"]},
    ]
    preview = memory_cleanup_service.preview_memory_cleanup(targets)

    result = memory_cleanup_service.execute_memory_cleanup(
        targets,
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
        preview_token=preview["previewToken"],
    )

    assert result["totals"]["targetCount"] == 2
    assert result["totals"]["memoryPolicyResetCount"] == 1
    assert not memory_file.exists()
    refreshed = agent_directory_service.get_agent(agent["agentId"])
    assert refreshed is not None
    assert refreshed["workspacePath"] == f"workspace/agents/{agent['agentId']}"
    assert refreshed["memoryPolicyId"]


def test_memory_cleanup_execute_requires_exact_confirmation(cleanup_project: Path):
    targets = [{"targetType": "global_runtime_memory"}]
    preview = memory_cleanup_service.preview_memory_cleanup(targets)
    with pytest.raises(memory_cleanup_service.MemoryCleanupError):
        memory_cleanup_service.execute_memory_cleanup(
            targets,
            confirmation_phrase="delete",
            preview_token=preview["previewToken"],
        )


def test_memory_cleanup_execute_requires_matching_preview_token(cleanup_project: Path):
    target = {"targetType": "session_artifacts"}
    session_file = _write(cleanup_project / "workspace" / "sessions" / "session-a" / "turn.json", "{}")

    with pytest.raises(memory_cleanup_service.MemoryCleanupError, match="preview"):
        memory_cleanup_service.execute_memory_cleanup(
            [target],
            confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
            preview_token="",
        )

    preview = memory_cleanup_service.preview_memory_cleanup([target])
    assert preview["previewToken"]

    with pytest.raises(memory_cleanup_service.MemoryCleanupError, match="targets"):
        memory_cleanup_service.execute_memory_cleanup(
            [{"targetType": "evaluation_artifacts"}],
            confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
            preview_token=preview["previewToken"],
        )

    assert session_file.exists()


def test_memory_cleanup_preview_token_is_single_use(cleanup_project: Path):
    target = {"targetType": "evaluation_artifacts"}
    preview = memory_cleanup_service.preview_memory_cleanup([target])

    first = memory_cleanup_service.execute_memory_cleanup(
        [target],
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
        preview_token=preview["previewToken"],
    )

    assert first["outcome"] == "succeeded"
    with pytest.raises(memory_cleanup_service.MemoryCleanupError, match="already used"):
        memory_cleanup_service.execute_memory_cleanup(
            [target],
            confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
            preview_token=preview["previewToken"],
        )


def test_memory_cleanup_preview_token_expires_without_deleting(
    cleanup_project: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    now = {"value": 10.0}
    monkeypatch.setattr(memory_cleanup_service.time, "monotonic", lambda: now["value"])
    target = {"targetType": "session_artifacts"}
    session_file = _write(cleanup_project / "workspace" / "sessions" / "session-a" / "turn.json", "{}")
    preview = memory_cleanup_service.preview_memory_cleanup([target])
    now["value"] += memory_cleanup_service.PREVIEW_TOKEN_TTL_SECONDS + 1

    with pytest.raises(memory_cleanup_service.MemoryCleanupError, match="expired"):
        memory_cleanup_service.execute_memory_cleanup(
            [target],
            confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
            preview_token=preview["previewToken"],
        )

    assert session_file.exists()


def test_memory_cleanup_execute_rejects_stale_preview_without_deleting(cleanup_project: Path):
    target = {"targetType": "session_artifacts"}
    original = _write(cleanup_project / "workspace" / "sessions" / "session-a" / "turn.json", "{}")
    preview = memory_cleanup_service.preview_memory_cleanup([target])
    added_after_preview = _write(cleanup_project / "workspace" / "sessions" / "session-b" / "turn.json", "{}")

    with pytest.raises(memory_cleanup_service.MemoryCleanupError, match="stale"):
        memory_cleanup_service.execute_memory_cleanup(
            [target],
            confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
            preview_token=preview["previewToken"],
        )

    assert original.exists()
    assert added_after_preview.exists()


def test_memory_cleanup_execute_reports_partial_failure(cleanup_project: Path, monkeypatch: pytest.MonkeyPatch):
    evaluation_file = _write(cleanup_project / "workspace" / "evaluation" / "candidate.json", "{}")
    session_file = _write(cleanup_project / "workspace" / "sessions" / "session-a" / "turn.json", "{}")
    targets = [
        {"targetType": "evaluation_artifacts"},
        {"targetType": "session_artifacts"},
    ]
    preview = memory_cleanup_service.preview_memory_cleanup(targets)
    original_execute_delete_path = memory_cleanup_service._execute_delete_path

    def execute_with_one_failure(cleanup_path):
        if cleanup_path.path == cleanup_project / "workspace" / "sessions":
            return memory_cleanup_service._execution_result(
                cleanup_path.path,
                cleanup_path.kind,
                cleanup_path.action,
                "failed",
                message="simulated lock",
            )
        return original_execute_delete_path(cleanup_path)

    monkeypatch.setattr(memory_cleanup_service, "_execute_delete_path", execute_with_one_failure)

    result = memory_cleanup_service.execute_memory_cleanup(
        targets,
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
        preview_token=preview["previewToken"],
    )

    assert result["outcome"] == "partial"
    assert result["totals"]["failedTargetCount"] == 1
    assert [target["status"] for target in result["targets"]] == ["executed", "failed"]
    assert not evaluation_file.exists()
    assert session_file.exists()


def test_memory_cleanup_execute_contains_unexpected_target_failure(
    cleanup_project: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    evaluation_file = _write(cleanup_project / "workspace" / "evaluation" / "candidate.json", "{}")
    session_file = _write(cleanup_project / "workspace" / "sessions" / "session-a" / "turn.json", "{}")
    targets = [
        {"targetType": "evaluation_artifacts"},
        {"targetType": "session_artifacts"},
    ]
    preview = memory_cleanup_service.preview_memory_cleanup(targets)
    original_execute_target = memory_cleanup_service._execute_target

    def execute_with_unexpected_failure(target, *, before=None):
        if target.target_type == "session_artifacts":
            raise RuntimeError("simulated unexpected failure")
        return original_execute_target(target, before=before)

    monkeypatch.setattr(memory_cleanup_service, "_execute_target", execute_with_unexpected_failure)

    result = memory_cleanup_service.execute_memory_cleanup(
        targets,
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
        preview_token=preview["previewToken"],
    )

    assert result["outcome"] == "partial"
    assert [target["status"] for target in result["targets"]] == ["executed", "failed"]
    assert result["targets"][1]["paths"][0]["message"] == "RuntimeError: simulated unexpected failure"
    assert not evaluation_file.exists()
    assert session_file.exists()


def test_memory_cleanup_execute_reports_audit_write_failure(
    cleanup_project: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    target = {"targetType": "evaluation_artifacts"}
    preview = memory_cleanup_service.preview_memory_cleanup([target])

    def fail_audit(_payload):
        raise PermissionError("simulated audit lock")

    monkeypatch.setattr(memory_cleanup_service, "_append_cleanup_audit", fail_audit)

    result = memory_cleanup_service.execute_memory_cleanup(
        [target],
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
        preview_token=preview["previewToken"],
    )

    assert result["outcome"] == "partial"
    assert result["totals"]["auditFailureCount"] == 1
    assert result["audit"] == {
        "status": "failed",
        "message": "PermissionError: simulated audit lock",
    }
