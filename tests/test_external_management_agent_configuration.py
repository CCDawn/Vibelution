"""Configuration management retains native owners, read purity and CAS evidence."""
from __future__ import annotations

from concurrent.futures import Future
from contextlib import nullcontext
from copy import deepcopy
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from tests.test_external_management_workspace import env
from tests.test_external_management_session_parameters import parameters_env


@pytest.fixture
def configuration_env(parameters_env, monkeypatch):
    from core.chat.conversation_store import ConversationStore
    from core.web.services.agent_config_authority import canonical_agent_config_payload
    from core.web.services.external_management.agent_configuration import AgentConfigurationControl
    from core.web.services.external_management.asset_control import AssetControl
    from core.web.services.agent_config_authority import DEFAULT_AGENT_CONTEXT_COMPRESSION_CREATION_POLICY

    data = parameters_env
    data.agent.update(displayName="Research helper", updatedAt="2026-11-05T01:00:00Z",
        promptTemplateId="prompt-chat-default", primaryMode="chat", createdBy="user",
        contextCompressionPolicy=deepcopy(DEFAULT_AGENT_CONTEXT_COMPRESSION_CREATION_POLICY))
    data.agent["metadata"].update(personaProfile={"personality": "Careful", "secret": "SECRET persona"},
        taskProfile={"mission": "Read evidence"}, secret="SECRET metadata")
    data.save()
    monkeypatch.setattr(AssetControl, "_owners", lambda _self: data.directory)
    monkeypatch.setattr(data.directory, "agent_session_lifecycle_transaction", lambda: nullcontext())
    monkeypatch.setattr(data.native, "_owners", lambda: data.directory)
    monkeypatch.setattr(data.native, "operation_receipts", None)
    with ConversationStore(data.root / "configuration.sqlite3") as store:
        store.repository.create_agent(agent_id="agent-a", display_name=data.agent["displayName"],
            kind="persistent", config=canonical_agent_config_payload(data.agent), source="test").result(timeout=3)
        monkeypatch.setattr(data.native, "_control_store", lambda: store)
        data.control = AgentConfigurationControl(data.native)
        data.store = store
        data.owner_calls = []

        def write(kind, values):
            data.owner_calls.append((kind, deepcopy(values)))
            if kind == "model":
                data.agent["metadata"]["llmModelParameters"]["fixture/model"] = deepcopy(values)
            elif kind == "budget":
                if values:
                    data.agent["metadata"]["sessionBudgetParameters"] = deepcopy(values)
                else:
                    data.agent["metadata"].pop("sessionBudgetParameters", None)
            else:
                data.agent["contextCompressionPolicy"] = deepcopy(values)
            data.agent["configRevision"] += 1
            data.agent["updatedAt"] = "2026-11-05T02:00:00Z"
            data.save()
            return deepcopy(data.agent)

        def model_owner(agent_id, **kwargs):
            assert agent_id == "agent-a" and kwargs["expected_config_revision"] == 7
            assert kwargs["expected_model_ref"] == "fixture/model"
            assert kwargs["supported_reasoning_efforts"] == ["low", "high"]
            return write("model", {"contextWindow": kwargs["context_window"], "reasoningEffort": kwargs["reasoning_effort"]})

        def budget_owner(agent_id, **kwargs):
            assert agent_id == "agent-a" and kwargs["expected_config_revision"] == 7
            return write("budget", kwargs["values"])

        monkeypatch.setattr(data.directory, "update_agent_model_parameters_if_current", model_owner)
        monkeypatch.setattr(data.directory, "update_agent_budget_parameters_if_current", budget_owner)
        operation = importlib.import_module("core.web.services.agent_operation_service")

        def compression_owner(agent_id, **kwargs):
            assert agent_id == "agent-a" and kwargs["expected_config_revision"] == 7
            assert set(kwargs["updates"]) == {"contextCompressionPolicy"}
            return write("compression", kwargs["updates"]["contextCompressionPolicy"])

        monkeypatch.setattr(operation, "update_agent_from_catalog_request", compression_owner)
        yield data


def request(kind, parameters, revision=7):
    return {"agent_id": "agent-a", "expected_config_revision": revision, "kind": kind, "parameters": parameters}


def test_public_contract_import_is_owner_free():
    script = """
import sys
from core.web.services.external_management.agent_configuration_contracts import AgentConfigurationResponse, AgentParametersUpdate
assert 'core.web.services.agent_directory_service' not in sys.modules
assert 'core.web.services.session_service' not in sys.modules
assert 'core.web.services.external_management.service' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("kind,block", [
    ("budget", {}), ("budget", {"maxCallsPerTurn": True}), ("budget", {"maxCallsPerTurn": "12"}),
    ("budget", {"maxCallsPerTurn": -1}), ("budget", {"maxCallsPerTurn": 201}),
    ("model", {"maxCallsPerTurn": 12}),
    ("model", {"expected_model_ref": "fixture/model", "context_window": 0, "reasoning_effort": ""}),
    ("model", {"expected_model_ref": "fixture/model", "context_window": 10, "reasoning_effort": "", "temperature": 1}),
    ("compression", {"policy": {"mode": "inherit"}}),
])
def test_parameter_contract_rejects_wrong_block_and_unowned_fields(kind, block):
    from core.web.services.external_management.agent_configuration_contracts import AgentParametersUpdate
    with pytest.raises(ValidationError):
        AgentParametersUpdate.model_validate(request(kind, block))


def test_read_configuration_is_finite_existing_only_and_roundtrips(configuration_env, monkeypatch):
    from config import settings, public_config, model_catalog
    from core.web.services.external_management.agent_configuration_contracts import AgentConfigurationResponse

    data = configuration_env
    def forbidden(*_a, **_kw):
        pytest.fail("Configuration GET attempted a write, repair or hydration")
    for owner, names in ((data.directory, ("get_agent", "get_agent_parameter_snapshot", "load_state", "_load_repaired_state_for_read")),
        (settings, ("get_config", "get_settings", "reload_config")),
        (public_config, ("load_public_config", "save_public_config")),
        (model_catalog, ("load_model_catalog_state", "save_model_catalog_state"))):
        for name in names:
            monkeypatch.setattr(owner, name, forbidden)
    monkeypatch.setattr(data.store.writer, "submit", forbidden)
    before = {str(path): path.read_bytes() for path in data.root.rglob("*") if path.is_file() and not path.name.endswith("-shm")}
    result = data.control.read_configuration("agent-a")
    assert AgentConfigurationResponse.model_validate(result).model_dump() == result
    assert result["compiledMatches"] is True
    assert result["personaProfile"]["personality"] == "Careful"
    assert result["parameters"]["model"]["effective"] == {"available": True, "contextWindow": 32000, "reasoningEffort": "high"}
    assert result["parameters"]["model"]["origin"]["contextWindow"] == "agent_model_parameters"
    assert result["parameters"]["budget"]["effective"] == {"available": True, "maxCallsPerTurn": 0}
    assert result["parameters"]["compression"]["origin"] == "agent"
    assert "SECRET" not in json.dumps(result) and "metadata" not in result and "prompt" not in result
    assert before == {str(path): path.read_bytes() for path in data.root.rglob("*") if path.is_file() and not path.name.endswith("-shm")}


def test_missing_override_and_runtime_do_not_invent_effective_defaults(configuration_env, monkeypatch):
    from config import settings
    from types import SimpleNamespace
    data = configuration_env
    data.agent["metadata"].pop("sessionBudgetParameters")
    data.save()
    monkeypatch.setattr(settings, "_settings", SimpleNamespace(_config=None))
    result = data.control.read_configuration("agent-a")
    assert result["parameters"]["budget"]["effective"] == {"available": False, "maxCallsPerTurn": None}
    assert result["parameters"]["budget"]["origin"] == "family_or_base_unavailable"
    assert result["parameters"]["model"]["effective"]["available"] is False


def test_budget_candidates_are_declared_data_without_fabricating_effective_policy(configuration_env):
    data = configuration_env
    data.agent["metadata"].pop("sessionBudgetParameters")
    data.agent["toolPolicy"] = {"maxCallsPerTurn": 32, "maxCallsPerTurnByModelFamily": {"qwen": 48, "default": 32},
        "perToolRules": {"read_file_tool": {"approvalGrants": "SECRET grant"}}}
    data.save()
    result = data.control.read_configuration("agent-a")["parameters"]["budget"]
    assert result["declaredPolicy"] == {"maxCallsPerTurn": 32, "maxCallsPerTurnByModelFamily": {"qwen": 48, "default": 32}}
    assert result["effective"] == {"available": False, "maxCallsPerTurn": None}
    assert "SECRET" not in json.dumps(result)


def test_read_preserves_native_profile_lengths_and_task_type_capacity(configuration_env):
    data = configuration_env
    background = "背" * 2001
    task_types = [f"task-{index}" for index in range(13)]
    data.agent["metadata"]["personaProfile"]["background"] = background
    data.agent["metadata"]["taskProfile"]["taskTypes"] = task_types
    data.agent["contextCompressionPolicy"]["preservation"]["retentionFocus"] = ["k" * 201] * 33
    data.save()
    result = data.control.read_configuration("agent-a")
    assert result["personaProfile"]["background"] == background
    assert result["taskProfile"]["taskTypes"] == task_types
    assert len(result["parameters"]["compression"]["stored"]["preservation"]["retentionFocus"]) == 33


def test_effective_reasoning_value_comes_from_native_adapter(configuration_env):
    data = configuration_env
    data.runtime_config.llm.model_library["fixture/model"]["reasoning_effort_map"] = {"high": "low"}
    result = data.control.read_configuration("agent-a")["parameters"]["model"]
    assert result["stored"]["reasoningEffort"] == "high"
    assert result["effective"]["reasoningEffort"] == "low"


def test_legacy_compression_does_not_initialize_runtime_but_versioned_policy_is_resolved(configuration_env, monkeypatch):
    from config import settings
    from core.web.services.team.challenge_cup_context_policy import CHALLENGE_CUP_CONTEXT_POLICY_VERSION
    data = configuration_env
    monkeypatch.setattr(settings, "get_config", lambda: pytest.fail("Legacy compression read initialized config"))
    legacy = data.control.read_configuration("agent-a")["parameters"]["compression"]
    assert legacy["stored"]["maxTokenLimit"] == 262144
    assert legacy["effective"]["available"] is False
    assert legacy["effective"]["source"] == "native_runtime_reader_required"
    data.agent["contextCompressionPolicy"].update(policyVersion=CHALLENGE_CUP_CONTEXT_POLICY_VERSION,
        compressionTriggerTokenLimit=20000, postCompressionTargetTokenLimit=10000)
    data.save()
    current = data.control.read_configuration("agent-a")["parameters"]["compression"]
    assert current["effective"]["available"] is True
    assert current["effective"]["contextWindowLimit"] == 32000
    assert current["effective"]["compressionTriggerTokenLimit"] <= 32000


def test_profileless_personal_agent_remains_manageable(configuration_env):
    from core.web.services.agent_config_authority import canonical_agent_config_payload
    data = configuration_env
    data.agent["roleKey"] = ""
    data.agent["metadata"].pop("personaProfile")
    data.agent["metadata"].pop("taskProfile")
    assert data.directory._is_profileless_session_agent(data.agent)
    data.save()
    current = data.store.repository.get_current_agent_config("agent-a")
    data.store.repository.compare_and_swap_agent_config(agent_id="agent-a",
        expected_config_revision_id=current["configRevisionId"], display_name=data.agent["displayName"],
        kind="persistent", status="active", config=canonical_agent_config_payload(data.agent), source="test").result(timeout=3)
    assert data.control.read_configuration("agent-a")["compiledMatches"] is True
    assert data.control.update_parameters(request("budget", {"maxCallsPerTurn": 12}))["verified"] is True


def test_native_revision_conflict_remains_a_no_write_rejection(configuration_env, monkeypatch):
    from core.web.services.external_management.service import ManagementError
    data = configuration_env
    def conflict(*_args, **_kwargs):
        raise data.directory.AgentStateConflictError("changed")
    monkeypatch.setattr(data.directory, "update_agent_budget_parameters_if_current", conflict)
    with pytest.raises(ManagementError) as error:
        data.control.update_parameters(request("budget", {"maxCallsPerTurn": 12}))
    assert error.value.code == "STATE_CONFLICT"
    assert data.agent["configRevision"] == 7


def test_compiled_owner_replacement_after_native_write_is_unconfirmed(configuration_env, monkeypatch):
    from types import SimpleNamespace
    from core.web.services.external_management.service import ManagementError
    data = configuration_env
    original = data.directory.update_agent_budget_parameters_if_current
    replacement = SimpleNamespace(repository=data.store.repository)
    def switched(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(data.native, "_control_store", lambda: replacement)
        return result
    monkeypatch.setattr(data.directory, "update_agent_budget_parameters_if_current", switched)
    with pytest.raises(ManagementError) as error:
        data.control.update_parameters(request("budget", {"maxCallsPerTurn": 12}))
    assert error.value.code == "OPERATION_UNCONFIRMED"
    assert data.agent["configRevision"] == 8


@pytest.mark.parametrize("kind,block", [
    ("model", {"expected_model_ref": "fixture/model", "context_window": 48000, "reasoning_effort": ""}),
    ("budget", {"maxCallsPerTurn": None}), ("budget", {"maxCallsPerTurn": 0}), ("budget", {"maxCallsPerTurn": 200}),
    ("compression", None),
])
def test_update_uses_exactly_one_owner_then_real_compiled_cas(configuration_env, kind, block):
    from core.web.services.agent_config_authority import canonical_agent_config_payload
    data = configuration_env
    if kind == "compression":
        block = {"policy": {**deepcopy(data.agent["contextCompressionPolicy"]), "maxTokenLimit": 40000}}
    original = data.store.repository.get_current_agent_config("agent-a")["configRevisionId"]
    result = data.control.update_parameters(request(kind, block))
    assert result["action"] == "agent_parameters_update" and result["verified"] is True and result["revision"] == 8
    assert len(data.owner_calls) == 1 and data.owner_calls[0][0] == kind
    compiled = data.store.repository.get_current_agent_config("agent-a")
    assert compiled["config"] == canonical_agent_config_payload(data.agent)
    # Budget isn't in the canonical hash; current revision may legitimately
    # retain the same compiled identity while the Agent revision advances.
    if kind != "budget":
        assert compiled["configRevisionId"] != original


@pytest.mark.parametrize("fault,code", [("revision", "STATE_CONFLICT"), ("model", "STATE_CONFLICT"),
    ("maximum", "INVALID_INPUT"), ("reasoning", "INVALID_INPUT"), ("compiled", "CONFIG_SNAPSHOT_MISMATCH")])
def test_prewrite_failures_never_call_native_owner(configuration_env, fault, code):
    from core.web.services.external_management.service import ManagementError
    data = configuration_env
    block = {"expected_model_ref": "fixture/model", "context_window": 48000, "reasoning_effort": "high"}
    revision = 6 if fault == "revision" else 7
    if fault == "model":
        block["expected_model_ref"] = "fixture/other"
    elif fault == "maximum":
        block["context_window"] = 64001
    elif fault == "reasoning":
        block["reasoning_effort"] = "unsupported"
    elif fault == "compiled":
        data.agent["displayName"] = "Changed registry"
        data.save()
    with pytest.raises(ManagementError) as error:
        data.control.update_parameters(request("model", block, revision))
    assert error.value.code == code
    assert data.owner_calls == []


@pytest.mark.parametrize("fault", ["cas", "ack", "owner_noop"])
def test_after_native_write_failures_are_unconfirmed(configuration_env, monkeypatch, fault):
    from core.web.services.external_management import operation_receipts
    from core.web.services.external_management.service import ManagementError
    data = configuration_env
    marker = None
    if fault == "cas":
        def fail(**_kwargs):
            result = Future()
            result.set_exception(ValueError("CAS conflict"))
            return result
        monkeypatch.setattr(data.store.repository, "compare_and_swap_agent_config", fail)
    elif fault == "ack":
        marker = {"test": "ack"}
        monkeypatch.setattr(operation_receipts, "record_success", lambda *_a: (_ for _ in ()).throw(OSError("disk")))
    else:
        monkeypatch.setattr(data.directory, "update_agent_budget_parameters_if_current", lambda *_a, **_kw: deepcopy(data.agent))
    with pytest.raises(ManagementError) as error:
        data.control.update_parameters(request("budget", {"maxCallsPerTurn": 12}), marker)
    assert error.value.code == "OPERATION_UNCONFIRMED"


@pytest.mark.parametrize("protected", ["archived", "pa", "system", "protected", "team", "companion", "binding", "hidden"])
def test_protected_classes_reject_configuration_reads_and_writes(configuration_env, protected):
    from core.web.services.external_management.service import ManagementError
    data = configuration_env
    if protected == "archived":
        data.agent["status"] = "archived"
    elif protected == "pa":
        data.agent["roleKey"] = "personal_assistant"
    elif protected in {"system", "protected"}:
        data.agent["metadata"]["systemRole" if protected == "system" else "protected"] = True
    elif protected == "team":
        data.team_index.write_text(json.dumps({"teams": [{"teamId": "team-a", "name": "Team", "status": "active", "members": [{"agentId": "agent-a"}]}]}), encoding="utf-8")
    elif protected == "companion":
        data.agent["metadata"]["virtualHumanCompanion"] = True
    elif protected == "binding":
        (data.plugin_root / "binding.json").write_text('{"agentId":"agent-a","enabled":true}', encoding="utf-8")
    else:
        data.agent["conversationIndexKind"] = "hidden"
    data.save()
    for operation in (lambda: data.control.read_configuration("agent-a"),
        lambda: data.control.update_parameters(request("budget", {"maxCallsPerTurn": 12}))):
        with pytest.raises(ManagementError) as error:
            operation()
        assert error.value.code in {"AGENT_UNAVAILABLE", "AGENT_PROTECTED"}
    assert data.owner_calls == []
