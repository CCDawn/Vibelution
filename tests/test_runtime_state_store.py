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
