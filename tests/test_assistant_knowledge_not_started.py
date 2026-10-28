"""No-start proof is usable only with the main fence and no business trace."""
from core.assistant_runtime.knowledge_not_started import read_verified_not_started
from core.assistant_runtime.migration_knowledge import _digest
from tests.test_assistant_knowledge_sync_launcher import _record


def test_not_started_requires_intact_main_records_and_no_claim_or_plan(tmp_path):
    root = tmp_path / 'native'; root.mkdir()
    operation = 'ksync-' + 'a' * 40
    _record(root, operation + '.attempt', 'unknown')
    assert not read_verified_not_started(root, operation)
    _record(root, operation, 'not_started')
    assert read_verified_not_started(root, operation)
    plan = root / 'knowledge_migrations/sync_operations' / (_digest(operation) + '.plan.json')
    plan.parent.mkdir(parents=True)
    plan.write_text('{}')
    assert not read_verified_not_started(root, operation)
    plan.unlink()
    item_dir = root / 'knowledge_migrations/sync_items' / _digest(operation)
    item_dir.mkdir(parents=True)
    assert not read_verified_not_started(root, operation)
    item_dir.rmdir()
    claim = root / 'initial_migration_claims' / operation / 'claim.json'
    claim.parent.mkdir(parents=True)
    claim.write_text('{}')
    assert not read_verified_not_started(root, operation)
    claim.unlink(); claim.parent.rmdir()
    assert read_verified_not_started(root, operation)
    import hashlib
    attempt = root.parent / 'initial-migration-results' / (hashlib.sha256((operation + '.attempt').encode()).hexdigest() + '.json')
    attempt.write_text('{}')
    assert not read_verified_not_started(root, operation)
