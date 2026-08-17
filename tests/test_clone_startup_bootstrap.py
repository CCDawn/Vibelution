"""Clone-startup bootstrap: launcher/storage/agent must boot without a pre-existing venv."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.infrastructure.boot_pipeline import project_venv_python, run_preflight_doctor


PROJECT_ROOT = Path(__file__).resolve().parents[1]


_BLOCK_PYDANTIC = """
import importlib.util
import sys

class _BlockPydantic:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "pydantic" or fullname.startswith("pydantic."):
            raise ImportError("pydantic must not be imported during clone bootstrap")
        return None

sys.meta_path.insert(0, _BlockPydantic())
sys.path.insert(0, {project_root!r})
"""


def _run_isolated(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        check=False,
    )


def test_storage_resolve_does_not_import_pydantic(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    (project / ".git").mkdir()
    identity = project / ".vibelution" / "project.json"
    identity.parent.mkdir()
    identity.write_text('{"schemaVersion": 1, "projectId": "clone-startup-test"}\n', encoding="utf-8")
    code = _BLOCK_PYDANTIC.format(project_root=str(PROJECT_ROOT)) + f"""
from vibelution_storage import resolve_active_project_storage_paths
paths = resolve_active_project_storage_paths({str(project)!r})
print(paths.logs)
"""
    result = _run_isolated(code)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "logs" in result.stdout


def test_python_launcher_module_imports_without_pydantic():
    launcher_path = PROJECT_ROOT / "scripts" / "vibelution_launcher.py"
    code = _BLOCK_PYDANTIC.format(project_root=str(PROJECT_ROOT)) + f"""
spec = importlib.util.spec_from_file_location("vibelution_launcher_clone_startup", {str(launcher_path)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print("ok" if callable(getattr(module, "main", None)) else "missing-main")
"""
    result = _run_isolated(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_project_venv_python_is_posix_bin_on_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    assert project_venv_python(tmp_path) == tmp_path / ".venv" / "bin" / "python"


def test_project_venv_python_is_windows_scripts_on_win32(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    assert project_venv_python(tmp_path) == tmp_path / ".venv" / "Scripts" / "python.exe"


def test_preflight_doctor_posix_accepts_venv_without_powershell(monkeypatch, tmp_path):
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "executable", str(venv_python))
    subprocess_run = MagicMock(side_effect=AssertionError("powershell doctor must not run on POSIX"))
    monkeypatch.setattr("core.infrastructure.boot_pipeline.subprocess.run", subprocess_run)
    config = SimpleNamespace(runtime=SimpleNamespace(preflight_doctor=True, require_venv=True))

    run_preflight_doctor(config, project_root=tmp_path)
    subprocess_run.assert_not_called()


def test_preflight_doctor_posix_mismatch_names_bin_python(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "system-python"))
    config = SimpleNamespace(runtime=SimpleNamespace(preflight_doctor=True, require_venv=True))

    with pytest.raises(RuntimeError, match=r"\.venv/bin/python"):
        run_preflight_doctor(config, project_root=tmp_path)
