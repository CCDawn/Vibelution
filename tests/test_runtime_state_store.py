import json

from core.runtime_manager import state_store


def test_save_state_suppresses_persistent_windows_lock(tmp_path, monkeypatch, capsys):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"stateVersion": 7}), encoding="utf-8")
    monotonic_values = iter(
        [
            0.0,
            state_store.WRITE_RETRY_TIMEOUT_SECONDS + 0.1,
            10.0,
            10.0 + state_store.WRITE_FALLBACK_TIMEOUT_SECONDS + 0.1,
        ]
    )

    monkeypatch.setattr(state_store, "STATE_PATH", state_path)
    monkeypatch.setattr(state_store, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(state_store.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(state_store.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(state_store.os, "replace", lambda src, dst: (_ for _ in ()).throw(PermissionError("locked")))
    monkeypatch.setattr(
        state_store,
        "_write_text_in_place",
        lambda path, text: (_ for _ in ()).throw(PermissionError("still locked")),
    )

    payload = state_store.save_state({"stateVersion": 7, "runtimeState": "running"})

    assert payload["stateVersion"] == 8
    assert json.loads(state_path.read_text(encoding="utf-8")) == {"stateVersion": 7}
    assert "state write skipped after retries" in capsys.readouterr().err


def test_state_store_atomic_write_text_falls_back_when_tempfile_creation_fails(tmp_path, monkeypatch):
    target_path = tmp_path / "state.json"
    monkeypatch.setattr(state_store, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(state_store.tempfile, "mkstemp", lambda **kwargs: (_ for _ in ()).throw(OSError("No space left on device")))

    result = state_store._atomic_write_text(target_path, "hello")

    assert result is True
    assert target_path.read_text(encoding="utf-8") == "hello"


def test_save_pid_uses_best_effort_write(tmp_path, monkeypatch):
    pid_path = tmp_path / "daemon.pid"
    calls = []
    monkeypatch.setattr(state_store, "PID_PATH", pid_path)
    monkeypatch.setattr(state_store, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(state_store, "_atomic_write_text", lambda path, text, suppress_write_failure=False: calls.append((path, text, suppress_write_failure)) or False)

    state_store.save_pid(321)

    assert calls == [(pid_path, "321", True)]


def test_save_pid_persists_identity_and_clear_pid_removes_it(tmp_path, monkeypatch):
    pid_path = tmp_path / "daemon.pid"
    identity_path = tmp_path / "daemon.identity.json"
    monkeypatch.setattr(state_store, "PID_PATH", pid_path)
    monkeypatch.setattr(state_store, "DAEMON_IDENTITY_PATH", identity_path)
    monkeypatch.setattr(
        state_store,
        "capture_process_identity",
        lambda pid: {"pid": pid, "createTime": 12.5, "executable": "C:/Python/python.exe"},
    )

    state_store.save_pid(321)

    assert json.loads(identity_path.read_text(encoding="utf-8")) == {
        "pid": 321,
        "createTime": 12.5,
        "executable": "C:/Python/python.exe",
    }
    assert state_store.load_pid_identity()["pid"] == 321
    state_store.clear_pid(321)
    assert not identity_path.exists()
