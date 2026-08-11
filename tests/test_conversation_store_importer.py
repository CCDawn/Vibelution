from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.chat.conversation_store.database as conversation_database
from core.chat.conversation_store import ConversationStore
from core.chat.conversation_store.importer import (
    AgentConfigImportError,
    LegacyAgentConfigImporter,
)
from core.web.services.agent_config_authority import (
    agent_config_hash,
    canonical_agent_config_payload,
)


@pytest.fixture
def safe_sqlite_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        conversation_database.sqlite3,
        "sqlite_version_info",
        (3, 51, 3),
    )


def _open_store(tmp_path: Path) -> ConversationStore:
    store = ConversationStore(tmp_path / "workspace" / "chat" / "conversations.sqlite3")
    store.open()
    return store


def _agent(
    agent_id: str,
    *,
    display_name: str = "Alpha",
    model_id: str = "gpt-5.6-luna",
    status: str = "active",
) -> dict[str, object]:
    return {
        "agentId": agent_id,
        "displayName": display_name,
        "kind": "assistant",
        "llmBindings": {"dialogue": {"modelId": model_id}},
        "promptTemplateId": "chat",
        "toolPolicyId": "tool-default",
        "toolPolicy": {"policyId": "tool-default"},
        "memoryPolicyId": "memory-default",
        "memoryPolicy": {"policyId": "memory-default"},
        "metadata": {
            "llmReasoningEffort": {"dialogue": "medium"},
            "personaProfile": {"role": "assistant"},
        },
        "permissionPreset": "request_approval",
        "status": status,
    }


def _write_registry(path: Path, agents: list[dict[str, object]]) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 7,
                "agents": agents,
                "toolPolicies": {"tool-default": {"policyId": "tool-default"}},
                "memoryPolicies": {
                    "memory-default": {"policyId": "memory-default"}
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path.read_bytes()


def test_importer_creates_canonical_agent_revisions_without_modifying_source(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    source_path = tmp_path / "workspace" / "agents" / "agents.json"
    alpha = _agent("agent-alpha")
    beta = _agent("agent-beta", display_name="Beta", status="archived")
    source_before = _write_registry(source_path, [alpha, beta])
    store = _open_store(tmp_path)
    try:
        report = LegacyAgentConfigImporter(store.repository).import_file(source_path)

        assert source_path.read_bytes() == source_before
        assert report["created"] == 2
        assert report["revised"] == 0
        assert report["reused"] == 0

        imported = store.repository.get_agent("agent-alpha")
        assert imported is not None
        assert imported["displayName"] == "Alpha"
        assert imported["currentConfigRevisionId"] == (
            f"agent-alpha:{agent_config_hash(alpha)}"
        )

        current = store.repository.get_current_agent_config("agent-alpha")
        assert current is not None
        assert current["config"] == canonical_agent_config_payload(alpha)
        assert current["configHash"] == agent_config_hash(alpha)
        assert current["source"] == "legacy_agents_json"
        assert store.repository.get_agent("agent-beta")["status"] == "archived"
    finally:
        store.close()


def test_importer_is_idempotent_and_preserves_immutable_config_revisions(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    source_path = tmp_path / "workspace" / "agents" / "agents.json"
    alpha = _agent("agent-alpha")
    _write_registry(source_path, [alpha])
    store = _open_store(tmp_path)
    try:
        importer = LegacyAgentConfigImporter(store.repository)
        first = importer.import_file(source_path)
        original_revision_id = first["agents"][0]["configRevisionId"]
        assert importer.import_file(source_path)["reused"] == 1

        changed = _agent("agent-alpha", model_id="deepseek-v4-flash")
        _write_registry(source_path, [changed])
        changed_report = importer.import_file(source_path)
        assert changed_report["created"] == 0
        assert changed_report["revised"] == 1

        current = store.repository.get_current_agent_config("agent-alpha")
        previous = store.repository.get_agent_config_revision(
            "agent-alpha",
            original_revision_id,
        )
        assert current is not None
        assert previous is not None
        assert current["configRevisionId"] != original_revision_id
        assert current["config"] == canonical_agent_config_payload(changed)
        assert previous["config"] == canonical_agent_config_payload(alpha)
    finally:
        store.close()


@pytest.mark.parametrize(
    "agents, expected_message",
    [
        ([_agent("agent-alpha"), _agent("agent-alpha")], "duplicate agentId"),
        ([{**_agent("agent-alpha"), "agentId": "  "}], "agentId"),
    ],
)
def test_importer_rejects_invalid_registry_before_any_sqlite_mutation(
    tmp_path: Path,
    safe_sqlite_runtime: None,
    agents: list[dict[str, object]],
    expected_message: str,
):
    source_path = tmp_path / "workspace" / "agents" / "agents.json"
    _write_registry(source_path, agents)
    store = _open_store(tmp_path)
    try:
        with pytest.raises(AgentConfigImportError, match=expected_message):
            LegacyAgentConfigImporter(store.repository).import_file(source_path)
        assert store.repository.get_agent("agent-alpha") is None
    finally:
        store.close()


def test_importer_does_not_archive_agents_absent_from_a_later_snapshot(
    tmp_path: Path,
    safe_sqlite_runtime: None,
):
    source_path = tmp_path / "workspace" / "agents" / "agents.json"
    alpha = _agent("agent-alpha")
    beta = _agent("agent-beta", display_name="Beta")
    _write_registry(source_path, [alpha, beta])
    store = _open_store(tmp_path)
    try:
        importer = LegacyAgentConfigImporter(store.repository)
        importer.import_file(source_path)
        _write_registry(source_path, [alpha])
        importer.import_file(source_path)

        beta_after = store.repository.get_agent("agent-beta")
        assert beta_after is not None
        assert beta_after["status"] == "active"
        assert beta_after["archivedAtMs"] is None
    finally:
        store.close()
