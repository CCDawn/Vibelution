"""Managed PA write actions: team_create, knowledge_ingest, config_update.

All three actions live behind personal_assistant_manage_tool's closed dispatch
table and stay in the high-risk per-call-approval tier. config_update is a
closed whitelist applied through the optimistic-hash operator config
transaction; any unknown or forbidden key rejects the whole request.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import tomllib
from pathlib import Path

import pytest

from core.web.services import (
    agent_directory_service as directory,
    session_service,
    team_knowledge_service,
    team_service,
)
from core.web.services import personal_assistant_service as service
from tests.test_personal_assistant_service import (
    finance_env as _finance_env,
)
from tests.test_personal_assistant_service import personal_env as _personal_env
from tools import pa_managed_writes
from tools import personal_assistant_tools as pa_tools

finance_env = _finance_env
personal_env = _personal_env
MANAGE = "personal_assistant_manage_tool"


@pytest.fixture
def assistant_runtime(personal_env, monkeypatch):
    row = service.create_personal_assistant()["assistant"]
    monkeypatch.setattr(
        directory,
        "current_agent_runtime",
        lambda: {
            "agentId": row["agentId"],
            "sessionId": row["directSessionId"],
        },
    )
    return row


# ---------------------------------------------------------------------------
# team_create
# ---------------------------------------------------------------------------


def test_team_create_builds_empty_team_and_reuses_same_name(finance_env):
    first = json.loads(pa_managed_writes.team_create_tool(name="交付协同", description="PA 托管"))
    assert first["ok"] is True and first["teamId"]
    team = team_service.get_team(first["teamId"])
    assert team["name"] == "交付协同"
    second = json.loads(pa_managed_writes.team_create_tool(name="交付协同"))
    assert second["ok"] is True and second["teamId"] == first["teamId"]


def test_team_create_materializes_dev_team_template(finance_env):
    result = json.loads(pa_managed_writes.team_create_tool(name="模板团队", templateId="dev-team"))
    assert result["ok"] is True and result["teamId"]
    team = team_service.get_team(result["teamId"])
    assert len(team.get("members") or []) == 4


def test_team_create_rejects_missing_name_and_unknown_template(finance_env):
    missing = json.loads(pa_managed_writes.team_create_tool(name="   "))
    assert missing["ok"] is False and missing["error"] == "invalid_input"
    unknown = json.loads(pa_managed_writes.team_create_tool(name="模板团队", templateId="no-such-template"))
    assert unknown["ok"] is False
    assert unknown["message"]  # template service error text is returned verbatim


def test_manage_dispatch_binds_signatures_and_rejects_extra_fields(
    personal_env, assistant_runtime
):
    blocked = json.loads(
        pa_tools.personal_assistant_manage_tool(
            "team_create", '{"name": "越权团队", "actor_agent_id": "someone-else"}'
        )
    )
    assert blocked["ok"] is False and blocked["status"] == "blocked"
    assert team_service.list_teams()["summary"]["teamCount"] == 0

    unknown = json.loads(
        pa_tools.personal_assistant_manage_tool("config_write", "{}")
    )
    assert unknown["ok"] is False
    # 4275f9de8 reworded the closed-dispatch rejection (fail-closed path itself
    # unchanged) from "不支持的管理操作" to "尚未登记此操作".
    assert "尚未登记此操作" in unknown["message"]


def test_manage_dispatch_runs_team_create_end_to_end(finance_env, assistant_runtime):
    result = json.loads(
        pa_tools.personal_assistant_manage_tool(
            "team_create", '{"name": "端到端团队", "description": "via manage tool"}'
        )
    )
    assert result["ok"] is True
    assert result["teamId"]
    assert team_service.get_team(result["teamId"])["name"] == "端到端团队"


# ---------------------------------------------------------------------------
# knowledge_ingest
# ---------------------------------------------------------------------------


def _seed_team_with_pa_lead(finance_env, assistant_runtime):
    helper = directory.create_agent_instance(
        display_name="Inbox Helper", direct_session_id="inbox-helper-session"
    )
    team = team_service.create_team(
        name="PA Knowledge Team",
        members=[
            {"agentId": assistant_runtime["agentId"], "role": "lead"},
            {"agentId": helper["agentId"], "role": "member"},
        ],
    )
    base = team_knowledge_service.create_knowledge_base(
        team["teamId"], name="PA KB", actor_agent_id=assistant_runtime["agentId"]
    )
    return helper, team, base


def _stage_session_document(helper, team_id: str) -> str:
    session = session_service.create_chat_session(
        title="Helper session", agent_id=helper["agentId"], created_by="pa-managed-writes-test"
    )
    from core.web.services.session import document_attachments

    attachment = document_attachments.store_session_user_document_attachment(
        session["id"],
        "结论：受控写动作仅按白名单执行。\n".encode("utf-8"),
        filename="findings.md",
        content_type="text/markdown",
    )
    source = team_knowledge_service.collect_session_attachment_to_inbox(
        "team",
        team_id,
        session_id=session["id"],
        attachment_id=attachment["artifactId"],
        actor_agent_id=helper["agentId"],
        title="验收纪要",
    )
    return source["inboxSourceId"]


def test_knowledge_ingest_direct_ingests_screened_source(
    finance_env, assistant_runtime
):
    helper, team, base = _seed_team_with_pa_lead(finance_env, assistant_runtime)
    inbox_source_id = _stage_session_document(helper, team["teamId"])
    base_ref = base.get("scopedKnowledgeBaseId") or base["knowledgeBaseId"]

    result = json.loads(
        pa_managed_writes.knowledge_ingest_tool(
            inboxSourceId=inbox_source_id,
            ownerType="team",
            ownerId=team["teamId"],
            knowledgeBaseId=base_ref,
            title="受控入库",
        )
    )
    assert result["ok"] is True, result
    assert result["knowledgeItemId"]
    assert result["inboxSourceId"] == inbox_source_id
    items = team_knowledge_service.list_knowledge_items(base_ref, agent_id=assistant_runtime["agentId"])
    assert items["summary"]["itemCount"] == 1


def test_knowledge_ingest_requires_identity_fields(finance_env, assistant_runtime, monkeypatch):
    def _forbid(*_args, **_kwargs):
        pytest.fail("knowledge ingest reached the service without required fields")

    monkeypatch.setattr(team_knowledge_service, "review_owner_inbox_source", _forbid)
    # Dispatch signature binding rejects missing/extra fields before any call.
    missing = json.loads(
        pa_tools.personal_assistant_manage_tool(
            "knowledge_ingest", '{"inboxSourceId": "isrc-1", "ownerType": "team"}'
        )
    )
    assert missing["ok"] is False and missing["status"] == "blocked"
    extra = json.loads(
        pa_tools.personal_assistant_manage_tool(
            "knowledge_ingest",
            '{"inboxSourceId": "isrc-1", "ownerType": "team", "ownerId": "team-1", "content": "代写内容"}',
        )
    )
    assert extra["ok"] is False and extra["status"] == "blocked"


def test_knowledge_ingest_passes_service_errors_verbatim(
    finance_env, assistant_runtime
):
    helper, team, base = _seed_team_with_pa_lead(finance_env, assistant_runtime)
    missing_source = json.loads(
        pa_managed_writes.knowledge_ingest_tool(
            inboxSourceId="isrc-does-not-exist",
            ownerType="team",
            ownerId=team["teamId"],
            knowledgeBaseId=base.get("scopedKnowledgeBaseId") or base["knowledgeBaseId"],
        )
    )
    assert missing_source["ok"] is False
    assert "Inbox source not found." in missing_source["message"]

    # A manually-collected (non session-document) source cannot be ingested in
    # source_document mode: the assistant cannot author knowledge content.
    staged = team_knowledge_service.collect_source_to_inbox(
        "team",
        team["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "not a document"},
        original_content="Plain staged text that is not a session document.",
        title="Plain source",
        actor_agent_id=helper["agentId"],
    )
    not_document = json.loads(
        pa_managed_writes.knowledge_ingest_tool(
            inboxSourceId=staged["inboxSourceId"],
            ownerType="team",
            ownerId=team["teamId"],
            knowledgeBaseId=base.get("scopedKnowledgeBaseId") or base["knowledgeBaseId"],
        )
    )
    assert not_document["ok"] is False
    assert "source_document" in not_document["message"]


# ---------------------------------------------------------------------------
# config_update
# ---------------------------------------------------------------------------

CONFIG_TEXT = """# operator note: keep this comment
[ui]
language = "zh"
max_log_entries = 100
show_ascii_art = true

[user_profile]
bio = "平台操作者"

[llm]
schema_version = 2

[llm.providers.pixel_relay]
label = "Local Pixel Runtime"
service_class = "local_runtime"
vendor = "custom"
driver = "openai"
base_url = "http://127.0.0.1:8000/v1"
auth_kind = "none"
credential_ref = "none"
requires_credential = false

[llm.providers.pixel_relay.protocols]
default = "responses"
allowed = ["responses", "chat_completions"]

[llm.providers.pixel_relay.models."gpt-5.6-luna"]
upstream_id = "gpt-5.6-luna"
enabled = true

[llm.providers.pixel_relay.models."nightshift-9"]
upstream_id = "nightshift-9"
enabled = true

[llm.profiles.primary]
model_ref = "pixel_relay/gpt-5.6-luna"

[llm.profiles.secondary]
model_ref = "pixel_relay/nightshift-9"
"""


@pytest.fixture
def operator_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(CONFIG_TEXT, encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config_path))
    return config_path


def _read_config(config_path: Path) -> dict:
    return tomllib.loads(config_path.read_text(encoding="utf-8"))


def test_config_update_applies_whitelisted_keys_in_one_transaction(operator_config):
    result = json.loads(
        pa_managed_writes.config_update_tool(
            [
                {"section": "ui", "key": "language", "value": "en"},
                {"section": "ui", "key": "show_ascii_art", "value": False},
                {"section": "ui", "key": "refresh_rate", "value": 8},
                {"section": "user_profile", "key": "display_name", "value": "阿真"},
                {
                    "section": "user_profile",
                    "key": "preferences",
                    "value": ["回复保持简短", "先给结论"],
                },
                {
                    "section": "llm",
                    "key": "profiles.primary.model_ref",
                    "value": "pixel_relay/nightshift-9",
                },
            ]
        )
    )
    assert result["ok"] is True, result
    data = _read_config(operator_config)
    assert data["ui"]["language"] == "en"
    assert data["ui"]["show_ascii_art"] is False
    assert data["ui"]["refresh_rate"] == 8
    assert data["user_profile"]["display_name"] == "阿真"
    assert data["user_profile"]["preferences"] == ["回复保持简短", "先给结论"]
    assert data["llm"]["profiles"]["primary"]["model_ref"] == "pixel_relay/nightshift-9"
    assert data["llm"]["profiles"]["secondary"]["model_ref"] == "pixel_relay/nightshift-9"
    assert "# operator note: keep this comment" in operator_config.read_text(encoding="utf-8")
    assert data["ui"]["max_log_entries"] == 100


def test_config_update_rejects_unknown_sections_and_non_list_payload(operator_config):
    mixed = json.loads(
        pa_managed_writes.config_update_tool(
            [{"section": "ui", "key": "language", "value": "en"}, {"section": "extra", "key": "x", "value": 1}]
        )
    )
    assert mixed["ok"] is False
    malformed = json.loads(pa_managed_writes.config_update_tool("not-a-list"))
    assert malformed["ok"] is False


@pytest.mark.parametrize(
    "item",
    [
        {"section": "llm.providers.pixel_relay", "key": "credential_ref", "value": "env:EVIL_KEY"},
        {"section": "llm", "key": "providers", "value": {"pixel_relay": {}}},
        {"section": "external_agent_gateway", "key": "enabled", "value": True},
        {"section": "user_profile", "key": "avatar_image_path", "value": "C:/evil.png"},
        {"section": "llm", "key": "profiles.primary.credential_ref", "value": "env:EVIL_KEY"},
        {"section": "ui", "key": "language", "value": "fr"},
        {"section": "ui", "key": "refresh_rate", "value": "fast"},
        {"section": "ui", "key": "show_ascii_art", "value": "true"},
        {"section": "ui", "key": "startup_warmup", "value": False},
    ],
)
def test_config_update_rejects_disguised_and_unknown_keys(operator_config, item):
    before = operator_config.read_bytes()
    result = json.loads(pa_managed_writes.config_update_tool([item]))
    assert result["ok"] is False, item
    assert operator_config.read_bytes() == before


def test_config_update_fails_closed_on_mixed_batch(operator_config):
    before = operator_config.read_bytes()
    result = json.loads(
        pa_managed_writes.config_update_tool(
            [
                {"section": "ui", "key": "language", "value": "en"},
                {"section": "llm.providers.pixel_relay", "key": "credential_ref", "value": "env:EVIL_KEY"},
            ]
        )
    )
    assert result["ok"] is False
    assert "整体拒绝" in result["message"]
    assert operator_config.read_bytes() == before


def test_config_update_rejects_unknown_profile_and_unknown_provider(operator_config):
    unknown_profile = json.loads(
        pa_managed_writes.config_update_tool(
            [{"section": "llm", "key": "profiles.ghost.model_ref", "value": "pixel_relay/nightshift-9"}]
        )
    )
    assert unknown_profile["ok"] is False
    assert "模型偏好档位" in unknown_profile["message"]
    unknown_provider = json.loads(
        pa_managed_writes.config_update_tool(
            [{"section": "llm", "key": "profiles.primary.model_ref", "value": "ghost-provider/m-1"}]
        )
    )
    assert unknown_provider["ok"] is False
    assert "Provider" in unknown_provider["message"]


def test_config_update_reports_stale_hash_and_writes_nothing(operator_config, monkeypatch):
    from config.public_config import load_public_config as original_load

    def stale_load(*args, **kwargs):
        data = original_load(*args, **kwargs)
        drifted = copy.deepcopy(data)
        drifted.setdefault("user_profile", {})["display_name"] = "另一个进程改过"
        return drifted

    monkeypatch.setattr("config.public_config.load_public_config", stale_load)
    before = operator_config.read_bytes()
    result = json.loads(
        pa_managed_writes.config_update_tool(
            [{"section": "ui", "key": "language", "value": "en"}]
        )
    )
    monkeypatch.undo()
    assert result["ok"] is False
    assert result["error"] == "config_conflict"
    assert result["status"] == "blocked"
    assert operator_config.read_bytes() == before


def test_manage_dispatch_end_to_end_config_update(finance_env, assistant_runtime, operator_config):
    result = json.loads(
        pa_tools.personal_assistant_manage_tool(
            "config_update",
            json.dumps({"updates": [{"section": "ui", "key": "show_welcome", "value": False}]}),
        )
    )
    assert result["ok"] is True, result
    data = _read_config(operator_config)
    assert data["ui"]["show_welcome"] is False

    rejected = json.loads(
        pa_tools.personal_assistant_manage_tool(
            "config_update",
            json.dumps({"updates": [{"section": "llm", "key": "providers", "value": {}}]}),
        )
    )
    assert rejected["ok"] is False


# ---------------------------------------------------------------------------
# Launcher canonical routing (dedicated assistant host process)
#
# The launcher PA never reaches the platform adapter dispatch table; it routes
# through core.assistant_runtime.actions.execute_action. These tests pin the
# canonical contract source, the per-call approval gate and the single
# executor mapping so neither surface can drift away from pa_managed_writes.
# team_create is not one of them: the canonical face sources it from the
# native TEAM_LIFECYCLE remote management registry, and the guard tests below
# pin both the single source and the ACTION_MODELS/PA registry disjointness.
# ---------------------------------------------------------------------------

CANONICAL_MANAGED_WRITES = ("knowledge_ingest", "config_update")


def test_launcher_contracts_stay_aligned_with_pa_managed_writes_executors():
    from core.assistant_runtime.actions import _management_contracts
    from core.web.services.external_management.contracts import (
        PA_MANAGED_WRITE_MODELS,
        pa_managed_write_contracts,
    )

    assert set(PA_MANAGED_WRITE_MODELS) == set(pa_managed_writes.LAUNCHER_MANAGED_WRITE_ACTIONS) == set(CANONICAL_MANAGED_WRITES)
    for name, executor in pa_managed_writes.LAUNCHER_MANAGED_WRITE_ACTIONS.items():
        assert executor is getattr(pa_managed_writes, f"{name}_tool")
        signature = inspect.signature(executor)
        adapter_required = {item.name for item in signature.parameters.values() if item.default is inspect.Parameter.empty}
        # Registry layer: pure adapter-face shape; the tool functions remain the
        # content validation authority.
        schema = pa_managed_write_contracts()[name]["parameters"]
        assert set(schema["properties"]) == set(signature.parameters)
        assert set(schema["required"]) == adapter_required
        for item in signature.parameters.values():
            if item.default is not inspect.Parameter.empty:
                assert schema["properties"][item.name]["default"] == item.default
        assert pa_managed_write_contracts()[name]["governed"] is True
        # Canonical layer: the same shape plus the injected project_id/request_id
        # envelope, exactly like every remote management action.
        launcher_schema = _management_contracts()[name][0].model_json_schema()
        assert set(launcher_schema["properties"]) == set(signature.parameters) | {"project_id", "request_id"}
        assert set(launcher_schema["required"]) == adapter_required | {"project_id", "request_id"}


def test_pa_managed_writes_and_action_models_stay_disjoint():
    """One action name must never live in both canonical registries.

    _management_contracts merges ACTION_MODELS and PA_MANAGED_WRITE_MODELS
    into the same canonical index dict; a duplicate key would silently
    overwrite whichever contract was registered first. team_create in
    particular is owned by TEAM_LIFECYCLE_ACTION_MODELS (native remote
    management authority), so it must stay out of the PA registry.
    """
    from core.web.services.external_management.contracts import ACTION_MODELS, PA_MANAGED_WRITE_MODELS

    overlap = set(ACTION_MODELS) & set(PA_MANAGED_WRITE_MODELS)
    assert overlap == set(), f"dual-registered canonical actions: {sorted(overlap)}"
    assert set(ACTION_MODELS).isdisjoint(pa_managed_writes.LAUNCHER_MANAGED_WRITE_ACTIONS)


def test_team_create_is_owned_by_the_native_team_lifecycle_registry(monkeypatch):
    """Canonical team_create has exactly one source: TEAM_LIFECYCLE/ACTION_MODELS.

    The external team-management flow registers team_create as a full remote
    management action (scope=teams:create, idempotency marker,
    OPERATION_UNCONFIRMED semantics); the PA managed-write layer keeps only
    the adapter-face tool for the platform dispatch table.
    """
    from core.assistant_runtime import actions
    from core.assistant_runtime.actions import _management_contracts
    from core.web.services.external_management.contracts import ACTION_MODELS
    from core.web.services.external_management.team_lifecycle_contracts import TeamCreate

    assert ACTION_MODELS["team_create"] is TeamCreate
    assert "team_create" not in pa_managed_writes.LAUNCHER_MANAGED_WRITE_ACTIONS
    monkeypatch.setattr(actions, "_binding", (object(), object(), None))
    page = actions.execute_action("index", {"query": "team_create"})
    rows = [item for item in page["actions"] if item["action"] == "team_create"]
    assert len(rows) == 1 and rows[0]["governed"] is True and rows[0]["scope"] == "teams:create"
    detail = actions.execute_action("describe", {"action": "team_create"})
    assert detail["governed"] is True and detail["scope"] == "teams:create"
    assert {"name", "description", "purpose", "members"} <= set(detail["parameters"]["properties"])
    assert "templateId" not in detail["parameters"]["properties"]
    launcher_schema = _management_contracts()["team_create"][0].model_json_schema()
    assert {"purpose", "members"} <= set(launcher_schema["properties"])
    assert {"project_id", "request_id"} <= set(launcher_schema["required"])


def test_launcher_index_and_describe_surface_canonical_managed_writes(monkeypatch):
    from core.assistant_runtime import actions
    from core.web.services.external_management.contracts import ACTION_MODELS

    # The canonical PA writes must never leak into the remotely invocable
    # management registry: project dispatch has no implementation for them.
    for name in CANONICAL_MANAGED_WRITES:
        assert name not in ACTION_MODELS
    monkeypatch.setattr(actions, "_binding", (object(), object(), None))
    for name in CANONICAL_MANAGED_WRITES:
        page = actions.execute_action("index", {"query": name})
        row = next(item for item in page["actions"] if item["action"] == name)
        assert row["governed"] is True
        detail = actions.execute_action("describe", {"action": name})
        assert detail["governed"] is True and detail["action"] == name
        assert {"project_id", "request_id"} <= set(detail["parameters"]["required"])
        assert detail["parameters"]["additionalProperties"] is False


@pytest.mark.anyio
async def test_launcher_routing_reaches_pa_managed_writes_only_after_approval(tmp_path, monkeypatch):
    from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter

    service = adapter(tmp_path, ClientProbe())
    bind_actions(service, asyncio.get_running_loop())
    executed = []

    def _executor(name, payload):
        def _run(**kwargs):
            executed.append((name, kwargs))
            return json.dumps(payload)
        return _run

    receipts = {
        "knowledge_ingest": {"ok": True, "status": "ingested", "message": "知识来源已入库。", "inboxSourceId": "isrc-1"},
        "config_update": {"ok": True, "status": "completed", "message": "已更新：ui.language。"},
    }
    request_parameters = {
        "knowledge_ingest": {"inboxSourceId": "isrc-1", "ownerType": "team", "ownerId": "team-1"},
        "config_update": {"updates": [{"section": "ui", "key": "language", "value": "en"}]},
    }
    expected_kwargs = {
        "knowledge_ingest": {"inboxSourceId": "isrc-1", "ownerType": "team", "ownerId": "team-1",
                             "knowledgeBaseId": "", "title": "", "summary": "", "tags": ""},
        "config_update": {"updates": [{"section": "ui", "key": "language", "value": "en"}]},
    }
    for name in CANONICAL_MANAGED_WRITES:
        monkeypatch.setitem(pa_managed_writes.LAUNCHER_MANAGED_WRITE_ACTIONS, name, _executor(name, receipts[name]))
    runtime = {"agentId": "assistant", "sessionId": "own"}
    try:
        for name in CANONICAL_MANAGED_WRITES:
            before = len(executed)
            request = {"project_id": "project-a", "request_id": "req-1", **request_parameters[name]}
            unapproved = await asyncio.to_thread(execute_action, name, request)
            assert unapproved == {"ok": False, "status": "approval_required", "action": name,
                                  "tool": "personal_assistant_manage_tool"}
            assert len(executed) == before
            result = await asyncio.to_thread(execute_action, name, request, runtime=runtime, governed=True)
            assert result == receipts[name]
            # The executor receives exactly the adapter-face parameters; the
            # canonical envelope is consumed by the authorization gate.
            assert len(executed) == before + 1
            assert executed[-1] == (name, expected_kwargs[name])
        # Unregistered projects never reach the executor.
        with pytest.raises(ValueError, match="Project is not authorized"):
            await asyncio.to_thread(execute_action, "config_update",
                                    {"project_id": "other-project", "request_id": "req-2",
                                     "updates": [{"section": "ui", "key": "language", "value": "zh"}]},
                                    runtime=runtime, governed=True)
        assert len(executed) == 2
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_launcher_canonical_team_create_routes_to_the_native_management_service(tmp_path):
    """team_create on the canonical face must dispatch, never run a local tool."""
    from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter

    service = adapter(tmp_path, ClientProbe())
    bind_actions(service, asyncio.get_running_loop())
    invoked = []

    class _ProbeManagement:
        def invoke(self, project_id, *, action, request_id, parameters):
            invoked.append((project_id, action, request_id, parameters))
            async def _noop():
                return {"status": "completed", "requestId": request_id}
            return _noop()

    original = service.management
    service.management = _ProbeManagement()
    runtime = {"agentId": "assistant", "sessionId": "own"}
    try:
        result = await asyncio.to_thread(
            execute_action, "team_create",
            {"project_id": "project-a", "request_id": "req-team-1", "name": "正本托管团队", "purpose": "协同"},
            runtime=runtime, governed=True)
        assert result == {"status": "completed", "requestId": "req-team-1"}
        assert invoked == [("project-a", "team_create", "req-team-1",
                            {"name": "正本托管团队", "description": "", "purpose": "协同", "members": []})]
    finally:
        service.management = original
        unbind_actions(service)


@pytest.mark.anyio
async def test_launcher_canonical_config_update_runs_real_transaction(operator_config, tmp_path):
    from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter

    service = adapter(tmp_path, ClientProbe())
    bind_actions(service, asyncio.get_running_loop())
    try:
        result = await asyncio.to_thread(
            execute_action, "config_update",
            {"project_id": "project-a", "request_id": "req-cfg-1",
             "updates": [{"section": "ui", "key": "language", "value": "en"}]},
            runtime={"agentId": "assistant", "sessionId": "own"}, governed=True)
        assert result["ok"] is True, result
        assert _read_config(operator_config)["ui"]["language"] == "en"
    finally:
        unbind_actions(service)
