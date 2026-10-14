"""Async test work must finish before a fixture restores its storage root."""
import threading
import time

import pytest

from core.web.services import session_service

pytestmark = pytest.mark.serial


def test_storage_drain_waits_for_late_prompt_read_before_root_restore(
    tmp_path, monkeypatch, isolate_runtime_manager_evolution_store
):
    drain = isolate_runtime_manager_evolution_store
    assert callable(drain), "Storage isolation must expose an early drain boundary"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    observed_roots = []

    def read_prompt():
        time.sleep(0.05)
        observed_roots.append(session_service.PROJECT_ROOT)

    def produce_read():
        time.sleep(0.02)
        threading.Thread(
            target=read_prompt, name="session-create-prompt-warm-lifetime", daemon=True
        ).start()

    session_service._SESSION_EXECUTOR.submit(produce_read)
    drain()
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path / "restored-root")
    assert observed_roots == [tmp_path]
