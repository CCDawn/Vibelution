"""Reminder handoff rejects cutover in real, isolated native processes."""
from __future__ import annotations

import textwrap

from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


_SETUP = r'''
import hashlib, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
def no_network(event, _args):
    if event == 'socket.connect':
        raise AssertionError('reminder preview must not contact a provider')
sys.addaudithook(no_network)
from core.assistant_runtime import migration_reminders as reminders
from core.assistant_runtime.migration_affairs import import_affairs
from core.assistant_runtime.migration_io import MigrationIOError, read_stable_file
from core.assistant_runtime.migration_profile import offline_migration_profile
from core.web.services import personal_affairs_service
root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
source = root.parent / 'legacy/agents/old-pa/plugins/personal-affairs/affairs/items.jsonl'
source.parent.mkdir(parents=True, exist_ok=True)
rows = [
    {'schemaVersion': 1, 'itemId': 'overdue', 'kind': 'todo', 'title': 'PRIVATE_TITLE',
     'note': 'PRIVATE_NOTE', 'status': 'open', 'dueAt': '2026-10-26T00:00:00Z',
     'createdAt': '2026-10-01T00:00:00Z'},
    {'schemaVersion': 1, 'itemId': 'today', 'kind': 'schedule', 'title': 'PRIVATE_TITLE',
     'status': 'open', 'dueAt': '2026-10-27T23:00:00Z', 'createdAt': '2026-10-01T00:00:00Z'},
    {'schemaVersion': 1, 'itemId': 'future', 'kind': 'goal', 'title': 'PRIVATE_TITLE',
     'status': 'open', 'dueAt': '2026-11-01T00:00:00Z', 'createdAt': '2026-10-01T00:00:00Z'},
    {'schemaVersion': 1, 'itemId': 'done', 'kind': 'todo', 'title': 'PRIVATE_TITLE',
     'status': 'done', 'dueAt': '2026-10-26T00:00:00Z', 'createdAt': '2026-10-01T00:00:00Z'},
    {'schemaVersion': 1, 'itemId': 'cancelled', 'kind': 'todo', 'title': 'PRIVATE_TITLE',
     'status': 'cancelled', 'dueAt': '2026-10-26T00:00:00Z', 'createdAt': '2026-10-01T00:00:00Z'},
]
raw = b''.join(json.dumps(row).encode() + b'\n' for row in rows)
if not source.exists():
    source.write_bytes(raw)
scope = {'projectId': 'old-project', 'instanceId': 'old-instance', 'agentId': 'old-pa'}
now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
def preview(lease, **changes):
    return reminders.preview_reminder_handoff(lease, changes.pop('source', read_stable_file(source, 4096)),
        source_scope=changes.pop('source_scope', scope), now=changes.pop('now', now), **changes)
def migrate(lease):
    return import_affairs(lease, read_stable_file(source, 4096), source_scope=scope,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), migration_id='reminder-fixture')
def files():
    # An active native OS lock intentionally denies unrelated opens. Inspect
    # persisted content without trying to open its exclusively held sidecar.
    return {p: p.read_bytes() for p in root.parent.rglob('*')
            if p.is_file() and not p.name.endswith('.lock')}
def fails(code, call):
    try:
        call()
    except MigrationIOError as error:
        assert str(error) == code, str(error)
        assert 'PRIVATE' not in str(error)
    else:
        raise AssertionError('unsafe reminder observation accepted')
'''


def run(tmp_path, code):
    _run(tmp_path, _SETUP + textwrap.dedent(code), config_text=TEST_MODEL_CONFIG)


def test_matching_native_copy_still_rejects_cutover_after_process_restart(tmp_path):
    code = r'''
        with offline_migration_profile() as lease:
            migrate(lease)
            before = files()
            result = preview(lease)
            assert files() == before, 'preview changed a ledger, dedup record or receipt'
            assert result['sourceItemCount'] == result['targetItemCount'] == result['matchedItemCount'] == 5
            assert result['missingItemCount'] == result['conflictingItemCount'] == 0
            assert result['sourceDueItemCount'] == 2
            assert result['targetAgentId'] == lease.agent_id
            assert result['targetSessionId'] == lease.session_id
            assert result['currentReminderOwner'] == 'legacy_workbench_human_attention'
            assert result['readOnly'] and not result['executionAttempted']
            assert not result['readyForCutover'] and not result['sourceQuiesced']
            assert not result['deliveryStateTransferred']
            assert set(result['pendingChecks']) == {
                'source_notification_fence_unavailable', 'delivery_watermark_unavailable',
                'target_reminder_consumer_unavailable'}
            encoded = json.dumps(result)
            assert 'PRIVATE' not in encoded and str(root) not in encoded and str(source) not in encoded
            record = root.parent / 'reminder-preview-first-process.json'
            if record.exists():
                previous = json.loads(record.read_text())
                assert previous['pid'] != os.getpid()
                assert result == previous['result']
            else:
                record.write_text(json.dumps({'pid': os.getpid(), 'result': result}))
    '''
    for _ in range(2):
        run(tmp_path, code)


def test_preview_reports_missing_and_changed_items_without_importing_or_delivering(tmp_path):
    run(tmp_path, r'''
        with offline_migration_profile() as lease:
            before = files()
            absent = preview(lease)
            assert absent['targetSha256'] is None and absent['missingItemCount'] == 5
            assert 'target_affairs_missing' in absent['pendingChecks']
            assert files() == before, 'missing target preview created files'
            migrate(lease)
            service = personal_affairs_service.get_personal_affairs_service()
            service.complete_item(lease.agent_id, item_id='overdue')
            ledger = service.store._path(lease.agent_id, 'affairs/items.jsonl')
            target_rows = [json.loads(line) for line in ledger.read_bytes().splitlines()]
            service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl',
                [row for row in target_rows if row['itemId'] != 'today'])
            before = files()
            changed = preview(lease)
            assert changed['matchedItemCount'] == 3
            assert changed['missingItemCount'] == changed['conflictingItemCount'] == 1
            assert 'affairs_snapshot_mismatch' in changed['pendingChecks']
            assert not changed['readyForCutover'] and files() == before
            # A forged source quiet marker or localStorage seen entry is not
            # accepted as a capability by this closed function signature.
            try:
                preview(lease, source_quiesced=True, delivered_ids=['overdue'])
            except TypeError:
                pass
            else:
                raise AssertionError('caller flags established delivery authority')
    ''')


def test_changed_source_target_and_invalid_bindings_reject_without_mutation(tmp_path):
    run(tmp_path, r'''
        from dataclasses import replace
        from unittest.mock import patch
        with offline_migration_profile() as lease:
            migrate(lease)
            stale = read_stable_file(source, 4096)
            source.write_bytes(raw + b'\n')
            before = files()
            fails('source_changed', lambda: preview(lease, source=stale))
            assert files() == before
            source.write_bytes(raw)
            current = read_stable_file(source, 4096)
            fails('affairs_source_hash_mismatch', lambda: preview(lease,
                source=replace(current, raw=b'x' * len(current.raw))))
            fails('reminders_source_binding_invalid', lambda: preview(lease,
                source_scope={**scope, 'agentId': 'different-pa'}))
            fails('reminders_source_binding_invalid', lambda: preview(lease, source=raw))
            fails('reminders_source_scope_invalid', lambda: preview(lease, source_scope={**scope, 'quiet': True}))
            fails('reminders_aware_time_required', lambda: preview(lease, now=datetime(2026, 10, 27)))
            with patch.object(personal_affairs_service, 'PROJECT_ROOT', root.parent):
                fails('reminders_target_binding_invalid', lambda: preview(lease))
            # Change the target after its initial read. The preview must fail
            # rather than publish matching counts for an obsolete snapshot.
            service = personal_affairs_service.get_personal_affairs_service()
            verify = reminders.verify_snapshot
            def edit_at_final_read(snapshot):
                if snapshot.path == source:
                    service.complete_item(lease.agent_id, item_id='overdue')
                verify(snapshot)
            with patch.object(reminders, 'verify_snapshot', edit_at_final_read):
                fails('source_changed', lambda: preview(lease))
            assert next(row for row in service.list_items(lease.agent_id)['items']
                if row['itemId'] == 'overdue')['status'] == 'done'
            assert source.read_bytes() == raw
        fails('affairs_profile_lease_required', lambda: preview(lease))
    ''')


def test_concurrent_native_edit_and_preview_never_claim_delivery_or_cutover(tmp_path):
    run(tmp_path, r'''
        import threading
        with offline_migration_profile() as lease:
            migrate(lease)
            service = personal_affairs_service.get_personal_affairs_service()
            go, finish = threading.Event(), threading.Event()
            errors = []
            def edit():
                try:
                    go.wait(10)
                    for _ in range(12):
                        service.complete_item(lease.agent_id, item_id='overdue')
                        service.reopen_item(lease.agent_id, item_id='overdue')
                except BaseException as error:
                    errors.append(error)
                finally:
                    finish.set()
            writer = threading.Thread(target=edit)
            writer.start()
            go.set()
            observations = []
            for _ in range(12):
                try:
                    result = preview(lease)
                    assert not result['readyForCutover'] and not result['deliveryStateTransferred']
                    observations.append(result)
                except MigrationIOError as error:
                    assert str(error) in {'source_changed', 'source_unavailable_or_changed'}
            writer.join(15)
            assert finish.is_set() and not errors
            final = preview(lease)
            assert final['matchedItemCount'] == 4 and final['conflictingItemCount'] == 1
            assert not final['readyForCutover']
            assert source.read_bytes() == raw
            # Lease capabilities are thread-affine. A parallel reader cannot
            # reuse the operator's lease or create a second delivery owner.
            denied = []
            def other_reader():
                try:
                    preview(lease)
                except MigrationIOError as error:
                    denied.append(str(error))
            reader = threading.Thread(target=other_reader)
            reader.start()
            reader.join(10)
            assert denied == ['affairs_profile_lease_required']
            # A different interpreter has neither the thread capability nor
            # ownership of this same profile's OS lock. It must stop before
            # native bootstrap, observation or reminder-consumer activation.
            import subprocess
            child_code = """
import sys
def no_network(event, _args):
    if event == 'socket.connect':
        raise AssertionError('competing preview contacted a provider')
sys.addaudithook(no_network)
from core.assistant_runtime import native
from core.assistant_runtime.migration_profile import offline_migration_profile
try:
    with offline_migration_profile():
        raise AssertionError('competing process acquired live target profile')
except TimeoutError:
    assert not native._STARTED
    print('profile_busy')
"""
            ledger = service.store._path(lease.agent_id, 'affairs/items.jsonl')
            ledger_before = ledger.read_bytes()
            child = subprocess.run([sys.executable, '-c', child_code], capture_output=True,
                text=True, encoding='utf-8', timeout=20,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            assert child.returncode == 0 and child.stdout.strip() == 'profile_busy', child.stderr
            assert ledger.read_bytes() == ledger_before and source.read_bytes() == raw
    ''')
