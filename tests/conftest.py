#!/usr/bin/env python3
"""
pytest 配置和共享 fixtures

提供测试所需的共享资源：
- 单例重置（防止测试间状态泄漏）
- 隔离工作空间
- 可复用 mock 对象
"""

import pytest
import os
import sys
import ast
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows: pytest tmp basename 使用完整测试函数名（最长 ~60 字符），叠加
# developer-mode 沙盒/team 知识库等深层目录会超过 260 字符路径上限并抛
# WinError 206。将临时根移到短路径（优先 C:\vtmp，失败时回退系统 temp），
# 必须在 pytest 初始化 basetemp 之前生效（conftest import 时机足够早）。
if os.name == "nt":
    _short_temp_root = r"C:\vtmp"
    try:
        Path(_short_temp_root).mkdir(parents=True, exist_ok=True)
    except OSError:
        _short_temp_root = os.path.join(tempfile.gettempdir(), "vtmp")
    os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", _short_temp_root)

# Team-workflow behavioral cases live in five domain packs for xdist loadfile.
# The historical aggregate re-exports the same cases and must not be collected
# together with those packs (double-count / double-run).
_TEAM_WORKFLOW_AGGREGATE = "test_team_workflow_orchestration_service.py"
_TEAM_WORKFLOW_DOMAIN_PACKS = frozenset(
    {
        "test_team_workflow_structure_cases.py",
        "test_team_workflow_source_collection_cases.py",
        "test_team_workflow_experiment_cases.py",
        "test_team_workflow_research_knowledge_cases.py",
        "test_team_workflow_remainder_cases.py",
    }
)


# ============================================================================
# web/dist 自包含占位 — worktree 里 route contract 测试的环境自足
# ============================================================================
# Git worktree 只检出被追踪文件，gitignored 的 web/dist 构建产物只存在于根
# checkout。完整后端启动（create_app + TestClient）在 register_spa_routes 处
# 要求该目录存在，否则所有 route contract 测试以 RuntimeError 假红。会话开始
# 时按生产同一解析逻辑补一个最小占位目录（仅在缺失时），会话结束且无并发
# 会话持有时清理；根 checkout 存在真实构建时完全零操作。


def pytest_sessionstart(session):
    try:
        from tests.helpers.web_dist_placeholder import acquire_web_dist_placeholder

        session._web_dist_placeholder = acquire_web_dist_placeholder(PROJECT_ROOT)
    except Exception:  # noqa: BLE001 - 测试基础设施不得阻断收集
        session._web_dist_placeholder = None


def pytest_sessionfinish(session, exitstatus):
    placeholder = getattr(session, "_web_dist_placeholder", None)
    if placeholder is not None:
        try:
            from tests.helpers.web_dist_placeholder import release_web_dist_placeholder

            release_web_dist_placeholder(placeholder)
        except Exception:  # noqa: BLE001
            pass


def _pytest_arg_paths(config) -> list[Path]:
    paths: list[Path] = []
    for raw in getattr(config, "args", []) or []:
        text = str(raw).split("::", 1)[0].strip()
        if not text or text.startswith("-"):
            continue
        path = Path(text)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        else:
            path = path.resolve()
        paths.append(path)
    return paths


def pytest_ignore_collect(collection_path=None, path=None, config=None):
    """Skip the team-workflow aggregate when domain packs (or a tests tree) are collected.

    Note: some pytest invocations still collect explicit file args even when this
    hook returns True; ``pytest_collection_modifyitems`` is the hard dedupe gate.
    """
    if config is None:
        return False
    raw = collection_path if collection_path is not None else path
    try:
        file_path = Path(raw)
    except TypeError:
        file_path = Path(str(raw))
    if file_path.name != _TEAM_WORKFLOW_AGGREGATE:
        return False

    targets = _pytest_arg_paths(config)
    if not targets:
        # No explicit args: default discovery under testpaths → prefer domain packs.
        return True

    for target in targets:
        if target.is_dir():
            # Collecting tests/ (or any parent tree) already picks up domain packs.
            return True
        if target.name in _TEAM_WORKFLOW_DOMAIN_PACKS:
            return True
        # Explicit aggregate path (alone or with non-domain files) keeps compatibility.
    return False


# Storage bootstrap modules resolve checkout-owned mutable state (runtime
# manager events, legacy .runtime trees) from ambient environment variables.
# Import-time evaluation happens after test fixtures may have monkeypatched
# those variables, so files importing them must ride the runtime-manager
# isolation stack or storage_migration step/readiness events can append into
# the real checkout's `.runtime` tree or the operator projects home.
_RUNTIME_MODULE_PREFIXES = (
    "core.web",
    "core.runtime_manager",
    "core.ui.chat_state",
    "core.infrastructure.storage_migration",
    "vibelution_storage",
)

_SINGLETON_ONLY_MODULE_PREFIXES = (
    "config.settings",
    "core.infrastructure.state",
    "core.infrastructure.agent_session",
    "core.infrastructure.event_bus",
    "core.infrastructure.tool_executor",
    "core.infrastructure.git_memory",
    "core.orchestration.task_planner",
    "core.prompt_manager",
)

_TRANSITIVE_TEST_MODULE_PREFIXES = (
    "tests._support.team_workflow",
    "tests.test_agent_config_workspace_service",
)


def _collect_import_modules(path: Path) -> frozenset[str] | None:
    """Return imported module names from a test file, or None when parsing fails."""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return None

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
    return frozenset(modules)


def _module_matches_prefix(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def _modules_need_runtime_manager_isolation(modules: frozenset[str]) -> bool:
    for module in modules:
        if _module_matches_prefix(module, _RUNTIME_MODULE_PREFIXES):
            return True
        if module == "core.web.services" or module.startswith("core.web.services."):
            return True
        if _module_matches_prefix(module, _TRANSITIVE_TEST_MODULE_PREFIXES):
            return True
    return False


def _modules_need_singleton_reset(modules: frozenset[str]) -> bool:
    if _modules_need_runtime_manager_isolation(modules):
        return True
    return any(_module_matches_prefix(module, _SINGLETON_ONLY_MODULE_PREFIXES) for module in modules)


@lru_cache(maxsize=512)
def _test_file_needs_runtime_manager_isolation(path_value: str) -> bool:
    """Return whether a test module needs the expensive web/runtime isolation stack."""
    if not path_value:
        return False
    modules = _collect_import_modules(Path(path_value))
    if modules is None:
        return True
    return _modules_need_runtime_manager_isolation(modules)


@lru_cache(maxsize=512)
def _test_file_needs_singleton_reset(path_value: str) -> bool:
    """Return whether a test module touches singleton-heavy runtime modules."""
    if not path_value:
        return False
    modules = _collect_import_modules(Path(path_value))
    if modules is None:
        return True
    return _modules_need_singleton_reset(modules)


def _reset_agent_directory_caches(agent_directory_service):
    invalidate_repaired = getattr(agent_directory_service, "_invalidate_repaired_state_cache", None)
    if callable(invalidate_repaired):
        invalidate_repaired()
    cache_lock = getattr(agent_directory_service, "_AGENT_API_HYDRATION_CACHE_LOCK", None)
    if cache_lock is not None:
        with cache_lock:
            agent_directory_service._AGENT_API_HYDRATION_CACHE_SIGNATURE = None
            agent_directory_service._AGENT_API_HYDRATION_CACHE = None
    recent_cache = getattr(agent_directory_service, "_JSONL_RECENT_CACHE", None)
    if isinstance(recent_cache, dict):
        recent_cache.clear()
    count_cache = getattr(agent_directory_service, "_JSONL_COUNT_CACHE", None)
    if isinstance(count_cache, dict):
        count_cache.clear()


# ============================================================================
# 单例重置 — 最关键的熵增防护机制
# ============================================================================

@pytest.fixture(autouse=True)
def reset_singletons(request):
    """
    每个测试前后重置所有模块级单例变量，防止测试间状态泄漏。

    覆盖：
    - StateManager (state.py)
    - EventBus (event_bus.py)
    - TaskManager (task_planner.py)
    - ToolExecutor (tool_executor.py)
    - PromptManager (prompt_manager.py)
    """
    path_value = str(getattr(request.node, "path", "") or getattr(request.node, "fspath", "") or "")
    if not _test_file_needs_singleton_reset(path_value):
        yield
        return

    # 保存并重置 state.py 单例
    import core.infrastructure.state as _state_mod
    _orig_state = _state_mod._state_manager
    _state_mod._state_manager = None

    # 保存并重置 config.settings 单例
    import config.settings as _settings_mod
    _orig_settings = _settings_mod._settings
    _orig_config_path = _settings_mod._config_path
    _settings_mod._settings = None
    _settings_mod._config_path = None

    # 保存并重置 agent_session.py 单例
    import core.infrastructure.agent_session as _session_mod
    _orig_session = _session_mod._agent_session
    _session_mod._agent_session = None

    # 保存并重置 event_bus.py 单例
    import core.infrastructure.event_bus as _eb_mod
    _orig_bus = _eb_mod._event_bus
    _eb_mod._event_bus = None

    # 保存并重置 task_planner.py 单例
    try:
        import core.orchestration.task_planner as _tp_mod
        _orig_tp = _tp_mod._task_manager_instance
        _tp_mod._task_manager_instance = None
        _orig_tp_root = _tp_mod._task_manager_root
        _tp_mod._task_manager_root = None
    except ImportError:
        pass

    # 保存并重置 tool_executor.py 单例
    try:
        import core.infrastructure.tool_executor as _te_mod
        _orig_te = _te_mod._tool_executor
        _te_mod._tool_executor = None
    except ImportError:
        pass

    # 保存并重置 prompt_manager.py 单例
    try:
        import core.prompt_manager.prompt_manager as _pm_mod
        _orig_pm = _pm_mod._prompt_manager
        _pm_mod._prompt_manager = None
    except ImportError:
        pass

    # 保存并重置 git_memory.py 单例
    try:
        import core.infrastructure.git_memory as _gm_mod
        _orig_gm = _gm_mod._git_memory_service
        _gm_mod._git_memory_service = None
    except ImportError:
        pass

    yield

    # 测试后恢复原始单例（或保持 None）
    _state_mod._state_manager = _orig_state
    _settings_mod._settings = _orig_settings
    _settings_mod._config_path = _orig_config_path
    _session_mod._agent_session = _orig_session
    _eb_mod._event_bus = _orig_bus
    try:
        _tp_mod._task_manager_instance = _orig_tp
        _tp_mod._task_manager_root = _orig_tp_root
    except (NameError, AttributeError):
        pass
    try:
        _te_mod._tool_executor = _orig_te
    except (NameError, AttributeError):
        pass
    try:
        _pm_mod._prompt_manager = _orig_pm
    except (NameError, AttributeError):
        pass
    try:
        _gm_mod._git_memory_service = _orig_gm
    except (NameError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def isolate_team_workflow_review_llm(monkeypatch):
    """Team-workflow review runners must never resolve a real model in tests.

    ``llm_review_runners`` wires the operator-configured LLM into digest
    drafting and the hypothesis review chain.  Tests must stay on the
    deterministic DEV fixtures even when the host machine carries real
    provider credentials, so resolution is pinned to ``None``; tests that
    exercise the real path inject their own fake ``llm`` mapping.
    """
    try:
        from core.web.services.team_workflow import llm_review_runners
    except Exception:
        return

    monkeypatch.setattr(llm_review_runners, "resolve_review_llm", lambda: None)


@pytest.fixture(autouse=True)
def isolate_team_workflow_literature_contrast(monkeypatch):
    """Hypothesis review must never hit real literature providers in tests.

    The executor's pre-review literature contrast retrieval is a real HTTP
    side effect (shared rate-limited arXiv/OpenAlex transport).  Tests pin it
    to a ``None`` stub — the executor treats that as "no contrast available"
    and keeps byte-identical candidate shapes.  Tests that exercise the
    contrast path inject their own fake retriever via ``monkeypatch``.
    """
    try:
        from core.web.services.team_workflow import literature_contrast
    except Exception:
        return

    monkeypatch.setattr(
        literature_contrast, "retrieve_literature_contrast", lambda *a, **k: None
    )


@pytest.fixture(autouse=True)
def isolate_runtime_manager_evolution_store(tmp_path, monkeypatch, request):
    """Keep manager-owned evolution snapshots out of the real .runtime tree."""
    path_value = str(getattr(request.node, "path", "") or getattr(request.node, "fspath", "") or "")
    if not _test_file_needs_runtime_manager_isolation(path_value):
        yield
        return

    from core.runtime_manager import evolution_store
    from core.runtime_manager import work_run_store
    from core.runtime_manager import scene_logging as scene_logging_module
    from core.infrastructure import developer_sandbox
    from core.infrastructure import storage_migration as storage_migration_module
    from core.web.services import runtime_scene_service
    from core.web.services import agent_directory_service
    from core.web.services import agent_mode_binding_service
    from core.web.services import prompt_template_service
    from core.web.services import supervised_agent_service
    from core.web.services import team_service
    from core.web.services import chat_room_service
    try:
        from core.web.services import session_service
    except Exception:
        session_service = None

    runtime_manager_dir = tmp_path / ".runtime" / "runtime-manager"
    evolution_dir = runtime_manager_dir / "evolution"
    self_runs_dir = evolution_dir / "self" / "runs"
    supervised_runs_dir = evolution_dir / "supervised" / "runs"
    work_runs_dir = runtime_manager_dir / "work_runs"
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"

    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: tmp_path / "workspace")
    monkeypatch.setattr(evolution_store, "EVOLUTION_DIR", evolution_dir)
    monkeypatch.setattr(evolution_store, "SELF_RUNS_DIR", self_runs_dir)
    monkeypatch.setattr(evolution_store, "SUPERVISED_RUNS_DIR", supervised_runs_dir)
    monkeypatch.setattr(evolution_store, "SELF_INDEX_PATH", evolution_dir / "self" / "index.json")
    monkeypatch.setattr(evolution_store, "SUPERVISED_INDEX_PATH", evolution_dir / "supervised" / "index.json")
    monkeypatch.setattr(evolution_store, "_WORK_RUN_STORE", work_run_store.WorkRunStore(root=evolution_dir))
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_dir)
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    # Runtime-manager file events must never reach the real checkout or the
    # operator projects home: `EVENTS_PATH` is a module constant evaluated at
    # (possibly lazy, environment-sensitive) import time, so pin it to tmp_path
    # together with its directory bootstrap.
    runtime_manager_events_path = runtime_manager_dir / "events.jsonl"
    monkeypatch.setattr(scene_logging_module, "EVENTS_PATH", runtime_manager_events_path)
    monkeypatch.setattr(
        scene_logging_module,
        "ensure_runtime_manager_dirs",
        lambda: runtime_manager_events_path.parent.mkdir(parents=True, exist_ok=True),
    )
    # The readiness-blocked flood suppressor keeps per-signature timestamps in
    # module state; without a reset an earlier test's signature silently drops
    # later tests' readiness_blocked events within the 300s window.
    storage_migration_module._readiness_blocked_log_state.clear()
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _reset_agent_directory_caches(agent_directory_service)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_agent_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    previous_chat_room_executor = chat_room_service._CHAT_ROOM_EXECUTOR
    isolated_chat_room_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pytest-chat-room")
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", isolated_chat_room_executor)
    with chat_room_service._CHAT_ROOM_ROUND_CONTROLS_LOCK:
        chat_room_service._CHAT_ROOM_ROUND_CONTROLS.clear()
    with chat_room_service._CHAT_ROOM_STREAM_SUBSCRIBERS_LOCK:
        chat_room_service._CHAT_ROOM_STREAM_SUBSCRIBERS.clear()
    if session_service is not None:
        previous_executor = session_service._SESSION_EXECUTOR
        isolated_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pytest-web-chat-turn")
        monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", isolated_executor)
        monkeypatch.setattr(session_service, "_WORK_RUN_STORE", work_run_store.WorkRunStore(root=work_runs_dir))
        monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
        with session_service._RUNNING_SESSIONS_LOCK:
            session_service._RUNNING_SESSION_IDS.clear()
            session_service._SESSION_ACTIVE_TURN_IDS.clear()
            session_service._SESSION_ACTIVE_TURN_LEASES.clear()
        if hasattr(session_service, "_SESSION_TURN_SCHEDULER"):
            session_service._SESSION_TURN_SCHEDULER.clear()
        else:
            with session_service._SESSION_AGENT_SCHEDULER_LOCK:
                session_service._SESSION_AGENT_ACTIVE_TURN_IDS.clear()
                session_service._SESSION_AGENT_QUEUES.clear()
        with session_service._SESSION_TURN_CONTROLS_LOCK:
            session_service._SESSION_TURN_CONTROLS.clear()
        yield
        with chat_room_service._CHAT_ROOM_ROUND_CONTROLS_LOCK:
            chat_room_service._CHAT_ROOM_ROUND_CONTROLS.clear()
        with chat_room_service._CHAT_ROOM_STREAM_SUBSCRIBERS_LOCK:
            chat_room_service._CHAT_ROOM_STREAM_SUBSCRIBERS.clear()
        isolated_chat_room_executor.shutdown(wait=True, cancel_futures=True)
        monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", previous_chat_room_executor)
        isolated_executor.shutdown(wait=True, cancel_futures=True)
        monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", previous_executor)
        with session_service._RUNNING_SESSIONS_LOCK:
            session_service._RUNNING_SESSION_IDS.clear()
            session_service._SESSION_ACTIVE_TURN_IDS.clear()
            session_service._SESSION_ACTIVE_TURN_LEASES.clear()
        if hasattr(session_service, "_SESSION_TURN_SCHEDULER"):
            session_service._SESSION_TURN_SCHEDULER.clear()
        else:
            with session_service._SESSION_AGENT_SCHEDULER_LOCK:
                session_service._SESSION_AGENT_ACTIVE_TURN_IDS.clear()
                session_service._SESSION_AGENT_QUEUES.clear()
        with session_service._SESSION_TURN_CONTROLS_LOCK:
            session_service._SESSION_TURN_CONTROLS.clear()
        _reset_agent_directory_caches(agent_directory_service)
    else:
        try:
            yield
        finally:
            with chat_room_service._CHAT_ROOM_ROUND_CONTROLS_LOCK:
                chat_room_service._CHAT_ROOM_ROUND_CONTROLS.clear()
            with chat_room_service._CHAT_ROOM_STREAM_SUBSCRIBERS_LOCK:
                chat_room_service._CHAT_ROOM_STREAM_SUBSCRIBERS.clear()
            isolated_chat_room_executor.shutdown(wait=True, cancel_futures=True)
            monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", previous_chat_room_executor)
            _reset_agent_directory_caches(agent_directory_service)


# ============================================================================
# 隔离工作空间
# ============================================================================

@pytest.fixture
def isolated_workspace(tmp_path):
    """
    提供隔离的 workspace 目录结构，确保测试不触碰真实 workspace/。

    目录结构：
        tmp_path/
        └── workspace/
            ├── memory/
            │   └── archives/
            └── prompts/
    """
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "memory").mkdir()
    (ws / "memory" / "archives").mkdir()
    (ws / "prompts").mkdir()
    return ws


# ============================================================================
# 可复用 Mock 对象
# ============================================================================

@pytest.fixture
def mock_llm_response():
    """返回可自定义的 mock LLM 响应。"""
    from unittest.mock import MagicMock
    resp = MagicMock()
    resp.content = "This is a test response."
    resp.tool_calls = []
    resp.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
    return resp


@pytest.fixture
def project_root():
    """返回项目根目录（Path 对象）。"""
    return PROJECT_ROOT


# ============================================================================
# 自动标记 — 根据文件路径自动应用 pytest markers
# ============================================================================

def drop_team_workflow_aggregate_duplicates(items) -> None:
    """Prefer domain packs over the aggregate re-export when both are collected."""
    has_domain_pack = any(
        any(pack in item.nodeid.replace("\\", "/") for pack in _TEAM_WORKFLOW_DOMAIN_PACKS)
        for item in items
    )
    if not has_domain_pack:
        return
    items[:] = [
        item
        for item in items
        if _TEAM_WORKFLOW_AGGREGATE not in item.nodeid.replace("\\", "/")
    ]


def pytest_collection_modifyitems(items):
    """
    根据测试文件路径自动应用 markers，无需在每个文件手动加装饰器。

    标记规则：
    - tests/test_xxx.py (tools/)  → tools
    - tests/test_xxx.py (core/infrastructure/) → infrastructure
    - tests/test_xxx.py (core/orchestration/)  → orchestration
    - tests/test_xxx.py (config/)  → config

    Also drop the team-workflow aggregate re-export when any domain pack is
    present so full-suite / multi-path collection never double-runs cases.
    """
    from pathlib import Path

    drop_team_workflow_aggregate_duplicates(items)

    source_cache: dict[Path, str] = {}

    for item in items:
        fspath = Path(str(item.fspath))
        rel = fspath.relative_to(PROJECT_ROOT).as_posix()
        item_path = str(item.fspath)

        # Source-based markers (inferred from test file name)
        stem = fspath.stem  # e.g., "test_shell_tools" → "shell_tools"

        # Heuristic: check what the test file imports to determine layer
        source = source_cache.get(fspath)
        if source is None:
            source = fspath.read_text(encoding="utf-8")[:2000]
            source_cache[fspath] = source
        if "core.infrastructure" in source or "core/infrastructure" in source:
            item.add_marker(pytest.mark.infrastructure)
        elif "core.orchestration" in source or "core/orchestration" in source:
            item.add_marker(pytest.mark.orchestration)
        elif "config" in stem and "tools" not in stem:
            item.add_marker(pytest.mark.config)
        elif "tools." in source or "from tools" in source or "import tools" in source:
            item.add_marker(pytest.mark.tools)
