"""Private SQLite reminder receipts: real Windows processes, no notifications."""
from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time

import pytest

from core.assistant_runtime.reminder_receipts import ReminderReceiptError, ReminderReceiptStore

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows namespace leases")
REPO = Path(__file__).resolve().parents[1]


def opened(root, *, create=False, maximum=1, owner="test-owner"):
    return ReminderReceiptStore(root, owner_id=owner, maximum=maximum, create=create, busy_timeout_ms=5000)


_WORKER = r'''
import json, os, sys, time
from pathlib import Path
from core.assistant_runtime.reminder_receipts import ReminderReceiptError, ReminderReceiptStore
root, event, phase = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
class CrashCommit:
    def __init__(self, connection, after): self.connection, self.after = connection, after
    def __getattr__(self, name): return getattr(self.connection, name)
    def execute(self, sql, *args):
        if sql == 'COMMIT' and not self.after: os._exit(71)
        result = self.connection.execute(sql, *args)
        if sql == 'COMMIT' and self.after: os._exit(72)
        return result
try:
    with ReminderReceiptStore(root, owner_id='test-owner', maximum=1, busy_timeout_ms=5000) as store:
        if phase == 'kill':
            conn = store._active()
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("INSERT INTO reminder_receipts VALUES (? ,?,'pending',NULL)", (event,'a'*64))
            (root.parent/'ready').write_text('ready')
            while True: time.sleep(.1)
        if phase.startswith('reserve_'):
            store._connection = CrashCommit(store._connection, phase.endswith('after'))
        result = store.reserve(event)
        if result['created']:
            fd = os.open(root.parent/'effects', os.O_WRONLY|os.O_APPEND|os.O_CREAT)
            try: os.write(fd, (event+'\n').encode()); os.fsync(fd)
            finally: os.close(fd)
            if phase == 'after_effect': os._exit(73)
            if phase.startswith('receipt_'):
                store._connection = CrashCommit(store._connection, phase.endswith('after'))
            store.record_submitted(event,result['attemptToken'],channel='system_notification')
        result.pop('attemptToken', None)
        print(json.dumps(result))
except ReminderReceiptError as error:
    print(json.dumps({'error':str(error)}))
'''


def command(root, event="event", phase="normal"):
    return [sys.executable, "-c", _WORKER, str(root), event, phase]


def run(root, event="event", phase="normal"):
    result = subprocess.run(command(root, event, phase), cwd=REPO, capture_output=True,
                            text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    assert not result.stderr, result.stderr
    return result


def effects(root):
    path = root.parent / "effects"
    return path.read_text().splitlines() if path.exists() else []


def test_only_explicit_initialization_creates_and_reopen_binds_owner_capacity(tmp_path):
    root = tmp_path / "receipts"
    with pytest.raises(ReminderReceiptError):
        with opened(root):
            pass
    assert not root.exists()
    with opened(root, create=True) as store:
        assert store.pending() == []
    for options in ({"owner": "another"}, {"maximum": 2}):
        with pytest.raises(ReminderReceiptError, match="receipt_owner_or_capacity_mismatch"):
            with opened(root, **options):
                pass
    (root / "reminders.sqlite3-journal").unlink()
    with pytest.raises(ReminderReceiptError, match="receipt_leaf_unavailable"):
        with opened(root):
            pass
    assert not (root / "reminders.sqlite3-journal").exists()


def test_submission_is_not_seen_and_only_winning_owner_can_record_callbacks(tmp_path):
    root = tmp_path / "receipts"
    with opened(root, create=True) as store:
        result = store.reserve("event")
        assert result["created"] and result["state"] == "pending" and result["pendingVerification"]
        token = result["attemptToken"]
        with opened(root) as other:
            assert not other.reserve("event")["created"]
            with pytest.raises(ReminderReceiptError, match="receipt_attempt_owner_required"):
                other.record_submitted("event", token, channel="system_notification")
        result = store.record_submitted("event", token, channel="system_notification")
        assert result["state"] == "submitted" and result["pendingVerification"] and not result["interactionObserved"]
        assert "attemptToken" not in store.get("event")
        assert "token_hash" not in json.dumps(store.pending())
        with pytest.raises(ReminderReceiptError, match="receipt_channel_conflict"):
            store.record_opened("event", token, channel="assistant_window")
        # The database's limit remains authoritative even if a caller mutates
        # the Python object's configuration after opening it.
        store.maximum = 2
        with pytest.raises(ReminderReceiptError, match="receipt_capacity_exceeded"):
            store.reserve("second")
        store.record_opened("event", token, channel="system_notification")
        # A late send callback cannot downgrade an already observed click.
        assert store.record_submitted("event", token, channel="system_notification")["state"] == "opened"
        assert store.pending() == []
    with opened(root) as restarted:
        assert restarted.get("event")["interactionObserved"]
        assert not restarted.reserve("event")["created"]
    with pytest.raises(ReminderReceiptError, match="receipt_owner_context_required"):
        store.get("event")


def test_real_host_restart_accepts_retained_native_click_token_without_submission_ownership(tmp_path):
    root = tmp_path / "receipts"
    original = r'''
import json,os,sys
from pathlib import Path
from core.assistant_runtime.reminder_receipts import ReminderReceiptStore
with ReminderReceiptStore(Path(sys.argv[1]),owner_id='test-owner',maximum=1,create=True) as store:
    result=store.reserve('event')
    store.record_submitted('event',result['attemptToken'],channel='system_notification')
    print(json.dumps({'pid':os.getpid(),'token':result['attemptToken']}))
'''
    first = subprocess.run([sys.executable, "-c", original, str(root)], cwd=REPO,
                           capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    assert first.returncode == 0, first.stderr
    retained = json.loads(first.stdout)
    restarted = r'''
import json,os,sys
from pathlib import Path
from core.assistant_runtime.reminder_receipts import ReminderReceiptError,ReminderReceiptStore
retained=json.loads(sys.stdin.read()); token=retained['token']
with ReminderReceiptStore(Path(sys.argv[1]),owner_id='test-owner',maximum=1) as store:
    assert os.getpid()!=retained['pid']
    before=store.get('event')
    assert before['state']=='submitted' and not before['interactionObserved']
    for method,value,channel,code in [
        (store.record_recovered_opened, '0'*64, 'system_notification', 'receipt_attempt_owner_required'),
        (store.record_recovered_opened, token, 'assistant_window', 'receipt_channel_conflict'),
        (store.record_submitted, token, 'system_notification', 'receipt_attempt_owner_required'),
        (store.record_opened, token, 'system_notification', 'receipt_attempt_owner_required')]:
        try: method('event',value,channel=channel)
        except ReminderReceiptError as error: assert str(error)==code
        else: raise AssertionError('untrusted or mismatched callback accepted')
        assert store.get('event')==before
    result=store.record_recovered_opened('event',token,channel='system_notification')
    assert result['state']=='opened' and result['interactionObserved'] and not result['pendingVerification']
    assert store.record_recovered_opened('event',token,channel='system_notification')==result
    assert not store.reserve('event')['created']
    try: store.record_submitted('event',token,channel='system_notification')
    except ReminderReceiptError as error: assert str(error)=='receipt_attempt_owner_required'
    else: raise AssertionError('recovery granted submission ownership')
    print(json.dumps({'pid':os.getpid(),'result':result}))
'''
    second = subprocess.run([sys.executable, "-c", restarted, str(root)], cwd=REPO,
                            input=json.dumps(retained), capture_output=True, text=True, timeout=10,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["result"]["state"] == "opened"
    with opened(root) as store:
        assert store.get("event")["interactionObserved"]


def test_recovered_click_requires_existing_bound_channel_not_an_unknown_pending_attempt(tmp_path):
    root = tmp_path / "receipts"
    with opened(root, create=True) as store:
        token = store.reserve("event")["attemptToken"]
    with opened(root) as restarted:
        before = restarted.get("event")
        with pytest.raises(ReminderReceiptError, match="receipt_channel_unconfirmed"):
            restarted.record_recovered_opened("event", token, channel="system_notification")
        assert restarted.get("event") == before
        assert before["state"] == "pending" and not before["interactionObserved"]
        with pytest.raises(ReminderReceiptError, match="receipt_attempt_owner_required"):
            restarted.record_recovered_opened("missing", token, channel="system_notification")


@pytest.mark.parametrize("distinct", [False, True])
def test_real_process_unique_id_and_capacity_are_one_transaction(tmp_path, distinct):
    root = tmp_path / "receipts"
    with opened(root, create=True):
        pass
    ids = [f"event-{index}" if distinct else "same-event" for index in range(8)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda event: run(root, event), ids))
    assert all(result.returncode == 0 for result in results)
    rows = [json.loads(result.stdout) for result in results]
    assert sum(result.get("created", False) for result in rows) == 1
    assert len(effects(root)) == 1
    if distinct:
        assert sum(result.get("error") == "receipt_capacity_exceeded" for result in rows) == 7
    with opened(root) as restarted:
        assert len(restarted.pending()) == 1


@pytest.mark.parametrize("phase", ["reserve_before", "reserve_after", "after_effect", "receipt_before", "receipt_after"])
def test_real_process_crash_boundaries_never_replay_existing_attempt(tmp_path, phase):
    root = tmp_path / "receipts"
    with opened(root, create=True):
        pass
    crashed = run(root, phase=phase)
    assert crashed.returncode in {71, 72, 73}
    with opened(root) as recovered:
        receipt = recovered.get("event")
        if phase == "reserve_before":
            assert receipt is None
        else:
            assert receipt["state"] == ("submitted" if phase == "receipt_after" else "pending")
            assert receipt["pendingVerification"] and not receipt["interactionObserved"]
    restart = run(root)
    assert restart.returncode == 0
    assert json.loads(restart.stdout)["created"] == (phase == "reserve_before")
    assert len(effects(root)) == (0 if phase == "reserve_after" else 1)


def test_terminate_process_rolls_back_active_reservation(tmp_path):
    root = tmp_path / "receipts"
    with opened(root, create=True):
        pass
    child = subprocess.Popen(command(root, phase="kill"), cwd=REPO, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        until = time.monotonic() + 10
        while not (tmp_path / "ready").exists():
            assert child.poll() is None and time.monotonic() < until
            time.sleep(.02)
        child.kill()
        child.communicate(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
    with opened(root) as store:
        assert store.get("event") is None
    assert json.loads(run(root).stdout)["created"] and len(effects(root)) == 1


def test_existing_native_handles_block_cross_process_directory_and_leaf_replacement(tmp_path):
    root = tmp_path / "receipts"
    probe = r'''
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);results=[]
for path in [root,root.parent,root/'reminders.sqlite3',root/'reminders.sqlite3-journal']:
    try:path.rename(path.with_name(path.name+'-replaced'));results.append('UNSAFE')
    except OSError as error:results.append(error.winerror)
print(json.dumps(results))
'''
    with opened(root, create=True) as store:
        result = subprocess.run([sys.executable, "-c", probe, str(root)], capture_output=True,
                                text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0 and json.loads(result.stdout) == [32, 32, 32, 32]
        assert store.reserve("event")["created"]
    # Native leases are released, rather than leaking an undeletable test tree.
    root.rename(tmp_path / "after-close")


def test_linked_leaves_and_foreign_schema_fail_closed(tmp_path):
    import apsw
    root = tmp_path / "receipts"
    root.mkdir()
    external = tmp_path / "external"
    external.write_bytes(b"unchanged")
    (root / "reminders.sqlite3").hardlink_to(external)
    with pytest.raises(ReminderReceiptError):
        with opened(root, create=True):
            pass
    assert external.read_bytes() == b"unchanged"
    (root / "reminders.sqlite3").unlink()
    conn = apsw.Connection(str(root / "reminders.sqlite3"))
    conn.execute("CREATE TABLE foreign_table(id)")
    conn.close()
    with pytest.raises(ReminderReceiptError, match="receipt_schema_invalid"):
        with opened(root, create=True):
            pass


@pytest.mark.parametrize("statement", [
    "CREATE TABLE sqliteXextra(id TEXT)",
    "CREATE TRIGGER sqliteXerase AFTER INSERT ON reminder_receipts "
    "BEGIN DELETE FROM reminder_receipts WHERE event_id=NEW.event_id; END",
], ids=["table", "trigger"])
def test_sqliteX_named_schema_objects_cannot_hide_as_sqlite_internal_objects(tmp_path, statement):
    import apsw
    root = tmp_path / "receipts"
    with opened(root, create=True):
        pass
    conn = apsw.Connection(str(root / "reminders.sqlite3"))
    try:
        conn.execute("PRAGMA journal_mode=PERSIST")
        conn.execute(statement)
        names_before = list(conn.execute("SELECT type,name,sql FROM sqlite_schema ORDER BY name"))
    finally:
        conn.close()
    with pytest.raises(ReminderReceiptError, match="receipt_schema_invalid"):
        with opened(root):
            pytest.fail("foreign schema reached reminder admission")
    conn = apsw.Connection(str(root / "reminders.sqlite3"))
    try:
        assert list(conn.execute("SELECT type,name,sql FROM sqlite_schema ORDER BY name")) == names_before
        assert list(conn.execute("SELECT count(*) FROM reminder_receipts")) == [(0,)]
    finally:
        conn.close()


def test_foreign_wal_header_is_rejected_before_sqlite_can_open_unpinned_sidecars(tmp_path):
    import apsw
    root = tmp_path / "receipts"
    with opened(root, create=True):
        pass
    conn = apsw.Connection(str(root / "reminders.sqlite3"))
    assert list(conn.execute("PRAGMA journal_mode=WAL")) == [("wal",)]
    conn.close()
    assert not (root / "reminders.sqlite3-wal").exists()
    # WAL conversion removes the old rollback journal. Restore an empty leaf
    # so this case specifically exercises the header guard, not missing-file denial.
    (root / "reminders.sqlite3-journal").touch()
    with pytest.raises(ReminderReceiptError, match="receipt_header_invalid"):
        with opened(root):
            pass
    assert not (root / "reminders.sqlite3-wal").exists()
    assert not (root / "reminders.sqlite3-shm").exists()


def test_corrupt_database_is_not_reinitialized_or_silently_repaired(tmp_path):
    root = tmp_path / "receipts"
    with opened(root, create=True) as store:
        store.reserve("event")
    path = root / "reminders.sqlite3"
    path.write_bytes(b"invalid-receipt-database")
    for create in [False, True]:
        with pytest.raises(ReminderReceiptError, match="receipt_header_invalid"):
            with opened(root, create=create):
                pass
        assert path.read_bytes() == b"invalid-receipt-database"


def test_crash_inside_native_sqlite_sync_recovers_hot_journal_with_pins(tmp_path):
    root = tmp_path / "receipts"
    with opened(root, create=True):
        pass
    script = textwrap.dedent(r'''
        import os,sys,apsw
        from pathlib import Path
        import core.assistant_runtime.reminder_receipts as module
        armed=False
        class File(apsw.VFSFile):
            def xSync(self, flags):
                super().xSync(flags)
                if armed: os._exit(76)
        class VFS(apsw.VFS):
            def xOpen(self,name,flags): return File('win32',name,flags)
        vfs=VFS('reminder-sync-test','win32')
        original=apsw.Connection
        def connect(path,**kwargs): return original(path,vfs='reminder-sync-test',**kwargs)
        module.apsw.Connection=connect
        with module.ReminderReceiptStore(Path(sys.argv[1]),owner_id='test-owner',maximum=1) as store:
            armed=True
            store.reserve('event')
        raise AssertionError('native xSync fault did not run')
    ''')
    result = subprocess.run([sys.executable, "-c", script, str(root)], cwd=REPO, capture_output=True,
                            text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 76, result.stderr
    with opened(root) as recovered:
        assert recovered.get("event") is None
        assert recovered.reserve("event")["created"]
