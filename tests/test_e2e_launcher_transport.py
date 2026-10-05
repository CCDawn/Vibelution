"""E2E 生命周期通道边界：保留 native、拒绝误操作、不重试或关闭共享壳。"""

import os
from contextlib import contextmanager
from subprocess import CompletedProcess, TimeoutExpired
from types import SimpleNamespace

import pytest

from tests.e2e.helpers import launcher, launcher_ipc


def test_native_e2e_deadline_outlives_product_startup_envelope():
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "scripts/windows_launcher_entry/VibelutionLauncher.cs").read_text(encoding="utf-8")
    budget = re.search(r"bridgeTimeoutMs\s*=\s*startup\s*\?\s*(\d+)", source)
    assert budget is not None, "Native Launcher deadline contract moved; review the E2E budget"
    assert launcher.START_TIMEOUT_SECONDS > int(budget.group(1)) / 1000


def test_e2e_fixture_lifecycle_keeps_test_body_watchdog(monkeypatch, pytestconfig):
    import pytest_timeout

    from tests.e2e import conftest

    monkeypatch.setenv("VIBELUTION_E2E", "1")
    markers = []
    item = SimpleNamespace(
        path=conftest.E2E_DIR / "test_team_bootstrap_journeys.py",
        config=pytestconfig,
        get_closest_marker=lambda name: markers[-1].mark if markers else None,
        add_marker=markers.append,
    )
    before = pytest_timeout._get_item_settings(item)
    conftest.pytest_collection_modifyitems([item])
    after = pytest_timeout._get_item_settings(item)
    assert after.func_only is True
    assert after.timeout == before.timeout and after.timeout > 0


@pytest.mark.parametrize("boundary", ["disabled", "explicit-timeout", "outside-e2e"])
def test_e2e_watchdog_hook_preserves_other_timeout_contracts(monkeypatch, boundary):
    from tests.e2e import conftest

    monkeypatch.setenv("VIBELUTION_E2E", "0" if boundary == "disabled" else "1")
    explicit = pytest.mark.timeout(17, func_only=False).mark if boundary == "explicit-timeout" else None
    added = []
    item = SimpleNamespace(
        path=(conftest.E2E_DIR.parent if boundary == "outside-e2e" else conftest.E2E_DIR) / "test_boundary.py",
        get_closest_marker=lambda name: explicit,
        add_marker=added.append,
    )
    conftest.pytest_collection_modifyitems([item])
    assert added == []


def test_default_transport_preserves_native(monkeypatch, tmp_path):
    monkeypatch.delenv("VIBELUTION_E2E_LAUNCHER_TRANSPORT", raising=False)
    monkeypatch.delenv("VIBELUTION_E2E_MODE", raising=False)
    calls = []
    monkeypatch.setattr(launcher, "run_launcher_command", lambda *args, **kwargs: calls.append((args, kwargs)) or CompletedProcess([], 0))
    launcher.start_instance(tmp_path)
    launcher.stop_instance(tmp_path)
    assert calls == [
        ((tmp_path, "start"), {"hidden_presentation": True, "timeout_seconds": 915.0}),
        ((tmp_path, "stop"), {"hidden_presentation": False, "timeout_seconds": 300.0}),
    ]


def test_native_stop_keeps_its_original_bounded_budget(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBELUTION_E2E_LAUNCHER_TRANSPORT", "native")
    executable = tmp_path / "Launcher.exe"
    executable.touch()
    monkeypatch.setattr(launcher, "LAUNCHER_EXE", executable)
    calls = []
    monkeypatch.setattr(launcher.subprocess, "run", lambda *args, **kwargs: calls.append(kwargs) or CompletedProcess([], 0))
    launcher.stop_instance(tmp_path)
    assert calls[0]["timeout"] == 300.0


@pytest.mark.parametrize("transport", ["", "unknown"])
def test_invalid_transport_fails_before_lifecycle(monkeypatch, tmp_path, transport):
    monkeypatch.setenv("VIBELUTION_E2E_LAUNCHER_TRANSPORT", transport)
    monkeypatch.setattr(launcher, "run_launcher_command", lambda *a, **k: pytest.fail("unexpected lifecycle"))
    with pytest.raises(launcher.LauncherCommandError, match="未知"):
        launcher.start_instance(tmp_path)


def test_task_root_rejects_main_other_tree_and_non_task_branch(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher_ipc, "OWNER_ROOT", tmp_path)
    (tmp_path / ".git").mkdir()
    with pytest.raises(launcher.LauncherCommandError, match="worktree"):
        launcher_ipc._task_root(tmp_path)
    (tmp_path / ".git").rmdir()
    (tmp_path / ".git").write_text("gitdir: example")
    with pytest.raises(launcher.LauncherCommandError, match="worktree"):
        launcher_ipc._task_root(tmp_path / "other")
    monkeypatch.setattr(launcher_ipc.subprocess, "run", lambda *a, **k: CompletedProcess([], 0, "main\n"))
    with pytest.raises(launcher.LauncherCommandError, match="codex/"):
        launcher_ipc._task_root(tmp_path)
    monkeypatch.setattr(launcher_ipc.subprocess, "run", lambda *a, **k: CompletedProcess([], 0, "codex/test\n"))
    assert launcher_ipc._task_root(tmp_path) == tmp_path


@pytest.mark.parametrize("urls", [["http://127.0.0.1:8000/launcher"], [launcher_ipc.LAUNCHER_URL] * 2])
def test_launcher_selection_rejects_wrong_or_ambiguous_window(urls):
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[SimpleNamespace(url=url) for url in urls])])
    with pytest.raises(launcher.LauncherCommandError, match="唯一"):
        launcher_ipc._find_launcher_page(browser)


@pytest.mark.parametrize("result", [{"ok": True, "payload": {"accepted": True}}, {"ok": False, "payload": {"accepted": True}}, {"ok": True, "payload": {"accepted": False}}, None])
def test_ipc_calls_once_disconnects_driver_and_never_falls_back(monkeypatch, tmp_path, result):
    sync_api = pytest.importorskip("playwright.sync_api")
    calls = []
    monkeypatch.setenv("VIBELUTION_E2E_LAUNCHER_TRANSPORT", "desktop_ipc")
    monkeypatch.delenv("VIBELUTION_E2E_MODE", raising=False)
    monkeypatch.setattr(launcher_ipc, "_task_root", lambda root: tmp_path)
    monkeypatch.setattr(launcher_ipc, "invoke_instance_command", launcher_ipc._invoke_desktop_command)
    monkeypatch.setattr(launcher_ipc, "discover_desktop_shell", lambda root: {"webSocketDebuggerUrl": "ws://test"})
    monkeypatch.setattr(launcher, "run_launcher_command", lambda *a, **k: pytest.fail("native fallback"))
    page = SimpleNamespace(url=launcher_ipc.LAUNCHER_URL, evaluate=lambda script, args: calls.append(args) or result)
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[page])], close=lambda: pytest.fail("shared browser closed"))

    @contextmanager
    def driver():
        try:
            yield SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=lambda *a, **k: browser))
        finally:
            calls.append("driver disconnected")

    monkeypatch.setattr(sync_api, "sync_playwright", driver)
    if result and result.get("ok") and result["payload"]["accepted"]:
        launcher.start_instance(tmp_path)
    else:
        with pytest.raises(launcher.LauncherCommandError, match="未受理"):
            launcher.start_instance(tmp_path)
    assert calls == [{"command": "start", "instanceId": "worktree:" + str(tmp_path).lower(), "hiddenPresentation": True, "timeoutMs": 30_000}, "driver disconnected"]


@pytest.mark.parametrize("outcome", [CompletedProcess([], 0, "", ""), CompletedProcess([], 1, "", "rejected"), TimeoutExpired([], 130)])
def test_ipc_client_subprocess_is_bounded_hidden_and_not_retried(monkeypatch, tmp_path, outcome):
    calls = []
    monkeypatch.setattr(launcher_ipc, "_task_root", lambda root: tmp_path)

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(launcher_ipc.subprocess, "run", run)
    if isinstance(outcome, Exception) or outcome.returncode:
        with pytest.raises(launcher.LauncherCommandError, match="不重试"):
            launcher_ipc.invoke_instance_command(tmp_path, "start", hidden_presentation=True)
    else:
        launcher_ipc.invoke_instance_command(tmp_path, "start", hidden_presentation=True)
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[1:] == ["-m", "tests.e2e.helpers.launcher_ipc", str(tmp_path), "start", "--hidden-presentation"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["timeout"] == 130
    assert kwargs["creationflags"] == launcher_ipc.CREATION_FLAGS


@pytest.mark.serial
@pytest.mark.skipif(os.environ.get("VIBELUTION_E2E") != "1", reason="真实 JS 引擎验证需要显式启用 E2E")
def test_ipc_javascript_checks_identity_before_invoking():
    sync_api = pytest.importorskip("playwright.sync_api")
    # 用真实 JS 引擎运行同一请求函数；只替换浏览器全局，不触碰任何实例。
    script = """async args => {
      let invoked = 0;
      const location = {href: args.url};
      const window = {vibelutionLauncher: {
        getDesktopShellSummary: async () => {
          if (args.delay) await new Promise(resolve => setTimeout(resolve, args.delay));
          return {currentWindow: {role: args.role}};
        },
        launcherInvoke: async () => { invoked++; return {ok: true, payload: {accepted: true}}; }
      }};
      try { return {result: await (INVOKE)(args.request), invoked}; }
      catch (error) {
        if (args.delay) await new Promise(resolve => setTimeout(resolve, args.delay * 2));
        return {error: error.message, invoked};
      }
    }""".replace("INVOKE", launcher_ipc._INVOKE)
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            request = {"command": "start", "instanceId": "worktree:test", "hiddenPresentation": True, "timeoutMs": 1000}
            for url, role in [("http://wrong", "launcher"), (launcher_ipc.LAUNCHER_URL, "branch-workbench")]:
                output = page.evaluate(script, {"url": url, "role": role, "request": request})
                assert output["invoked"] == 0
                assert "requires" in output["error"]
            output = page.evaluate(script, {"url": launcher_ipc.LAUNCHER_URL, "role": "launcher", "request": request})
            assert output == {"result": {"ok": True, "payload": {"accepted": True}}, "invoked": 1}
            output = page.evaluate(script, {"url": launcher_ipc.LAUNCHER_URL, "role": "launcher", "delay": 20, "request": {**request, "timeoutMs": 1}})
            assert "timed out" in output["error"]
            assert output["invoked"] == 0  # 迟到的身份结果也不能在超时后启动实例。
        finally:
            browser.close()
