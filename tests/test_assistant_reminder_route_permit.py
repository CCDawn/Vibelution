"""Real cross-process route exclusion and explicit sender drain."""
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from core.assistant_runtime.migration_io import MigrationIOError
from core.assistant_runtime.reminder_source_lease import ReminderSourceLeaseOwner
from tests.test_assistant_history_preview import setup_preview  # noqa: F401
from tests.test_assistant_reminder_source_identity import prepare

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows route file gate")


def _child(code, root):
    return subprocess.run([sys.executable, "-B", "-c", code, str(root)], capture_output=True,
                          text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)


def test_missing_markers_are_guarded_and_revocation_waits_for_permit(setup_preview):
    dispatch, workspace, _ = setup_preview
    _, ledger = prepare(dispatch, workspace)
    root = dispatch._admitted_projects()["registered:1"]
    from core.infrastructure import developer_sandbox
    from vibelution_storage import resolve_project_storage_paths, storage_migration_state_path
    active = developer_sandbox._active_state_path(root)
    marker = storage_migration_state_path(resolve_project_storage_paths(root))
    assert not active.exists() and not marker.exists()
    owner = ReminderSourceLeaseOwner(dispatch, dispatch.history_preview)
    permit = owner.acquire_permit("registered:1", 1)
    assert permit["coverage"] == "cooperating_route_writers" and permit["unmanagedSenders"] == "unknown"
    assert owner.check_permit(permit["permitId"])["ledgerKey"] == permit["ledgerKey"]
    sandbox = "from pathlib import Path; import sys; from core.infrastructure.developer_sandbox import _ensure_active_state; _ensure_active_state(Path(sys.argv[1]))"
    apply = "from pathlib import Path; import sys; import core.infrastructure.storage_migration as m; m._run_logged_storage_migration_step=lambda **kw: print('entered'); m.apply_storage_migration(Path(sys.argv[1]))"
    rollback = "from pathlib import Path; import sys; import core.infrastructure.storage_migration as m; m._run_logged_storage_migration_step=lambda **kw: print('entered'); m.rollback_storage_switch(Path(sys.argv[1]))"
    for code in (sandbox, apply, rollback):
        assert _child(code, root).returncode != 0
    assert not active.exists() and not marker.exists() and ledger.read_text(encoding="utf-8") == ""
    owner.begin_revocation()
    with pytest.raises(MigrationIOError):
        owner.check_permit(permit["permitId"])
    with ThreadPoolExecutor(max_workers=1) as pool:
        draining = pool.submit(owner.wait_revocation)
        assert threading.Event().wait(.2) is False and not draining.done()
        assert _child(sandbox, root).returncode != 0
        owner.release_permit(permit["permitId"])
        draining.result(timeout=10)
    owner.end_revocation()
    assert _child(sandbox, root).returncode == 0
    assert active.exists()
    assert _child(apply, root).stdout.strip() == "entered"
    assert _child(rollback, root).stdout.strip() == "entered"
    owner.close()


def test_private_host_registry_and_shutdown_wait_for_sender_release(tmp_path, setup_preview):
    from fastapi.testclient import TestClient
    from core.assistant_runtime.history_host import HistoryHost
    from core.assistant_runtime.host import create_app
    from tests.test_assistant_runtime_host import Native
    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    root = dispatch._admitted_projects()["registered:1"]
    profile = tmp_path / "assistant-profile"
    profile.mkdir(exist_ok=True)
    history = HistoryHost(profile, "generation-1", dispatch, dispatch.history_preview)
    stopped = threading.Event()
    app = create_app(native=Native(), token="private-test-token", dispatch=dispatch,
                     history_control=history, on_shutdown=stopped.set)
    auth = {"Authorization": "Bearer private-test-token"}
    prefix = "/api/assistant/legacy-reminders/permit/"
    with TestClient(app, base_url="http://127.0.0.1", headers=auth) as client:
        assert client.post(prefix + "acquire", json={"projectId": "registered:1", "revision": 1, "permitId": "a" * 64, "path": str(root)}).status_code == 422
        acquired = client.post(prefix + "acquire", json={"projectId": "registered:1", "revision": 1, "permitId": "a" * 64})
        assert acquired.status_code == 200
        permit = acquired.json()
        assert permit["coverage"] == "cooperating_route_writers" and permit["readyForCutover"] is False
        token = {"permitId": permit["permitId"]}
        assert client.post(prefix + "check", json=token).status_code == 200
        with ThreadPoolExecutor(max_workers=1) as pool:
            registry = pool.submit(client.put, "/api/assistant/project-registry", json={
                "schemaVersion": 1, "revision": 2, "projects": {"registered:1": str(root)}})
            for _ in range(100):
                if client.post(prefix + "check", json=token).status_code == 409:
                    break
                threading.Event().wait(.01)
            else:
                raise AssertionError("registry did not revoke permit")
            assert not registry.done()
            assert client.post(prefix + "acquire", json={"projectId": "registered:1", "revision": 1, "permitId": "b" * 64}).status_code == 409
            assert client.post(prefix + "release", json=token).status_code == 200
            assert registry.result(timeout=10).status_code == 200
        acquired = client.post(prefix + "acquire", json={"projectId": "registered:1", "revision": 2, "permitId": "c" * 64})
        assert acquired.status_code == 200
        token = {"permitId": acquired.json()["permitId"]}
        with ThreadPoolExecutor(max_workers=1) as pool:
            shutdown = pool.submit(client.post, "/api/assistant/shutdown")
            for _ in range(100):
                if client.post(prefix + "check", json=token).status_code == 409:
                    break
                threading.Event().wait(.01)
            else:
                raise AssertionError("shutdown did not revoke permit")
            assert not shutdown.done() and not stopped.is_set()
            assert client.post(prefix + "release", json=token).status_code == 200
            assert shutdown.result(timeout=10).status_code == 200 and stopped.is_set()


def test_client_owned_permit_id_drains_lost_acquire_and_blocks_late_delivery(setup_preview, monkeypatch):
    import core.assistant_runtime.reminder_source_lease as module
    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    owner = ReminderSourceLeaseOwner(dispatch, dispatch.history_preview)
    token = "d" * 64
    entered, resume = threading.Event(), threading.Event()
    original = module.observe_reminder_source
    def paused(*args):
        entered.set()
        assert resume.wait(10)
        return original(*args)
    monkeypatch.setattr(module, "observe_reminder_source", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        acquiring = pool.submit(owner.acquire_permit, "registered:1", 1, token)
        assert entered.wait(10)
        release = pool.submit(owner.release_permit, token)
        assert threading.Event().wait(.2) is False and not release.done()
        resume.set()
        release.result(timeout=10)
        with pytest.raises(MigrationIOError):
            acquiring.result(timeout=10)
    owner.release_permit(token)
    with pytest.raises(MigrationIOError):
        owner.acquire_permit("registered:1", 1, token)
    new_token = "e" * 64
    owner.release_permit(new_token)  # Release may arrive before acquire.
    with pytest.raises(MigrationIOError):
        owner.acquire_permit("registered:1", 1, new_token)
    owner.close()


def test_release_cycles_keep_working_across_the_retired_capacity_threshold(setup_preview, monkeypatch):
    """A lifetime of releases must not make acquire permanently capacity-bound.

    Released ids stay rejected (the anti-replay contract above), but the
    memory is a bounded most-recent window: after more releases than the
    retention bound, ordinary acquire/release cycles must keep succeeding.
    """
    import core.assistant_runtime.reminder_source_lease as module
    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    owner = ReminderSourceLeaseOwner(dispatch, dispatch.history_preview)
    # Simulate a host lifetime that has already released the full bound.
    owner._retired_permit_ids.update(("%064x" % index, None) for index in range(module._MAX_RETIRED_PERMITS))
    for cycle in range(4):
        permit = owner.acquire_permit("registered:1", 1)
        assert owner.check_permit(permit["permitId"])["ledgerKey"] == permit["ledgerKey"]
        owner.release_permit(permit["permitId"])
        assert len(owner._retired_permit_ids) <= module._MAX_RETIRED_PERMITS
    # A still-remembered released id stays rejected by the anti-replay rule.
    with pytest.raises(MigrationIOError):
        owner.acquire_permit("registered:1", 1, "%064x" % (module._MAX_RETIRED_PERMITS - 1))
    owner.close()


def test_failed_release_is_retryable_and_keeps_pins_attested(setup_preview, monkeypatch):
    """One transient close failure must not fail the permit forever."""
    import core.assistant_runtime.reminder_source_lease as module
    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    root = dispatch._admitted_projects()["registered:1"]
    owner = ReminderSourceLeaseOwner(dispatch, dispatch.history_preview)
    original = module.ExitStack
    class FlakyStack(original):
        closes = 0
        def close(self):
            FlakyStack.closes += 1
            if FlakyStack.closes == 1:
                raise OSError("transient unlock failure")
            return original.close(self)
    # Patched before acquire so the permit's own pin stack is a FlakyStack.
    monkeypatch.setattr(module, "ExitStack", FlakyStack)
    permit = owner.acquire_permit("registered:1", 1)
    token = permit["permitId"]
    with pytest.raises(MigrationIOError, match="reminder_lease_release_unavailable"):
        owner.release_permit(token)
    # The failed close keeps the permit row and every pin attested as held.
    assert token in owner._permits
    assert owner.check_permit(token)["ledgerKey"] == permit["ledgerKey"]
    blocked = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('blocked')"
    assert _child(blocked, root / "agents" / "agent-pa" / "plugins" / "personal-affairs" / "affairs" / "items.jsonl").returncode != 0
    sandbox = "from pathlib import Path; import sys; from core.infrastructure.developer_sandbox import _ensure_active_state; _ensure_active_state(Path(sys.argv[1]))"
    assert _child(sandbox, root).returncode != 0
    # The retry completes the remaining close steps and frees the source.
    owner.release_permit(token)
    assert token not in owner._permits
    assert _child("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('free')", root / "agents" / "agent-pa" / "plugins" / "personal-affairs" / "affairs" / "items.jsonl").returncode == 0
    assert _child(sandbox, root).returncode == 0
    # The id stays retired: a late acquire must never re-bind, and a late
    # release stays an idempotent no-op.
    with pytest.raises(MigrationIOError):
        owner.acquire_permit("registered:1", 1, token)
    owner.release_permit(token)
    owner.close()


def test_shutdown_close_force_drops_still_held_permits_after_bounded_wait(setup_preview, caplog):
    """close() must never hang forever on a sender that never releases."""
    import logging
    dispatch, workspace, _ = setup_preview
    _, ledger = prepare(dispatch, workspace)
    owner = ReminderSourceLeaseOwner(dispatch, dispatch.history_preview)
    permit = owner.acquire_permit("registered:1", 1)
    import time
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="core.assistant_runtime.reminder_source_lease"):
        owner.close(timeout=0.2)
    assert time.monotonic() - started < 5
    assert any("force-dropped 1 held permit" in row.getMessage() for row in caplog.records)
    assert not owner._permits
    assert _child("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('free')", ledger).returncode == 0


def test_host_permit_errors_carry_distinguishable_codes(tmp_path, setup_preview):
    from fastapi.testclient import TestClient
    from core.assistant_runtime.history_host import HistoryHost
    from core.assistant_runtime.host import create_app
    from tests.test_assistant_runtime_host import Native
    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    profile = tmp_path / "assistant-profile"
    profile.mkdir(exist_ok=True)
    history = HistoryHost(profile, "generation-1", dispatch, dispatch.history_preview)
    app = create_app(native=Native(), token="private-test-token", dispatch=dispatch,
                     history_control=history, on_shutdown=lambda: None)
    auth = {"Authorization": "Bearer private-test-token"}
    prefix = "/api/assistant/legacy-reminders/permit/"
    with TestClient(app, base_url="http://127.0.0.1", headers=auth) as client:
        response = client.post(prefix + "acquire", json={"projectId": "registered:1", "revision": 99, "permitId": "a" * 64})
        assert response.status_code == 409
        assert response.json()["detail"] == {"code": "reminder_lease_request_invalid", "retryable": False}
        acquired = client.post(prefix + "acquire", json={"projectId": "registered:1", "revision": 1, "permitId": "b" * 64})
        assert acquired.status_code == 200
        token = {"permitId": acquired.json()["permitId"]}
        client.post(prefix + "release", json=token)
        released = client.post(prefix + "release", json=token)
        assert released.status_code == 200 and released.json() == {"schemaVersion": 1, "released": True}
