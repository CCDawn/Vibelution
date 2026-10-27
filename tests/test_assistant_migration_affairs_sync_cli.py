"""Synthetic end-to-end reconciliation via the existing offline subprocess."""
import json

from tests.test_assistant_migration_cli import AGENT, active_personal_case, call


def test_target_outcome_is_not_misreported_as_source_change():
    from scripts.assistant_migration_activate import mark_reconciliation
    result = {}
    mark_reconciliation(result, 'sync', 'affairs_sync_outcome_unknown')
    assert result['outcomeUnknown'] and result['requiresReconciliation']
    assert 'sourceValidation' not in result and not result['readyForCutover']


def test_offline_sync_keeps_divergent_target_and_imports_new_item(tmp_path, monkeypatch, capsys):
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    assert call(monkeypatch, *args) == 0
    capsys.readouterr()
    source = workspace / 'agents' / AGENT / 'plugins/personal-affairs/affairs/items.jsonl'
    row = json.loads(source.read_text(encoding='utf-8'))
    source.write_text(json.dumps({**row, 'title': 'source edit'}) + '\n'
        + json.dumps({**row, 'itemId': 'new', 'title': 'source addition'}) + '\n', encoding='utf-8')
    ledger = next(target.glob('agents/*/plugins/personal-affairs/affairs/items.jsonl'))
    ledger.write_text(json.dumps({**row, 'title': 'user edit'}) + '\n', encoding='utf-8')
    sync_args = ('--sync-affairs', AGENT, '--source-config', args[3],
        '--target-profile', target, '--target-config', args[7], '--migration-id', 'cli-final',
        '--baseline-migration-id', 'cli-activation')
    assert call(monkeypatch, *sync_args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'partial' and report['sync']['appliedCount'] == 1
    assert report['sync']['conflictCount'] == 1 and not report['readyForCutover']
    archive = json.loads((target / 'history_sources/migrations/cli-final/manifest.json').read_text(encoding='utf-8'))
    assert {entry['category'] for entry in archive['entries']} == {'personal_affairs'}
    assert not archive['snapshotCompleteAtScan']
    rows = [json.loads(line) for line in ledger.read_text(encoding='utf-8').splitlines()]
    assert {r['itemId']: r['title'] for r in rows} == {'old-todo': 'user edit', 'new': 'source addition'}
    assert call(monkeypatch, *sync_args) == 0
    retry = json.loads(capsys.readouterr().out)
    assert retry['sync']['reused'] and retry['sync']['conflictCount'] == 1
    assert [json.loads(line) for line in ledger.read_text(encoding='utf-8').splitlines()] == rows
