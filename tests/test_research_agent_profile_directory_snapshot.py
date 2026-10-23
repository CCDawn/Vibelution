"""``_agent_profile`` 全量 list_agents 收敛为轮内快照后的解析等价回归。

背景：``_agent_profile`` 的兜底查找过去每次都调 ``list_agents(detail="full")``
全量投影全部 agent（research-team 每轮每成员一次，m×n 放大）。现在同一
project_root、同注册表签名、TTL 内复用一次快照。

本文件锁定：
1. 解析等价：mode_bound 命中 / mode pool roleKey 回落 / researchAgentKey 命中 /
   roleKey 回落 / challengeCupTeamId 跳过 / 重复绑定报错 / 未知 key 报错，
   逐字保持快照化之前的语义。
2. 复用生效：同一轮多个成员共享一次 detail=full 投影；``project_root`` 显式
   透传给每次底层调用。
3. 失效正确：注册表重写后立即取到新值；``project_root=None`` 不进缓存。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest

from core.research import agent_runner as agent_runner_module
from core.research.agent_runner import LLMResearchAgentRunner
from core.web.services import (
    agent_directory_service,
    agent_mode_binding_service,
)


class _RootWorkspace:
    """Workspace double carrying an explicit project root."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.root = project_root / "workspace"

    def read_research_prompt(self, filename: str) -> str:
        return f"fallback prompt {filename}"


@pytest.fixture(autouse=True)
def _reset_snapshot_cache():
    # getattr 容错：等价矩阵用例需要对改前代码同样可跑（基线对照）。
    reset = getattr(agent_runner_module, "reset_research_directory_snapshot_cache", None)
    if reset is not None:
        reset()
    yield
    if reset is not None:
        reset()


def _write_registry(root: Path, agents: list[dict[str, Any]], *, mtime_ns: int | None = None) -> Path:
    registry_path = agent_directory_service.registry_path(project_root=root)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": agent_directory_service.AGENT_REGISTRY_VERSION,
                "agents": agents,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if mtime_ns is not None:
        os.utime(registry_path, ns=(mtime_ns, mtime_ns))
    return registry_path


def _seed_root(tmp_path: Path) -> dict[str, Any]:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)

    def agent(agent_id: str, **overrides: Any) -> dict[str, Any]:
        item: dict[str, Any] = {
            "agentId": agent_id,
            "agentCode": agent_id[-8:].upper(),
            "displayName": f"Agent {agent_id}",
            "kind": "persistent",
            "primaryMode": "research",
            "roleKey": "",
            "status": "active",
            "workspacePath": f"workspace/agents/{agent_id}",
            "metadata": {},
        }
        item.update({key: value for key, value in overrides.items() if key != "metadata"})
        item["metadata"] = {**item["metadata"], **overrides.get("metadata", {})}
        return item

    agents = [
        agent(
            "agent-broad",
            displayName="广搜 Agent",
            roleKey="research_broad",
            llmBindings={"dialogue": {"modelId": "model-broad"}},
            metadata={"researchAgentKey": "broad"},
        ),
        agent(
            "agent-deep",
            displayName="深搜 Agent",
            roleKey="research_deep",
            metadata={"researchAgentKey": "deep"},
        ),
        agent(
            "agent-skeptic",
            displayName="质疑 Agent V1",
            roleKey="research_skeptic",
            llmBindings={"dialogue": {"modelId": "model-skeptic"}},
            metadata={
                "researchAgentKey": "skeptic",
                "researchPromptFilename": "skeptic.md",
                "researchProfileId": "skeptic-profile",
            },
        ),
        # challengeCup 成员即使带 researchAgentKey 也必须被跳过。
        agent(
            "agent-cup-skeptic",
            roleKey="research_skeptic",
            metadata={"researchAgentKey": "skeptic", "challengeCupTeamId": "cup-1"},
        ),
        # 无 researchAgentKey，走 roleKey 回落。
        agent(
            "agent-verifier",
            displayName="核验 Agent",
            roleKey="research_verifier",
            metadata={"researchPromptFilename": "verifier.md"},
        ),
        # 同 key 双绑 → ValueError。
        agent("agent-dup-a", metadata={"researchAgentKey": "dup"}),
        agent("agent-dup-b", metadata={"researchAgentKey": "dup"}),
    ]
    _write_registry(root, agents)

    binding_path = agent_mode_binding_service.mode_binding_path(project_root=root)
    binding_path.parent.mkdir(parents=True, exist_ok=True)
    binding_path.write_text(
        json.dumps(
            {
                "schemaVersion": agent_mode_binding_service.MODE_BINDING_VERSION,
                "bindings": [
                    {
                        "mode": "research",
                        "defaultAgentId": "agent-broad",
                        "availableAgentIds": ["agent-broad", "agent-deep"],
                        "pool": ["agent-broad", "agent-deep"],
                        "flowBindings": {"broad": "agent-broad"},
                        "slots": {},
                        "excludedAgentIds": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "root": root,
        "workspace": _RootWorkspace(root),
        "agents_by_id": {item["agentId"]: item for item in agents},
    }


def _runner() -> LLMResearchAgentRunner:
    return LLMResearchAgentRunner(search_provider=object())


def test_profile_resolution_matches_are_preserved(tmp_path, monkeypatch):
    info = _seed_root(tmp_path)
    monkeypatch.setattr(agent_runner_module, "get_workspace", lambda: info["workspace"])
    runner = _runner()

    # mode_bound 命中：flowBindings 直达。
    broad = runner._agent_profile("broad")
    assert broad["agentId"] == "agent-broad"
    assert broad["agentDisplayName"] == "广搜 Agent"
    assert broad["llmBindings"] == {"dialogue": {"modelId": "model-broad"}}
    assert broad["agent"]["agentId"] == "agent-broad"

    # mode pool roleKey 回落：deep 无 flowBinding，从 pool 按 roleKey 匹配。
    deep = runner._agent_profile("deep")
    assert deep["agentId"] == "agent-deep"

    # 兜底全量扫描：researchAgentKey 命中，challengeCup 成员被跳过。
    skeptic = runner._agent_profile("skeptic")
    assert skeptic["agentId"] == "agent-skeptic"
    assert skeptic["promptFilename"] == "skeptic.md"
    assert skeptic["profileId"] == "skeptic-profile"
    assert skeptic["roleKey"] == "research_skeptic"
    assert skeptic["enabled"] is True
    assert "challengeCupTeamId" not in skeptic["agent"]["metadata"]

    # 兜底全量扫描：无 researchAgentKey 时 roleKey 回落。
    verifier = runner._agent_profile("verifier")
    assert verifier["agentId"] == "agent-verifier"
    assert verifier["promptFilename"] == "verifier.md"

    with pytest.raises(ValueError, match="Unknown research agent: ghost"):
        runner._agent_profile("ghost")

    with pytest.raises(ValueError, match="Research AgentDirectory binding is duplicated: dup"):
        runner._agent_profile("dup")


def test_snapshot_reuses_one_full_projection_across_members(tmp_path, monkeypatch):
    info = _seed_root(tmp_path)
    monkeypatch.setattr(agent_runner_module, "get_workspace", lambda: info["workspace"])

    real_list_agents = agent_directory_service.list_agents
    calls: list[dict[str, Any]] = []

    def counting_list_agents(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(dict(kwargs))
        return real_list_agents(**kwargs)

    monkeypatch.setattr(agent_directory_service, "list_agents", counting_list_agents)
    runner = _runner()

    for agent_key in ("broad", "deep", "skeptic", "verifier", "skeptic"):
        runner._agent_profile(agent_key)

    full_calls = [item for item in calls if item.get("detail") == "full"]
    assert len(full_calls) == 1, f"expected one full projection, got {len(full_calls)}"
    assert full_calls[0]["include_archived"] is False
    assert full_calls[0]["project_root"] == info["root"]


def test_registry_rewrite_invalidates_snapshot(tmp_path, monkeypatch):
    info = _seed_root(tmp_path)
    monkeypatch.setattr(agent_runner_module, "get_workspace", lambda: info["workspace"])
    runner = _runner()

    first = runner._agent_profile("skeptic")
    assert first["agentDisplayName"] == "质疑 Agent V1"

    agents = json.loads(
        agent_directory_service.registry_path(project_root=info["root"]).read_text(encoding="utf-8")
    )["agents"]
    for item in agents:
        if item.get("agentId") == "agent-skeptic":
            item["displayName"] = "质疑 Agent V2"
    registry_path = _write_registry(
        info["root"],
        agents,
        mtime_ns=int(os.stat(agent_directory_service.registry_path(project_root=info["root"])).st_mtime_ns) + 10_000_000,
    )
    assert registry_path.exists()

    second = runner._agent_profile("skeptic")
    assert second["agentDisplayName"] == "质疑 Agent V2"


def test_none_project_root_bypasses_snapshot(tmp_path, monkeypatch):
    info = _seed_root(tmp_path)

    class _NoRootWorkspace:
        def read_research_prompt(self, filename: str) -> str:
            return f"fallback prompt {filename}"

    real_list_agents = agent_directory_service.list_agents
    calls: list[dict[str, Any]] = []

    def stub_list_agents(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(dict(kwargs))
        return real_list_agents(**kwargs)

    monkeypatch.setattr(agent_runner_module, "get_workspace", lambda: _NoRootWorkspace())
    monkeypatch.setattr(agent_directory_service, "list_agents", stub_list_agents)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", info["root"])
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", info["root"])
    runner = _runner()

    first = runner._agent_profile("skeptic")
    second = runner._agent_profile("skeptic")
    assert first["agentId"] == "agent-skeptic"
    assert second["agentId"] == "agent-skeptic"
    full_calls = [item for item in calls if item.get("detail") == "full"]
    assert len(full_calls) == 2, "project_root=None must not enter the snapshot cache"


def test_concurrent_members_share_snapshot(tmp_path, monkeypatch):
    info = _seed_root(tmp_path)
    monkeypatch.setattr(agent_runner_module, "get_workspace", lambda: info["workspace"])

    real_list_agents = agent_directory_service.list_agents
    calls: list[dict[str, Any]] = []
    lock = threading.Lock()

    def counting_list_agents(**kwargs: Any) -> list[dict[str, Any]]:
        with lock:
            calls.append(dict(kwargs))
        return real_list_agents(**kwargs)

    monkeypatch.setattr(agent_directory_service, "list_agents", counting_list_agents)
    runner = _runner()

    barrier = threading.Barrier(4)
    failures: list[str] = []
    expectations = {
        "broad": "agent-broad",
        "deep": "agent-deep",
        "skeptic": "agent-skeptic",
        "verifier": "agent-verifier",
    }

    def worker(agent_key: str) -> None:
        try:
            barrier.wait(timeout=30)
            profile = runner._agent_profile(agent_key)
            if profile.get("agentId") != expectations[agent_key]:
                failures.append(f"{agent_key}: resolved {profile.get('agentId')}")
        except Exception as exc:  # pragma: no cover - surfaced via failures
            failures.append(f"{agent_key}: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(key,)) for key in expectations]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
        assert not thread.is_alive()

    assert failures == []
    full_calls = [item for item in calls if item.get("detail") == "full"]
    assert len(full_calls) == 1
