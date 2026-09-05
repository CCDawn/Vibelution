import io
import json

import pytest

from core.launcher import desktop_debug


@pytest.fixture
def debug_fixture(tmp_path, monkeypatch):
    owner = {"owner": "electron", "pid": 12, "createTime": 10, "executable": "electron.exe"}
    record = {**owner, "workspaceRoot": str(tmp_path), "httpEndpoint": "http://127.0.0.1:54321",
              "webSocketDebuggerUrl": "ws://127.0.0.1:54321/devtools/browser/current"}
    monkeypatch.setattr(desktop_debug, "resolve_desktop_shell_launch_roots", lambda root: (tmp_path, None))
    monkeypatch.setattr(desktop_debug, "read_desktop_shell_owner", lambda root: owner)
    monkeypatch.setattr(desktop_debug, "_identity_status", lambda value: "match")
    monkeypatch.setattr(desktop_debug, "desktop_shell_owner_path", lambda root: tmp_path / "desktop_shell_owner.json")
    calls = []

    class Opener:
        def open(self, url, timeout):
            calls.append(url)
            payload = {"Browser": "Chrome", "webSocketDebuggerUrl": record["webSocketDebuggerUrl"]} if url.endswith("version") else [{"id": "page1", "type": "page", "url": "http://127.0.0.1:8000"}]
            return io.StringIO(json.dumps(payload))

    monkeypatch.setattr(desktop_debug, "build_opener", lambda *args: Opener())

    def write():
        (tmp_path / "desktop_debug.json").write_text(json.dumps(record))

    write()
    return tmp_path, record, calls, write


def test_discovers_live_shell_from_branch_without_starting_anything(debug_fixture):
    root, record, calls, _ = debug_fixture
    result = desktop_debug.discover_desktop_debug(root / ".worktrees" / "branch")
    assert result["httpEndpoint"] == record["httpEndpoint"]
    assert result["targets"][0]["id"] == "page1"
    assert len(calls) == 2


@pytest.mark.parametrize("field,value", [("pid", 99), ("createTime", 99), ("executable", "other.exe"), ("httpEndpoint", "http://192.168.1.1:54321")])
def test_rejects_stale_or_nonlocal_record_before_http(debug_fixture, field, value):
    root, record, calls, write = debug_fixture
    record[field] = value
    write()
    with pytest.raises(RuntimeError):
        desktop_debug.discover_desktop_debug(root)
    assert not calls


def test_dead_or_reused_owner_is_not_a_live_debug_endpoint(debug_fixture, monkeypatch):
    root, _, calls, _ = debug_fixture
    monkeypatch.setattr(desktop_debug, "_identity_status", lambda value: "mismatch")
    with pytest.raises(RuntimeError, match="verified live"):
        desktop_debug.discover_desktop_debug(root)
    assert not calls


def test_port_reuse_requires_fresh_discovery(debug_fixture):
    root, record, _, _ = debug_fixture
    record["webSocketDebuggerUrl"] = "ws://127.0.0.1:54321/devtools/browser/new"
    with pytest.raises(RuntimeError, match="changed"):
        desktop_debug.discover_desktop_debug(root)
