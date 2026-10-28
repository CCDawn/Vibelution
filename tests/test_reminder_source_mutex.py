"""Real Windows mutex interoperability; every key is randomly generated."""
import os
import secrets
import subprocess
import threading
import json
import time
import sys
from queue import Queue
from pathlib import Path

import pytest

from core.infrastructure.reminder_source_mutex import ReminderMutexError, _try_digest
from tests.test_assistant_history_preview import setup_preview  # noqa: F401


@pytest.fixture
def addon():
    value = os.environ.get("VIBELUTION_MUTEX_TEST_ADDON", "")
    if os.name != "nt" or not value or not Path(value).is_file():
        pytest.skip("requires a separately built temporary Windows native addon")
    return value


def node(addon, key, source):
    env = {**os.environ, "MUTEX_TEST_ADDON": addon, "MUTEX_TEST_KEY": key}
    return subprocess.run(["node", "-e", source], env=env, capture_output=True,
                          text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)


@pytest.mark.skipif(os.name != "nt", reason="requires a Windows mutex")
def test_dead_owner_thread_can_be_recovered_without_silent_clean_handoff():
    import ctypes
    from ctypes import wintypes
    key, ready = secrets.token_hex(32), Queue()

    def owner():
        lease = _try_digest(key)
        ready.put(lease)
        try:
            raise RuntimeError("fixture failure")
        except RuntimeError:
            pass  # Simulate an unhandled operation failure without releasing.

    worker = threading.Thread(target=owner)
    worker.start()
    original = ready.get(timeout=5)
    worker.join(timeout=5)
    assert not worker.is_alive() and original is not None
    stale_handle = original._handle
    with pytest.raises(ReminderMutexError):
        original.check()
    with pytest.raises(ReminderMutexError):
        original.release()
    recovered = _try_digest(key)
    assert recovered is not None and recovered.abandoned is True
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    api.GetHandleInformation.restype = wintypes.BOOL
    flags = wintypes.DWORD()
    assert original._handle is None and not api.GetHandleInformation(stale_handle, ctypes.byref(flags))
    try:
        recovered.check()
        assert _try_digest(key) is None
    finally:
        recovered.release()
    following = _try_digest(key)
    assert following is not None
    following.release()


@pytest.mark.skipif(os.name != "nt", reason="requires a Windows mutex")
def test_owner_object_cannot_be_replaced_by_same_numeric_thread_id(monkeypatch):
    import core.infrastructure.reminder_source_mutex as mutex

    lease = _try_digest(secrets.token_hex(32))
    assert lease is not None
    class Impostor:
        ident = lease._thread.ident
        def is_alive(self):
            return True
    try:
        with monkeypatch.context() as patch:
            patch.setattr(mutex, "current_thread", lambda: Impostor())
            with pytest.raises(ReminderMutexError):
                lease.check()
            with pytest.raises(ReminderMutexError):
                lease.release()
        lease.check()
    finally:
        lease.release()


def test_dead_owner_stays_uncertain_if_another_process_acquired_first(addon):
    key, result = secrets.token_hex(32), Queue()
    worker = threading.Thread(target=lambda: result.put(_try_digest(key)))
    worker.start(); original = result.get(timeout=5); worker.join(timeout=5)
    assert original is not None and not worker.is_alive()
    source = "const a=require(process.env.MUTEX_TEST_ADDON),h=a.tryAcquireReminderMutex(process.env.MUTEX_TEST_KEY); if(!h)process.exit(2); console.log('held'); process.stdin.once('data',()=>{a.releaseReminderMutex(h.handle);process.exit(0)})"
    env = {**os.environ, "MUTEX_TEST_ADDON": addon, "MUTEX_TEST_KEY": key}
    child = subprocess.Popen(["node", "-e", source], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        ready = Queue()
        threading.Thread(target=lambda: ready.put(child.stdout.readline()), daemon=True).start()
        assert ready.get(timeout=10).strip() == "held"
        assert _try_digest(key) is None
        assert original._handle is not None
        child.stdin.write("release\n"); child.stdin.flush()
        assert child.wait(timeout=10) == 0
        recovered = _try_digest(key)
        assert recovered is not None and recovered.abandoned is True
        recovered.release()
    finally:
        if child.poll() is None:
            child.kill(); child.wait(timeout=10)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream:
                stream.close()


def test_python_owner_blocks_electron_then_explicit_release_allows_it(addon):
    key = secrets.token_hex(32)
    lease = _try_digest(key)
    assert lease is not None and not lease.abandoned
    try:
        assert _try_digest(key) is None  # Windows mutexes otherwise allow recursive acquisition.
        result = node(addon, key, "const a=require(process.env.MUTEX_TEST_ADDON); console.log(a.tryAcquireReminderMutex(process.env.MUTEX_TEST_KEY)===null?'busy':'bad')")
        assert result.returncode == 0 and result.stdout.strip() == "busy"
        errors = []
        thread = threading.Thread(target=lambda: errors.append(pytest.raises(ReminderMutexError, lease.release)))
        thread.start(); thread.join(timeout=5)
        assert not thread.is_alive() and errors
        checks = []
        thread = threading.Thread(target=lambda: checks.append(pytest.raises(ReminderMutexError, lease.check)))
        thread.start(); thread.join(timeout=5)
        assert not thread.is_alive() and checks
        start = time.monotonic()
        assert _try_digest(key) is None
        assert time.monotonic() - start < 1
    finally:
        lease.release()
    result = node(addon, key, "const a=require(process.env.MUTEX_TEST_ADDON), k=process.env.MUTEX_TEST_KEY; const h=a.tryAcquireReminderMutex(k); if(!h)process.exit(2); console.log(h.abandoned, a.tryAcquireReminderMutex(k)===null); a.releaseReminderMutex(h.handle); try {a.releaseReminderMutex(h.handle);process.exit(3)} catch {}")
    assert result.returncode == 0 and result.stdout.strip() == "false true"


def test_electron_worker_cannot_reenter_mutex_held_by_main_thread(addon):
    key = secrets.token_hex(32)
    source = r"""
const {Worker}=require('node:worker_threads');
const a=require(process.env.MUTEX_TEST_ADDON), key=process.env.MUTEX_TEST_KEY;
const held=a.tryAcquireReminderMutex(key); if(!held)process.exit(2);
try { structuredClone(held.handle); process.exit(5) } catch {}
const worker=new Worker(`const {parentPort,workerData}=require('node:worker_threads');
const a=require(workerData.addon); parentPort.postMessage(a.tryAcquireReminderMutex(workerData.key)===null)`,
  {eval:true,workerData:{addon:process.env.MUTEX_TEST_ADDON,key}});
worker.on('message', value=>{ console.log(value); a.releaseReminderMutex(held.handle); });
worker.on('error',()=>process.exit(3));
"""
    result = node(addon, key, source)
    assert result.returncode == 0 and result.stdout.strip() == "true"


def test_electron_worker_exit_does_not_permanently_block_same_process(addon):
    key = secrets.token_hex(32)
    source = r"""
const {Worker}=require('node:worker_threads');
const a=require(process.env.MUTEX_TEST_ADDON), key=process.env.MUTEX_TEST_KEY;
const worker=new Worker(`const {parentPort,workerData}=require('node:worker_threads');
const a=require(workerData.addon); const held=a.tryAcquireReminderMutex(workerData.key);
parentPort.postMessage(Boolean(held))`, {eval:true,workerData:{addon:process.env.MUTEX_TEST_ADDON,key}});
worker.on('message', value=>{if(!value)process.exit(2)});
worker.on('error',()=>process.exit(3));
worker.on('exit', code=>{ if(code!==0)process.exit(4); const h=a.tryAcquireReminderMutex(key);
  console.log(h ? 'acquired' : 'busy'); if(h)a.releaseReminderMutex(h.handle); });
"""
    result = node(addon, key, source)
    assert result.returncode == 0 and result.stdout.strip() == "acquired"


def test_electron_crash_abandons_mutex_and_python_reports_uncertain(addon):
    import ctypes
    from ctypes import wintypes

    key = secrets.token_hex(32)
    env = {**os.environ, "MUTEX_TEST_ADDON": addon, "MUTEX_TEST_KEY": key}
    source = "const a=require(process.env.MUTEX_TEST_ADDON); let h=a.tryAcquireReminderMutex(process.env.MUTEX_TEST_KEY); if(!h)process.exit(2); h=null; global.gc(); console.log('held'); process.stdin.resume()"
    child = subprocess.Popen(["node", "--expose-gc", "-e", source], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateMutexW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    keep = None
    try:
        ready = Queue()
        threading.Thread(target=lambda: ready.put(child.stdout.readline()), daemon=True).start()
        assert ready.get(timeout=10).strip() == "held"
        start = time.monotonic()
        assert _try_digest(key) is None
        assert time.monotonic() - start < 1
        # Keep the kernel object alive after the owner exits so Windows can
        # expose WAIT_ABANDONED to its next owner.
        keep = api.CreateMutexW(None, False, "Local\\Vibelution.ReminderSource.v1." + key)
        assert keep
        child.kill(); child.wait(timeout=10)
        lease = _try_digest(key)
        assert lease is not None and lease.abandoned is True
        lease.release()
        again = _try_digest(key)
        assert again is not None and again.abandoned is False
        again.release()
    finally:
        if child.poll() is None:
            child.kill(); child.wait(timeout=10)
        if keep:
            api.CloseHandle(keep)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream:
                stream.close()


def test_python_crash_is_reported_abandoned_to_electron(addon):
    import ctypes
    from ctypes import wintypes

    key = secrets.token_hex(32)
    env = {**os.environ, "MUTEX_TEST_KEY": key}
    source = "import os,sys; from core.infrastructure.reminder_source_mutex import _try_digest; h=_try_digest(os.environ['MUTEX_TEST_KEY']); print('held' if h else 'busy',flush=True); sys.stdin.read()"
    child = subprocess.Popen([sys.executable, "-c", source], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateMutexW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    keep = None
    try:
        ready = Queue()
        threading.Thread(target=lambda: ready.put(child.stdout.readline()), daemon=True).start()
        assert ready.get(timeout=10).strip() == "held"
        keep = api.CreateMutexW(None, False, "Local\\Vibelution.ReminderSource.v1." + key)
        assert keep
        child.kill(); child.wait(timeout=10)
        result = node(addon, key, "const a=require(process.env.MUTEX_TEST_ADDON),h=a.tryAcquireReminderMutex(process.env.MUTEX_TEST_KEY); if(!h)process.exit(2); console.log(h.abandoned); a.releaseReminderMutex(h.handle)")
        assert result.returncode == 0 and result.stdout.strip() == "true"
    finally:
        if child.poll() is None:
            child.kill(); child.wait(timeout=10)
        if keep:
            api.CloseHandle(keep)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream:
                stream.close()


def test_untrusted_values_cannot_be_passed_as_observations():
    from core.infrastructure.reminder_source_mutex import try_acquire_reminder_source_mutex, trusted_reminder_source_mutex_key
    with pytest.raises(ReminderMutexError, match="reminder_mutex_invalid"):
        try_acquire_reminder_source_mutex({"ledgerKey": "a" * 64})
    with pytest.raises(ReminderMutexError, match="reminder_mutex_invalid"):
        trusted_reminder_source_mutex_key("a" * 64)


def test_trusted_observation_uses_the_same_mutex_in_both_runtimes(addon, setup_preview):
    from core.assistant_runtime.reminder_source_identity import observe_reminder_source
    from core.infrastructure.reminder_source_mutex import try_acquire_reminder_source_mutex, trusted_reminder_source_mutex_key
    dispatch, workspace, _ = setup_preview
    registry = workspace / "agents/agents.json"
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["agents"][0]["primaryMode"] = "general"
    registry.write_text(json.dumps(data), encoding="utf-8")
    root = dispatch._admitted_projects()["registered:1"]
    ledger = root / "agents/agent-pa/plugins/personal-affairs/affairs/items.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("", encoding="utf-8")
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as source:
        key = trusted_reminder_source_mutex_key(source)
        with try_acquire_reminder_source_mutex(source) as lease:
            lease.check()
            result = node(addon, key, "const a=require(process.env.MUTEX_TEST_ADDON); console.log(a.tryAcquireReminderMutex(process.env.MUTEX_TEST_KEY)===null?'busy':'bad')")
            assert result.returncode == 0 and result.stdout.strip() == "busy"
            registry.write_text(registry.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with pytest.raises(ValueError):
                lease.check()
