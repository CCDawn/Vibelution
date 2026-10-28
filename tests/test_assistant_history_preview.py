import asyncio
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
from core.assistant_runtime.dispatch import DispatchService
from core.assistant_runtime.history_preview import HistoryPreview
from core.assistant_runtime.migration_io import MigrationIOError
from tests.test_assistant_migration_history import AGENT, source, write_json


@pytest.fixture
def setup_preview(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    root = workspace.parent.resolve()
    write_json(root / ".vibelution/project.json", {"schemaVersion": 1, "projectId": "example-project"})
    config = tmp_path / "operator/config.toml"
    config.parent.mkdir()
    config.write_text("", encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config))
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(config.parent))
    monkeypatch.setenv("VIBELUTION_PROJECTS_HOME", str(tmp_path / "projects"))
    # Production host pins this to its own profile, not the selected project.
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "assistant-profile/data"))
    from vibelution_storage import resolve_active_project_storage_paths
    active_workspace = resolve_active_project_storage_paths(root, config_path=config).data / "workspace"
    shutil.copytree(workspace, active_workspace)
    workspace = active_workspace
    dispatch = DispatchService(tmp_path / "assistant-profile", {})
    dispatch.replace_projects({"schemaVersion": 1, "revision": 1, "projects": {"registered:1": str(root)}})
    clock = [100.0]
    dispatch.history_preview = HistoryPreview(dispatch, config, clock=lambda: clock[0], ttl=30)
    return dispatch, workspace, clock


@pytest.mark.anyio
async def test_model_action_previews_real_registered_project_without_content_or_paths(setup_preview):
    dispatch, workspace, _ = setup_preview
    before = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        result = await asyncio.to_thread(execute_action, "history_source_preview", {"project_id": "registered:1"})
        assert result["projectId"] == "registered:1"
        assert result["sourceProjectId"] == "example-project"
        assert result["assistantAgentId"] == AGENT
        assert result["authorized"] is False and result["readyForCutover"] is False
        assert "PRIVATE_PROMPT" not in json.dumps(result)
        assert str(workspace) not in json.dumps(result)
        assert dispatch.history_preview.verify_preview(result["previewId"]) == result
        assert before == {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    finally:
        unbind_actions(dispatch)


@pytest.mark.parametrize("change", ["expiry", "revoke", "suspend", "registry", "config", "revision", "workspace"])
def test_preview_refuses_stale_authority(setup_preview, change):
    dispatch, workspace, clock = setup_preview
    result = dispatch.history_preview.preview("registered:1")
    if change == "expiry":
        clock[0] += 30
    elif change == "revoke":
        dispatch.replace_projects({"schemaVersion": 1, "revision": 2, "projects": {}})
    elif change == "suspend":
        dispatch.suspend_projects()
    elif change == "registry":
        registry = workspace / "agents/agents.json"
        registry.write_text(registry.read_text(encoding="utf-8") + " ", encoding="utf-8")
    elif change == "config":
        dispatch.history_preview._config.write_text("# changed\n", encoding="utf-8")
    elif change == "revision":
        root = dispatch._admitted_projects()["registered:1"]
        dispatch.replace_projects({"schemaVersion": 1, "revision": 2, "projects": {"registered:1": str(root)}})
    else:
        workspace.rename(workspace.with_name("old-workspace"))
        workspace.mkdir()
    with pytest.raises(MigrationIOError, match="history_preview_(expired|changed)"):
        dispatch.history_preview.verify_preview(result["previewId"])


def test_multiple_old_assistants_never_auto_select(setup_preview):
    dispatch, workspace, _ = setup_preview
    registry = workspace / "agents/agents.json"
    data = json.loads(registry.read_text(encoding="utf-8"))
    second = dict(data["agents"][0], agentId="another-pa", directSessionId="other-direct")
    data["agents"].append(second)
    registry.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MigrationIOError, match="history_source_ambiguous"):
        dispatch.history_preview.preview("registered:1")


def test_one_turn_preview_allows_each_migration_purpose_once(setup_preview):
    dispatch, _, _ = setup_preview
    preview = dispatch.history_preview
    token = preview.preview("registered:1", turn_id="turn-1")["previewId"]
    for purpose in ("history", "personal", "knowledge"):
        assert preview.consume_for_import(token, "registered:1", 1, "turn-1", purpose=purpose)[3] == AGENT
        with pytest.raises(MigrationIOError):
            preview.consume_for_import(token, "registered:1", 1, "turn-1", purpose=purpose)


@pytest.mark.parametrize("change", ["turn", "revision", "registry", "stop", "expiry", "exclusive"])
def test_reused_preview_revalidates_authority_and_remains_turn_bound(setup_preview, change):
    dispatch, workspace, clock = setup_preview
    preview = dispatch.history_preview
    token = preview.preview("registered:1", turn_id="turn-1")["previewId"]
    preview.consume_for_import(token, "registered:1", 1, "turn-1", purpose="history")
    turn, revision = "turn-1", 1
    if change == "turn":
        turn = "turn-2"
    elif change == "revision":
        revision = 2
    elif change == "registry":
        registry = workspace / "agents/agents.json"
        registry.write_text(registry.read_text(encoding="utf-8") + " ", encoding="utf-8")
    elif change == "stop":
        preview.stop_turn(turn)
    elif change == "expiry":
        clock[0] += 30
    with pytest.raises(MigrationIOError):
        if change == "exclusive":
            preview.consume_for_import(token, "registered:1", revision, turn)
        else:
            preview.consume_for_import(token, "registered:1", revision, turn, purpose="personal")


def test_exclusive_preview_cannot_be_used_for_migration_afterwards(setup_preview):
    dispatch, _, _ = setup_preview
    preview = dispatch.history_preview
    token = preview.preview("registered:1", turn_id="turn-1")["previewId"]
    preview.consume_for_import(token, "registered:1", 1, "turn-1")
    with pytest.raises(MigrationIOError):
        preview.consume_for_import(token, "registered:1", 1, "turn-1", purpose="personal")


def test_retirement_fences_an_inflight_source_verification(setup_preview):
    dispatch, _, _ = setup_preview
    preview = dispatch.history_preview
    token = preview.preview("registered:1", turn_id="turn-1")["previewId"]
    reached, resume = threading.Event(), threading.Event()
    row = list(preview._previews[token])
    verify = row[1]
    def paused_verify():
        reached.set()
        assert resume.wait(5)
        verify()
    row[1] = paused_verify
    preview._previews[token] = tuple(row)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(preview.consume_for_import, token, "registered:1", 1, "turn-1", purpose="personal")
        assert reached.wait(5)
        try:
            preview.retire(token)
        finally:
            resume.set()
        with pytest.raises(MigrationIOError, match="history_preview_changed"):
            future.result(timeout=5)


def test_retirement_revokes_already_issued_source_guard_after_all_purposes(setup_preview):
    dispatch, _, _ = setup_preview
    preview = dispatch.history_preview
    token = preview.preview("registered:1", turn_id="turn-1")["previewId"]
    for purpose in ("history", "personal", "knowledge"):
        binding = preview.consume_for_import(token, "registered:1", 1, "turn-1", purpose=purpose)
    preview.retire(token)
    with pytest.raises(ValueError, match="preview retired"):
        binding[4]()


@pytest.mark.parametrize("mode", ["exclusive", "removed", "expired"])
def test_new_preview_cannot_orphan_inflight_retirement_guard(setup_preview, mode):
    dispatch, _, clock = setup_preview
    preview = dispatch.history_preview
    token = preview.preview("registered:1", turn_id="turn-1")["previewId"]
    if mode == "exclusive":
        binding = preview.consume_for_import(token, "registered:1", 1, "turn-1")
    else:
        binding = preview.consume_for_import(token, "registered:1", 1, "turn-1", purpose="history")
        if mode == "removed":
            with pytest.raises(MigrationIOError):
                preview.consume_for_import(token, "registered:1", 1, "wrong-turn", purpose="personal")
        else:
            clock[0] += 30
    reached, resume = threading.Event(), threading.Event()
    def worker():
        reached.set()
        assert resume.wait(5)
        binding[4]()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        assert reached.wait(5)
        try:
            preview.preview("registered:1", turn_id="turn-1")
            preview.retire(token)
        finally:
            resume.set()
        with pytest.raises(ValueError, match="preview retired"):
            future.result(timeout=5)


def test_legacy_project_ignores_assistant_host_data_home(tmp_path, monkeypatch):
    original = source(tmp_path)
    root = original.parent.resolve()
    write_json(root / ".vibelution/project.json", {"schemaVersion": 1, "projectId": "example-project"})
    (root / ".git").mkdir()
    (root / ".runtime").mkdir()
    (root / ".runtime/legacy-state").write_text("legacy", encoding="utf-8")
    config = tmp_path / "operator/config.toml"
    config.parent.mkdir()
    config.write_text("", encoding="utf-8")
    user_root = tmp_path / "user"
    legacy = user_root / "Documents/Vibelution/data/workspace"
    host = tmp_path / "assistant-profile/data/workspace"
    shutil.copytree(original, legacy)
    shutil.copytree(original, host)
    registry = host / "agents/agents.json"
    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["agents"][0]["agentId"] = "host-assistant"
    registry.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(user_root))
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(host.parent))
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config))
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(config.parent))
    monkeypatch.setenv("VIBELUTION_PROJECTS_HOME", str(tmp_path / "projects"))
    dispatch = DispatchService(tmp_path / "assistant-profile", {})
    dispatch.replace_projects({"schemaVersion": 1, "revision": 1, "projects": {"registered:1": str(root)}})
    preview = HistoryPreview(dispatch, config)
    result = preview.preview("registered:1")
    assert result["assistantAgentId"] == AGENT
    assert preview.verify_preview(result["previewId"]) == result
    legacy.rename(legacy.with_name("removed-workspace"))
    with pytest.raises(MigrationIOError):
        preview.verify_preview(result["previewId"])
    with pytest.raises(MigrationIOError):
        preview.preview("registered:1")
    legacy.with_name("removed-workspace").rename(legacy)
    config.write_text(f'[storage]\ndata_home = "{host.parent.as_posix()}"\n', encoding="utf-8")
    with pytest.raises(MigrationIOError, match="history_source_unavailable"):
        preview.preview("registered:1")
