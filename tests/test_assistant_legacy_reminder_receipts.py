import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from core.assistant_runtime.legacy_reminder_receipts import LegacyReminderReceipts
from core.assistant_runtime.reminder_receipts import ReminderReceiptError


NOW = datetime(2026, 10, 28, 1, tzinfo=timezone.utc)
SOURCE = "a" * 64
EVENT = "affair-reminder:fictional-item:20261028"


def owner(path):
    return LegacyReminderReceipts(path, clock=lambda: NOW)


def test_reservation_is_scoped_and_only_owner_can_settle(tmp_path):
    root = tmp_path / "legacy-receipts"
    store = owner(root)
    request = {"sourceKey": SOURCE, "eventId": EVENT}
    first = store.reserve(request)
    assert first["state"] == "reserved" and len(first["attemptToken"]) == 64
    assert first["eventKey"] == "legacy:f1889ea2d4f47cf2288166d5ff33ba0a7fd8a99c4f3d89aab03d262ad051c623"
    duplicate = store.reserve(request)
    assert duplicate == {"schemaVersion": 1, "eventKey": first["eventKey"], "state": "pending"}
    other = store.reserve({**request, "sourceKey": "b" * 64})
    assert other["state"] == "reserved" and other["eventKey"] != first["eventKey"]
    with pytest.raises(ReminderReceiptError, match="receipt_attempt_owner_required"):
        store.settle({**request, "attemptToken": other["attemptToken"], "channel": "system_notification"})
    settled = store.settle({**request, "attemptToken": first["attemptToken"], "channel": "system_notification"})
    assert settled == {"schemaVersion": 1, "eventKey": first["eventKey"],
                       "state": "submitted", "channel": "system_notification"}
    store.close()
    reopened = owner(root)
    assert reopened.reserve(request) == {"schemaVersion": 1, "eventKey": first["eventKey"],
                                         "state": "submitted", "channel": "system_notification"}
    assert reopened.reserve({**request, "sourceKey": "b" * 64})["state"] == "pending"
    reopened.close()


def test_only_one_competing_thread_reserves(tmp_path):
    root = tmp_path / "legacy-receipts"
    initial = owner(root)
    initial._store("20261028", create=True)
    initial.close()
    barrier = threading.Barrier(2)

    def compete():
        store = owner(root)
        try:
            barrier.wait(timeout=5)
            result = store.reserve({"sourceKey": SOURCE, "eventId": EVENT})
            if result["state"] == "reserved":
                store.settle({"sourceKey": SOURCE, "eventId": EVENT,
                              "attemptToken": result["attemptToken"], "channel": "assistant_window"})
            return result
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: compete(), range(2)))
    assert [r["state"] for r in results].count("reserved") == 1
    assert sum("attemptToken" in r for r in results) == 1
    assert {r["eventKey"] for r in results} == {results[0]["eventKey"]}


def test_process_death_preserves_unknown_attempt_without_replay(tmp_path):
    root = tmp_path / "legacy-receipts"
    script = r'''
import os, sys
from datetime import datetime, timezone
from pathlib import Path
from core.assistant_runtime.legacy_reminder_receipts import LegacyReminderReceipts
o = LegacyReminderReceipts(Path(sys.argv[1]), clock=lambda: datetime(2026,10,28,1,tzinfo=timezone.utc))
r = o.reserve({"sourceKey": "a" * 64, "eventId": "affair-reminder:fictional-item:20261028"})
assert r["state"] == "reserved"
os._exit(0)
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, str(root)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env=os.environ.copy(), timeout=30, check=False,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0
    reopened = owner(root)
    pending = reopened.reserve({"sourceKey": SOURCE, "eventId": EVENT})
    assert pending["state"] == "pending" and "attemptToken" not in pending
    reopened.close()


def test_request_validation_fails_before_creating_ledger(tmp_path):
    root = tmp_path / "legacy-receipts"
    store = owner(root)
    for request in ({"sourceKey": SOURCE, "eventId": EVENT, "path": "ignored"},
                    {"sourceKey": "not-trusted", "eventId": EVENT},
                    {"sourceKey": SOURCE, "eventId": "affair-reminder:fictional-item:20261027"}):
        with pytest.raises(ReminderReceiptError):
            store.reserve(request)
    assert not root.exists()
    store.close()


def test_owner_is_thread_bound_and_invalid_settlement_keeps_pending(tmp_path):
    store = owner(tmp_path / "legacy-receipts")
    request = {"sourceKey": SOURCE, "eventId": EVENT}
    reservation = store.reserve(request)
    with pytest.raises(ReminderReceiptError, match="legacy_reminder_request_invalid"):
        store.settle({**request, "attemptToken": reservation["attemptToken"], "channel": []})
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(store.reserve, request)
        with pytest.raises(ReminderReceiptError, match="legacy_reminder_owner_closed"):
            future.result()
    assert store.reserve(request)["state"] == "pending"
    store.close()


def test_old_owner_cannot_open_historical_days_by_settling(tmp_path):
    root = tmp_path / "legacy-receipts"
    previous = LegacyReminderReceipts(root, clock=lambda: datetime(2026, 10, 27, 1, tzinfo=timezone.utc))
    request = {"sourceKey": SOURCE, "eventId": "affair-reminder:fictional-item:20261027"}
    reservation = previous.reserve(request)
    previous.close()

    current = owner(root)
    with pytest.raises(ReminderReceiptError, match="receipt_attempt_owner_required"):
        current.settle({**request, "attemptToken": reservation["attemptToken"], "channel": "system_notification"})
    assert current.stores == {}
    current.close()


def test_unknown_attempts_across_more_than_32_days_remain_pending(tmp_path):
    now = [NOW]
    store = LegacyReminderReceipts(tmp_path / "legacy-receipts", clock=lambda: now[0])
    first = None
    for offset in range(35):
        now[0] = NOW + timedelta(days=offset)
        request = {"sourceKey": SOURCE, "eventId": "affair-reminder:fixture:" + now[0].strftime("%Y%m%d")}
        reservation = store.reserve(request)
        assert reservation["state"] == "reserved"
        assert len(store.stores) <= 32
        if first is None:
            first = (request, reservation["attemptToken"])
    with pytest.raises(ReminderReceiptError, match="receipt_attempt_owner_required"):
        store.settle({**first[0], "attemptToken": first[1], "channel": "system_notification"})
    now[0] = NOW
    assert store.reserve(first[0])["state"] == "pending"
    with pytest.raises(ReminderReceiptError, match="receipt_attempt_owner_required"):
        store.settle({**first[0], "attemptToken": first[1], "channel": "system_notification"})
    store.close()
    reopened = owner(tmp_path / "legacy-receipts")
    assert reopened.reserve(first[0])["state"] == "pending"
    reopened.close()


def test_delayed_settlement_before_capacity_preserves_live_owner(tmp_path):
    now = [NOW]
    store = LegacyReminderReceipts(tmp_path / "legacy-receipts", clock=lambda: now[0])
    request = {"sourceKey": SOURCE, "eventId": EVENT}
    token = store.reserve(request)["attemptToken"]
    now[0] += timedelta(days=1)
    store.reserve({"sourceKey": SOURCE, "eventId": "affair-reminder:fixture:20261029"})
    assert store.settle({**request, "attemptToken": token, "channel": "assistant_window"})["state"] == "submitted"
    now[0] = NOW
    assert store.reserve(request)["state"] == "submitted"
    store.close()


def test_abandon_checks_token_and_fences_late_settlement(tmp_path):
    store = owner(tmp_path / "legacy-receipts")
    request = {"sourceKey": SOURCE, "eventId": EVENT}
    attempt = store.reserve(request)
    token = attempt["attemptToken"]
    other = store.reserve({**request, "sourceKey": "b" * 64})
    with pytest.raises(ReminderReceiptError, match="receipt_attempt_owner_required"):
        store.abandon({**request, "attemptToken": other["attemptToken"]})
    assert store.abandon({**request, "attemptToken": token})["state"] == "abandoned"
    with pytest.raises(ReminderReceiptError, match="receipt_attempt_owner_required"):
        store.settle({**request, "attemptToken": token, "channel": "system_notification"})
    assert store.reserve(request)["state"] == "pending"
    store.close()
    reopened = owner(tmp_path / "legacy-receipts")
    assert reopened.reserve(request)["state"] == "pending"
    with pytest.raises(ReminderReceiptError, match="receipt_attempt_owner_required"):
        reopened.abandon({**request, "attemptToken": token})
    reopened.close()


def test_settlement_before_abandon_cannot_be_undone(tmp_path):
    store = owner(tmp_path / "legacy-receipts")
    request = {"sourceKey": SOURCE, "eventId": EVENT}
    token = store.reserve(request)["attemptToken"]
    assert store.settle({**request, "attemptToken": token, "channel": "assistant_window"})["state"] == "submitted"
    with pytest.raises(ReminderReceiptError, match="receipt_attempt_owner_required"):
        store.abandon({**request, "attemptToken": token})
    assert store.reserve(request)["state"] == "submitted"
    store.close()


def test_private_host_reserve_settle_and_shutdown_use_one_owned_thread(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import core.assistant_runtime.host as host
    import core.assistant_runtime.legacy_reminder_receipts as receipts

    calls = []
    class Owner(LegacyReminderReceipts):
        def __init__(self, path):
            super().__init__(path)
            calls.append(("init", threading.get_ident()))
        def reserve(self, request):
            calls.append(("reserve", threading.get_ident()))
            return super().reserve(request)
        def settle(self, request):
            calls.append(("settle", threading.get_ident()))
            return super().settle(request)
        def abandon(self, request):
            calls.append(("abandon", threading.get_ident()))
            return super().abandon(request)
        def close(self):
            calls.append(("close", threading.get_ident()))
            super().close()

    class Native:
        root = tmp_path
        assistant = {"agentId": "native", "directSessionId": "session"}
        def bootstrap(self): return {"assistant": self.assistant}
        def shutdown(self): pass

    monkeypatch.setattr(host, "NativeFacade", Native)
    monkeypatch.setattr(receipts, "LegacyReminderReceipts", Owner)
    event = "affair-reminder:fixture:" + datetime.now(timezone.utc).strftime("%Y%m%d")
    request = {"sourceKey": SOURCE, "eventId": event}
    headers = {"Authorization": "Bearer private-test-token"}
    with TestClient(host.create_app(native=Native(), token="private-test-token"), base_url="http://127.0.0.1") as client:
        path = "/api/assistant/legacy-reminders/reserve"
        assert client.post(path, json=request).status_code == 401
        assert client.post(path, json=request, headers={**headers, "Origin": "http://127.0.0.1"}).status_code == 403
        assert client.post(path, json={**request, "agentId": "untrusted"}, headers=headers).status_code == 422
        assert client.post(path + "?extra=1", json=request, headers=headers).status_code == 422
        response = client.post(path, json=request, headers=headers)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        reservation = response.json()
        assert reservation["state"] == "reserved"
        duplicate = client.post(path, json=request, headers=headers).json()
        assert duplicate["state"] == "pending" and "attemptToken" not in duplicate
        settled = client.post("/api/assistant/legacy-reminders/settle", headers=headers,
                              json={**request, "attemptToken": reservation["attemptToken"], "channel": "system_notification"})
        assert settled.json()["state"] == "submitted"
        other_request = {**request, "sourceKey": "b" * 64}
        other = client.post(path, json=other_request, headers=headers).json()
        abandoned = client.post("/api/assistant/legacy-reminders/abandon", headers=headers,
                                json={**other_request, "attemptToken": other["attemptToken"]})
        assert abandoned.json()["state"] == "abandoned"
        assert client.post(path, json=other_request, headers=headers).json()["state"] == "pending"
    assert [name for name, _ in calls] == ["init", "reserve", "reserve", "settle", "reserve", "abandon", "reserve", "close"]
    assert len({thread for _, thread in calls}) == 1
