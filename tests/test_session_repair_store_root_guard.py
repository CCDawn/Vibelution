"""Session-repair mint must never land in an identity-less fallback store.

回归根因：research 后台流会把 ``agent_directory_service.PROJECT_ROOT``
临时改成无 ``.vibelution/project.json`` 身份的实例 data 目录；路由层
``formal_workspace_path`` 对无身份根静默回落共享默认 workspace。修复线程
在污染窗口内执行 ``ensure_agent_for_session`` 时，替身 Agent 被铸进错误库。

守卫契约（``ops_residual._untrusted_session_repair_store_root``）：
- 有效根无身份、且 data home 是未被显式指定的默认回落 -> 拒绝铸造/更新，
  只读返回既有 agent（或 None），不 raise；
- data home 被显式指定（``VIBELUTION_DATA_HOME`` / ``[storage].data_home`` /
  pytest pin）-> 无身份回落与既有语义一致，保持可铸造；
- 显式 ``project_root`` 传参在全局根被污染时仍路由到正确实例存储。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from config.paths import resolve_workspace_home
from core.infrastructure import developer_sandbox
from core.web.services import agent_directory_service
from core.web.services.agent_directory import ops_residual
from vibelution_storage import (
    PROJECTS_HOME_ENV,
    resolve_project_storage_paths,
)


def _write_identity(project_root: Path, project_id: str = "guard-clean") -> Path:
    path = project_root / ".vibelution" / "project.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"schemaVersion": 1, "projectId": project_id}) + "\n",
        encoding="utf-8",
    )
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def _isolated_guard_storage_env(tmp_path, monkeypatch):
    """Pin every storage surface into tmp and isolate the Documents fallback.

    ``PROJECTS_HOME_ENV`` keeps identity-routed instance stores under tmp;
    ``VIBELUTION_CONFIG_PATH`` pointing at a missing file keeps
    ``resolve_configured_data_home()`` deterministic (None) so the guard's
    operator-override branch cannot see the real operator config;
    ``USERPROFILE`` redirection keeps the *default* Documents fallback home
    inside tmp so a broken guard can never touch the real operator tree.
    """

    monkeypatch.setenv(PROJECTS_HOME_ENV, str(tmp_path / "projects-home"))
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "operator" / "config.toml"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "fake-user"))
    monkeypatch.delenv("VIBELUTION_DATA_HOME", raising=False)
    for _git_var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_GLOBAL"):
        monkeypatch.delenv(_git_var, raising=False)
    yield


def test_polluted_root_blocks_mint_and_clean_root_recovers(tmp_path, monkeypatch):
    """用例 A：污染窗口不铸造、回落库无新文件；干净根下补铸成功。"""

    clean_root = tmp_path / "clean-checkout"
    clean_root.mkdir()
    _write_identity(clean_root, "guard-clean")
    polluted_root = tmp_path / "polluted-instance-data"
    polluted_root.mkdir()

    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", polluted_root)

    # In-test the conftest stubs developer_sandbox.resolve_workspace_home to
    # tmp_path/workspace; that stub IS the routed no-identity fallback here,
    # so it is the wrong-store target this assertion must watch.
    routed_fallback = developer_sandbox.resolve_workspace_home()

    result = agent_directory_service.ensure_agent_for_session(
        "session-guard-a",
        display_name="污染窗口会话",
        created_by="session_repair",
    )

    assert result is None
    assert not (routed_fallback / "agents" / "agents.json").exists()
    assert not (routed_fallback / "agents").exists()
    assert not (resolve_workspace_home() / "agents" / "agents.json").exists()
    assert list(polluted_root.iterdir()) == []

    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", clean_root)

    agent = agent_directory_service.ensure_agent_for_session(
        "session-guard-a",
        display_name="恢复后的会话",
        created_by="session_repair",
    )

    assert agent is not None and str(agent.get("agentId") or "").strip()
    assert agent["conversationIndexKind"] == agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT
    canonical_workspace = resolve_project_storage_paths(clean_root).workspace
    registry = canonical_workspace / "agents" / "agents.json"
    assert registry.exists()
    stored = json.loads(registry.read_text(encoding="utf-8"))
    direct_agents = [
        item
        for item in stored.get("agents") or []
        if str(item.get("directSessionId") or "").strip() == "session-guard-a"
    ]
    assert direct_agents and direct_agents[0]["agentId"] == agent["agentId"]
    assert direct_agents[0].get("createdBy") == "session_repair"
    assert not (routed_fallback / "agents" / "agents.json").exists()


def test_polluted_root_returns_existing_agent_without_rewriting_store(tmp_path, monkeypatch):
    """用例 B：污染根下已存在同 directSession 的 agent -> 只读返回，落盘不变。"""

    polluted_root = tmp_path / "polluted-instance-data"
    polluted_root.mkdir()
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", polluted_root)

    registry = agent_directory_service.registry_path()
    seeded_agent = {
        "agentId": "agent-guard-b",
        "agentCode": "AG0001",
        "kind": "persistent",
        "displayName": "污染前替身",
        "primaryMode": "chat",
        "roleKey": "",
        "promptTemplateId": "",
        "llmBindings": {"dialogue": {"modelId": "model-primary"}},
        "directSessionId": "session-guard-b",
        "workspacePath": "workspace/agents/agent-guard-b",
        "memoryPolicyId": "memory-agent-guard-b",
        "createdBy": "session_repair",
        "status": "active",
        "metadata": {
            "conversationIndexKind": agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
            "functionalDisplayName": "污染前替身",
        },
        "createdAt": _now_iso(),
        "updatedAt": _now_iso(),
    }
    seeded_state = {
        "version": agent_directory_service.AGENT_REGISTRY_VERSION,
        "updatedAt": _now_iso(),
        "agents": [seeded_agent],
        "toolPolicies": {},
        "memoryPolicies": {},
    }
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps(seeded_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    before_bytes = registry.read_bytes()

    agent = agent_directory_service.ensure_agent_for_session(
        "session-guard-b",
        display_name="改名尝试会被拒绝",
        llm_bindings={"dialogue": {"modelId": "model-rewrite-attempt"}},
        created_by="session_repair",
    )

    assert agent is not None
    assert str(agent.get("agentId") or "").strip() == "agent-guard-b"
    assert str(agent.get("directSessionId") or "").strip() == "session-guard-b"
    assert registry.read_bytes() == before_bytes


def test_explicit_project_root_pins_store_while_global_root_polluted(tmp_path, monkeypatch):
    """用例 C：显式 project_root（带身份）穿透污染全局根，铸进正确实例存储。"""

    clean_root = tmp_path / "clean-checkout"
    clean_root.mkdir()
    _write_identity(clean_root, "guard-explicit")
    polluted_root = tmp_path / "polluted-instance-data"
    polluted_root.mkdir()
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", polluted_root)

    agent = agent_directory_service.ensure_agent_for_session(
        "session-guard-c",
        display_name="显式根会话",
        created_by="session_repair",
        project_root=clean_root,
    )

    assert agent is not None and str(agent.get("agentId") or "").strip()
    canonical_workspace = resolve_project_storage_paths(clean_root).workspace
    registry = canonical_workspace / "agents" / "agents.json"
    assert registry.exists()
    stored = json.loads(registry.read_text(encoding="utf-8"))
    direct_agents = [
        item
        for item in stored.get("agents") or []
        if str(item.get("directSessionId") or "").strip() == "session-guard-c"
    ]
    assert direct_agents and direct_agents[0]["agentId"] == agent["agentId"]
    assert not (developer_sandbox.resolve_workspace_home() / "agents").exists()
    assert not (resolve_workspace_home() / "agents").exists()
    assert list(polluted_root.iterdir()) == []
    # scoped root is a ContextVar pin only: the polluted global stays as-is.
    assert agent_directory_service.PROJECT_ROOT == polluted_root


def test_pinned_data_home_keeps_existing_mint_semantics(tmp_path, monkeypatch):
    """用例 D：显式 VIBELUTION_DATA_HOME 下无身份根仍按现状铸造（对齐 ssot 契约）。"""

    data_home = tmp_path / "operator-data-home"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    identity_less_root = tmp_path / "identity-less-root"
    identity_less_root.mkdir()
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", identity_less_root)

    # The explicit data-home pin marks the identity-less fallback as trusted:
    # the guard must stay out of the way so existing callers keep minting.
    assert ops_residual._untrusted_session_repair_store_root() is None

    agent = agent_directory_service.ensure_agent_for_session(
        "session-guard-d",
        display_name="现状语义会话",
        created_by="session_repair",
    )

    assert agent is not None and str(agent.get("agentId") or "").strip()
    assert agent["conversationIndexKind"] == agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT
    # The mint lands exactly where the router routes the identity-less root
    # (the conftest stubs the fallback home to tmp_path/workspace in tests).
    registry = agent_directory_service.registry_path()
    assert registry == developer_sandbox.formal_workspace_path(identity_less_root, "agents", "agents.json")
    assert registry.exists()
    stored = json.loads(registry.read_text(encoding="utf-8"))
    stored_agent = next(
        item
        for item in stored.get("agents") or []
        if str(item.get("agentId") or "").strip() == agent["agentId"]
    )
    model_id = str(
        ((stored_agent.get("llmBindings") or {}).get(agent_directory_service.DEFAULT_AGENT_LLM_SLOT) or {}).get("modelId")
        or ""
    ).strip()
    assert model_id
