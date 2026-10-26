"""Current Agent parameter reads freeze native sources without provisioning."""
from __future__ import annotations

import copy
import json
import tomllib
from types import SimpleNamespace

import pytest

from tests.test_external_management_workspace import env


PUBLIC_CONFIG = '''
[llm]
schema_version = 2
[llm.providers.fixture]
label = "Fictional provider"
service_class = "local_runtime"
driver = "openai"
base_url = "http://127.0.0.1:9/v1"
auth_kind = "none"
credential_ref = "none"
requires_credential = false
context_window = 96000
[llm.providers.fixture.protocols]
default = "chat_completions"
allowed = ["chat_completions"]
[llm.providers.fixture.models.model]
upstream_id = "fictional-reasoner"
interaction_contract = "tool_chat"
model_protocol = "openai_chat_tools"
context_window = 64000
[llm.providers.fixture.models.model.defaults]
reasoning_effort_values = ["low", "high"]
default_reasoning_effort = "low"
reasoning_effort_adapter = "reasoning_effort"
[llm.profiles.primary]
model_ref = "fixture/model"
'''


@pytest.fixture
def parameters_env(env, monkeypatch):
    from config import public_config, settings
    from config.model_catalog import empty_model_catalog_state
    from config.paths import resolve_model_catalog_state_path
    from core.web.services.external_management import session_parameters as reader
    from core.infrastructure import developer_sandbox

    public = tomllib.loads(PUBLIC_CONFIG)
    runtime = public_config.build_effective_config(public)
    path = env.root / "config.toml"
    path.write_text(PUBLIC_CONFIG, encoding="utf-8")
    catalog_path = resolve_model_catalog_state_path(path)
    catalog = empty_model_catalog_state()
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(public_config, "CONFIG_PATH", path)
    monkeypatch.setattr(env.directory, "CONFIG_PATH", path)
    old_save = env.save
    env.registry = env.root / "agents" / "agents.json"
    env.registry.parent.mkdir()
    def save():
        old_save()
        env.registry.write_text(json.dumps({"agents": [env.agent]}), encoding="utf-8")
    env.save = save
    env.plugin_root = env.root / "agents" / "agent-a" / "plugins" / "virtual-human-life"
    env.plugin_root.mkdir(parents=True)
    env.directory_store = SimpleNamespace(repository=env.repository,
        database=SimpleNamespace(path=env.root / "formal-runtime" / "conversations.sqlite3"))
    monkeypatch.setattr(env.directory_runtime, "get_open_directory_store", lambda: env.directory_store)
    def formal_path(project, *parts):
        assert project == env.root
        return env.root.joinpath(*parts)
    monkeypatch.setattr(developer_sandbox, "formal_workspace_path", formal_path)
    visibility_source = reader._visibility_source
    def source(snapshot, kind, agent_id=None):
        env.calls.append({"agents": "registry", "team_member_ids": "team-index", "binding": "binding"}[kind])
        return visibility_source(snapshot, kind, agent_id)
    monkeypatch.setattr(reader, "_visibility_source", source)
    monkeypatch.setattr(settings, "_settings", SimpleNamespace(_config=runtime))
    env.agent.update(configRevision=7, llmBindings={"dialogue": {"modelId": "fixture/model"}},
        metadata={"llmModelParameters": {"fixture/model": {"contextWindow": 32000, "reasoningEffort": "high"}},
                  "sessionBudgetParameters": {"maxCallsPerTurn": 0}})
    env.save()
    env.reader, env.public, env.runtime_config = reader, public, runtime
    env.config_path, env.catalog_path, env.catalog = path, catalog_path, catalog
    return env


def test_current_parameters_freeze_sources_and_never_ensure_or_read_body(parameters_env, monkeypatch):
    from config import model_catalog, public_config, settings
    from core.llm import discovery
    from core.web.services import agent_model_candidate_service as candidates
    from core.infrastructure import developer_sandbox
    env = parameters_env
    def forbidden(*_a, **_k):
        pytest.fail("implicit getter, writer, hydration or model request")
    for owner, names in ((settings, ("get_settings", "get_config", "reload_config", "ensure_global_config_initialized")),
                         (public_config, ("load_public_config", "get_public_config_snapshot", "save_public_config")),
                         (model_catalog, ("load_model_catalog_state", "save_model_catalog_state")),
                         (discovery, ("load_model_catalog_state",)),
                         (candidates, ("list_agent_model_candidates",)),
                         (developer_sandbox, ("_ensure_active_state", "seeded_sandbox_workspace_path",
                            "sandboxed_workspace_path", "route_workspace_path")),
                         (env.sessions, ("get_config", "_ensure_session_conversation_record", "get_session_llm_options",
                                         "get_session_budget_parameters_view", "get_agent"))):
        for name in names:
            monkeypatch.setattr(owner, name, forbidden)
    monkeypatch.setattr(env.service.store, "write", forbidden)
    monkeypatch.setattr(env.service.store, "lock", forbidden)
    before = {str(p): p.read_bytes() for p in env.root.rglob("*") if p.is_file()}
    result = env.reader.read_session_parameters(env.root, env.directory, "session-a")
    assert result == {"source": "native-current-agent-runtime-parameters", "untrustedContent": True,
        "catalogState": "existing", "parameters": {"sessionId": "session-a", "agentId": "agent-a",
            "configRevision": 7, "currentModelId": "fixture/model", "currentReasoningEffort": "high",
            "reasoningEffortValues": ["low", "high"], "contextWindow": 32000, "maxContextWindow": 64000,
            "budget": {"revision": 7, "maxCallsPerTurn": 0}}}
    assert env.calls == ["directory", "runtime", "registry", "team-index", "binding"]
    assert "SECRET" not in json.dumps(result) and "choices" not in result["parameters"]
    assert before == {str(p): p.read_bytes() for p in env.root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("fault", ["config_missing", "config_corrupt", "runtime_unloaded", "catalog_corrupt",
    "revision_bool", "revision_missing", "revision_negative", "bindings_bad", "metadata_bad", "runtime_model_missing"])
def test_unavailable_parameter_sources_fail_closed(parameters_env, monkeypatch, fault):
    from config import settings
    from core.web.services.external_management.service import ManagementError
    env = parameters_env
    if fault == "config_missing":
        env.config_path.unlink()
    elif fault == "config_corrupt":
        env.config_path.write_text("[broken", encoding="utf-8")
    elif fault == "runtime_unloaded":
        monkeypatch.setattr(settings, "_settings", SimpleNamespace(_config=None))
    elif fault == "catalog_corrupt":
        env.catalog_path.write_text('{"schemaVersion":2,"providers":[]}', encoding="utf-8")
    elif fault == "revision_bool":
        env.agent["configRevision"] = True
    elif fault == "revision_missing":
        env.agent.pop("configRevision")
    elif fault == "revision_negative":
        env.agent["configRevision"] = -1
    elif fault == "bindings_bad":
        env.agent["llmBindings"] = []
    elif fault == "metadata_bad":
        env.agent["metadata"] = []
    else:
        env.runtime_config.llm.model_library.clear()
    env.save()
    with pytest.raises(ManagementError) as error:
        env.reader.read_session_parameters(env.root, env.directory, "session-a")
    # Visibility owns malformed metadata; parameter-source failures are 503.
    expected = ("SESSION_UNAVAILABLE", 404) if fault == "metadata_bad" else ("SESSION_PARAMETERS_UNAVAILABLE", 503)
    assert (error.value.code, error.value.status_code) == expected


def test_absent_catalog_is_explicit_empty_observation(parameters_env):
    env = parameters_env
    env.catalog_path.unlink()
    result = env.reader.read_session_parameters(env.root, env.directory, "session-a")
    assert result["catalogState"] == "absent"
    assert result["parameters"]["reasoningEffortValues"] == ["low", "high"]
    assert not env.catalog_path.exists()


def test_native_none_effort_is_retained_in_closed_projection(parameters_env, monkeypatch):
    from config import public_config, settings
    env = parameters_env
    saved = PUBLIC_CONFIG.replace('["low", "high"]', '["none", "high"]').replace(
        'default_reasoning_effort = "low"', 'default_reasoning_effort = "none"')
    env.config_path.write_text(saved, encoding="utf-8")
    monkeypatch.setattr(settings, "_settings", SimpleNamespace(
        _config=public_config.build_effective_config(tomllib.loads(saved))))
    env.agent["metadata"]["llmModelParameters"]["fixture/model"]["reasoningEffort"] = "none"
    env.save()
    view = env.reader.read_session_parameters(env.root, env.directory, "session-a")["parameters"]
    assert view["currentReasoningEffort"] == "none"
    assert view["reasoningEffortValues"] == ["none", "high"]


@pytest.mark.parametrize("current_fingerprint", [True, False])
def test_verified_reasoning_uses_saved_provider_fingerprint(parameters_env, monkeypatch, current_fingerprint):
    from config import public_config, settings
    from config.llm_identity import provider_discovery_fingerprint
    env = parameters_env
    # No operator/family effort values: only verified observations may supply them.
    saved = PUBLIC_CONFIG.replace('model_protocol = "openai_chat_tools"', 'model_protocol = ""').replace(
        'reasoning_effort_values = ["low", "high"]\ndefault_reasoning_effort = "low"\nreasoning_effort_adapter = "reasoning_effort"', "")
    env.config_path.write_text(saved, encoding="utf-8")
    public = tomllib.loads(saved)
    runtime = public_config.build_effective_config(public)
    runtime.llm.providers["fixture"].base_url = "http://127.0.0.1:10/runtime-only"
    runtime.llm.model_library["fixture/model"].update(reasoning_effort_values=["low", "high"],
        reasoning_effort_adapter="reasoning_effort", default_reasoning_effort="low")
    monkeypatch.setattr(settings, "_settings", SimpleNamespace(_config=runtime))
    fingerprint = provider_discovery_fingerprint(public["llm"]["providers"]["fixture"])
    env.catalog["providers"] = {"fixture": {"models": {"model": {"reasoningContract": {
        "verificationStatus": "verified", "providerFingerprint": fingerprint if current_fingerprint else "stale",
        "source": "runtime_probe", "effortValues": ["low", "high"], "default": "low", "adapter": "reasoning_effort"}}}}}
    env.catalog_path.write_text(json.dumps(env.catalog), encoding="utf-8")
    result = env.reader.read_session_parameters(env.root, env.directory, "session-a")["parameters"]
    assert result["reasoningEffortValues"] == (["low", "high"] if current_fingerprint else [])
    assert result["currentReasoningEffort"] == ("high" if current_fingerprint else "")


def test_runtime_profile_reasoning_and_saved_candidate_basis_stay_separate(parameters_env, monkeypatch):
    from config import settings
    env = parameters_env
    monkeypatch.setenv("AGENT_RUNTIME_PROFILE", "ci")
    monkeypatch.setenv("AGENT_LLM__PROFILES__PRIMARY__REASONING_EFFORT", "high")
    runtime = settings.ConfigLoader(str(env.config_path)).load()
    assert runtime.runtime.profile == "ci"
    assert runtime.llm.profiles["primary"].reasoning_effort == "high"
    monkeypatch.setattr(settings, "_settings", SimpleNamespace(_config=runtime))
    env.agent["metadata"] = {"llmReasoningEffort": {"dialogue": "low"},
        "llmModelParameters": {"fixture/model": {"reasoningEffort": ""}}}
    env.save()
    result = env.reader.read_session_parameters(env.root, env.directory, "session-a")["parameters"]
    assert result["currentReasoningEffort"] == "high"
    assert result["reasoningEffortValues"] == ["low", "high"]
    assert result["contextWindow"] == result["maxContextWindow"] == 64000
    assert result["budget"] == {"revision": 7, "maxCallsPerTurn": None}


def test_missing_developer_authority_is_not_initialized(parameters_env, monkeypatch):
    from core.infrastructure import developer_sandbox
    from core.web.services.external_management.service import ManagementError
    env = parameters_env
    env.config_path.write_text(PUBLIC_CONFIG + "\n[launcher.developer_mode]\nenabled = true\n", encoding="utf-8")
    missing = env.root / "missing-mode" / "active.json"
    monkeypatch.setattr(developer_sandbox, "_active_state_path", lambda _root: missing)
    def forbidden(*_a, **_k):
        pytest.fail("missing developer authority was initialized or seeded")
    for name in ("_ensure_active_state", "seeded_sandbox_workspace_path", "sandboxed_workspace_path", "route_workspace_path"):
        monkeypatch.setattr(developer_sandbox, name, forbidden)
    before = {str(p): p.read_bytes() for p in env.root.rglob("*") if p.is_file()}
    with pytest.raises(ManagementError) as error:
        env.reader.read_session_parameters(env.root, env.directory, "session-a")
    assert (error.value.code, error.value.status_code) == ("SESSION_PARAMETERS_UNAVAILABLE", 503)
    assert not missing.parent.exists()
    assert before == {str(p): p.read_bytes() for p in env.root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("case", ["base", "legacy", "explicit_clear"])
def test_complete_snapshot_matches_old_native_effective_fields(parameters_env, monkeypatch, case):
    from core.llm import discovery
    from core.web.services.agent_model_candidate_service import project_agent_model_candidates
    from core.web.services.session.agent_runtime import _session_llm_options_from_agent
    from core.web.services.session.budget_parameters import _budget_parameters_view
    from tools.pa_workspace_actions import _llm_public
    env = parameters_env
    if case != "base":
        env.agent["metadata"]["llmReasoningEffort"] = {"dialogue": "high"}
        entry = env.agent["metadata"]["llmModelParameters"]["fixture/model"]
        if case == "legacy":
            entry.pop("reasoningEffort")
        else:
            entry["reasoningEffort"] = ""
    env.save()
    monkeypatch.setattr(env.sessions, "get_config", lambda: copy.deepcopy(env.runtime_config))
    monkeypatch.setattr(discovery, "load_model_catalog_state", lambda: copy.deepcopy(env.catalog))
    choices = project_agent_model_candidates(env.public, env.catalog)
    old_llm = _llm_public(_session_llm_options_from_agent("session-a", copy.deepcopy(env.agent), choices[0], choices=choices))
    current = env.reader.read_session_parameters(env.root, env.directory, "session-a")["parameters"]
    assert {"sessionId": current["sessionId"], "agentId": current["agentId"],
        "modelRef": current["currentModelId"], "configRevision": current["configRevision"],
        "contextWindow": current["contextWindow"], "maxContextWindow": current["maxContextWindow"],
        "reasoningEffort": current["currentReasoningEffort"], "reasoningEffortValues": current["reasoningEffortValues"]} == old_llm
    assert current["budget"] == _budget_parameters_view(env.agent)


@pytest.mark.parametrize("declared,provider,expected", [(64000, 96000, 64000), (None, 96000, 96000), (None, None, 0)])
def test_context_maximum_retains_old_library_provider_rule(parameters_env, declared, provider, expected):
    env = parameters_env
    entry = env.runtime_config.llm.model_library["fixture/model"]
    entry.pop("context_window", None)
    if declared is not None:
        entry["context_window"] = declared
    env.runtime_config.llm.providers["fixture"].context_window = provider
    env.agent["metadata"]["llmModelParameters"]["fixture/model"]["contextWindow"] = 200000
    env.save()
    env.catalog["providers"] = {"fixture": {"models": {"model": {"contextWindow": 500000}}}}
    env.catalog_path.write_text(json.dumps(env.catalog), encoding="utf-8")
    result = env.reader.read_session_parameters(env.root, env.directory, "session-a")["parameters"]
    assert result["contextWindow"] == result["maxContextWindow"] == expected


@pytest.mark.parametrize("private", ["pa", "team", "companion", "archived", "hidden", "cross_binding"])
def test_parameter_read_retains_native_private_session_rejection(parameters_env, private):
    from core.web.services.external_management.service import ManagementError
    env = parameters_env
    if private == "pa":
        env.agent["roleKey"] = "personal_assistant"
    elif private == "team":
        env.team_index.write_text('{"teams":[{"members":[{"agentId":"agent-a"}]}]}', encoding="utf-8")
    elif private == "companion":
        (env.plugin_root / "binding.json").write_text('{"enabled":true,"agentId":"agent-a"}', encoding="utf-8")
    elif private == "archived":
        env.agent["status"] = "archived"
    elif private == "hidden":
        env.row["hiddenFromIndex"] = True
    else:
        env.runtime["agent_id"] = "different-agent"
    env.save()
    with pytest.raises(ManagementError) as error:
        env.reader.read_session_parameters(env.root, env.directory, "session-a")
    assert (error.value.code, error.value.status_code) == ("SESSION_UNAVAILABLE", 404)


def test_validator_returns_frozen_agent_only_when_requested(parameters_env):
    from core.web.services.external_management.workspace import _validated_session_snapshot
    env = parameters_env
    assert len(_validated_session_snapshot(env.root, env.directory, "session-a")) == 3
    captured = _validated_session_snapshot(env.root, env.directory, "session-a", return_agent=True)
    assert len(captured) == 4 and captured[3] == env.agent
    captured[3]["metadata"]["sessionBudgetParameters"]["maxCallsPerTurn"] = 20
    assert env.agent["metadata"]["sessionBudgetParameters"]["maxCallsPerTurn"] == 0


def _sandbox_pair(env, monkeypatch):
    from core.infrastructure import developer_sandbox
    env.config_path.write_text(PUBLIC_CONFIG + "\n[launcher.developer_mode]\nenabled = true\n", encoding="utf-8")
    sandboxes = env.root / "sandboxes"
    for token in ("a", "b"):
        workspace = sandboxes / token / "workspace"
        (workspace / "agents" / "agent-a" / "plugins" / "virtual-human-life").mkdir(parents=True)
        (workspace / "agents" / "agents.json").write_text(json.dumps({"agents": [env.agent]}), encoding="utf-8")
        (workspace / "teams").mkdir()
        (workspace / "teams" / "teams.json").write_text('{"teams":[]}', encoding="utf-8")
    active = env.root / "active.json"
    active.write_text('{"schemaVersion":1,"sandboxId":"a"}', encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "_active_state_path", lambda _root: active)
    monkeypatch.setattr(developer_sandbox, "_sandbox_root", lambda _root, token: sandboxes / token)
    return active, sandboxes


@pytest.mark.parametrize("change", ["switch", "aba", "developer_toggle", "config_path", "store", "store_closed", "store_generation", "database_path"])
def test_parameter_authority_change_after_registry_is_rejected(parameters_env, monkeypatch, change):
    from core.web.services.external_management.service import ManagementError
    env = parameters_env
    active, sandboxes = _sandbox_pair(env, monkeypatch)
    # The directory may legitimately remain on its already-open formal DB.
    original = env.reader._visibility_source
    def source(snapshot, kind, agent_id=None):
        result = original(snapshot, kind, agent_id)
        if kind == "agents":
            if change in {"switch", "aba"}:
                active.write_text('{"schemaVersion":1,"sandboxId":"b"}', encoding="utf-8")
                if change == "aba":
                    active.write_text('{"schemaVersion":1,"sandboxId":"a"}', encoding="utf-8")
                    # Make the ABA generation unambiguous even on coarse filesystems.
                    import os
                    stamp = active.stat()
                    os.utime(active, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 10000000))
            elif change == "developer_toggle":
                env.config_path.write_text(PUBLIC_CONFIG + "\n[launcher.developer_mode]\nenabled = false\n", encoding="utf-8")
            elif change == "config_path":
                other = env.root / "other-config.toml"
                other.write_text(env.config_path.read_text(encoding="utf-8"), encoding="utf-8")
                monkeypatch.setattr(env.directory, "CONFIG_PATH", other)
            elif change == "store":
                env.directory_store = SimpleNamespace(repository=env.repository, database=env.directory_store.database)
            elif change == "store_closed":
                monkeypatch.setattr(env.directory_runtime, "get_open_directory_store", lambda: None)
            elif change == "store_generation":
                monkeypatch.setattr(env.directory_runtime, "_GENERATION", env.directory_runtime._GENERATION + 1)
            else:
                env.directory_store.database.path = env.root / "different-database.sqlite3"
        return result
    monkeypatch.setattr(env.reader, "_visibility_source", source)
    with pytest.raises(ManagementError) as error:
        env.reader.read_session_parameters(env.root, env.directory, "session-a")
    assert (error.value.code, error.value.status_code) == ("SESSION_PARAMETERS_UNAVAILABLE", 503)


@pytest.mark.parametrize("private", ["roster", "binding"])
def test_sandbox_switch_cannot_hide_private_roster_or_binding(parameters_env, monkeypatch, private):
    from core.web.services.external_management.service import ManagementError
    env = parameters_env
    active, sandboxes = _sandbox_pair(env, monkeypatch)
    if private == "roster":
        (sandboxes / "a" / "workspace" / "teams" / "teams.json").write_text(
            '{"teams":[{"members":[{"agentId":"agent-a"}]}]}', encoding="utf-8")
    else:
        (sandboxes / "a" / "workspace" / "agents" / "agent-a" / "plugins" / "virtual-human-life" / "binding.json").write_text(
            '{"enabled":true,"agentId":"agent-a"}', encoding="utf-8")
    original = env.reader._visibility_source
    def source(snapshot, kind, agent_id=None):
        result = original(snapshot, kind, agent_id)
        if kind == "agents":
            active.write_text('{"schemaVersion":1,"sandboxId":"b"}', encoding="utf-8")
        return result
    monkeypatch.setattr(env.reader, "_visibility_source", source)
    with pytest.raises(ManagementError) as error:
        env.reader.read_session_parameters(env.root, env.directory, "session-a")
    assert (error.value.code, error.value.status_code) == ("SESSION_PARAMETERS_UNAVAILABLE", 503)


def test_formal_open_directory_and_stable_sandbox_sources_remain_supported(parameters_env, monkeypatch):
    env = parameters_env
    _sandbox_pair(env, monkeypatch)
    result = env.reader.read_session_parameters(env.root, env.directory, "session-a")
    assert result["parameters"]["agentId"] == "agent-a"
    assert result["parameters"]["budget"]["revision"] == 7


def test_validator_cannot_use_transient_replacement_store_with_same_repository(parameters_env, monkeypatch):
    from core.web.services.external_management.service import ManagementError
    env = parameters_env
    original = env.directory_store
    replacement = SimpleNamespace(repository=env.repository, database=original.database)
    reads = 0
    def store():
        nonlocal reads
        reads += 1
        return replacement if reads == 2 else original
    monkeypatch.setattr(env.directory_runtime, "get_open_directory_store", store)
    with pytest.raises(ManagementError) as error:
        env.reader.read_session_parameters(env.root, env.directory, "session-a")
    assert (error.value.code, error.value.status_code) == ("SESSION_PARAMETERS_UNAVAILABLE", 503)


@pytest.mark.parametrize("fault", ["duplicate", "oversized", "changed", "directory"])
def test_binding_authority_is_strict_bounded_and_stable(parameters_env, monkeypatch, fault):
    from core.web.services.external_management.service import ManagementError
    env = parameters_env
    path = env.plugin_root / "binding.json"
    if fault == "duplicate":
        path.write_text('{"enabled":true,"enabled":false,"agentId":"agent-a"}', encoding="utf-8")
    elif fault == "oversized":
        path.write_text('{"enabled":false,"pad":"' + "x" * (64 * 1024) + '"}', encoding="utf-8")
    elif fault == "directory":
        path.mkdir()
    else:
        path.write_text('{"enabled":false,"agentId":"agent-a"}', encoding="utf-8")
        real_open = type(path).open
        class ReplacingStream:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return self.stream.__exit__(*args)
            def fileno(self):
                return self.stream.fileno()
            def read(self, *args):
                raw = self.stream.read(*args)
                replacement = path.with_suffix(".next")
                replacement.write_text('{"enabled":true,"agentId":"agent-a"}', encoding="utf-8")
                replacement.replace(path)
                return raw
        def open_file(target, *args, **kwargs):
            stream = real_open(target, *args, **kwargs)
            return ReplacingStream(stream) if target == path and args and args[0] == "rb" else stream
        monkeypatch.setattr(type(path), "open", open_file)
    with pytest.raises(ManagementError) as error:
        env.reader.read_session_parameters(env.root, env.directory, "session-a")
    assert (error.value.code, error.value.status_code) == ("SESSION_PARAMETERS_UNAVAILABLE", 503)


@pytest.mark.parametrize("payload", [
    '{"teams":[{"members":[{"agentId":"agent-a"}]}],"teams":[]}',
    '{"teams":[],"ignored":NaN}',
])
def test_team_roster_json_is_strict(parameters_env, payload):
    from core.web.services.external_management.service import ManagementError
    env = parameters_env
    env.team_index.write_text(payload, encoding="utf-8")
    with pytest.raises(ManagementError) as error:
        env.reader.read_session_parameters(env.root, env.directory, "session-a")
    assert (error.value.code, error.value.status_code) == ("SESSION_PARAMETERS_UNAVAILABLE", 503)
