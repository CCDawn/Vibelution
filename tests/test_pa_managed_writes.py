"""Managed PA write actions: team_create, knowledge_ingest, config_update.

All three actions live behind personal_assistant_manage_tool's closed dispatch
table and stay in the high-risk per-call-approval tier. config_update is a
closed whitelist applied through the optimistic-hash operator config
transaction; any unknown or forbidden key rejects the whole request.
"""

from __future__ import annotations

import copy
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
    assert "不支持的管理操作" in unknown["message"]


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
