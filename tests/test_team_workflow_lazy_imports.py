"""Cold-process guards for route registration versus execution dependencies."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _cold_process(source: str) -> None:
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1")
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("leaf", ["paths", "errors"])
def test_runtime_contract_import_does_not_load_service(leaf: str) -> None:
    _cold_process(f"""
        import importlib, sys
        importlib.import_module('core.web.services.team_workflow.research_runtime.{leaf}')
        assert 'core.web.services.team_workflow.research_runtime.service' not in sys.modules
    """)


def test_route_registration_does_not_load_execution_only_modules() -> None:
    _cold_process("""
        import importlib.abc, sys

        blocked = {
            'core.web.services.team_workflow.research_runtime.service',
            'core.research.formal_runner',
            'core.research.smoke_runner',
        }
        class BlockExecutionImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in blocked:
                    raise AssertionError('Execution dependency loaded at registration: ' + fullname)
        sys.meta_path.insert(0, BlockExecutionImports())

        from fastapi import FastAPI
        from core.web.routes.team_workflows import router
        app = FastAPI()
        app.include_router(router, prefix='/api')
        paths = app.openapi()['paths']
        assert '/api/teams/{team_id}/workflow-orchestration' in paths
        assert '/api/teams/{team_id}/workflow-orchestration/experiments/status' in paths
        assert len(paths) > 100
        assert blocked.isdisjoint(sys.modules)
    """)


def test_lazy_exports_keep_original_objects_and_error_identity() -> None:
    _cold_process("""
        import importlib, sys
        from core.web.services import team_workflow_orchestration_service as facade
        assert 'core.research.smoke_runner' not in sys.modules
        assert 'core.research.formal_runner' not in sys.modules
        assert facade.smoke_runner is importlib.import_module('core.research.smoke_runner')
        assert facade.formal_runner is importlib.import_module('core.research.formal_runner')
        from core.web.services.team_workflow import research_runtime as package
        from core.web.services.team_workflow.research_runtime.errors import ResearchWorkflowError
        from core.web.services.team_workflow.research_runtime import service
        from core.web.services.team_workflow.research_runtime import run_creation
        from core.web.routes.team_workflows import research_runtime as routes
        assert service.ResearchWorkflowError is ResearchWorkflowError
        assert run_creation.ResearchWorkflowError is ResearchWorkflowError
        assert routes.ResearchWorkflowError is ResearchWorkflowError
        assert package.ResearchWorkflowRuntimeService is service.ResearchWorkflowRuntimeService
        assert package.get_research_workflow_runtime_service is service.get_research_workflow_runtime_service
        marker = object()
        service._SERVICE = marker
        assert routes.get_research_workflow_runtime_service() is marker
        assert routes._map_error(ResearchWorkflowError('bad input', code='invalid_run_input')).status_code == 422
    """)


def test_runtime_factory_inspection_does_not_load_workers() -> None:
    _cold_process("""
        import importlib.abc, sys

        blocked = {
            'core.web.services.team_workflow.research_runtime.adapter_dispatch_worker',
            'core.web.services.team_workflow.research_runtime.real_domain_ports',
            'core.web.services.team_workflow.research_runtime.delivery_worker',
            'core.web.services.team_workflow.research_runtime.outbox_pump',
        }
        class BlockWorkers(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in blocked:
                    raise AssertionError('Worker loaded during inspection: ' + fullname)
        sys.meta_path.insert(0, BlockWorkers())
        from core.web.services.team_workflow.research_runtime import runtime_factory as factory
        assert factory.production_workflow_runtime() is None
        assert factory.wake_production_workflow_runtime() is False
        assert blocked.isdisjoint(sys.modules)
    """)
