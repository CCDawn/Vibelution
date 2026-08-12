"""Shared Ledger HTTP harness for T8 route tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.team_workflows import research_runtime as research_runtime_module
from core.web.services.team_workflow.research_runtime.formal_read_runtime import (
    reset_formal_read_runtime_for_tests,
)
from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
    reset_formal_write_runtime_for_tests,
)
from core.web.services.team_workflow.research_runtime.runtime_factory import (
    WorkflowRuntime,
    build_workflow_runtime,
)


@contextmanager
def ledger_http_client(
    tmp_path: Path,
    monkeypatch,
) -> Iterator[tuple[TestClient, WorkflowRuntime]]:
    data_root = tmp_path / "research_workflows"
    data_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(data_root))
    runtime = build_workflow_runtime(data_root / "workflow-ledger.sqlite")
    app = FastAPI()
    app.include_router(research_runtime_module.router, prefix="/api")
    client = TestClient(app)
    try:
        yield client, runtime
    finally:
        runtime.close()
        reset_formal_read_runtime_for_tests()
        reset_formal_write_runtime_for_tests()
