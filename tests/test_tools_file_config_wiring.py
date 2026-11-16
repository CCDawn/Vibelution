"""tools.file.* must drive the file write/edit tools."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import tools.shell_tools as shell_tools


def _cfg(*, edit_enabled: bool = True, create_enabled: bool = True,
         encoding_priority: list[str] | None = None):
    return SimpleNamespace(
        tools=SimpleNamespace(
            file=SimpleNamespace(
                edit_enabled=edit_enabled,
                create_enabled=create_enabled,
                syntax_check_enabled=True,
                encoding_priority=encoding_priority or ["utf-8", "gbk"],
            )
        )
    )


def test_policy_reads_config(monkeypatch):
    import config

    monkeypatch.setattr(
        config, "get_config",
        lambda: _cfg(edit_enabled=False, create_enabled=False, encoding_priority=["gbk"]),
    )
    policy = shell_tools._file_tool_policy()
    assert policy["edit_enabled"] is False
    assert policy["create_enabled"] is False
    assert policy["encoding_priority"] == ["gbk"]


def test_policy_falls_back_when_config_breaks(monkeypatch):
    import config

    def _boom():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(config, "get_config", _boom)
    policy = shell_tools._file_tool_policy()
    assert policy["edit_enabled"] is True
    assert policy["create_enabled"] is True
    assert policy["encoding_priority"] == list(shell_tools.DEFAULT_ENCODING_PRIORITY)


def test_create_file_blocked_when_disabled(monkeypatch):
    import config

    monkeypatch.setattr(config, "get_config", lambda: _cfg(create_enabled=False))
    result = shell_tools.create_file("blocked_write.py", "print(1)")
    assert "禁用" in result
    assert "tools.file.create_enabled" in result


def test_edit_file_blocked_when_disabled(monkeypatch):
    import config

    monkeypatch.setattr(config, "get_config", lambda: _cfg(edit_enabled=False))
    result = shell_tools.edit_file("any.py", "old", "new")
    assert "禁用" in result
    assert "tools.file.edit_enabled" in result


def test_detect_encoding_follows_configured_priority(monkeypatch, tmp_path):
    import config

    path = Path(tmp_path) / "gbk.txt"
    path.write_bytes("中文内容".encode("gbk"))
    monkeypatch.setattr(
        config, "get_config", lambda: _cfg(encoding_priority=["gbk", "utf-8"])
    )
    assert shell_tools._detect_encoding(path) == "gbk"
