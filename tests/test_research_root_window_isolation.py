"""Research root windows must stay thread-isolated from module globals.

回归根因：``research_service`` 四处「save→改模块级 ``PROJECT_ROOT``→调用→
finally 恢复」窗口把进程级全局当作上下文传递；并发线程（如会话修复铸造）
在窗口内解析 Agent 存储根被带偏，替身 Agent 落进无身份回落库。迁移后契约：

- research 的读写一律走 ``scoped_project_root`` 上下文或显式 ``project_root``
  参数；
- 模块级 ``PROJECT_ROOT``（agent_directory / session / mode_binding 三个
  service）在 research 调用期间全程不变；
- 显式根的落库走身份路由实例存储，绝不落在共享默认回落 workspace。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from core.infrastructure import developer_sandbox
from core.web.services import (
    agent_directory_service,
    agent_mode_binding_service,
    research_service,
    session_service,
)
from vibelution_storage import (
    PROJECTS_HOME_ENV,
    resolve_project_storage_paths,
)


def _write_identity(project_root: Path, project_id: str) -> None:
    path = project_root / ".vibelution" / "project.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schemaVersion": 1, "projectId": project_id}) + "\n",
        encoding="utf-8",
    )


class _WorkspaceDouble:
    """Production-shaped workspace double（显式 project_root 分支 + research IO 面）."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.root = project_root / "workspace"

    def research_prompts_dir(self) -> Path:
        return self.root / "prompts" / "research"

    def get_research_prompt_path(self, filename: str) -> Path:
        return self.research_prompts_dir() / filename

    def get_research_agent_config_path(self) -> Path:
        return self.research_prompts_dir() / "agents.json"

    def get_research_flow_canvas_path(self) -> Path:
        return self.research_prompts_dir() / "flow_canvas.json"

    def read_research_agent_config(self) -> dict:
        return {"schemaVersion": 1, "agents": []}

    def write_research_agent_config(self, _data: dict) -> bool:
        return True

    def write_research_prompt(self, filename: str, content: str) -> bool:
        path = self.get_research_prompt_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True

    def read_research_prompt(self, filename: str) -> str:
        path = self.get_research_prompt_path(filename)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def read_research_flow_canvas(self) -> dict:
        return {"nodes": [], "edges": []}

    def write_research_flow_canvas(self, _data: dict) -> bool:
        return True


@pytest.fixture(autouse=True)
def _isolated_research_root_env(tmp_path, monkeypatch):
    """隔离存储面；必须摘掉 conftest 钉的 DATA_HOME 才能测跨根路由。"""

    monkeypatch.setenv(PROJECTS_HOME_ENV, str(tmp_path / "projects-home"))
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "operator" / "config.toml"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "fake-user"))
    # tests/conftest.py 对全部测试 autouse 钉 VIBELUTION_DATA_HOME；
    # 不摘掉会把无身份回落与身份路由压到同一 data home，掩蔽隔离断言。
    monkeypatch.delenv("VIBELUTION_DATA_HOME", raising=False)
    for _git_var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_GLOBAL"):
        monkeypatch.delenv(_git_var, raising=False)
    yield


def _wire_research_workspace(monkeypatch: pytest.MonkeyPatch, workspace: _WorkspaceDouble) -> None:
    monkeypatch.setattr(research_service, "get_workspace", lambda: workspace)
    monkeypatch.setattr(
        research_service,
        "_list_llm_config_options",
        lambda: [{"configId": "primary"}],
    )
    monkeypatch.setattr(
        session_service,
        "llm_bindings_for_profile_id",
        lambda _profile_id: {"dialogue": {"modelId": "iso-model"}},
    )


def test_research_binding_save_never_mutates_shared_roots_under_concurrency(
    tmp_path, monkeypatch
):
    """W1 并发契约：research 保存期间模块根全程不变，修复铸造落对库。"""

    # pytest conftest 把模块根钉到 tmp_path（无身份）；补写身份以对齐生产
    # 「模块根 == 带身份仓库根」的收敛前提，否则身份路由在用例内被拒。
    module_root = Path(agent_directory_service.PROJECT_ROOT)
    _write_identity(module_root, "iso-module")
    workspace = _WorkspaceDouble(module_root)
    _wire_research_workspace(monkeypatch, workspace)

    services = (
        agent_directory_service,
        session_service,
        agent_mode_binding_service,
    )
    initial_roots = {svc.__name__: svc.PROJECT_ROOT for svc in services}
    module_store = resolve_project_storage_paths(module_root).workspace
    fallback = developer_sandbox.resolve_workspace_home()

    barrier = threading.Barrier(2)
    failures: list[str] = []
    minted_ids: list[str] = []

    def research_worker() -> None:
        try:
            barrier.wait(timeout=30)
            research_service.save_research_agent_binding(
                "broad",
                "research_broad_explorer",
                "primary",
                label="隔离广搜 Agent",
                prompt_filename="broad.md",
            )
        except Exception as exc:  # noqa: BLE001 - surfaced via failures
            failures.append(f"research: {type(exc).__name__}: {exc}")

    def repair_worker() -> None:
        try:
            barrier.wait(timeout=30)
            for index in range(6):
                for name, root in initial_roots.items():
                    current = {
                        agent_directory_service.__name__: agent_directory_service.PROJECT_ROOT,
                        session_service.__name__: session_service.PROJECT_ROOT,
                        agent_mode_binding_service.__name__: agent_mode_binding_service.PROJECT_ROOT,
                    }[name]
                    if current != root:
                        failures.append(f"module root mutated during research window: {name}")
                        return
                agent = agent_directory_service.ensure_agent_for_session(
                    f"session-iso-repair-{index}",
                    display_name=f"并发修复会话 {index}",
                    created_by="session_repair",
                )
                if agent is None:
                    failures.append("concurrent repair mint returned None under clean module root")
                    return
                minted_ids.append(str(agent.get("agentId")))
        except Exception as exc:  # noqa: BLE001 - surfaced via failures
            failures.append(f"repair: {type(exc).__name__}: {exc}")

    threads = [
        threading.Thread(target=research_worker, name="research-save"),
        threading.Thread(target=repair_worker, name="session-repair"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
        assert not thread.is_alive()

    assert failures == []
    for name, root in initial_roots.items():
        assert {
            agent_directory_service.__name__: agent_directory_service.PROJECT_ROOT,
            session_service.__name__: session_service.PROJECT_ROOT,
            agent_mode_binding_service.__name__: agent_mode_binding_service.PROJECT_ROOT,
        }[name] == root

    registry = module_store / "agents" / "agents.json"
    assert registry.exists()
    stored = json.loads(registry.read_text(encoding="utf-8"))
    stored_ids = {str(item.get("agentId")) for item in stored.get("agents") or []}
    assert set(minted_ids) <= stored_ids
    research_agents = [
        item
        for item in stored.get("agents") or []
        if str(item.get("roleKey") or "").strip() == "research_broad"
    ]
    assert research_agents, "research agent must land in the module-root routed store"
    assert not (fallback / "agents" / "agents.json").exists()


def test_research_mode_binding_rw_uses_explicit_project_root(tmp_path, monkeypatch):
    """W2/W3 契约：mode binding 读写走显式根，模块根不动。"""

    root_a = tmp_path / "checkout-a"
    root_a.mkdir()
    _write_identity(root_a, "iso-a")
    workspace = _WorkspaceDouble(root_a)
    _wire_research_workspace(monkeypatch, workspace)

    default_agent_root = agent_directory_service.PROJECT_ROOT
    default_binding_root = agent_mode_binding_service.PROJECT_ROOT

    with agent_directory_service.scoped_project_root(root_a):
        seeded = agent_directory_service.create_agent_instance(
            display_name="模式绑定宿主 Agent",
            llm_bindings={"dialogue": {"modelId": "iso-model"}},
            primary_mode="research",
            role_key="research_host",
        )
    host_agent_id = str(seeded["agentId"])

    research_service._update_research_mode_binding_for_workspace(
        default_agent_id=host_agent_id,
        available_agent_ids=[host_agent_id],
        pool=[host_agent_id],
        flow_bindings={},
    )
    research_entry = research_service._read_research_mode_binding_for_workspace()

    assert str(research_entry.get("defaultAgentId") or "").strip() == host_agent_id
    explicit_path = agent_mode_binding_service.mode_binding_path(project_root=root_a)
    module_path = agent_mode_binding_service.mode_binding_path()
    assert explicit_path != module_path
    assert explicit_path.exists()
    root_a_store = resolve_project_storage_paths(root_a).workspace
    assert explicit_path.resolve().is_relative_to(root_a_store.resolve())
    assert agent_directory_service.PROJECT_ROOT == default_agent_root
    assert agent_mode_binding_service.PROJECT_ROOT == default_binding_root
    assert not (
        developer_sandbox.resolve_workspace_home() / "agent_config" / "mode_bindings.json"
    ).exists()


def test_research_agent_config_read_uses_explicit_project_root(tmp_path, monkeypatch):
    """W4 契约：Agent 配置 SSOT 读取与 configPath 均解析自显式根。"""

    root_b = tmp_path / "checkout-b"
    root_b.mkdir()
    _write_identity(root_b, "iso-b")
    workspace = _WorkspaceDouble(root_b)
    _wire_research_workspace(monkeypatch, workspace)

    with agent_directory_service.scoped_project_root(root_b):
        agent_directory_service.create_agent_instance(
            display_name="探针广搜 Agent",
            llm_bindings={"dialogue": {"modelId": "iso-model"}},
            primary_mode="research",
            role_key="research_probe",
            prompt_template_id="prompt-probe",
            metadata={
                "researchAgentKey": "probe",
                "researchTemplateId": "research_broad_explorer",
                "researchPromptFilename": "probe.md",
                "configSurface": "agent_config",
            },
        )

    default_agent_root = agent_directory_service.PROJECT_ROOT
    config = research_service._load_research_agent_config()

    assert [item["key"] for item in config["agents"]] == ["probe"]
    assert config["configPath"] == str(
        agent_directory_service.registry_path(project_root=root_b)
    )
    assert config["configPath"] != str(agent_directory_service.registry_path())
    root_b_store = resolve_project_storage_paths(root_b).workspace
    assert Path(config["configPath"]).resolve().is_relative_to(root_b_store.resolve())
    assert agent_directory_service.PROJECT_ROOT == default_agent_root
