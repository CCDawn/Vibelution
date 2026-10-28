"""Recovery confirmation requires both the drained result and its original claim."""
import json

from core.assistant_runtime.knowledge_recovery_result import read_verified_recovery_job_result
from tests.test_assistant_knowledge_sync_launcher import _record


def test_recovery_result_rejects_missing_or_corrupt_attempt_and_claim(tmp_path):
    root = tmp_path / 'native'; root.mkdir()
    operation = 'krec-' + 'a' * 40
    assert read_verified_recovery_job_result(root, operation) is None
    _record(root, operation + '.attempt', 'unknown')
    assert read_verified_recovery_job_result(root, operation) == 'unknown'
    _record(root, operation, 'completed')
    assert read_verified_recovery_job_result(root, operation) == 'unknown'
    claim = root / 'initial_migration_claims' / operation / 'claim.json'
    claim.parent.mkdir(parents=True)
    claim.write_text(json.dumps({'schemaVersion':1, 'operationId':operation, 'category':'knowledge_recovery'}), encoding='utf-8')
    assert read_verified_recovery_job_result(root, operation) == 'completed'
    claim.write_text('{}', encoding='utf-8')
    assert read_verified_recovery_job_result(root, operation) == 'unknown'
    claim.write_text(json.dumps({'schemaVersion':1, 'operationId':operation, 'category':'knowledge_recovery'}), encoding='utf-8')
    import hashlib
    attempt = root.parent / 'initial-migration-results' / (hashlib.sha256((operation + '.attempt').encode()).hexdigest() + '.json')
    attempt.write_text('{}', encoding='utf-8')
    assert read_verified_recovery_job_result(root, operation) == 'unknown'


def test_recovery_job_with_verified_no_start_is_terminal_and_retryable(tmp_path):
    root = tmp_path / 'native'; root.mkdir()
    operation = 'krec-' + 'b' * 40
    _record(root, operation + '.attempt', 'unknown')
    _record(root, operation, 'not_started')
    assert read_verified_recovery_job_result(root, operation) == 'not_started'
    claim = root / 'initial_migration_claims' / operation / 'claim.json'
    claim.parent.mkdir(parents=True); claim.write_text('{}')
    assert read_verified_recovery_job_result(root, operation) == 'unknown'
