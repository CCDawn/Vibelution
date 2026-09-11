"""Agent 文件工具的路径边界：显式绝对路径不再一律放行。

历史行为：`_is_path_allowed` 对任意绝对路径直接返回 True（注释称是为了不改变
受控测试/临时目录行为），`create_file` 又对绝对输入跳过 PathSandbox，于是
`write_file_tool` 可以覆盖任意系统路径；`edit_file` 完全没有包含性检查。
现在边界是显式的：项目 / 工作区 / 本项目存储根 / 临时根 / operator 显式配置的
`security.allowed_directories`，外加 danger_full_access 逃生口。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import shell_tools as shell_tools_module
from tools.shell_tools import create_file, edit_file, list_directory, read_file


def _outside_dir() -> Path:
    """一个确定不在任何允许根内的目录（不落在 tmp / 项目 / 用户存储里）。"""
    drive = os.environ.get("SystemDrive") or "C:"
    return Path(f"{drive}{os.sep}") / "vibelution-boundary-probe"


@pytest.fixture()
def outside_file() -> Path:
    root = _outside_dir()
    path = root / "probe.txt"
    root.mkdir(parents=True, exist_ok=True)
    path.write_text("sensitive-content", encoding="utf-8")
    try:
        yield path
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_create_file_refuses_absolute_path_outside_allowed_roots(outside_file: Path):
    result = create_file(file_path=str(outside_file), content="owned")

    assert "[SECURITY]" in result
    assert outside_file.read_text(encoding="utf-8") == "sensitive-content"


def test_create_file_refuses_new_file_outside_allowed_roots():
    target = _outside_dir() / "created-by-tool.txt"
    try:
        result = create_file(file_path=str(target), content="owned")

        assert "[SECURITY]" in result
        assert not target.exists()
    finally:
        shutil.rmtree(_outside_dir(), ignore_errors=True)


def test_edit_file_refuses_absolute_path_outside_allowed_roots(outside_file: Path):
    result = edit_file(
        file_path=str(outside_file),
        search_string="sensitive-content",
        replace_string="owned",
    )

    assert "[SECURITY]" in result
    assert outside_file.read_text(encoding="utf-8") == "sensitive-content"


def test_read_file_refuses_absolute_path_outside_allowed_roots(outside_file: Path):
    result = read_file(file_path=str(outside_file))

    assert "错误" in result
    assert "sensitive-content" not in result


def test_list_directory_refuses_absolute_path_outside_allowed_roots(outside_file: Path):
    payload = json.loads(list_directory(path=str(outside_file.parent)))

    assert payload["status"] == "error"
    assert payload["code"] == "PATH_NOT_ALLOWED"


def test_boundary_message_names_the_extension_knobs(outside_file: Path):
    result = create_file(file_path=str(outside_file), content="owned")

    assert "security.allowed_directories" in result
    assert "danger_full_access" in result


def test_temp_directory_stays_usable():
    temp_root = Path(tempfile.mkdtemp(prefix="vibelution_boundary_"))
    try:
        target = temp_root / "notes.txt"
        result = create_file(file_path=str(target), content="ok")

        assert "[SECURITY]" not in result
        assert target.read_text(encoding="utf-8") == "ok"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_project_relative_write_stays_anchored_and_allowed(monkeypatch, tmp_path: Path):
    fake_root = tmp_path / "project"
    fake_workspace = fake_root / "workspace"
    fake_workspace.mkdir(parents=True)
    monkeypatch.setattr(shell_tools_module, "PROJECT_ROOT", fake_root.resolve())
    monkeypatch.setattr(shell_tools_module, "_get_workspace_root", lambda: fake_workspace.resolve())

    result = create_file(file_path="nested/created.txt", content="ok")

    assert "[SECURITY]" not in result
    assert (fake_workspace / "nested" / "created.txt").read_text(encoding="utf-8") == "ok"


def test_home_directory_is_not_an_allowed_root_by_default():
    """`tools.allowed_directories` 的默认值包含整个用户主目录，不能拿来做边界。"""
    assert shell_tools_module._is_path_allowed(str(Path.home() / "vibelution-probe.txt")) is False


def test_configured_security_allowed_directories_extend_the_boundary(
    monkeypatch, outside_file: Path
):
    import config

    monkeypatch.setattr(
        config,
        "get_config",
        lambda: SimpleNamespace(
            security=SimpleNamespace(allowed_directories=[str(outside_file.parent)])
        ),
    )

    assert shell_tools_module._is_path_allowed(str(outside_file)) is True
    result = create_file(file_path=str(outside_file), content="allowed-now")

    assert "[SECURITY]" not in result
    assert outside_file.read_text(encoding="utf-8") == "allowed-now"


def test_danger_full_access_still_bypasses_the_boundary(monkeypatch, outside_file: Path):
    from core.infrastructure import codex_cli_sandbox

    monkeypatch.setattr(
        codex_cli_sandbox,
        "_current_agent_sandbox_mode",
        lambda: codex_cli_sandbox._DANGER_FULL_ACCESS_SANDBOX_MODE,
    )

    result = create_file(file_path=str(outside_file), content="bypass-ok")

    assert "[SECURITY]" not in result
    assert outside_file.read_text(encoding="utf-8") == "bypass-ok"
