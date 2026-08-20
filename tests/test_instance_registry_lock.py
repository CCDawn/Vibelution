import json
import statistics
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.runtime_manager import instance_lock as lock
from core.runtime_manager import instances_registry as registry

PROTOCOL_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "launcher"
    / "instance_lock_protocol.json"
)


@pytest.fixture
def registry_file(tmp_path, monkeypatch):
    path = tmp_path / "Vibelution" / "instances.json"
    monkeypatch.setattr(registry, "instances_registry_path", lambda: path)
    return path


def _load_protocol() -> dict:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def test_protocol_constants_match_shared_fixture():
    protocol = _load_protocol()
    assert protocol["protocolVersion"] == 2
    assert lock.LOCKDIR_SUFFIX == protocol["lockdirSuffix"]
    assert lock.HOLDER_FILE_NAME == protocol["holderFileName"]
    assert lock.LOCK_POLL_SECONDS * 1000 == protocol["pollMs"]
    assert lock.LOCK_TIMEOUT_SECONDS * 1000 == protocol["timeoutMs"]
    assert lock.LOCK_STALE_SECONDS * 1000 == protocol["staleMs"]
    assert lock.MISSING_HOLDER_GRACE_SECONDS * 1000 == protocol["missingHolderGraceMs"]
    assert lock.LOCK_STALE_BROKEN_EVENT == protocol["staleBrokenEvent"]
    assert lock.LOCK_STALE_BROKEN_EVENT == "launcher.registry.lock_stale_broken"


def test_second_acquirer_waits_then_succeeds(registry_file):
    released = threading.Event()
    waited_ms: list[float] = []

    def holder() -> None:
        with lock.hold_instance_lock(registry_file):
            time.sleep(0.2)
        released.set()

    def waiter() -> None:
        started = time.perf_counter()
        with lock.hold_instance_lock(registry_file, timeout_seconds=2):
            waited_ms.append((time.perf_counter() - started) * 1000.0)

    first = threading.Thread(target=holder)
    second = threading.Thread(target=waiter)
    first.start()
    time.sleep(0.05)
    second.start()
    first.join(timeout=3)
    second.join(timeout=3)
    assert released.is_set()
    assert waited_ms and 120 <= waited_ms[0] <= 1500
    assert not lock.instance_lockdir_path(registry_file).exists()


def test_timeout_while_lock_held(registry_file):
    barrier = threading.Event()
    done = threading.Event()

    def holder() -> None:
        with lock.hold_instance_lock(registry_file):
            barrier.set()
            done.wait(timeout=3)

    thread = threading.Thread(target=holder)
    thread.start()
    assert barrier.wait(timeout=2)
    with pytest.raises(lock.InstanceLockTimeoutError), lock.hold_instance_lock(
        registry_file, timeout_seconds=0.15
    ):
        pass
    done.set()
    thread.join(timeout=3)


def test_stale_lock_is_broken_and_emits_event(registry_file):
    events: list[tuple[str, dict]] = []
    started_at = datetime.now(UTC) - timedelta(seconds=11)
    lock.plant_lockdir(registry_file, pid=4242, started_at=started_at)

    with lock.hold_instance_lock(registry_file, emit_event=lambda name, payload: events.append((name, payload))):
        holder = lock.read_lock_holder(lock.instance_lockdir_path(registry_file))
        assert holder is not None
        assert holder["pid"] == __import__("os").getpid()

    assert events
    name, payload = events[0]
    assert name == "launcher.registry.lock_stale_broken"
    assert payload["previousPid"] == 4242
    assert payload["reason"] == "stale_started_at"
    assert not lock.instance_lockdir_path(registry_file).exists()


def test_missing_holder_after_grace_is_broken(registry_file):
    events: list[tuple[str, dict]] = []
    lockdir = lock.instance_lockdir_path(registry_file)
    lockdir.mkdir(parents=True)
    time.sleep(0.15)

    with lock.hold_instance_lock(
        registry_file,
        missing_holder_grace_seconds=0.1,
        emit_event=lambda name, payload: events.append((name, payload)),
    ):
        pass

    assert events[0][0] == "launcher.registry.lock_stale_broken"
    assert events[0][1]["reason"] == "missing_holder"


def test_lock_roundtrip_overhead_stays_under_50ms(registry_file):
    samples: list[float] = []
    for _ in range(20):
        started = time.perf_counter()
        with lock.hold_instance_lock(registry_file):
            pass
        samples.append((time.perf_counter() - started) * 1000.0)
    assert statistics.median(samples) < 50


def test_registry_upsert_uses_lockdir_and_releases(registry_file):
    registry.upsert_instance("worktree:task", port=8000)
    lockdir = lock.instance_lockdir_path(registry_file)
    stale_lock_file = registry_file.with_name(f"{registry_file.name}.lock")
    assert registry.get_instance("worktree:task")["port"] == 8000
    assert not lockdir.exists()
    assert not stale_lock_file.exists()
