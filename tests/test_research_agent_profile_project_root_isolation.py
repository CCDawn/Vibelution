"""``PROJECT_ROOT`` 显式传参的并发隔离契约。

research agent runner 曾对三个 service 的模块级 ``PROJECT_ROOT`` 做
save-swap-restore 换根；并发线程会互相覆盖（A 的 finally 恢复把 B 正在
使用的根换回旧值），解析到错误 workspace 的 agent/prompt。现在读取路径
一律显式传 ``project_root``，模块级根不再被改写。

本文件锁定三件事：
1. 两个线程并发用不同 ``project_root`` 解析 agent profile / system prompt，
   互不串线，各自拿到正确根的结果（Barrier 对齐起跑，循环多次）。
2. agent_directory 进程内缓存按根分区：不同根解析不命中彼此缓存。
3. ``project_root=None`` 仍回落模块级 ``PROJECT_ROOT``，既有调用方兼容。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from core.research import agent_runner as agent_runner_module
from core.research.agent_runner import LLMResearchAgentRunner
from core.web.services import (
    agent_directory_service,
    agent_mode_binding_service,
    prompt_template_service,
)


class _RootWorkspace:
    """Minimal workspace double carrying an explicit project root."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.root = project_root / "workspace"

    def read_research_prompt(self, filename: str) -> str:
        return f"fallback prompt {filename}"


def _seed_project_root(tmp_path: Path, slug: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Build one fully isolated workspace root with registry/binding/template."""

    monkeypatch.setenv("VIBELUTION_PROJECTS_HOME", str(tmp_path / "projects"))
    root = tmp_path / f"root-{slug}"
    identity_dir = root / ".vibelution"
    identity_dir.mkdir(parents=True, exist_ok=True)
    (identity_dir / "project.json").write_text(
        json.dumps({"schemaVersion": 1, "projectId": f"research-root-{slug}"}),
        encoding="utf-8",
    )

    agent_id = f"agent-research-{slug}"
    template_id = f"prompt-research-broad-root-{slug}"
    marker = f"ROOT-{slug.upper()}-PROMPT-MARKER"
    display_name = f"广搜 Agent {slug.upper()}"

    registry_path = agent_directory_service.registry_path(project_root=root)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": agent_directory_service.AGENT_REGISTRY_VERSION,
                "agents": [
                    {
                        "agentId": agent_id,
                        "agentCode": f"RA{slug.upper()}",
                        "displayName": display_name,
                        "kind": "persistent",
                        "primaryMode": "research",
                        "roleKey": "research_broad",
                        "status": "active",
                        "promptTemplateId": template_id,
                        "llmBindings": {"dialogue": {"modelId": "model-primary"}},
                        "workspacePath": f"workspace/agents/{agent_id}",
                        "metadata": {"researchAgentKey": "broad"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    binding_path = agent_mode_binding_service.mode_binding_path(project_root=root)
    binding_path.parent.mkdir(parents=True, exist_ok=True)
    binding_path.write_text(
        json.dumps(
            {
                "schemaVersion": agent_mode_binding_service.MODE_BINDING_VERSION,
                "bindings": [
                    {
                        "mode": "research",
                        "defaultAgentId": agent_id,
                        "availableAgentIds": [agent_id],
                        "pool": [agent_id],
                        "flowBindings": {"broad": agent_id},
                        "slots": {},
                        "excludedAgentIds": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    template_path = prompt_template_service.prompt_template_path(project_root=root)
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text(
        json.dumps(
            {
                "schemaVersion": prompt_template_service.PROMPT_TEMPLATE_INDEX_VERSION,
                "templates": [
                    {
                        "templateId": template_id,
                        "name": f"research broad {slug}",
                        "content": marker,
                        "status": "active",
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
        "agentId": agent_id,
        "templateId": template_id,
        "marker": marker,
        "displayName": display_name,
    }


def test_concurrent_agent_profile_resolution_is_root_isolated(tmp_path, monkeypatch):
    info_a = _seed_project_root(tmp_path, "a", monkeypatch)
    info_b = _seed_project_root(tmp_path, "b", monkeypatch)
    runner = LLMResearchAgentRunner(search_provider=object())

    default_agent_root = agent_directory_service.PROJECT_ROOT
    default_binding_root = agent_mode_binding_service.PROJECT_ROOT
    default_prompt_root = prompt_template_service.PROJECT_ROOT

    workspaces: dict[int, _RootWorkspace] = {}
    monkeypatch.setattr(agent_runner_module, "get_workspace", lambda: workspaces[threading.get_ident()])

    barrier = threading.Barrier(2)
    failures: list[str] = []

    def worker(slug: str, info: dict[str, Any]) -> None:
        workspaces[threading.get_ident()] = info["workspace"]
        try:
            barrier.wait(timeout=30)
            for _ in range(6):
                profile = runner._agent_profile("broad")
                if profile.get("agentDisplayName") != info["displayName"]:
                    failures.append(f"{slug}: profile resolved wrong root: {profile.get('agentDisplayName')}")
                    return
                if profile.get("promptTemplateId") != info["templateId"]:
                    failures.append(f"{slug}: prompt template resolved wrong root: {profile.get('promptTemplateId')}")
                    return
                prompt = runner._system_prompt("broad", contract="CONTRACT-BLOCK")
                if info["marker"] not in prompt:
                    failures.append(f"{slug}: system prompt resolved wrong root content")
                    return
        except Exception as exc:  # pragma: no cover - surfaced via failures
            failures.append(f"{slug}: {type(exc).__name__}: {exc}")

    threads = [
        threading.Thread(target=worker, args=("a", info_a), name="root-a"),
        threading.Thread(target=worker, args=("b", info_b), name="root-b"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
        assert not thread.is_alive()

    assert failures == []
    # 模块级根保持原值：runner 不再改写全局 PROJECT_ROOT。
    assert agent_directory_service.PROJECT_ROOT == default_agent_root
    assert agent_mode_binding_service.PROJECT_ROOT == default_binding_root
    assert prompt_template_service.PROJECT_ROOT == default_prompt_root


def test_agent_directory_caches_do_not_leak_across_roots(tmp_path, monkeypatch):
    info_a = _seed_project_root(tmp_path, "a", monkeypatch)
    info_b = _seed_project_root(tmp_path, "b", monkeypatch)
    root_a: Path = info_a["root"]
    root_b: Path = info_b["root"]

    # 交替解析触发 repaired-state / hydration / workspace-path 缓存往返。
    for _ in range(3):
        agents_a = agent_directory_service.list_agents(include_archived=False, detail="full", project_root=root_a)
        agents_b = agent_directory_service.list_agents(include_archived=False, detail="full", project_root=root_b)
        ids_a = {str(item.get("agentId") or "") for item in agents_a}
        ids_b = {str(item.get("agentId") or "") for item in agents_b}
        assert info_a["agentId"] in ids_a
        assert info_b["agentId"] not in ids_a
        assert info_b["agentId"] in ids_b
        assert info_a["agentId"] not in ids_b

    assert agent_directory_service.get_agent(info_a["agentId"], include_archived=False, project_root=root_b) is None
    assert agent_directory_service.get_agent(info_b["agentId"], include_archived=False, project_root=root_a) is None
    resolved = agent_directory_service.get_agent(info_a["agentId"], include_archived=False, project_root=root_a)
    assert resolved is not None
    assert resolved.get("displayName") == info_a["displayName"]


def test_workspace_path_cache_is_partitioned_by_root(tmp_path, monkeypatch):
    info_a = _seed_project_root(tmp_path, "a", monkeypatch)
    info_b = _seed_project_root(tmp_path, "b", monkeypatch)
    root_a: Path = info_a["root"]
    root_b: Path = info_b["root"]

    with agent_directory_service.scoped_project_root(root_a):
        path_a_first = agent_directory_service._workspace_path("agents", "agents.json")
        path_a_cached = agent_directory_service._workspace_path("agents", "agents.json")
    with agent_directory_service.scoped_project_root(root_b):
        path_b_first = agent_directory_service._workspace_path("agents", "agents.json")
    with agent_directory_service.scoped_project_root(root_a):
        path_a_again = agent_directory_service._workspace_path("agents", "agents.json")

    assert path_a_first == path_a_cached == path_a_again
    assert path_a_first != path_b_first


def test_mode_binding_and_prompt_reads_are_root_partitioned(tmp_path, monkeypatch):
    info_a = _seed_project_root(tmp_path, "a", monkeypatch)
    info_b = _seed_project_root(tmp_path, "b", monkeypatch)
    root_a: Path = info_a["root"]
    root_b: Path = info_b["root"]

    for _ in range(3):
        payload_a = agent_mode_binding_service.get_mode_bindings_payload(project_root=root_a)
        payload_b = agent_mode_binding_service.get_mode_bindings_payload(project_root=root_b)
        flow_a = ((payload_a.get("modes") or {}).get("research") or {}).get("flowBindings") or {}
        flow_b = ((payload_b.get("modes") or {}).get("research") or {}).get("flowBindings") or {}
        assert flow_a.get("broad") == info_a["agentId"]
        assert flow_b.get("broad") == info_b["agentId"]

        template_a = prompt_template_service.get_prompt_template(info_a["templateId"], project_root=root_a)
        template_b = prompt_template_service.get_prompt_template(info_b["templateId"], project_root=root_a)
        template_b_on_b = prompt_template_service.get_prompt_template(info_b["templateId"], project_root=root_b)
        assert template_a is not None and template_a.get("content") == info_a["marker"]
        # b 的模板在根 a 下不存在；缓存往返后根 b 下仍能解析到 b 自己的内容。
        assert template_b is None
        assert template_b_on_b is not None and template_b_on_b.get("content") == info_b["marker"]


def test_missing_template_id_stays_root_local(tmp_path, monkeypatch):
    info_a = _seed_project_root(tmp_path, "a", monkeypatch)
    info_b = _seed_project_root(tmp_path, "b", monkeypatch)
    root_a: Path = info_a["root"]
    root_b: Path = info_b["root"]

    # 根 a 的模板 id 在根 b 的独立索引中不存在，解析互不串线。
    template = prompt_template_service.get_prompt_template(info_a["templateId"], project_root=root_b)
    assert template is None
    assert prompt_template_service.get_prompt_template(info_b["templateId"], project_root=root_b) is not None
    assert prompt_template_service.get_prompt_template(info_a["templateId"], project_root=root_a) is not None


def test_default_root_falls_back_to_module_project_root(tmp_path, monkeypatch):
    info_a = _seed_project_root(tmp_path, "a", monkeypatch)
    root_a: Path = info_a["root"]
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", root_a)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", root_a)

    # 不传 project_root：回落模块级根，行为与既有调用方一致。
    agents = agent_directory_service.list_agents(include_archived=False, detail="summary")
    assert info_a["agentId"] in {str(item.get("agentId") or "") for item in agents}
    template = prompt_template_service.get_prompt_template(info_a["templateId"])
    assert template is not None and template.get("content") == info_a["marker"]
