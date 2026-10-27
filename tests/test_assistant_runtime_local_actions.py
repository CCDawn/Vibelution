"""Launcher-local catalog, routing and native approval boundaries."""

import pytest

from core.assistant_runtime import local_actions as local
from tools import pa_assistant_actions as assistant
from tools import pa_config_actions as config
from tools import pa_platform_actions as platform
from tools import pa_settings_actions as settings


def test_catalog_reuses_native_schema_and_governance_without_project_actions():
    contracts = local.contracts()
    expected = set(assistant.contracts()) | set(config.contracts()) | {
        "settings_catalog", "settings_update", "model_add", "model_options",
        "operator_image_options", "operator_image_select",
        "history_list", "history_read",
        "affairs_conflict_sets", "affairs_conflict_list", "affairs_conflict_read", "affairs_sync_receipt",
    }
    assert set(contracts) == expected
    for owner in (assistant, config):
        for name, native in owner.contracts().items():
            assert {key: contracts[name][key] for key in native if key != "description"} == {
                key: value for key, value in native.items() if key != "description"
            }
            if name == "assistant_settings_update":
                assert contracts[name]["description"] == native["description"] + " 当前轮结束后自动刷新生效，不要求用户手动刷新或重启。"
            else:
                assert contracts[name]["description"] == native["description"]
    for name in ("settings_update", "model_add", "model_options"):
        assert contracts[name] == {**platform.action_catalog(name), "governed": False}
    for name, contract in contracts.items():
        assert contract["action"] == name
        assert contract["parameters"]["additionalProperties"] is False
        assert type(contract["governed"]) is bool


@pytest.mark.parametrize("name", [
    "agent_create", "agent_update", "agent_archive", "agent_avatar", "avatar_options",
    "session_create", "session_stop", "session_delete", "team_create", "team_run",
    "team_status", "knowledge_ingest", "knowledge_acl_grant", "inbox", "config_update",
    "restart", "index", "describe", "future_action",
])
def test_project_and_unregistered_actions_never_reach_native_dispatch(monkeypatch, name):
    monkeypatch.setattr(platform, "execute_action", lambda *args, **kwargs: pytest.fail("native dispatch"))
    monkeypatch.setattr(platform, "execute_extension", lambda *args, **kwargs: pytest.fail("native extension"))
    with pytest.raises(ValueError, match="Launcher"):
        local.execute(name, {}, {"agentId": "assistant"}, governed=True)


def test_new_native_action_does_not_expand_launcher_allowlist(monkeypatch):
    native = assistant.contracts()
    monkeypatch.setattr(assistant, "contracts", lambda: {
        **native, "new_project_action": {"action": "new_project_action", "governed": False},
    })
    assert "new_project_action" not in local.contracts()
    with pytest.raises(ValueError):
        local.execute("new_project_action", {}, {})


@pytest.mark.parametrize("owner", [assistant, config])
def test_extensions_keep_the_same_owner_and_runtime(monkeypatch, owner):
    runtime = {"agentId": "current-assistant", "sessionId": "direct-session"}
    calls = []
    def execute(name, parameters, received_runtime, *, governed=False):
        calls.append((name, parameters, received_runtime, governed))
        return {"ok": True, "owner": owner.__name__}
    monkeypatch.setattr(owner, "execute", execute)
    for name, contract in owner.contracts().items():
        if name in {"model_remove", "provider_remove"}:
            continue
        result = local.execute(name, {}, runtime, governed=contract["governed"])
        assert result["owner"] == owner.__name__
        assert calls[-1] == (name, {}, runtime, contract["governed"])
        assert calls[-1][2] is runtime


@pytest.mark.parametrize("governed", [False, 1, "true"])
def test_sensitive_calls_keep_native_approval_guidance_and_never_run(monkeypatch, governed):
    monkeypatch.setattr(config, "execute", lambda *args, **kwargs: pytest.fail("unapproved config write"))
    for name, contract in config.contracts().items():
        if not contract["governed"]:
            continue
        if name in {"model_remove", "provider_remove"}:
            continue
        result = local.execute(name, {"governed": True}, {}, governed=governed)
        assert result == {
            "ok": False, "status": "approval_required", "action": name,
            "tool": "personal_assistant_manage_tool",
            "message": "使用 manage，action 保持不变，arguments_json 为这些参数的JSON；等待原生审批后执行。",
        }


@pytest.mark.parametrize("action,parameters", [
    ("model_remove", {"model_id": "provider/model"}),
    ("provider_remove", {"provider_id": "provider"}),
    ("model_update", {"model_id": "provider/model", "updates": {"enabled": False}}),
    ("provider_update", {"provider_id": "provider", "enabled": False}),
])
def test_reference_destructive_actions_wait_for_complete_cross_project_guard(monkeypatch, action, parameters):
    monkeypatch.setattr(platform, "execute_action", lambda *args, **kwargs: pytest.fail("unsafe single-project dispatch"))
    monkeypatch.setattr(platform, "execute_extension", lambda *args, **kwargs: pytest.fail("unsafe single-project extension"))
    result = local.execute(action, parameters, {}, governed=True)
    assert result["ok"] is False and result["status"] == "unavailable"
    assert result["error"] == "cross_project_reference_validation_unavailable"
    for name in ("model_remove", "provider_remove"):
        assert local.contracts()[name]["available"] is False


def test_settings_catalog_and_mutations_keep_settings_owner_and_strict_dto(monkeypatch):
    monkeypatch.setattr(settings, "settings_catalog", lambda: {"ok": True, "settings": ["native"]})
    assert local.execute("settings_catalog", {}, {}) == {"ok": True, "settings": ["native"]}
    updates = [{"section": "user_profile", "key": "display_name", "value": "Operator"}]
    monkeypatch.setattr(settings, "settings_update", lambda values: {"ok": True, "updates": values})
    # Native dispatch restores frozen model JSON containers before strict DTOs.
    assert local.execute("settings_update", {"updates": tuple(updates)}, {})["updates"] == updates
    monkeypatch.setattr(settings, "model_add", lambda **values: {"ok": True, **values})
    result = local.execute("model_add", {"provider_id": "existing", "upstream_id": "model"}, {})
    assert result == {"ok": True, "provider_id": "existing", "upstream_id": "model", "model_key": "", "label": ""}
    for action, parameters in (
        ("settings_catalog", {"agent_id": "foreign"}),
        ("settings_update", {"updates": updates, "project_id": "foreign"}),
        ("model_add", {"provider_id": "existing", "upstream_id": "model", "governed": True}),
    ):
        with pytest.raises(ValueError):
            local.execute(action, parameters, {})


def test_model_options_uses_existing_pagination_and_assistant_identity(monkeypatch):
    calls = []
    def options(args, runtime):
        calls.append((args.model_dump(), runtime))
        return {"ok": True, "currentModelId": "native/model"}
    monkeypatch.setattr(platform, "_model_options", options)
    runtime = {"agentId": "current-assistant"}
    assert local.execute("model_options", {"query": "native", "limit": 1}, runtime)["currentModelId"] == "native/model"
    assert calls == [({"query": "native", "model_id": "", "offset": 0, "limit": 1}, runtime)]


def test_ordinary_settings_cannot_be_used_as_project_or_policy_writes(monkeypatch):
    from pathlib import Path

    # Invalid fields must be rejected before config data or transactions.
    monkeypatch.setattr(settings, "_config_path", lambda: Path("unused-config.toml"))
    monkeypatch.setattr(settings, "_read_config", lambda path: pytest.fail("invalid config read"))
    monkeypatch.setattr(settings, "_transaction", lambda *args: pytest.fail("invalid settings write"))
    for section, key in (("agent", "display_name"), ("authorization", "writeScopes"), ("llm", "providers")):
        result = local.execute("settings_update", {"updates": [{"section": section, "key": key, "value": "x"}]}, {})
        assert not result["ok"] and result["error"] == "invalid_input"
