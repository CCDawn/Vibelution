import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from core.assistant_runtime.migration_io import MigrationIOError
from core.assistant_runtime.reminder_source_lease import ReminderSourceLeaseOwner
from tests.test_assistant_history_preview import setup_preview  # noqa: F401
from tests.test_assistant_reminder_source_identity import prepare

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows verified file handles")


def child(code, *args, timeout=20):
    return subprocess.run([sys.executable, "-B", "-c", code, *map(str, args)], capture_output=True,
                          text=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)


def test_lease_pins_real_ledger_and_authority_and_releases_on_close(setup_preview):
    dispatch, workspace, _ = setup_preview
    registry, ledger = prepare(dispatch, workspace)
    owner = ReminderSourceLeaseOwner(dispatch, dispatch.history_preview)
    lease = owner.acquire("registered:1", 1, 10000)
    assert lease["coverage"] == "existing_files_only" and lease["readyForCutover"] is False
    checked = owner.check(lease["leaseId"])
    assert checked["ledgerKey"] == lease["ledgerKey"] and 0 < checked["remainingMs"] <= 10000
    code = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('changed')"
    assert child(code, ledger).returncode != 0
    assert child(code, registry).returncode != 0
    assert ledger.read_text(encoding="utf-8") == ""
    owner.close()
    assert child(code, ledger).returncode == 0
    with pytest.raises(MigrationIOError, match="owner_closed"):
        owner.check(lease["leaseId"])
    assert not dispatch.history_preview._previews


def test_concurrent_native_transaction_fails_then_succeeds_after_release(setup_preview):
    dispatch, workspace, _ = setup_preview
    _, ledger = prepare(dispatch, workspace)
    root = dispatch._admitted_projects()["registered:1"]
    owner = ReminderSourceLeaseOwner(dispatch, dispatch.history_preview)
    lease = owner.acquire("registered:1", 1, 10000)
    code = """
import sys
from pathlib import Path
from core.agent_plugins.personal_affairs.service import PersonalAffairsService
s=PersonalAffairsService(Path(sys.argv[1]), agent_loader=lambda agent_id, **kw: {'agentId': agent_id}, source_mutex_guard=lambda agent: True)
s.add_item('agent-pa', kind='todo', title='fixture')
"""
    blocked = child(code, root)
    assert blocked.returncode != 0
    assert ledger.read_text(encoding="utf-8") == ""
    # The native writer creates and removes a temporary file before its atomic
    # replacement fails. The existing directory snapshot deliberately revokes
    # the observation when that namespace changes.
    with pytest.raises(MigrationIOError, match="observation_changed"):
        owner.check(lease["leaseId"])
    success = child(code, root)
    assert success.returncode == 0, success.stderr
    assert '"title": "fixture"' in ledger.read_text(encoding="utf-8")
    owner.close()


def test_lease_does_not_reacquire_electron_owned_source_mutex(setup_preview):
    from core.assistant_runtime.reminder_source_identity import observe_reminder_source
    from core.infrastructure.reminder_source_mutex import try_acquire_reminder_source_mutex
    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as observation:
        mutex = try_acquire_reminder_source_mutex(observation)
        assert mutex is not None
        try:
            owner = ReminderSourceLeaseOwner(dispatch, dispatch.history_preview)
            lease = owner.acquire("registered:1", 1, 10000)
            assert owner.check(lease["leaseId"])["ledgerKey"] == lease["ledgerKey"]
            owner.close()
        finally:
            mutex.release()


def test_missing_marker_can_change_and_check_revokes_lease(setup_preview):
    from core.infrastructure import developer_sandbox
    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    root = dispatch._admitted_projects()["registered:1"]
    marker = developer_sandbox._active_state_path(root)
    assert not marker.exists()
    owner = ReminderSourceLeaseOwner(dispatch, dispatch.history_preview)
    lease = owner.acquire("registered:1", 1, 10000)
    marker.parent.mkdir(parents=True, exist_ok=True)
    assert child("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('{}')", marker).returncode == 0
    with pytest.raises(MigrationIOError):
        owner.check(lease["leaseId"])
    with pytest.raises(MigrationIOError, match="lease_unavailable"):
        owner.check(lease["leaseId"])
    owner.close()


def test_expiry_and_explicit_revoke_release_handles(setup_preview):
    dispatch, workspace, _ = setup_preview
    _, ledger = prepare(dispatch, workspace)
    owner = ReminderSourceLeaseOwner(dispatch, dispatch.history_preview)
    lease = owner.acquire("registered:1", 1, 150)
    assert threading.Event().wait(0.4) is False
    with pytest.raises(MigrationIOError, match="lease_(unavailable|expired)"):
        owner.check(lease["leaseId"])
    lease = owner.acquire("registered:1", 1, 10000)
    owner.revoke_all()
    with pytest.raises(MigrationIOError, match="lease_unavailable"):
        owner.check(lease["leaseId"])
    assert child("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('free')", ledger).returncode == 0
    owner.close()


def test_expiry_releases_file_even_while_check_is_blocked(setup_preview, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import core.assistant_runtime.reminder_source_lease as module
    dispatch, workspace, _ = setup_preview
    _, ledger = prepare(dispatch, workspace)
    owner = ReminderSourceLeaseOwner(dispatch, dispatch.history_preview)
    lease = owner.acquire("registered:1", 1, 150)
    entered, resume = threading.Event(), threading.Event()
    def slow(_observation):
        entered.set()
        assert resume.wait(5)
        return lease["ledgerKey"]
    monkeypatch.setattr(module, "trusted_reminder_source_mutex_key", slow)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(owner.check, lease["leaseId"])
        assert entered.wait(5)
        assert threading.Event().wait(0.4) is False
        assert child("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('expired')", ledger).returncode == 0
        resume.set()
        with pytest.raises(MigrationIOError, match="lease_unavailable"):
            future.result(timeout=5)
    owner.close()


def test_shutdown_revokes_an_acquire_already_in_progress(setup_preview, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import core.assistant_runtime.reminder_source_lease as module
    dispatch, workspace, _ = setup_preview
    _, ledger = prepare(dispatch, workspace)
    owner = ReminderSourceLeaseOwner(dispatch, dispatch.history_preview)
    entered, resume = threading.Event(), threading.Event()
    original = module.observe_reminder_source
    def slow(*args):
        entered.set()
        assert resume.wait(5)
        return original(*args)
    monkeypatch.setattr(module, "observe_reminder_source", slow)
    with ThreadPoolExecutor(max_workers=2) as executor:
        acquisition = executor.submit(owner.acquire, "registered:1", 1, 10000)
        assert entered.wait(5)
        closing = executor.submit(owner.close)
        for _ in range(500):
            if owner._closed:
                break
            threading.Event().wait(0.01)
        assert owner._closed
        resume.set()
        with pytest.raises(MigrationIOError, match="owner_closed"):
            acquisition.result(timeout=5)
        closing.result(timeout=5)
    assert child("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('free')", ledger).returncode == 0


def test_host_process_death_releases_pinned_file(setup_preview):
    dispatch, workspace, _ = setup_preview
    _, ledger = prepare(dispatch, workspace)
    root = dispatch._admitted_projects()["registered:1"]
    config = dispatch.history_preview._config
    profile = workspace.parent.parent / "lease-test-profile"
    code = """
import os, sys
from pathlib import Path
from core.assistant_runtime.dispatch import DispatchService
from core.assistant_runtime.history_preview import HistoryPreview
from core.assistant_runtime.reminder_source_lease import ReminderSourceLeaseOwner
d=DispatchService(Path(sys.argv[3]), {})
d.replace_projects({'schemaVersion':1,'revision':1,'projects':{'registered:1':sys.argv[1]}})
p=HistoryPreview(d, Path(sys.argv[2]))
o=ReminderSourceLeaseOwner(d,p)
o.acquire('registered:1',1,10000)
print('ready',flush=True)
sys.stdin.readline()
"""
    process = subprocess.Popen([sys.executable, "-B", "-c", code, str(root), str(config), str(profile)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        assert process.stdout.readline().strip() == "ready"
        assert child("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('blocked')", ledger).returncode != 0
        process.kill()
        process.wait(timeout=10)
        assert child("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('after-exit')", ledger).returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
