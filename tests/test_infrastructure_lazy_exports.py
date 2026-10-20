"""Low-level infrastructure imports must not initialize unrelated services."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _cold(source):
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=ROOT,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1"),
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("leaf", ["", "atomic_io", "developer_sandbox", "git_process", "process_liveness"])
def test_low_level_imports_do_not_load_tool_or_model_services(leaf):
    _cold(f"""
        import importlib, sys
        importlib.import_module('core.infrastructure' + {('.' + leaf) if leaf else ''!r})
        for name in ('core.infrastructure.tool_executor', 'core.infrastructure.model_discovery', 'httpx'):
            assert name not in sys.modules, name
        # git_process owns a direct debug logger dependency; the package must
        # not introduce that dependency for leaves which do not use logging.
        if {leaf!r} != 'git_process':
            assert 'core.logging' not in sys.modules
    """)


def test_export_objects_and_star_import_remain_compatible():
    _cold("""
        import importlib
        import core.infrastructure as package
        expected = {
            'tool_executor': ('ToolExecutor', 'get_tool_executor'),
            'state': ('AgentState', 'StateManager', 'get_state_manager'),
            'event_bus': ('EventBus', 'EventNames', 'get_event_bus'),
            'security': ('SecurityValidator', 'get_security_validator'),
            'model_discovery': ('ModelDiscovery', 'DiscoveryStatus', 'ModelInfo', 'CompressionThresholds'),
            'workspace_manager': ('WorkspaceManager', 'get_workspace'),
            'tool_result': ('truncate_result',),
            'agent_session': ('AgentSessionState', 'get_session_state'),
            'background_tasks': ('BackgroundTaskManager', 'get_background_task_manager'),
            'cron_scheduler': ('CronScheduler', 'get_cron_scheduler'),
            'llm_utils': ('classify_llm_error', 'build_system_message', 'MAX_CONSECUTIVE_FAILURES'),
            'mental_model': ('MentalModel', 'CognitiveState', 'Diagnosis', 'ToolRecord', 'get_mental_model', 'reset_mental_model'),
            'workspace_cleaner': ('classify_file', 'scan_workspace_debris', 'clean_debris', 'auto_clean_session_debris', 'list_workspace_debris_tool', 'clean_workspace_debris_tool', 'get_session_files_tool'),
        }
        names = {name for group in expected.values() for name in group}
        assert names.issubset(dir(package))
        assert not hasattr(package, 'not_an_infrastructure_export')
        namespace = {}
        exec('from core.infrastructure import *', namespace)
        for suffix, exports in expected.items():
            module = importlib.import_module('core.infrastructure.' + suffix)
            for name in exports:
                assert namespace[name] is getattr(module, name)
                assert getattr(package, name) is getattr(module, name)
    """)


def test_concurrent_first_access_preserves_export_identity():
    _cold("""
        from concurrent.futures import ThreadPoolExecutor
        import importlib, threading
        import core.infrastructure as package
        barrier = threading.Barrier(4)
        names = ('ToolExecutor', 'ModelDiscovery', 'AgentState', 'EventBus')
        def load(name):
            barrier.wait(timeout=5)
            return getattr(package, name)
        with ThreadPoolExecutor(max_workers=4) as pool:
            exports = list(pool.map(load, names, timeout=15))
        for name, value in zip(names, exports):
            assert value is getattr(package, name)
        from core.infrastructure import atomic_io
        assert atomic_io is importlib.import_module('core.infrastructure.atomic_io')
    """)
