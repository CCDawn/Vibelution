import hashlib
import json
from pathlib import Path

import pytest

from core.assistant_runtime.migration_io import MigrationIOError


@pytest.fixture
def archive(tmp_path, monkeypatch):
    from core.assistant_runtime import native
    from core.assistant_runtime.initial_migration_binding import _directory, _intent_anchor, target_identity
    from core.assistant_runtime.main_control import initial_migration_id
    from core.web.services import agent_directory_service
    from core.web.services.session import directory_runtime

    root = tmp_path / "native"
    project, workspace = tmp_path / "source", tmp_path / "source" / "workspace"
    root.mkdir()
    workspace.mkdir(parents=True)
    agent_id, session_id = "target-agent", "target-session"
    live = root / "workspace" / "agents" / agent_id
    for name in ("memory/memory.json", "memory/summaries.jsonl", "events/episodic_events.jsonl",
                 "mental_model/rules.json", "mental_model/self_model.json"):
        path = live / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"existing target content")
    operation = initial_migration_id("registered-project", "", "personal")
    scope = {"projectId": "source-project", "instanceId": "source-instance", "agentId": "source-agent"}
    digest, target_dir = target_identity(root, agent_id, session_id)
    intent = {"schemaVersion": 1, "registeredProjectId": "registered-project", "sourceScope": scope,
        "category": "personal", "turnId": "turn-1", "operationId": operation, "revision": 1,
        "sourceIdentityDigest": "a" * 64, "registryDigest": "b" * 64, "targetIdentityDigest": digest,
        "projectDirectory": _directory(project), "workspaceDirectory": _directory(workspace),
        "targetDirectory": target_dir, "targetAgentId": agent_id, "targetSessionId": session_id,
        "authority": "native_policy_admitted", "readyForCutover": False}
    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    write_json(root / "initial_migration_intents" / _intent_anchor(intent) / "intent.json", intent)
    write_json(root / "initial_migration_claims" / operation / "claim.json",
               {"schemaVersion": 1, "operationId": operation, "category": "personal"})
    folder = root / "history_sources" / "migrations" / operation
    (folder / ".confirmed").mkdir(parents=True)
    files = [("episodic_memory", "src-ep", "episodic_events.jsonl", ""),
             ("personal_affairs", "src-aff", "affairs/items.jsonl", ""),
             ("memory", "src-mem", "memory.json", '{"core_wisdom":"旧偏好","current_goal":"old"}'),
             ("memory", "src-mem", "summaries.jsonl", '{"text":"旧摘要"}\n'),
             ("memory_summaries", "src-sum", "summaries.jsonl", '{"text":"旧摘要"}\n'),
             ("mental_model", "src-mental", "rules.json", '{"looping":{"threshold":3}}'),
             ("mental_model", "src-mental", "self_model.json", '{"strengths":["old"]}')]
    entries = []
    for category, ref, name, text in files:
        relative = f"sources/{ref}/{name}"
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = text.encode("utf-8")
        path.write_bytes(raw)
        entries.append({"sourceRef": ref, "category": category, "path": relative,
                        "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)})
    write_json(folder / "manifest.json", {"schemaVersion": 2, "migrationId": operation, "sourceScope": scope,
        "readOnly": True, "untrustedContent": True, "activePluginStateImported": False,
        "sourceComplete": False, "snapshotCompleteAtScan": True, "entries": entries, "readyForCutover": False})
    for name, count in (("episodic_migrations", "episodeCount"), ("affairs_migrations", "itemCount")):
        write_json(root / name / (hashlib.sha256(operation.encode()).hexdigest() + ".json"),
            {"schemaVersion": 1, "migrationId": operation, "sourceScope": scope,
             "sourceSha256": hashlib.sha256(b"").hexdigest(), "targetAgentId": agent_id, count: 0, "published": True})
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_OFFLINE_MIGRATION", False)
    monkeypatch.setattr(native, "_AGENT_ID", agent_id)
    monkeypatch.setattr(native, "_SESSION_ID", session_id)
    monkeypatch.setattr(native, "_STOP_REQUESTED", __import__("threading").Event())
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda **_: {"agentId": agent_id, "sessionId": session_id})
    monkeypatch.setattr(directory_runtime, "directory_store_project_root", lambda: root)
    return root, operation, folder, scope


def test_verified_archive_is_read_only_bounded_and_deduplicated(archive, monkeypatch):
    from core.assistant_runtime import legacy_memory_read as reader
    root, operation, folder, scope = archive
    monkeypatch.setattr(reader, "assistant_native_root", lambda: root)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = reader.list_legacy_memory(operation)
    assert result["sourceScope"] == scope and result["readOnly"] and result["untrustedContent"]
    assert {item["kind"] for item in result["items"]} == {"memory", "summaries", "mental_rules", "mental_self"}
    page = reader.read_legacy_memory(operation, "memory", offset=0, limit=7, expected_version=result["archiveVersion"])
    assert page["text"] and page["nextOffset"] == 7 and page["untrustedContent"]
    next_page = reader.read_legacy_memory(operation, "memory", offset=page["nextOffset"], limit=1600,
                                          expected_version=result["archiveVersion"])
    assert page["text"] + next_page["text"] == '{"core_wisdom":"旧偏好","current_goal":"old"}'
    assert reader.read_legacy_memory(operation, "summaries")["text"] == '{"text":"旧摘要"}\n'
    assert reader.read_legacy_memory(operation, "mental_rules")["text"] == '{"looping":{"threshold":3}}'
    assert reader.read_legacy_memory(operation, "mental_self")["text"] == '{"strengths":["old"]}'
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_rejects_wrong_identity_tampered_archive_and_invalid_inputs(archive, monkeypatch):
    from core.assistant_runtime import legacy_memory_read as reader, native
    root, operation, folder, _ = archive
    monkeypatch.setattr(reader, "assistant_native_root", lambda: root)
    with pytest.raises(MigrationIOError):
        reader.list_legacy_memory("../outside")
    with pytest.raises(MigrationIOError):
        reader.read_legacy_memory(operation, "../../outside")
    with pytest.raises(MigrationIOError):
        reader.read_legacy_memory(operation, "memory", offset=2, expected_version=None)
    monkeypatch.setattr(native, "_AGENT_ID", "other-agent")
    with pytest.raises(MigrationIOError):
        reader.list_legacy_memory(operation)
    monkeypatch.setattr(native, "_AGENT_ID", "target-agent")
    (folder / "sources/src-mem/memory.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(MigrationIOError):
        reader.list_legacy_memory(operation)


def test_disallows_stale_version_unknown_and_unconfirmed_archive(archive, monkeypatch):
    from core.assistant_runtime import legacy_memory_read as reader
    root, operation, folder, _ = archive
    monkeypatch.setattr(reader, "assistant_native_root", lambda: root)
    listing = reader.list_legacy_memory(operation)
    with pytest.raises(MigrationIOError, match="version_changed"):
        reader.read_legacy_memory(operation, "memory", expected_version="0" * 64)
    with pytest.raises(MigrationIOError):
        reader.list_legacy_memory("initial-" + "0" * 40)
    with pytest.raises(MigrationIOError):
        reader.read_legacy_memory(operation, "memory", limit=1601)
    assert listing["archiveVersion"]
    (folder / ".confirmed").rmdir()
    with pytest.raises(MigrationIOError):
        reader.list_legacy_memory(operation)


def test_rejects_linked_archive_file_and_wrong_source_scope(archive, tmp_path, monkeypatch):
    import os
    from core.assistant_runtime import legacy_memory_read as reader
    root, operation, folder, _ = archive
    monkeypatch.setattr(reader, "assistant_native_root", lambda: root)
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original = manifest["sourceScope"]["agentId"]
    manifest["sourceScope"]["agentId"] = "wrong-agent"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(MigrationIOError):
        reader.list_legacy_memory(operation)
    manifest["sourceScope"]["agentId"] = original
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    path = folder / "sources/src-mem/memory.json"
    contents = path.read_bytes()
    other = tmp_path / "untrusted-link-target"
    other.write_bytes(contents)
    path.unlink()
    try:
        os.symlink(other, path)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(MigrationIOError):
        reader.list_legacy_memory(operation)


def test_conflicting_summary_copies_and_oversized_source_fail_closed(archive, monkeypatch):
    from core.assistant_runtime import legacy_memory_read as reader
    root, operation, folder, _ = archive
    monkeypatch.setattr(reader, "assistant_native_root", lambda: root)
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = folder / "sources/src-sum/summaries.jsonl"
    summary.write_text("different", encoding="utf-8")
    row = next(row for row in manifest["entries"] if row["sourceRef"] == "src-sum")
    row.update(size=summary.stat().st_size, sha256=hashlib.sha256(summary.read_bytes()).hexdigest())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(MigrationIOError, match="ambiguous"):
        reader.list_legacy_memory(operation)
    summary.write_bytes('{"text":"旧摘要"}\n'.encode("utf-8"))
    row.update(size=summary.stat().st_size, sha256=hashlib.sha256(summary.read_bytes()).hexdigest())
    memory = folder / "sources/src-mem/memory.json"
    memory.write_bytes(b"x" * (1024 * 1024 + 1))
    row = next(row for row in manifest["entries"] if row["path"].endswith("/memory.json"))
    row.update(size=memory.stat().st_size, sha256=hashlib.sha256(memory.read_bytes()).hexdigest())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    listing = reader.list_legacy_memory(operation)
    assert next(item for item in listing["items"] if item["kind"] == "memory")["readable"] is False
    with pytest.raises(MigrationIOError, match="unavailable"):
        reader.read_legacy_memory(operation, "memory")


def test_reads_archive_published_by_native_source_writer(archive, tmp_path, monkeypatch):
    from core.assistant_runtime import legacy_memory_read as reader
    from core.assistant_runtime.initial_migration_binding import _intent_anchor, read_initial_intent
    from core.assistant_runtime.main_control import initial_migration_id
    from core.assistant_runtime.migration_paths import resolve_source_paths, source_snapshot
    from core.assistant_runtime.migration_source_archive import import_source_snapshots

    root, old_operation, _, scope = archive
    scope = {**scope, "projectId": "source-project-2"}
    monkeypatch.setattr(reader, "assistant_native_root", lambda: root)
    project, workspace = tmp_path / "source", tmp_path / "source/workspace"
    source = workspace / "agents" / scope["agentId"]
    for relative, raw in {"events/episodic_events.jsonl": b"", "plugins/personal-affairs/affairs/items.jsonl": b"",
                          "memory/memory.json": b'{"core_wisdom":"fixture"}',
                          "memory/summaries.jsonl": b'{"summary":"fixture"}\n',
                          "mental_model/rules.json": b'{}', "mental_model/self_model.json": b'{}'}.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    agent = {"agentId": scope["agentId"], "directSessionId": "source-session", "roleKey": "personal_assistant",
             "metadata": {"personalAssistantProfile": "personal_assistant_v1"}}
    snapshot = source_snapshot(resolve_source_paths(project_root=project, workspace=workspace,
        project_id=scope["projectId"], instance_id=scope["instanceId"], agent_row=agent, memory_policy={}))
    operation = initial_migration_id("registered-project-2", "", "personal")
    result = import_source_snapshots(snapshot, root, operation, source_roots=(project, workspace), authority_verify=lambda: None)
    assert result["published"]
    intent = read_initial_intent(root, old_operation)
    intent.update(registeredProjectId="registered-project-2", operationId=operation, sourceScope=scope)
    intent_path = root / "initial_migration_intents" / _intent_anchor(intent) / "intent.json"
    intent_path.parent.mkdir(parents=True)
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    claim = root / "initial_migration_claims" / operation / "claim.json"
    claim.parent.mkdir(parents=True)
    claim.write_text(json.dumps({"schemaVersion": 1, "operationId": operation, "category": "personal"}), encoding="utf-8")
    for name, count in (("episodic_migrations", "episodeCount"), ("affairs_migrations", "itemCount")):
        receipt = {"schemaVersion": 1, "migrationId": operation, "sourceScope": scope,
                   "sourceSha256": hashlib.sha256(b"").hexdigest(), "targetAgentId": "target-agent", count: 0, "published": True}
        (root / name / (hashlib.sha256(operation.encode()).hexdigest() + ".json")).write_text(json.dumps(receipt), encoding="utf-8")
    listing = reader.list_legacy_memory(operation)
    assert {entry["kind"] for entry in listing["items"]} == {"memory", "summaries", "mental_rules", "mental_self"}
    assert reader.read_legacy_memory(operation, "memory")["text"] == '{"core_wisdom":"fixture"}'


def test_json_escaped_multibyte_pages_fit_tool_output_budget(archive, monkeypatch):
    from core.assistant_runtime import legacy_memory_read as reader
    root, operation, folder, _ = archive
    monkeypatch.setattr(reader, "assistant_native_root", lambda: root)
    data = ('"\\\n\t你好😀' * 600).encode("utf-8")
    path = folder / "sources/src-mem/memory.json"
    path.write_bytes(data)
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = next(row for row in manifest["entries"] if row["path"].endswith("/memory.json"))
    row.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    listing = reader.list_legacy_memory(operation)
    assert len(json.dumps({"source": "launcher-assistant", "untrustedContent": True, **listing}, ensure_ascii=False).encode("utf-8")) <= 3300
    offset, collected = 0, []
    while offset is not None:
        page = reader.read_legacy_memory(operation, "memory", offset=offset, limit=1600,
                                         expected_version=listing["archiveVersion"])
        assert len(json.dumps({"source": "launcher-assistant", "untrustedContent": True, **page}, ensure_ascii=False).encode("utf-8")) <= 3300
        collected.append(page["text"])
        offset = page["nextOffset"]
    assert "".join(collected) == data.decode("utf-8")


def test_actual_bound_runtime_identity_is_required(archive, monkeypatch):
    from core.assistant_runtime import legacy_memory_read as reader
    from core.web.services import agent_directory_service as directory
    from core.web.services.agent_directory.ops_residual import current_agent_runtime
    root, operation, _, _ = archive
    monkeypatch.setattr(reader, "assistant_native_root", lambda: root)
    monkeypatch.setattr(directory, "current_agent_runtime", current_agent_runtime)
    monkeypatch.setattr(directory, "_agent_runtime_from_env", lambda: {"agentId": "target-agent", "sessionId": "target-session"})
    with pytest.raises(MigrationIOError, match="owner_unavailable"):
        reader.list_legacy_memory(operation)
    token = directory._CURRENT_AGENT_RUNTIME.set({"agentId": "target-agent", "sessionId": "target-session"})
    try:
        assert reader.list_legacy_memory(operation)["readOnly"]
    finally:
        directory._CURRENT_AGENT_RUNTIME.reset(token)


def test_assistant_tool_reads_confirmed_archive_with_bound_runtime(archive, monkeypatch):
    from core.assistant_runtime import actions, legacy_memory_read as reader
    from core.infrastructure import native_runtime
    from core.web.services import agent_directory_service as directory
    from core.web.services.agent_directory.ops_residual import current_agent_runtime
    from tools import personal_assistant_tools as tools

    root, operation, _, scope = archive
    runtime = {"agentId": "target-agent", "sessionId": "target-session"}
    monkeypatch.setattr(reader, "assistant_native_root", lambda: root)
    monkeypatch.setattr(directory, "current_agent_runtime", current_agent_runtime)
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(tools, "_identity", lambda: runtime)
    monkeypatch.setattr(actions, "_binding", (object(), None, None))
    token = directory._CURRENT_AGENT_RUNTIME.set(runtime)
    try:
        listing = json.loads(tools.personal_assistant_action_tool("legacy_memory_list", {"operation_id": operation}))
        assert listing["sourceScope"] == scope and listing["untrustedContent"] is True
        result = json.loads(tools.personal_assistant_action_tool("legacy_memory_read", {
            "operation_id": operation, "kind": "memory", "expected_version": listing["archiveVersion"]}))
        assert "旧偏好" in result["text"] and result["activeMemoryChanged"] is False
    finally:
        directory._CURRENT_AGENT_RUNTIME.reset(token)
