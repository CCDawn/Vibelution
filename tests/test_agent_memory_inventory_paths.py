import os

import pytest

from core.infrastructure import developer_sandbox
from core.web.services import agent_directory_service, memory_service


@pytest.fixture
def inventory_paths(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    roots = {"formal": tmp_path / "formal", "active": tmp_path / "formal"}
    calls = {"formal": 0, "active": 0, "relative_root": 0, "agent_paths": []}
    agents = [
        {"agentId": agent_id, "workspacePath": f"workspace/agents/{agent_id}"}
        for agent_id in ("first", "second")
    ]

    def formal_root(root):
        assert root == project.resolve()
        calls["formal"] += 1
        return roots["formal"]

    def active_root(root):
        assert root == project.resolve()
        calls["active"] += 1
        return roots["active"]

    def seeded_path(root, *parts):
        assert root == project.resolve()
        if parts:
            calls["agent_paths"].append(parts)
        else:
            calls["relative_root"] += 1
        return roots["active"].joinpath(*parts)

    monkeypatch.setattr(memory_service, "PROJECT_ROOT", project)
    monkeypatch.setattr(developer_sandbox, "formal_workspace_path", formal_root)
    monkeypatch.setattr(developer_sandbox, "sandboxed_workspace_path", active_root)
    monkeypatch.setattr(memory_service, "_sandboxed_workspace_path", seeded_path)
    monkeypatch.setattr(agent_directory_service, "list_agents", lambda **kwargs: agents)
    monkeypatch.setattr(memory_service, "_agent_formal_knowledge_summary", lambda *args: {})
    return project, roots, agents, calls


def test_inventory_reuses_roots_but_keeps_per_agent_path_routing(inventory_paths):
    _, roots, agents, calls = inventory_paths
    for agent in agents:
        memory = roots["active"] / "agents" / agent["agentId"] / "memory"
        (memory / "nested").mkdir(parents=True)
        (memory / "nested" / "lesson.md").write_text("private lesson", encoding="utf-8")

    payload = memory_service.get_agent_memory_inventory()

    assert payload["summary"]["privateFileCount"] == 2
    assert calls["formal"] == calls["active"] == calls["relative_root"] == 1
    assert calls["agent_paths"] == [("agents", "first"), ("agents", "second")]
    for entry in payload["agents"]:
        prefix = f"workspace/agents/{entry['agentId']}/memory"
        assert entry["privateMemoryRoot"] == prefix
        assert entry["items"][0]["path"] == f"{prefix}/nested/lesson.md"
        assert entry["items"][0]["content"] == ""
        assert entry["items"][0]["contentDeferred"] is True


def test_inventory_resolves_new_storage_roots_on_next_request(inventory_paths, tmp_path):
    _, roots, _, calls = inventory_paths
    first_memory = roots["active"] / "agents" / "first" / "memory"
    first_memory.mkdir(parents=True)
    (first_memory / "old.md").write_text("old", encoding="utf-8")
    before = memory_service.get_agent_memory_inventory(agent_id="first", include_content=True)

    roots["formal"] = roots["active"] = tmp_path / "new-storage"
    new_memory = roots["active"] / "agents" / "first" / "memory"
    new_memory.mkdir(parents=True)
    (new_memory / "new.md").write_text("new", encoding="utf-8")
    after = memory_service.get_agent_memory_inventory(agent_id="first", include_content=True)

    assert before["selectedAgent"]["items"][0]["content"] == "old"
    assert after["selectedAgent"]["items"][0]["content"] == "new"
    assert after["selectedAgent"]["items"][0]["relativePath"] == "new.md"
    assert calls["formal"] == calls["active"] == calls["relative_root"] == 2


@pytest.mark.parametrize("workspace", ["absolute", "relative", "workspace-traversal", "prefix-sibling"])
def test_inventory_rejects_escaped_workspaces_without_seeding_root(inventory_paths, tmp_path, workspace):
    project, _, agents, calls = inventory_paths
    candidates = {
        "absolute": str(tmp_path / "outside"),
        "relative": "../outside",
        "workspace-traversal": "workspace/../outside",
        "prefix-sibling": str(project.with_name("project-other")),
    }
    agents[:] = [{"agentId": "outside", "workspacePath": candidates[workspace]}]

    payload = memory_service.get_agent_memory_inventory(include_content=True)

    assert payload["agents"][0]["privateMemoryRoot"] == ""
    assert payload["agents"][0]["items"] == []
    assert payload["summary"]["warnings"]
    assert calls["relative_root"] == 0


def test_inventory_resolves_each_candidate_even_with_shared_roots(inventory_paths, tmp_path):
    _, roots, _, _ = inventory_paths
    active = roots["active"]
    active.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = active / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating a directory symlink is unavailable")
    context = memory_service._agent_memory_path_context(memory_service.PROJECT_ROOT)

    assert memory_service._resolve_agent_memory_root(
        memory_service.PROJECT_ROOT, str(link), path_context=context
    ) is None


def test_empty_inventory_does_not_resolve_workspace_roots(inventory_paths):
    _, _, agents, calls = inventory_paths
    agents.clear()

    assert memory_service.get_agent_memory_inventory()["agents"] == []
    assert calls["formal"] == calls["active"] == calls["relative_root"] == 0


def test_private_memory_revision_detects_same_second_same_size_updates(inventory_paths):
    _, roots, _, _ = inventory_paths
    memory = roots["active"] / "agents" / "first" / "memory"
    memory.mkdir(parents=True)
    path = memory / "lesson.md"
    second = 1_790_000_000_000_000_000
    path.write_text("before", encoding="utf-8")
    os.utime(path, ns=(second + 100_000_000, second + 100_000_000))
    before = memory_service.get_agent_memory_inventory(agent_id="first")["selectedAgent"]["items"][0]
    unchanged = memory_service.get_agent_memory_inventory(agent_id="first")["selectedAgent"]["items"][0]

    path.write_text("after!", encoding="utf-8")
    os.utime(path, ns=(second + 200_000_000, second + 200_000_000))
    after = memory_service.get_agent_memory_inventory(agent_id="first")["selectedAgent"]["items"][0]
    detail = memory_service.get_agent_memory_inventory(agent_id="first", include_content=True)

    assert before["updatedAt"] == after["updatedAt"]
    assert before["sizeBytes"] == after["sizeBytes"]
    assert before["revision"] == unchanged["revision"]
    assert before["revision"] != after["revision"]
    assert before["content"] == after["content"] == ""
    assert detail["selectedAgent"]["items"][0]["revision"] == after["revision"]
    assert detail["selectedAgent"]["items"][0]["content"] == "after!"


@pytest.mark.parametrize("agent_id", ["", "missing"])
def test_inventory_phase_timings_preserve_payload_and_measure_skipped_work(inventory_paths, monkeypatch, agent_id):
    _, _, agents, _ = inventory_paths
    now = [0.0]
    monkeypatch.setattr(memory_service.time, "perf_counter", lambda: now[0])
    monkeypatch.setattr(memory_service, "_now_iso", lambda: "2026-10-01T00:00:00Z")

    def list_agents(**kwargs):
        now[0] += 2.0
        return agents

    path_context = memory_service._agent_memory_path_context
    inventory_entry = memory_service._agent_memory_inventory_entry

    def timed_path_context(root):
        now[0] += 0.5
        return path_context(root)

    def timed_inventory_entry(*args, **kwargs):
        now[0] += 1.5
        return inventory_entry(*args, **kwargs)

    monkeypatch.setattr(agent_directory_service, "list_agents", list_agents)
    monkeypatch.setattr(memory_service, "_agent_memory_path_context", timed_path_context)
    monkeypatch.setattr(memory_service, "_agent_memory_inventory_entry", timed_inventory_entry)
    baseline = memory_service.get_agent_memory_inventory(agent_id=agent_id)
    phases = {"directory": -1.0, "paths": -1.0, "scan": -1.0, "total": -1.0}
    measured = memory_service.get_agent_memory_inventory(agent_id=agent_id, phase_timings=phases)

    assert measured == baseline
    assert "phase_timings" not in measured
    assert phases == (
        {"directory": 2000.0, "paths": 500.0, "scan": 3000.0, "total": 5500.0}
        if not agent_id
        else {"directory": 2000.0, "paths": 0.0, "scan": 0.0, "total": 2000.0}
    )
