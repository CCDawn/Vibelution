import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, timezone

import pytest

from core.assistant_runtime.reminder_receipts import ReminderReceiptError, ReminderReceiptStore
from core.assistant_runtime.reminder_source_identity import observe_reminder_source
from core.assistant_runtime.legacy_reminder_receipts import LegacyReminderReceipts
from core.infrastructure.reminder_source_mutex import trusted_reminder_source_mutex_key
from tests.test_assistant_history_preview import setup_preview  # noqa: F401
from tests.test_assistant_reminder_source_identity import prepare


def event(item_id, day="20261028"):
    return f"reminder:{day}:" + hashlib.sha256(item_id.encode("utf-8")).hexdigest()


def test_unknown_attempts_survive_reopen_without_fake_delivery_or_sender(tmp_path, setup_preview):
    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    root = tmp_path / "target" / "20261028"
    old = [event("affair-a"), event("affair-b")]
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as source:
        key = trusted_reminder_source_mutex_key(source)
        with ReminderReceiptStore(root, owner_id="target-owner", maximum=4, create=True) as store:
            assert store.suppress_legacy_events(old, source_observation=source, ledger_key=key, check_source=lambda: None) == {"created": 2, "retained": 0}
            assert store.suppress_legacy_events(old, source_observation=source, ledger_key=key, check_source=lambda: None) == {"created": 0, "retained": 2}
            for event_id in old:
                assert store.get(event_id)["state"] == "pending"
                result = store.reserve(event_id)
                assert result["created"] is False and "attemptToken" not in result
            assert store.drain_status()["registeredSenders"] == 0
            assert store.drain_status()["inflightAttempts"] == 0
            new_event = store.reserve(event("new-item"))
            assert new_event["created"] is True
            store.record_submitted(event("new-item"), new_event["attemptToken"], channel="system_notification")
        with ReminderReceiptStore(root, owner_id="target-owner", maximum=4) as reopened:
            for event_id in old:
                assert reopened.get(event_id)["state"] == "pending"
                assert reopened.reserve(event_id)["created"] is False
            assert reopened.get(event("new-item"))["state"] == "submitted"


def test_invalid_source_and_revocation_fail_closed_with_atomic_batch(tmp_path, setup_preview):
    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    root = tmp_path / "target" / "20261028"
    ids = [event("first"), event("second")]
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as source:
        key = trusted_reminder_source_mutex_key(source)
        with ReminderReceiptStore(root, owner_id="target-owner", maximum=4, create=True) as store:
            with pytest.raises(ReminderReceiptError, match="source_unavailable"):
                store.suppress_legacy_events(ids, source_observation=source, ledger_key="a" * 64, check_source=lambda: None)
            calls = [0]
            def revoked():
                calls[0] += 1
                return False if calls[0] == 3 else None
            with pytest.raises(ReminderReceiptError, match="source_unavailable"):
                store.suppress_legacy_events(ids, source_observation=source, ledger_key=key, check_source=revoked)
            assert [store.get(item) for item in ids] == [None, None]
            with pytest.raises(ReminderReceiptError, match="suppression_invalid"):
                store.suppress_legacy_events([event("wrong-day", "20261029")], source_observation=source, ledger_key=key, check_source=lambda: None)
            calls[0] = 0
            def lost_ack():
                calls[0] += 1
                return False if calls[0] == 4 else None
            with pytest.raises(ReminderReceiptError, match="source_unavailable"):
                store.suppress_legacy_events(ids, source_observation=source, ledger_key=key, check_source=lost_ack)
            assert all(store.get(item)["state"] == "pending" for item in ids)
            assert all(store.reserve(item)["created"] is False for item in ids)


def test_live_or_fallback_attempt_conflict_rolls_back_the_complete_batch(tmp_path, setup_preview):
    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    root = tmp_path / "target" / "20261028"
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as source:
        key = trusted_reminder_source_mutex_key(source)
        with ReminderReceiptStore(root, owner_id="target-owner", maximum=4, create=True) as store:
            active = store.reserve(event("active"))
            with pytest.raises(ReminderReceiptError, match="suppression_conflict"):
                store.suppress_legacy_events([event("fresh"), event("active")], source_observation=source, ledger_key=key, check_source=lambda: None)
            assert store.get(event("fresh")) is None
            store.record_submitted(event("active"), active["attemptToken"], channel="attention_fallback")
            with pytest.raises(ReminderReceiptError, match="suppression_conflict"):
                store.suppress_legacy_events([event("active")], source_observation=source, ledger_key=key, check_source=lambda: None)
            assert store.get(event("active"))["channel"] == "attention_fallback"


def test_capacity_failure_does_not_publish_a_partial_day(tmp_path, setup_preview):
    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    root = tmp_path / "target" / "20261028"
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as source:
        key = trusted_reminder_source_mutex_key(source)
        with ReminderReceiptStore(root, owner_id="target-owner", maximum=2, create=True) as store:
            existing = store.reserve(event("existing"))
            store.record_submitted(event("existing"), existing["attemptToken"], channel="system_notification")
            with pytest.raises(ReminderReceiptError, match="capacity_exceeded"):
                store.suppress_legacy_events([event("first"), event("second")], source_observation=source,
                                             ledger_key=key, check_source=lambda: None)
            assert store.get(event("first")) is None
            assert store.get(event("second")) is None


def test_electron_mapping_to_real_target_receipts_across_reopen(tmp_path, setup_preview):
    node = shutil.which("node")
    if node is None or os.name != "nt":
        pytest.skip("Windows and Node are required")
    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    repo = Path(__file__).resolve().parents[1]
    desktop = repo / "desktop/electron"
    source_key = "b" * 64
    first, second = "affair-reminder:first:20261028", "affair-reminder:second:20261028"
    receipts = LegacyReminderReceipts(tmp_path / "old-host-receipts", clock=lambda: datetime(2026, 10, 28, 1, tzinfo=timezone.utc))
    prior = receipts.reserve({"sourceKey": source_key, "eventId": first})
    receipts.settle({"sourceKey": source_key, "eventId": first, "attemptToken": prior["attemptToken"], "channel": "system_notification"})
    receipts.reserve({"sourceKey": source_key, "eventId": second})
    evidence = receipts.inventory()
    receipts.close()
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(json.dumps(evidence), encoding="utf-8")
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as source:
        ledger_key = trusted_reminder_source_mutex_key(source)
        entry = tmp_path / "mapping.ts"
        evidence_module = (desktop / "src/notifications/legacyReminderEvidence.ts").as_posix()
        coordinator_module = (desktop / "src/notifications/legacyReminderCoordinator.ts").as_posix()
        entry.write_text(f"""
import {{ readFileSync }} from 'node:fs';
import {{ join }} from 'node:path';
import {{ LegacyReminderEvidenceIndex, mapLegacyReminderSuppressions }} from {json.dumps(evidence_module)};
import {{ LegacyReminderDailyIntentStores }} from {json.dumps(coordinator_module)};
const root=process.env.TEST_MAPPING_ROOT, ledgerKey=process.env.TEST_MAPPING_LEDGER, sourceKey={json.dumps(source_key)};
const index=new LegacyReminderEvidenceIndex(join(root,'index'),()=>{{}});
await index.begin(ledgerKey,sourceKey,{json.dumps(first)});
await index.begin(ledgerKey,sourceKey,{json.dumps(second)});
await index.settle(ledgerKey,sourceKey,{json.dumps(first)});
const old=join(root,'old-intents'), stores=new LegacyReminderDailyIntentStores(old);
for(const row of index.inventory()) await stores.forDay(row.eventId.slice(-8)).reserve({{requestId:'legacy_'+row.eventKey.slice(7),projectId:'legacy-reminder-source',operation:'start'}});
const plan=mapLegacyReminderSuppressions({{index,oldIntentDirectory:old,receiptInventory:JSON.parse(readFileSync(process.env.TEST_MAPPING_EVIDENCE,'utf8')),
  ledger:{{ledgerKey,verify:()=>{{}}}},verifyGlobal:()=>{{}},verifyHistoryComplete:()=>{{}}}});
process.stdout.write(JSON.stringify(plan));
""", encoding="utf-8")
        output = tmp_path / "mapping.mjs"
        environment = {**os.environ, "TEST_MAPPING_ROOT": str(tmp_path), "TEST_MAPPING_LEDGER": ledger_key,
                       "TEST_MAPPING_EVIDENCE": str(evidence_file)}
        build = "require('esbuild').buildSync({entryPoints:[process.argv[1]],outfile:process.argv[2],bundle:true,platform:'node',format:'esm',logLevel:'silent'})"
        built = subprocess.run([node, "-e", build, str(entry), str(output)], cwd=desktop, env=environment,
                               capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        assert built.returncode == 0, built.stderr
        mapped = subprocess.run([node, str(output)], cwd=desktop, env=environment, capture_output=True,
                                text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        assert mapped.returncode == 0, mapped.stderr
        plan = json.loads(mapped.stdout)
        assert plan == {"schemaVersion": 1, "ledgerKey": ledger_key,
                        "days": [{"day": "20261028", "eventIds": sorted([event("first"), event("second")])}]}
        destination = tmp_path / "new-owner" / "20261028"
        with ReminderReceiptStore(destination, owner_id="target-owner", maximum=4, create=True) as store:
            assert store.suppress_legacy_events(plan["days"][0]["eventIds"], source_observation=source,
                                                ledger_key=plan["ledgerKey"], check_source=lambda: None)["created"] == 2
        with ReminderReceiptStore(destination, owner_id="target-owner", maximum=4) as store:
            assert all(store.reserve(item)["created"] is False for item in plan["days"][0]["eventIds"])
            assert all(store.get(item)["state"] == "pending" for item in plan["days"][0]["eventIds"])
            assert store.reserve(event("later"))["created"] is True
