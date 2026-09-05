"""Inherited research objectives do not turn evidence children into meetings."""

import json
from dataclasses import replace

import pytest

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.real_readiness_context import RealDomainReadinessContext
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import build_run_record


@pytest.mark.parametrize("workflow_id,expected", [
    (CHALLENGE_CUP_WORKFLOW_ID, True),
    ("challenge-cup-knowledge-sideflow", False),
])
def test_only_parent_workflow_owns_hypothesis_first_gate(tmp_path, workflow_id, expected):
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        record = replace(build_run_record(), workflow_id=workflow_id,
            input_snapshot_json=json.dumps({"researchObjectiveContract": {"hypothesisFirst": True}}))
        harness.store.submit(lambda uow: uow.repository.insert_run(record), force_flush=True).result(timeout=5)
        context = RealDomainReadinessContext(harness.store)
        assert context.hypothesis_first_flow(record.team_id, record.run_id) is expected
        assert context.hypothesis_first_flow("different-team", record.run_id) is False
    finally:
        harness.close()
