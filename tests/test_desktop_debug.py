import io
import json
from pathlib import Path

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


@pytest.fixture
def assistant_debug_fixture(debug_fixture, monkeypatch):
    root, record, calls, _ = debug_fixture
    record.update(schemaVersion=1, kind="launcher_assistant", workspaceRoot="", executable=str(root / "Vibelution.exe"))
    (root / "assistant").mkdir()

    def write():
        (root / "assistant/desktop_debug.json").write_text(json.dumps(record), encoding="utf-8")

    write()
    monkeypatch.setattr(desktop_debug, "resolve_desktop_shell_launch_roots", lambda *args: pytest.fail("must not resolve a project"))
    monkeypatch.setattr(desktop_debug, "read_desktop_shell_owner", lambda *args: pytest.fail("must not read a project owner"))
    return root, record, calls, write


def test_discovers_independent_assistant_from_fixed_user_data_record(assistant_debug_fixture, monkeypatch):
    root, record, calls, _ = assistant_debug_fixture
    identities = []
    monkeypatch.setattr(desktop_debug, "_identity_status", lambda value: identities.append(value) or "match")
    result = desktop_debug.discover_assistant_debug(root)
    assert result["kind"] == "launcher_assistant" and result["workspaceRoot"] == ""
    assert identities == [record]
    assert result["targets"][0]["id"] == "page1" and len(calls) == 2


@pytest.mark.parametrize("status", ["mismatch", "unknown", "missing"])
def test_assistant_rejects_unverified_native_process_before_http(assistant_debug_fixture, monkeypatch, status):
    root, _, calls, _ = assistant_debug_fixture
    monkeypatch.setattr(desktop_debug, "_identity_status", lambda value: status)
    with pytest.raises(RuntimeError, match="verified live"):
        desktop_debug.discover_assistant_debug(root)
    assert not calls


@pytest.mark.parametrize("field,value", [("kind", None), ("kind", "electron"), ("workspaceRoot", None),
    ("workspaceRoot", "."), ("workspaceRoot", " "), ("schemaVersion", 0), ("pid", True),
    ("pid", 1 << 128), ("createTime", 1 << 4096), ("createTime", float("nan")), ("executable", "relative.exe")])
def test_assistant_rejects_legacy_or_wrong_principal_record(assistant_debug_fixture, field, value):
    root, record, calls, write = assistant_debug_fixture
    record[field] = value
    write()
    with pytest.raises(RuntimeError):
        desktop_debug.discover_assistant_debug(root)
    assert not calls


def test_assistant_requires_absolute_user_data_root(assistant_debug_fixture):
    _, _, calls, _ = assistant_debug_fixture
    with pytest.raises(RuntimeError, match="absolute"):
        desktop_debug.discover_assistant_debug(Path("relative"))
    assert not calls


def test_assistant_never_falls_back_to_a_project_or_unbounded_record(assistant_debug_fixture):
    root, _, calls, _ = assistant_debug_fixture
    path = root / "assistant/desktop_debug.json"
    path.unlink()
    with pytest.raises(RuntimeError, match="unavailable"):
        desktop_debug.discover_assistant_debug(root)
    path.write_bytes(b"a" * (64 * 1024 + 1))
    with pytest.raises(RuntimeError, match="too large"):
        desktop_debug.discover_assistant_debug(root)
    assert not calls


def test_assistant_does_not_project_unknown_record_fields(assistant_debug_fixture):
    root, record, _, write = assistant_debug_fixture
    record["credential"] = "secret"
    write()
    assert "credential" not in desktop_debug.discover_assistant_debug(root)


@pytest.mark.parametrize("field,value", [("httpEndpoint", "http://remote.example:54321"),
    ("webSocketDebuggerUrl", "ws://remote.example:54321/devtools/browser/current"),
    ("webSocketDebuggerUrl", "ws://127.0.0.1:54322/devtools/browser/current"),
    ("webSocketDebuggerUrl", "ws://127.0.0.1:54321/devtools/browser/current?credential=secret")])
def test_assistant_uses_shared_loopback_origin_and_nonce_guards(assistant_debug_fixture, field, value):
    root, record, calls, write = assistant_debug_fixture
    record[field] = value
    write()
    with pytest.raises(RuntimeError):
        desktop_debug.discover_assistant_debug(root)
    assert not calls


def test_assistant_port_reuse_is_rejected_before_target_listing(assistant_debug_fixture):
    root, record, calls, _ = assistant_debug_fixture
    record["webSocketDebuggerUrl"] = "ws://127.0.0.1:54321/devtools/browser/reused"
    with pytest.raises(RuntimeError, match="changed"):
        desktop_debug.discover_assistant_debug(root)
    assert len(calls) == 1


def test_cli_modes_are_mutually_exclusive_and_legacy_default_is_retained(monkeypatch, capsys):
    from scripts import desktop_debug as command

    called = []
    monkeypatch.setattr(command, "discover_desktop_debug", lambda root: called.append(("project", root)) or {})
    monkeypatch.setattr(command, "discover_assistant_debug", lambda root: called.append(("assistant", root)) or {})
    assert command.main([]) == 0
    assert called[-1] == ("project", command.PROJECT_ROOT)
    assert command.main(["--assistant-user-data", str(command.PROJECT_ROOT)]) == 0
    assert called[-1] == ("assistant", command.PROJECT_ROOT)
    with pytest.raises(SystemExit) as error:
        command.main(["--assistant-user-data", str(command.PROJECT_ROOT), "--project", str(command.PROJECT_ROOT)])
    assert error.value.code == 2
    capsys.readouterr()


def test_cli_does_not_echo_unexpected_error_details(monkeypatch, capsys):
    from scripts import desktop_debug as command

    def failure(root):
        raise OSError("credential=secret must not leave the discovery boundary")
    monkeypatch.setattr(command, "discover_assistant_debug", failure)
    assert command.main(["--assistant-user-data", str(command.PROJECT_ROOT)]) == 1
    response = json.loads(capsys.readouterr().out)
    assert response["available"] is False and "secret" not in response["reason"]


def test_shared_discovery_refuses_redirects_without_following_remote_url(debug_fixture, monkeypatch):
    root, _, _, _ = debug_fixture

    def build(*handlers):
        redirect = next(handler for handler in handlers if isinstance(handler, desktop_debug._RejectRedirects))
        assert next(handler for handler in handlers if isinstance(handler, desktop_debug.ProxyHandler)).proxies == {}
        class Opener:
            def open(self, url, timeout):
                redirect.redirect_request(None, None, None, None, "http://remote.example/?credential=secret")
        return Opener()

    monkeypatch.setattr(desktop_debug, "build_opener", build)
    with pytest.raises(RuntimeError, match="must not redirect") as error:
        desktop_debug.discover_desktop_debug(root)
    assert "secret" not in str(error.value)
