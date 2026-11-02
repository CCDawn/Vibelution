"""All-registration references and the shared canonical-reference commit fence."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import threading
import tomllib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.assistant_runtime.configuration_references import (
    ConfigurationReferenceError, ConfigurationReferenceGuard, StoredConfigurationRegistryProvider,
)
from core.infrastructure.model_reference_fence import model_reference_fence
from core.web.services.model_reference_service import read_existing_model_reference_metadata


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def empty_store(workspace):
    from core.chat.conversation_store.database import ConversationDatabase
    path = workspace / "chat" / "conversations.sqlite3"
    database = ConversationDatabase(path)
    database.initialize()
    return path


def bind_store(path, model_id, *, session_model=None):
    from core.chat.conversation_store import ConversationStore
    with ConversationStore(path) as store:
        first = store.repository.create_agent(agent_id="agent-a", display_name="Fixture", kind="chat",
            config={"llmBindings": {"dialogue": {"modelId": session_model or model_id}}, "systemPrompt": "PRIVATE PROMPT"},
            source="test").result(timeout=5)
        if session_model:
            store.repository.create_session(session_id="old-session", agent_id="agent-a",
                agent_config_revision_id=first["configRevisionId"], title="").result(timeout=5)
            store.repository.compare_and_swap_agent_config(agent_id="agent-a", expected_config_revision_id=first["configRevisionId"],
                display_name="Fixture", kind="chat", status="active", config={"llmBindings": {"dialogue": {"modelId": model_id}}},
                source="test").result(timeout=5)


@pytest.fixture
def env(tmp_path, monkeypatch):
    import vibelution_storage as storage
    config = tmp_path / "config.toml"
    config.write_text('''[llm]
schema_version = 2
[llm.profiles.primary]
model_ref = "gamma/default"
[llm.providers.alpha]
base_url = "http://127.0.0.1:1901/v1"
service_class = "local_runtime"
vendor = "custom"
driver = "openai"
auth_kind = "none"
credential_ref = "none"
requires_credential = false
[llm.providers.alpha.models.spare]
upstream_id = "same-upstream"
[llm.providers.alpha.models.other]
upstream_id = "other"
[llm.providers.beta]
base_url = "http://127.0.0.1:1902/v1"
service_class = "local_runtime"
vendor = "custom"
driver = "openai"
auth_kind = "none"
credential_ref = "none"
requires_credential = false
[llm.providers.beta.models.spare]
upstream_id = "same-upstream"
[llm.providers.gamma]
base_url = "http://127.0.0.1:1903/v1"
service_class = "local_runtime"
vendor = "custom"
driver = "openai"
auth_kind = "none"
credential_ref = "none"
requires_credential = false
[llm.providers.gamma.models.default]
upstream_id = "default"
''', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config))
    from config import operator_config_transaction as transaction
    monkeypatch.setattr(transaction, "reload_config", lambda *_args: None)
    monkeypatch.setenv(storage.PROJECTS_HOME_ENV, str(tmp_path / "projects"))
    native = tmp_path / "native"
    native_workspace = native / "data" / "workspace"
    empty_store(native_workspace)
    registrations, roots, paths = [], [], []
    for index in range(2):
        root = tmp_path / f"project-{index}"
        write_json(root / ".vibelution" / "project.json", {"schemaVersion": 1, "projectId": f"project-{index}"})
        resolved = storage.resolve_project_storage_paths(root)
        write_json(storage.storage_migration_state_path(resolved), {"schemaVersion": 1, "status": "completed",
            "projectId": resolved.project_id, "instanceId": resolved.instance_id, "projectRoot": str(root)})
        empty_store(resolved.workspace)
        registrations.append({"integrationRoot": str(tmp_path), "baseProjectId": f"project-{index}",
            "root": str(root), "registrationUuid": str(uuid4()), "active": index == 0})
        roots.append(root)
        paths.append(resolved)
    registry = tmp_path / "registry.json"
    write_json(registry, {"schemaVersion": 1, "revision": 3, "registrations": registrations})
    provider = StoredConfigurationRegistryProvider(registry, native)
    guard = ConfigurationReferenceGuard(provider, config_path_provider=lambda: config)
    return SimpleNamespace(config=config, registry=registry, provider=provider, guard=guard, native=native,
        native_workspace=native_workspace, registrations=registrations, roots=roots, paths=paths)


def test_full_stored_registry_includes_inactive_and_native_profiles(env):
    inventory = env.provider()
    assert len(inventory["projects"]) == 2 and inventory["projects"][1]["active"] is False
    bind_store(env.paths[1].workspace / "chat" / "conversations.sqlite3", "alpha/spare")
    proof = env.guard.scan("model", "alpha/spare")
    assert proof.complete and proof.known_reference_count == 1 and proof.project_count == 3
    bind_store(env.native_workspace / "chat" / "conversations.sqlite3", "alpha/spare")
    proof = env.guard.scan("model", "alpha/spare")
    assert proof.complete and proof.known_reference_count == 2
    assert "PRIVATE PROMPT" not in json.dumps(proof.summary())


def test_old_session_compiled_pin_is_live_after_agent_switches_to_new_model(env):
    path = env.paths[0].workspace / "chat" / "conversations.sqlite3"
    bind_store(path, "alpha/other", session_model="alpha/spare")
    result = read_existing_model_reference_metadata(env.paths[0].workspace, env.paths[0].runtime)
    assert result["complete"]
    assert any(row["ownerType"] == "session" and row["modelId"] == "alpha/spare" for row in result["references"])
    assert env.guard.scan("model", "alpha/spare").known_reference_count == 1
    assert "PRIVATE PROMPT" not in json.dumps(result)


@pytest.mark.parametrize("failure", ["offline-root", "corrupt-db", "missing-db", "bad-registry", "bad-owner-json"])
def test_missing_corrupt_and_offline_authority_is_unknown_never_zero(env, failure):
    if failure == "offline-root":
        payload = json.loads(env.registry.read_text())
        payload["registrations"][1]["root"] = str(env.roots[1] / "offline")
        write_json(env.registry, payload)
    elif failure == "corrupt-db":
        (env.paths[1].workspace / "chat" / "conversations.sqlite3").write_bytes(b"broken")
    elif failure == "missing-db":
        (env.paths[1].workspace / "chat" / "conversations.sqlite3").unlink()
    elif failure == "bad-registry":
        env.registry.write_text("broken", encoding="utf-8")
    else:
        write_json(env.paths[1].workspace / "agents" / "agents.json", {"agents": "broken"})
    proof = env.guard.scan("model", "alpha/spare")
    assert not proof.complete and proof.summary()["liveReferenceCount"] is None
    assert proof.summary()["blocking"] is True and proof.issues


def test_admitted_subset_cannot_claim_complete_inventory(env):
    admitted = {"schemaVersion": 1, "revision": 3, "projects": {"only-authorized": str(env.roots[0])}}
    guard = ConfigurationReferenceGuard(lambda: admitted, config_path_provider=lambda: env.config)
    proof = guard.scan("model", "alpha/spare")
    assert not proof.complete and proof.summary()["liveReferenceCount"] is None


def test_direct_native_lease_inventory_is_consumed_without_model_paths(env):
    snapshot = env.provider()
    native_inventory = {"schemaVersion": 1, "leaseId": "private-native-lease", "revision": 3,
        "snapshotDigest": snapshot["authorityDigest"], "complete": True,
        "projects": [{"registrationId": row["projectId"], "baseProjectId": "project", "root": row["root"], "active": row["active"]}
                     for row in snapshot["projects"]], "nativeAssistantRoot": str(env.native)}
    proof = ConfigurationReferenceGuard(lambda: native_inventory, config_path_provider=lambda: env.config).scan("model", "alpha/spare")
    assert proof.complete and proof.known_reference_count == 0
    with pytest.raises(ConfigurationReferenceError, match="INVALID_REFERENCE_TARGET"):
        env.guard.scan("model", str(env.roots[0]))


def test_same_upstream_name_does_not_merge_distinct_provider_model_refs(env):
    bind_store(env.paths[0].workspace / "chat" / "conversations.sqlite3", "beta/spare")
    assert env.guard.scan("model", "alpha/spare").known_reference_count == 0
    assert env.guard.scan("provider", "alpha").known_reference_count == 0
    assert env.guard.scan("model", "beta/spare").known_reference_count == 1
    assert env.guard.scan("provider", "beta").known_reference_count == 1


def test_revision_source_and_config_changes_invalidate_a_prior_proof(env):
    first = env.guard.scan("model", "alpha/spare")
    assert first.complete
    payload = json.loads(env.registry.read_text())
    payload["revision"] += 1
    write_json(env.registry, payload)
    with pytest.raises(ConfigurationReferenceError, match="REFERENCE_STATE_CHANGED"):
        env.guard.assert_unchanged(first)
    current = env.guard.scan("model", "alpha/spare")
    bind_store(env.paths[1].workspace / "chat" / "conversations.sqlite3", "alpha/spare")
    with pytest.raises(ConfigurationReferenceError, match="REFERENCE_STATE_CHANGED"):
        env.guard.assert_unchanged(current)


def test_scan_is_read_only_and_never_creates_missing_project_authorities(env):
    before = {str(path): path.read_bytes() for path in env.registry.parent.rglob("*") if path.is_file() and path.suffix in {".json", ".toml", ".sqlite3"}}
    assert env.guard.scan("model", "alpha/spare").complete
    after = {str(path): path.read_bytes() for path in env.registry.parent.rglob("*") if path.is_file() and path.suffix in {".json", ".toml", ".sqlite3"}}
    assert before == after
    path = env.paths[1].workspace / "chat" / "conversations.sqlite3"
    path.unlink()
    assert not env.guard.scan("model", "alpha/spare").complete and not path.exists()


def test_writer_fence_is_reentrant_and_exception_releases_it(env):
    with pytest.raises(RuntimeError, match="fixture"):
        with model_reference_fence(env.config) as outer:
            outer.assert_owned()
            with model_reference_fence() as inner:
                inner.assert_owned()
            outer.assert_owned()
            raise RuntimeError("fixture")
    with pytest.raises(RuntimeError, match="not owned"):
        outer.assert_owned()
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(lambda: _take_fence(env.config)).result(timeout=2)


def _take_fence(config):
    with model_reference_fence(config) as lease:
        lease.assert_owned()
        return True


def test_zero_reference_write_requires_registry_lease_and_detects_config_drift(env):
    with pytest.raises(ConfigurationReferenceError, match="LEASE_REQUIRED"):
        with env.guard.zero_references("model", "alpha/spare", registry_lease=None):
            pytest.fail("missing lease allowed a write")
    calls = []
    lease = SimpleNamespace(assert_current=lambda: calls.append(True))
    with env.guard.zero_references("model", "alpha/spare", registry_lease=lease) as permit:
        assert permit.proof.complete and permit.proof.known_reference_count == 0
    assert len(calls) >= 4
    with pytest.raises(ConfigurationReferenceError, match="CONFIG_STATE_CHANGED"):
        with env.guard.zero_references("model", "alpha/spare", registry_lease=lease):
            env.config.write_text(env.config.read_text() + "\n# changed\n", encoding="utf-8")


def test_zero_reference_permit_checks_actual_native_commit_hash(env):
    from config.public_config import public_config_hash
    lease = SimpleNamespace(assert_current=lambda: None)
    with env.guard.zero_references("model", "alpha/spare", registry_lease=lease) as permit:
        env.config.write_text(env.config.read_text() + "\n# native committed\n", encoding="utf-8")
        permit.confirm_commit_hash(public_config_hash(tomllib.loads(env.config.read_text())))


def test_real_queued_reference_writer_waits_for_fence_on_execution_thread(env):
    from core.chat.conversation_store import ConversationStore
    path = env.paths[0].workspace / "chat" / "conversations.sqlite3"
    with ConversationStore(path) as store, ThreadPoolExecutor(max_workers=1) as pool:
        with model_reference_fence(env.config):
            future = pool.submit(lambda: store.repository.create_agent(agent_id="concurrent", display_name="Fixture", kind="chat",
                config={"llmBindings": {"dialogue": {"modelId": "alpha/spare"}}}, source="test")).result(timeout=2)
            # Submitting does not wait for another thread's fence. Its native
            # writer future cannot complete until the deleting owner releases.
            assert not future.done()
            assert env.guard.scan("model", "alpha/spare").known_reference_count == 0
        assert future.result(timeout=5)["agentId"] == "concurrent"
    lease = SimpleNamespace(assert_current=lambda: None)
    with pytest.raises(ConfigurationReferenceError, match="LIVE_MODEL_REFERENCES"):
        with env.guard.zero_references("model", "alpha/spare", registry_lease=lease):
            pytest.fail("committed reference was ignored")


def remove_native_model(env, permit=None):
    from config.operator_config_transaction import prepare_operator_config_transaction, apply_operator_config_transaction, remove_toml_table_tree
    from config.public_config import public_config_hash
    prepared = prepare_operator_config_transaction(operation_kind="test_reference_remove", config_path=env.config,
        expected_base_hash=public_config_hash(tomllib.loads(env.config.read_text())),
        mutate_text=lambda text: remove_toml_table_tree(text, ("llm", "providers", "alpha", "models", "spare")))
    result = apply_operator_config_transaction(prepared)
    if permit is not None:
        permit.confirm_commit_hash(result["hash"])
    return result


def test_queued_old_binding_after_native_delete_is_rejected_before_sqlite_commit(env):
    from core.chat.conversation_store import ConversationStore
    lease = SimpleNamespace(assert_current=lambda: None)
    path = env.paths[0].workspace / "chat" / "conversations.sqlite3"
    with ConversationStore(path) as store, ThreadPoolExecutor(max_workers=1) as pool:
        with env.guard.zero_references("model", "alpha/spare", registry_lease=lease) as permit:
            future = pool.submit(lambda: store.repository.create_agent(agent_id="too-late", display_name="Fixture", kind="chat",
                config={"llmBindings": {"dialogue": {"modelId": "alpha/spare"}}}, source="test")).result(timeout=2)
            assert not future.done()
            remove_native_model(env, permit)
        with pytest.raises(ValueError, match="removed or disabled"):
            future.result(timeout=5)
        assert store.repository.get_agent("too-late") is None
        assert store.repository.get_current_agent_config("too-late") is None


def test_provider_removal_retires_every_actual_model_without_confusing_other_provider(env):
    from config import operator_config_transaction as transaction
    from config.public_config import public_config_hash
    from core.chat.conversation_store import ConversationStore
    lease = SimpleNamespace(assert_current=lambda: None)
    with env.guard.zero_references("provider", "alpha", registry_lease=lease) as permit:
        prepared = transaction.prepare_operator_config_transaction(operation_kind="test_provider_remove", config_path=env.config,
            expected_base_hash=public_config_hash(tomllib.loads(env.config.read_text())),
            mutate_text=lambda text: transaction.remove_toml_table_tree(text, ("llm", "providers", "alpha")))
        result = transaction.apply_operator_config_transaction(prepared)
        permit.confirm_commit_hash(result["hash"])
    with ConversationStore(env.paths[0].workspace / "chat" / "conversations.sqlite3") as store:
        for model in ("alpha/spare", "alpha/other"):
            with pytest.raises(ValueError, match="removed or disabled"):
                store.repository.create_agent(agent_id=model.replace("/", "-"), display_name="Fixture", kind="chat",
                    config={"llmBindings": {"dialogue": {"modelId": model}}}, source="test").result(timeout=5)
        assert store.repository.create_agent(agent_id="beta-allowed", display_name="Fixture", kind="chat",
            config={"llmBindings": {"dialogue": {"modelId": "beta/spare"}}}, source="test").result(timeout=5)["agentId"] == "beta-allowed"


def test_failed_config_commit_marker_does_not_block_a_still_available_model(env, monkeypatch):
    from core.chat.conversation_store import ConversationStore
    from config import operator_config_transaction as transaction
    lease = SimpleNamespace(assert_current=lambda: None)
    before = env.config.read_bytes()
    calls = []
    def fail_first(*_args):
        calls.append(True)
        if len(calls) == 1:
            raise ValueError("test validation failed")
    monkeypatch.setattr(transaction, "reload_config", fail_first)
    with env.guard.zero_references("model", "alpha/spare", registry_lease=lease):
        with pytest.raises(transaction.OperatorConfigTransactionError):
            remove_native_model(env)
        assert env.config.read_bytes() == before
    path = env.paths[0].workspace / "chat" / "conversations.sqlite3"
    with ConversationStore(path) as store:
        created = store.repository.create_agent(agent_id="allowed", display_name="Fixture", kind="chat",
            config={"llmBindings": {"dialogue": {"modelId": "alpha/spare"}}}, source="test").result(timeout=5)
        assert created["agentId"] == "allowed"


def test_readding_model_allows_new_binding_and_unknown_opaque_ids_keep_old_contract(env):
    from core.chat.conversation_store import ConversationStore
    from config.operator_config_transaction import append_toml_table, prepare_operator_config_transaction, apply_operator_config_transaction
    from config.public_config import public_config_hash
    lease = SimpleNamespace(assert_current=lambda: None)
    with env.guard.zero_references("model", "alpha/spare", registry_lease=lease) as permit:
        remove_native_model(env, permit)
    current = env.config.read_text()
    prepared = prepare_operator_config_transaction(operation_kind="test_reference_readd", config_path=env.config,
        expected_base_hash=public_config_hash(tomllib.loads(current)), mutate_text=lambda text:
            append_toml_table(text, ("llm", "providers", "alpha", "models", "spare"), {"upstream_id": "same-upstream"}))
    apply_operator_config_transaction(prepared)
    with ConversationStore(env.paths[0].workspace / "chat" / "conversations.sqlite3") as store:
        for identity, model in (("readded", "alpha/spare"), ("opaque", "historical_opaque_model")):
            assert store.repository.create_agent(agent_id=identity, display_name="Fixture", kind="chat",
                config={"llmBindings": {"dialogue": {"modelId": model}}}, source="test").result(timeout=5)["agentId"] == identity


def test_retirement_write_failure_prevents_delete_and_corrupt_marker_fails_closed(env, monkeypatch):
    import core.infrastructure.atomic_io as io
    import core.infrastructure.model_reference_fence as fence
    lease = SimpleNamespace(assert_current=lambda: None)
    before = env.config.read_bytes()
    write = io.atomic_write_json
    def fail(path, *_args, **_kwargs):
        if ".model-reference-retirements" in str(path):
            raise OSError("fixture marker unavailable")
        return write(path, *_args, **_kwargs)
    monkeypatch.setattr(io, "atomic_write_json", fail)
    with pytest.raises(ConfigurationReferenceError, match="RETIREMENT_AUTHORITY_UNAVAILABLE"):
        with env.guard.zero_references("model", "alpha/spare", registry_lease=lease):
            pytest.fail("delete ran before durable retirement metadata")
    assert env.config.read_bytes() == before
    monkeypatch.setattr(io, "atomic_write_json", write)
    with env.guard.zero_references("model", "alpha/spare", registry_lease=lease):
        pass
    marker = fence._retirement_path(env.config)
    marker.write_text("broken", encoding="utf-8")
    with pytest.raises(ConfigurationReferenceError, match="RETIREMENT_AUTHORITY_UNAVAILABLE"):
        with env.guard.zero_references("model", "alpha/spare", registry_lease=lease):
            pytest.fail("corrupt marker allowed deletion")
    assert env.config.read_bytes() == before


def test_matching_permit_is_scoped_to_thread_target_and_exact_config(env):
    from core.assistant_runtime.configuration_references import has_active_reference_permit
    lease = SimpleNamespace(assert_current=lambda: None)
    assert not has_active_reference_permit("model", "alpha/spare")
    with env.guard.zero_references("model", "alpha/spare", registry_lease=lease):
        assert has_active_reference_permit("model", "alpha/spare", public_config=tomllib.loads(env.config.read_text()))
        with pytest.raises(ConfigurationReferenceError, match="TARGET_MISMATCH"):
            has_active_reference_permit("model", "alpha/other")
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(has_active_reference_permit, "model", "alpha/spare").result(timeout=2) is False
    assert not has_active_reference_permit("model", "alpha/spare")


def test_agent_direct_and_outer_state_owned_saves_do_not_invert_deletion_lock_order(env, monkeypatch):
    from core.web.services import agent_directory_service as directory
    from core.web.services.agent_directory.ops_residual import save_registry_payload
    target = env.paths[0].workspace / "agents" / "agents.json"
    write_json(target, {"agents": []})
    monkeypatch.setattr(directory, "registry_path", lambda: target)
    waiting = threading.Event()
    def outer_save():
        with directory._STATE_LOCK:
            waiting.set()
            return save_registry_payload({"agents": []}, enforce_shrink_guard=False)
    def direct_save():
        return save_registry_payload({"agents": []}, enforce_shrink_guard=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        with model_reference_fence(env.config):
            first = pool.submit(outer_save)
            assert waiting.wait(timeout=2)
            second = pool.submit(direct_save)
            # The deletion scan must not ask either writer for Agent State.
            assert env.guard.scan("model", "alpha/spare").complete
            assert not first.done() and not second.done()
        assert first.result(timeout=5)["agents"] == []
        assert second.result(timeout=5)["agents"] == []


def test_exact_json_owners_reject_new_retired_bindings_without_changing_old_data(env):
    from core.chatroom.store import ChatRoomStore
    from core.web.services.team.team_store import _write_json
    from core.runtime_manager.work_run_store import WorkRunStore
    lease = SimpleNamespace(assert_current=lambda: None)
    with env.guard.zero_references("model", "alpha/spare", registry_lease=lease) as permit:
        remove_native_model(env, permit)
    rooms = ChatRoomStore(env.paths[0].data)
    with pytest.raises(ValueError, match="removed or disabled"):
        rooms.save({"rooms": [{"roomId": "room", "participants": [{"dialogueModelId": "alpha/spare"}]}]})
    assert not rooms.state_path.exists()
    policy = env.paths[0].workspace / "teams" / "team" / "workflow_orchestration.json"
    with pytest.raises(ValueError, match="removed or disabled"):
        _write_json(policy, {"promptCachePolicy": {"modelId": "alpha/spare"}})
    assert not policy.exists()
    runs = WorkRunStore(env.paths[0].runtime / "runtime-manager" / "work_runs")
    with pytest.raises(ValueError, match="removed or disabled"):
        runs.persist_snapshot("supervised", {"runId": "run", "status": "running",
            "currentAgentBinding": {"modelId": "alpha/spare"}}, active_run_id="run")
    assert not runs.index_path("supervised").exists()


def test_duplicate_compiled_model_fields_cannot_hide_a_reference(env):
    from core.chat.conversation_store import runtime
    path = env.paths[0].workspace / "chat" / "conversations.sqlite3"
    bind_store(path, "alpha/other")
    connection = runtime.connect(str(path))
    try:
        connection.execute("UPDATE agent_config_revisions SET config_json=?", (
            '{"llmBindings":{"dialogue":{"modelId":"alpha/other"}},"llmBindings":{"dialogue":{"modelId":"alpha/spare"}}}',))
    finally:
        connection.close()
    proof = env.guard.scan("model", "alpha/spare")
    assert not proof.complete and "compiled_pins_unavailable" in proof.issues
    assert proof.summary()["liveReferenceCount"] is None


def test_native_developer_sandbox_is_part_of_complete_reference_inventory(env):
    workspace = env.native / ".runtime" / "developer-mode" / "sandboxes" / "native-sandbox" / "workspace"
    path = empty_store(workspace)
    bind_store(path, "alpha/spare")
    proof = env.guard.scan("model", "alpha/spare")
    assert proof.complete and proof.known_reference_count == 1


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("status", ["RUNNING", "unexpected_active_state"])
def test_sandbox_supervised_runtime_pairs_with_its_own_workspace(env, native, status):
    runtime = env.native / ".runtime" if native else env.paths[0].runtime
    sandbox = runtime / "developer-mode" / "sandboxes" / "fixture-sandbox"
    empty_store(sandbox / "workspace")
    runs = sandbox / ".runtime" / "runtime-manager" / "work_runs" / "supervised"
    write_json(runs / "index.json", {"activeRunIds": ["sandbox-only"]})
    write_json(runs / "runs" / "sandbox-only.json", {"runId": "sandbox-only", "status": status,
        "currentAgentBinding": {"modelId": "alpha/spare"}})
    before = {str(path): path.read_bytes() for path in sandbox.rglob("*") if path.is_file()}
    for kind, reference in (("model", "alpha/spare"), ("provider", "alpha")):
        proof = env.guard.scan(kind, reference)
        assert proof.known_reference_count == 1 and proof.summary()["blocking"]
        assert proof.complete is (status == "RUNNING")
        if status != "RUNNING":
            assert "supervised_activity_unknown" in proof.issues
    assert before == {str(path): path.read_bytes() for path in sandbox.rglob("*") if path.is_file()}
    assert not (runtime / "runtime-manager" / "work_runs").exists()


@pytest.mark.parametrize("status", ["RUNNING", "unexpected_active_state"])
def test_canonical_supervised_kind_and_activity_cannot_bypass_retirement(env, status):
    from core.runtime_manager.work_run_store import WorkRunStore
    lease = SimpleNamespace(assert_current=lambda: None)
    with env.guard.zero_references("model", "alpha/spare", registry_lease=lease) as permit:
        remove_native_model(env, permit)
    runs = WorkRunStore(env.paths[0].runtime / "runtime-manager" / "work_runs")
    with pytest.raises(ValueError, match="removed or disabled"):
        runs.persist_snapshot("SUPERVISED", {"runId": "uppercase", "status": status,
            "currentAgentBinding": {"modelId": "alpha/spare"}}, active_run_id="uppercase")
    assert not runs.index_path("supervised").exists()
    assert not (runs.runs_dir("supervised") / "uppercase.json").exists()


def test_unknown_sql_participant_fails_before_enqueue_and_native_config_rolls_back(env):
    from config import operator_config_transaction as transaction
    from config.public_config import public_config_hash
    from core.chat.conversation_store import ConversationStore
    before = env.config.read_bytes()
    prepared = transaction.prepare_operator_config_transaction(operation_kind="test_nested_sql_participant", config_path=env.config,
        expected_base_hash=public_config_hash(tomllib.loads(before.decode())),
        mutate_text=lambda text: text + "\n# candidate edit\n")
    rollbacks, futures = [], []
    with ConversationStore(env.paths[0].workspace / "chat" / "conversations.sqlite3") as store:
        def nested_sql():
            future = store.repository.create_agent(agent_id="unsupported-nested", display_name="Fixture", kind="chat",
                config={"llmBindings": {"dialogue": {"modelId": "alpha/spare"}}}, source="test")
            futures.append(future)
            assert future.done(), "Nested SQL must fail before waiting on another writer thread"
            future.result()
        participant = transaction.TransactionParticipant(name="unexpected-sql", apply=nested_sql,
            verify=lambda: pytest.fail("failed apply reached verify"), rollback=lambda: rollbacks.append(True))
        with pytest.raises(transaction.OperatorConfigTransactionError) as error:
            transaction.apply_operator_config_transaction(prepared, participants=[participant])
        assert error.value.status == "rolled_back" and rollbacks == [True]
        assert isinstance(futures[0].exception(), RuntimeError)
        assert "caller owns" in str(futures[0].exception())
        assert store.repository.get_agent("unsupported-nested") is None
        # The unsupported nested call did not poison the ordinary writer queue.
        assert store.repository.create_agent(agent_id="ordinary-after-rollback", display_name="Fixture", kind="chat",
            config={}, source="test").result(timeout=5)["agentId"] == "ordinary-after-rollback"
    assert env.config.read_bytes() == before


def test_promotion_owns_native_state_before_config_fence_and_normal_save_waits(env, tmp_path, monkeypatch):
    from tests.test_agent_model_promotion_service import _setup, _promote
    from core.web.services import agent_directory_service as directory
    from core.web.services import agent_model_promotion_service as promotion
    from core.web.services.agent_directory.ops_residual import save_registry_payload
    promotion_root = tmp_path / "promotion"
    promotion_root.mkdir()
    setup = _setup(promotion_root, monkeypatch)
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(setup["config_path"]))
    reached, release, saving = threading.Event(), threading.Event(), threading.Event()
    apply = promotion.apply_operator_config_transaction
    def checked_apply(*args, **kwargs):
        assert directory._STATE_LOCK._is_owned()
        reached.set()
        assert release.wait(timeout=5)
        return apply(*args, **kwargs)
    monkeypatch.setattr(promotion, "apply_operator_config_transaction", checked_apply)
    def save():
        saving.set()
        with directory._STATE_LOCK:
            payload = json.loads(setup["registry_path"].read_text(encoding="utf-8"))
            return save_registry_payload(payload, enforce_shrink_guard=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        promoted = pool.submit(_promote, setup)
        try:
            assert reached.wait(timeout=5)
            saved = pool.submit(save)
            assert saving.wait(timeout=2) and not saved.done()
        finally:
            release.set()
        assert promoted.result(timeout=5)["status"] == "completed"
        assert saved.result(timeout=5)["agents"]


def _route_seed(monkeypatch, formal, sandbox):
    from core.infrastructure import developer_sandbox
    monkeypatch.setattr(developer_sandbox, "formal_workspace_path", lambda _root, *parts: formal.joinpath(*parts))
    monkeypatch.setattr(developer_sandbox, "sandbox_workspace_path", lambda _root, *parts: sandbox.joinpath(*parts))
    return developer_sandbox


@pytest.mark.parametrize("parts", [("chat",), ("chat", "conversations.sqlite3")])
def test_sandbox_sqlite_seed_uses_live_wal_snapshot_without_reviving_old_binding(env, monkeypatch, parts):
    from core.chat.conversation_store import ConversationStore, runtime
    formal = env.paths[0].workspace
    sandbox = env.paths[0].runtime / "developer-mode" / "sandboxes" / "seed" / "workspace"
    owner = _route_seed(monkeypatch, formal, sandbox)
    path = formal / "chat" / "conversations.sqlite3"
    with ConversationStore(path) as store:
        original = store.repository.create_agent(agent_id="rebound", display_name="Fixture", kind="chat",
            config={"llmBindings": {"dialogue": {"modelId": "alpha/spare"}}}, source="test").result(timeout=5)
        store.checkpoint_wal_passive()
        store.repository.compare_and_swap_agent_config(agent_id="rebound", expected_config_revision_id=original["configRevisionId"],
            display_name="Fixture", kind="chat", status="active", config={"llmBindings": {"dialogue": {"modelId": "alpha/other"}}},
            source="test").result(timeout=5)
        assert Path(str(path) + "-wal").stat().st_size > 0
        main_only = runtime.connect(path.as_uri() + "?immutable=1", uri=True)
        try:
            old = main_only.execute("SELECT r.config_json FROM agents a JOIN agent_config_revisions r ON r.revision_id=a.current_config_revision_id").fetchone()[0]
            assert "alpha/spare" in old
        finally:
            main_only.close()
        # Source DB and WAL are observed after the live update, before backup.
        watched = [path, Path(str(path) + "-wal")]
        before = [(item.read_bytes(), item.stat().st_mtime_ns) for item in watched]
        owner.seeded_sandbox_workspace_path(env.roots[0], *parts)
        assert before == [(item.read_bytes(), item.stat().st_mtime_ns) for item in watched]
        assert store.repository.get_current_agent_config("rebound")["config"]["llmBindings"]["dialogue"]["modelId"] == "alpha/other"
        result = read_existing_model_reference_metadata(sandbox, sandbox.parent / ".runtime")
        assert result["complete"]
        assert [row["modelId"] for row in result["references"]] == ["alpha/other"]
    assert not (sandbox / "chat" / "conversations.sqlite3-wal").exists()


def test_sandbox_seed_failure_has_no_partial_ready_or_overwrite_and_retry_uses_native_backup(env, monkeypatch):
    from core.chat.conversation_store import runtime
    formal = env.paths[0].workspace
    sandbox = env.paths[0].runtime / "developer-mode" / "sandboxes" / "seed-failure" / "workspace"
    owner = _route_seed(monkeypatch, formal, sandbox)
    connect = runtime.connect
    calls = []
    def fail_backup(*args, **kwargs):
        calls.append((args, kwargs))
        raise OSError("fixture interrupted native SQLite backup")
    monkeypatch.setattr(runtime, "connect", fail_backup)
    with pytest.raises(OSError, match="interrupted"):
        owner.seeded_sandbox_workspace_path(env.roots[0], "chat")
    assert calls and calls[0][1] == {"uri": True}
    assert "mode=ro" in calls[0][0][0]
    assert not (sandbox / "chat").exists() and list(sandbox.glob(".chat.seed-*")) == []
    monkeypatch.setattr(runtime, "connect", connect)
    assert owner.seeded_sandbox_workspace_path(env.roots[0], "chat") == sandbox / "chat"
    target = sandbox / "chat" / "conversations.sqlite3"
    saved = target.read_bytes()
    monkeypatch.setattr(runtime, "connect", fail_backup)
    owner.seeded_sandbox_workspace_path(env.roots[0], "chat")
    assert target.read_bytes() == saved and len(calls) == 1


def test_interrupted_sqlite_seed_cleans_partial_staging_and_keeps_source(env, monkeypatch):
    from core.chat.conversation_store import runtime
    formal = env.paths[0].workspace
    sandbox = env.paths[0].runtime / "developer-mode" / "sandboxes" / "interrupted" / "workspace"
    owner = _route_seed(monkeypatch, formal, sandbox)
    source = formal / "chat" / "conversations.sqlite3"
    before = source.read_bytes(), source.stat().st_mtime_ns
    class InterruptedBackup:
        def execute(self, sql, values):
            assert sql == "VACUUM INTO ?"
            Path(values[0]).write_bytes(b"incomplete sqlite backup")
            raise OSError("fixture interrupted during native copy")
        def close(self):
            pass
    monkeypatch.setattr(runtime, "connect", lambda *_args, **_kwargs: InterruptedBackup())
    with pytest.raises(OSError, match="during native copy"):
        owner.seeded_sandbox_workspace_path(env.roots[0], "chat")
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert not (sandbox / "chat").exists() and list(sandbox.glob(".chat.seed-*")) == []


def test_db_seed_never_overwrites_a_target_created_during_copy(env, monkeypatch):
    formal = env.paths[0].workspace
    sandbox = env.paths[0].runtime / "developer-mode" / "sandboxes" / "target-race" / "workspace"
    owner = _route_seed(monkeypatch, formal, sandbox)
    target = sandbox / "chat" / "conversations.sqlite3"
    copy = owner._copy_reference_seed_file
    def copy_and_create_target(source, stage):
        result = copy(source, stage)
        target.write_bytes(b"concurrent native DB owner")
        return result
    monkeypatch.setattr(owner, "_copy_reference_seed_file", copy_and_create_target)
    with pytest.raises(FileExistsError):
        owner.seeded_sandbox_workspace_path(env.roots[0], "chat", "conversations.sqlite3")
    assert target.read_bytes() == b"concurrent native DB owner"
    assert list(target.parent.glob(".conversations.sqlite3.seed-*")) == []


def set_aliases(env, aliases):
    from config.operator_config_transaction import append_toml_table
    env.config.write_text(append_toml_table(env.config.read_text(), ("llm", "model_aliases"), aliases), encoding="utf-8")


def commit_alias_fixture(env, mutate, tables, *, permit=None):
    from config import operator_config_transaction as transaction
    from config.public_config import public_config_hash
    before = tomllib.loads(env.config.read_text())
    candidate = mutate(deepcopy(before))
    def at(payload, table):
        for part in table:
            payload = payload.get(part) if isinstance(payload, dict) else None
        return payload
    def mutate_text(text):
        for table in tables:
            if at(before, table) is not None:
                text = transaction.remove_toml_table_tree(text, table)
            if at(candidate, table) is not None:
                text = transaction.append_toml_table(text, table, at(candidate, table))
        assert tomllib.loads(text) == candidate
        return text
    prepared = transaction.prepare_operator_config_transaction(operation_kind="test_alias_reference_commit", config_path=env.config,
        expected_base_hash=public_config_hash(before), mutate_text=mutate_text)
    result = transaction.apply_operator_config_transaction(prepared)
    if permit is not None:
        permit.confirm_commit_hash(result["hash"])
    return candidate


def test_native_static_alias_is_not_a_binding_and_native_unpin_does_not_clear_it(env):
    from config.llm_provider_registry import unpin_llm_model
    set_aliases(env, {"ENTRY": "latest", "latest": "alpha/spare"})
    assert env.guard.scan("model", "alpha/spare").complete
    assert env.guard.scan("model", "alpha/spare").known_reference_count == 0
    with env.guard.zero_references("model", "alpha/spare", registry_lease=SimpleNamespace(assert_current=lambda: None)) as permit:
        saved = commit_alias_fixture(env, lambda config: unpin_llm_model(config, "alpha/spare"),
            [("llm", "providers", "alpha", "models", "spare")], permit=permit)
    assert saved["llm"]["model_aliases"] == {"ENTRY": "latest", "latest": "alpha/spare"}
    # Native unpin leaves unused aliases dangling; they do not make another
    # model's otherwise complete zero-reference proof unavailable.
    proof = env.guard.scan("model", "alpha/other")
    assert proof.complete and proof.known_reference_count == 0


def test_actual_alias_bindings_count_for_model_and_provider_across_old_pins_native_and_config(env):
    from config.operator_config_transaction import append_toml_table
    set_aliases(env, {"ENTRY": "latest", "latest": "alpha/spare", "beta-alias": "beta/spare"})
    bind_store(env.paths[1].workspace / "chat" / "conversations.sqlite3", "ENTRY")
    bind_store(env.native_workspace / "chat" / "conversations.sqlite3", "alpha/other", session_model="latest")
    env.config.write_text(append_toml_table(env.config.read_text(), ("git",), {"commit_message_model_ref": "ENTRY"}), encoding="utf-8")
    model = env.guard.scan("model", "alpha/spare")
    provider = env.guard.scan("provider", "alpha")
    assert model.complete and model.known_reference_count == 3
    assert provider.complete and provider.known_reference_count == 4
    beta = env.guard.scan("model", "beta/spare")
    assert beta.complete and beta.known_reference_count == 0


@pytest.mark.parametrize("aliases,raw", [
    ({"ENTRY": "alpha/spare"}, "entry"),
    ({"ENTRY": "Alpha/spare"}, "ENTRY"),
    ({"ENTRY": "alpha/missing"}, "ENTRY"),
    ({"ENTRY": "next", "next": "ENTRY"}, "ENTRY"),
    ({"ENTRY": ""}, "ENTRY"),
    ({"ENTRY": 1}, "ENTRY"),
])
def test_alias_case_cycles_bad_map_and_missing_target_are_explicitly_unavailable(env, aliases, raw):
    set_aliases(env, aliases)
    bind_store(env.paths[0].workspace / "chat" / "conversations.sqlite3", raw)
    proof = env.guard.scan("model", "alpha/spare")
    assert not proof.complete and proof.summary()["liveReferenceCount"] is None
    assert proof.summary()["blocking"]


@pytest.mark.parametrize("change", ["model-remove", "provider-disable", "model-remove-and-clear-alias"])
def test_queued_alias_is_rejected_after_real_native_model_or_provider_retirement(env, change):
    from config.llm_provider_registry import unpin_llm_model, update_llm_provider
    from core.chat.conversation_store import ConversationStore
    set_aliases(env, {"ENTRY": "latest", "latest": "alpha/spare"})
    kind, reference = ("provider", "alpha") if change == "provider-disable" else ("model", "alpha/spare")
    tables = [("llm", "providers", "alpha")] if change == "provider-disable" else [("llm", "providers", "alpha", "models", "spare")]
    if change == "model-remove-and-clear-alias":
        tables.append(("llm", "model_aliases"))
    def mutate(config):
        if change == "provider-disable":
            record = config["llm"]["providers"]["alpha"]
            return update_llm_provider(config, "alpha", {**record, "enabled": False})
        config = unpin_llm_model(config, "alpha/spare")
        if change == "model-remove-and-clear-alias":
            config["llm"].pop("model_aliases")
        return config
    with ConversationStore(env.paths[0].workspace / "chat" / "conversations.sqlite3") as store, ThreadPoolExecutor(max_workers=1) as pool:
        with env.guard.zero_references(kind, reference, registry_lease=SimpleNamespace(assert_current=lambda: None)) as permit:
            future = pool.submit(lambda: store.repository.create_agent(agent_id="late-alias", display_name="Fixture", kind="chat",
                config={"llmBindings": {"dialogue": {"modelId": "ENTRY"}}}, source="test")).result(timeout=2)
            assert not future.done()
            commit_alias_fixture(env, mutate, tables, permit=permit)
        with pytest.raises(ValueError, match="removed or disabled"):
            future.result(timeout=5)
        assert store.repository.get_agent("late-alias") is None
        assert store.repository.create_agent(agent_id="opaque-still-valid", display_name="Fixture", kind="chat",
            config={"llmBindings": {"dialogue": {"modelId": "unmarked_historical_opaque"}}}, source="test").result(timeout=5)["agentId"] == "opaque-still-valid"


def test_alias_lineage_can_be_restored_or_rebound_using_current_public_config(env):
    from config.llm_provider_registry import unpin_llm_model
    from core.chat.conversation_store import ConversationStore
    set_aliases(env, {"ENTRY": "latest", "latest": "alpha/spare"})
    with env.guard.zero_references("model", "alpha/spare", registry_lease=SimpleNamespace(assert_current=lambda: None)) as permit:
        commit_alias_fixture(env, lambda config: unpin_llm_model(config, "alpha/spare"),
            [("llm", "providers", "alpha", "models", "spare")], permit=permit)
    def rebind(config):
        config["llm"]["model_aliases"]["latest"] = "beta/spare"
        return config
    commit_alias_fixture(env, rebind, [("llm", "model_aliases")])
    with ConversationStore(env.paths[0].workspace / "chat" / "conversations.sqlite3") as store:
        assert store.repository.create_agent(agent_id="rebound-alias", display_name="Fixture", kind="chat",
            config={"llmBindings": {"dialogue": {"modelId": "ENTRY"}}}, source="test").result(timeout=5)["agentId"] == "rebound-alias"
    proof = env.guard.scan("provider", "beta")
    assert proof.complete and proof.known_reference_count == 1
    def restore(config):
        config["llm"]["providers"]["alpha"]["models"]["spare"] = {"upstream_id": "same-upstream"}
        config["llm"]["model_aliases"]["latest"] = "alpha/spare"
        return config
    commit_alias_fixture(env, restore, [("llm", "providers", "alpha", "models", "spare"), ("llm", "model_aliases")])
    with ConversationStore(env.paths[0].workspace / "chat" / "conversations.sqlite3") as store:
        assert store.repository.create_agent(agent_id="restored-alias", display_name="Fixture", kind="chat",
            config={"llmBindings": {"dialogue": {"modelId": "ENTRY"}}}, source="test").result(timeout=5)["agentId"] == "restored-alias"
    proof = env.guard.scan("model", "alpha/spare")
    assert proof.complete and proof.known_reference_count == 2


def test_alias_lineage_byte_limit_is_checked_before_persisting_a_marker(env):
    import hashlib
    import core.infrastructure.model_reference_fence as fence
    aliases = {f"entry-{index}-" + "x" * 300: "alpha/spare" for index in range(7000)}
    set_aliases(env, aliases)
    before = env.config.read_bytes()
    with model_reference_fence(env.config):
        with pytest.raises(ValueError, match="byte limit"):
            fence.record_model_retirements(["alpha/spare"], config_hash=hashlib.sha256(before).hexdigest(),
                reason="guarded_model_change", config_path=env.config)
    assert not fence._retirement_path(env.config).exists()
    assert env.config.read_bytes() == before
