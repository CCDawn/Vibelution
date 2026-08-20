from __future__ import annotations

import json
import os

from core.runtime_manager import daemon


def test_electron_owns_main_line_queue_when_marker_pid_is_alive(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(daemon, "RUNTIME_MANAGER_DIR", tmp_path)
    assert daemon.electron_owns_main_line_queue() is False
    assert daemon.should_run_workbench_idle_reconcile() is True

    (tmp_path / daemon.MAIN_LINE_QUEUE_OWNER_FILE).write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "owner": "electron",
                "pid": os.getpid(),
                "updatedAt": "2026-08-20T10:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    assert daemon.electron_owns_main_line_queue() is True
    assert daemon.should_run_workbench_idle_reconcile() is False


def test_electron_owns_main_line_queue_ignores_dead_or_invalid_marker(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(daemon, "RUNTIME_MANAGER_DIR", tmp_path)

    def _dead_pid(_pid: int, _signal: int) -> None:
        raise OSError("dead")

    monkeypatch.setattr(daemon.os, "kill", _dead_pid)
    (tmp_path / daemon.MAIN_LINE_QUEUE_OWNER_FILE).write_text(
        json.dumps({"schemaVersion": 1, "owner": "electron", "pid": 4242}),
        encoding="utf-8",
    )
    assert daemon.electron_owns_main_line_queue() is False
    (tmp_path / daemon.MAIN_LINE_QUEUE_OWNER_FILE).write_text(
        json.dumps({"schemaVersion": 1, "owner": "python", "pid": os.getpid()}),
        encoding="utf-8",
    )
    assert daemon.electron_owns_main_line_queue() is False
    assert daemon.should_run_workbench_idle_reconcile() is True
