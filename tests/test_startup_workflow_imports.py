"""Research runtime readiness must not import execution-only dependencies."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_build_keeps_execution_imports_lazy_and_facades_ready() -> None:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent("""
            import importlib.abc
            from pathlib import Path
            import sys
            import tempfile

            blocked = {
                "langgraph.graph",
                "langgraph.types",
                "langgraph.checkpoint.sqlite",
                "core.web.services.team_workflow.research_runtime.agent_node_execution",
            }
            class BlockExecutionImports(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname in blocked:
                        raise AssertionError("Execution import during runtime build: " + fullname)

            guard = BlockExecutionImports()
            sys.meta_path.insert(0, guard)
            from core.web.services.team_workflow.research_runtime.runtime_factory import build_workflow_runtime
            from core.web.services.team_workflow.research_runtime.formal_write_runtime import get_command_service, get_write_store
            from core.web.services.team_workflow.research_runtime.formal_read_runtime import get_query_service, get_formal_read_store
            from core.web.services.team_workflow.research_runtime.budget_window_resolver import injected_research_runtime_store

            with tempfile.TemporaryDirectory() as temp:
                runtime = build_workflow_runtime(Path(temp) / "workflow-ledger.sqlite")
                try:
                    assert get_command_service() is runtime.command_service
                    assert get_write_store() is runtime.store
                    assert get_query_service() is not None
                    assert get_formal_read_store() is runtime.store
                    assert injected_research_runtime_store() is runtime.store
                    assert blocked.isdisjoint(sys.modules)
                    # First graph use still resolves the real implementation.
                    sys.meta_path.remove(guard)
                    from core.research.workflow.challenge_cup_runtime import build_formal_graph
                    graph = build_formal_graph()
                    assert graph is not None
                    assert "langgraph.graph" in sys.modules
                finally:
                    runtime.close()
        """)],
        cwd=ROOT,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1"),
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    assert result.returncode == 0, result.stdout + result.stderr
