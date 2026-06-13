import subprocess

from core.web.services import cli_agent_service as service


def _configure_roots(monkeypatch, tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(service, "CLI_AGENT_REGISTRY_PATH", project_root / "workspace" / "cli_agents" / "cli_agents.json")
    monkeypatch.setattr(service, "RUN_RECORD_DIR", project_root / "workspace" / "cli_agents" / "runs")
    monkeypatch.setattr(service, "record_runtime_scene_event", lambda *args, **kwargs: {"accepted": False})
    return project_root


def test_codex_readonly_uses_exec_with_readonly_sandbox(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    calls = []

    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\codex.exe" if candidate == "codex.exe" else "")

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"type":"message"}\n', stderr="")

    monkeypatch.setattr(service.subprocess, "run", fake_run)

    result = service.run_cli_agent(
        agent_type="codex_code",
        task="Inspect the repository without changing files.",
        cwd=str(project_root),
        mode="readonly",
        timeout=15,
    )

    assert result["status"] == "ok"
    args, kwargs = calls[0]
    assert args[:2] == [r"C:\tools\codex.exe", "exec"]
    assert "--cd" in args
    assert str(project_root) in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[args.index("--ask-for-approval") + 1] == "never"
    assert "--json" in args
    assert args[-1] == "Inspect the repository without changing files."
    assert result["commandPreview"][-1].startswith("<task:")
    assert result["commandPreview"][-1] != args[-1]
    assert kwargs["cwd"] == str(project_root)
    assert kwargs["timeout"] == 15
    assert (service.RUN_RECORD_DIR / f"{result['runId']}.json").exists()


def test_mimo_worktree_mode_requires_sibling_worktree(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else "")

    result = service.run_cli_agent(
        agent_type="mimo_code",
        task="Make a change.",
        cwd=str(project_root),
        mode="worktree",
    )

    assert result["status"] == "error"
    assert result["code"] == "WORKTREE_REQUIRED"


def test_mimo_worktree_mode_builds_dir_and_agent_args(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    worktree = project_root.parent / "Vibelution-worktrees" / "cli-agent-demo"
    worktree.mkdir(parents=True)
    calls = []

    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else "")

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"status":"ok"}\n', stderr="")

    monkeypatch.setattr(service.subprocess, "run", fake_run)

    result = service.run_cli_agent(
        agent_type="mimo_code",
        task="Implement in this worktree.",
        cwd=str(worktree),
        mode="worktree",
        model="mimo-model",
        agent="build",
        allow_unsafe_permissions=True,
    )

    assert result["status"] == "ok"
    args, _kwargs = calls[0]
    assert args[:2] == [r"C:\tools\mimo.cmd", "run"]
    assert args[args.index("--dir") + 1] == str(worktree)
    assert args[args.index("--model") + 1] == "mimo-model"
    assert args[args.index("--agent") + 1] == "build"
    assert "--dangerously-skip-permissions" in args
    assert args[-1] == "Implement in this worktree."


def test_missing_cli_agent_executable_returns_error(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: "")

    result = service.run_cli_agent(
        agent_type="codex_code",
        task="Inspect only.",
        cwd=str(project_root),
    )

    assert result["status"] == "error"
    assert result["code"] == "CLI_AGENT_NOT_FOUND"
    assert result["executableCandidates"] == ["codex.exe", "codex"]


def test_windows_subprocess_kwargs_hide_console(monkeypatch):
    class StartupInfo:
        def __init__(self):
            self.dwFlags = 0
            self.wShowWindow = 0

    monkeypatch.setattr(service.os, "name", "nt", raising=False)
    monkeypatch.setattr(service.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(service.subprocess, "STARTUPINFO", StartupInfo, raising=False)
    monkeypatch.setattr(service.subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(service.subprocess, "SW_HIDE", 0, raising=False)

    kwargs = service._subprocess_no_window_kwargs()

    assert kwargs["creationflags"] & 0x08000000
    assert kwargs["startupinfo"].dwFlags & 1


def test_list_cli_agent_adapters_reports_availability(monkeypatch, tmp_path):
    _configure_roots(monkeypatch, tmp_path)

    def fake_which(candidate):
        return r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else ""

    monkeypatch.setattr(service.shutil, "which", fake_which)

    adapters = {item["id"]: item for item in service.list_cli_agent_adapters()}

    assert adapters["mimo_code"]["available"] is True
    assert adapters["codex_code"]["available"] is False
