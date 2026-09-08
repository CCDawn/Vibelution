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


@pytest.mark.parametrize("question_id", ["SCI-091", "SCI-096"])
@pytest.mark.parametrize("workflow_id,package,expected", [
    (CHALLENGE_CUP_WORKFLOW_ID, None, False),
    (CHALLENGE_CUP_WORKFLOW_ID, {}, False),
    (CHALLENGE_CUP_WORKFLOW_ID, {"contentHash": "a" * 64}, True),
    ("challenge-cup-knowledge-sideflow", {"contentHash": "a" * 64}, False),
])
def test_phase_two_uses_frozen_handoff_not_question_number(
    tmp_path, question_id, workflow_id, package, expected,
):
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        record = replace(
            build_run_record(), workflow_id=workflow_id, question_id=question_id,
            input_snapshot_json=json.dumps({
                "constraintSnapshot": {"phaseOneKnowledgePackage": package},
            }),
        )
        harness.store.submit(lambda uow: uow.repository.insert_run(record), force_flush=True).result(timeout=5)
        context = RealDomainReadinessContext(harness.store)
        assert context.phase_two_flow(record.team_id, record.run_id) is expected
        assert context.phase_two_flow("different-team", record.run_id) is False
        assert context.phase_two_flow(record.team_id, "missing-run") is False
    finally:
        harness.close()
