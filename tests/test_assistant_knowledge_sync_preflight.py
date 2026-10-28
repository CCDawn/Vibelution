"""Real configuration preflight never creates a sync execution attempt."""
import json
import os
import subprocess
import sys

from core.assistant_runtime.knowledge_sync_receipt import read_drained_job_result
from scripts import assistant_migration_inventory as cli
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_invalid_source_config_does_not_fence_an_unstarted_sync(tmp_path):
    _run(tmp_path, r'''
        import os
        from pathlib import Path
        from core.assistant_runtime import native
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        native.bootstrap(root)
        assert native.shutdown()['closed']
    ''', config_text=TEST_MODEL_CONFIG)
    target = tmp_path / 'native'
    from core.infrastructure.file_lock import cross_process_file_lock
    with cross_process_file_lock(target / 'host-owner', timeout=0):
        pass
    source = tmp_path / 'source.toml'
    source.write_text('[llm]\nschema_version = 1\n', encoding='utf-8')
    operation = 'ksync-' + 'a' * 40
    digest = 'b' * 64
    snapshot = target / ('.initial-migration-models-v1-' + operation + '-' + digest + '.toml')
    env = {key:value for key,value in os.environ.items() if not key.upper().startswith('VIBELUTION_')}
    env['PYTHONIOENCODING'] = 'utf-8'
    command = [sys.executable, str(cli.ROOT / 'scripts/assistant_migration_inventory.py'), '--knowledge-preflight',
        '--source-config', str(source), '--target-profile', str(target), '--target-config', str(snapshot),
        '--operation-id', operation, '--registry-digest', digest]
    bad = subprocess.run(command, env=env, cwd=cli.ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert bad.returncode != 0 and json.loads(bad.stdout)['state'] == 'unavailable'
    assert read_drained_job_result(target, operation) is None and not snapshot.exists()
    source.write_text(TEST_MODEL_CONFIG, encoding='utf-8')
    good = subprocess.run(command, env=env, cwd=cli.ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert good.returncode == 0 and json.loads(good.stdout)['state'] == 'ready'
    assert read_drained_job_result(target, operation) is None and snapshot.is_file()
