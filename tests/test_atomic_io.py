import json

from core.infrastructure import atomic_io


def test_atomic_write_text_retries_locked_replace(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    real_replace = atomic_io.os.replace
    attempts = {"count": 0}

    def flaky_replace(src, dst):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(atomic_io.os, "replace", flaky_replace)
    monkeypatch.setattr(atomic_io.time, "sleep", lambda seconds: None)

    atomic_io.atomic_write_text(target, "hello")

    assert attempts["count"] == 2
    assert target.read_text(encoding="utf-8") == "hello"
    assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_atomic_write_text_falls_back_when_tempfile_creation_fails(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    monkeypatch.setattr(
        atomic_io.tempfile,
        "mkstemp",
        lambda **kwargs: (_ for _ in ()).throw(OSError("No space left on device")),
    )

    atomic_io.atomic_write_text(target, "fallback")

    assert target.read_text(encoding="utf-8") == "fallback"


def test_atomic_write_json_serializes_payload(tmp_path):
    target = tmp_path / "state.json"

    atomic_io.atomic_write_json(target, {"name": "unified write", "items": [1, 2]})

    assert json.loads(target.read_text(encoding="utf-8")) == {"name": "unified write", "items": [1, 2]}
