"""Deterministic reseal on retry-program-handoff (production 005).

A terminal stage-one run can never re-enter the ``result_package`` system
action, so a delivery that failed on a stale sealed package (empty
``counterevidence_refs`` before the workflow-bound card bridge existed) was
unrecoverable.  These tests pin the best-effort reseal contract: it appends
a fresh immutable ``research_result_package`` the delivery step reads, it
stays away from runs the Challenge Program already registered, and any
rebuild failure falls back to the existing sealed package without breaking
the retry.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from core.research.workflow.ledger.records import RunRecord
from core.research.workflow.stage_one_definition import stage_one_creation_definition
from core.web.services.team_workflow import challenge_question_runs
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
    load_workflow_artifact_payload,
    put_workflow_artifact,
)

_TEAM_ID = "research-team"
_RUN_ID = "run-fbc374b1caf6"
_QUESTION_ID = "SCI-005"
_SIDE_FLOW_RUN_ID = "dprun-20261020104506966426-72158dab"
_RESEAL_KEY = "hf2:retry-program-handoff:snapshot-1"


def _stage_one_version_id() -> str:
    return stage_one_creation_definition()[1].workflowVersionId


def _input_snapshot() -> dict[str, Any]:
    return {
        "questionId": _QUESTION_ID,
        "sourceCollectionRunId": "sc-formal-side",
        "constraintSnapshot": {"formalWrites": False},
    }


def _run_record(**overrides: Any) -> RunRecord:
    record = RunRecord(
        run_id=_RUN_ID,
        team_id=_TEAM_ID,
        workflow_id="challenge-cup",
        workflow_version_id=_stage_one_version_id(),
        thread_id="thread-1",
        project_id="project-1",
        question_id=_QUESTION_ID,
        status="succeeded",
        run_version=42,
        last_event_sequence=10,
        input_snapshot_json=json.dumps(_input_snapshot()),
        input_snapshot_hash="a" * 64,
        safety_limits_json="{}",
        binding_snapshot_set_id="bss-1",
        active_node_id=None,
        parent_run_id=None,
        forked_from_checkpoint_id=None,
        completion_kind="proposal_completed",
        terminal_reason="stage_one_proposal_completed",
        blocked_problem_json=None,
        created_at_ms=1_000,
        updated_at_ms=2_000,
        completed_at_ms=2_000,
        structure_hash="s" * 64,
    )
    return replace(record, **overrides)


def _patch_challenge_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, records: list[dict[str, Any]]
) -> Path:
    """Point the immutable program index at a tmp file with given records."""

    index_path = tmp_path / "program_index.json"
    index_path.write_text(
        json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        challenge_question_runs, "_store_path", lambda team_id: index_path
    )
    return index_path


def _fake_v2_builder(package_id: str) -> Any:
    def build(**kwargs):
        record = kwargs["record"]
        assert record["inputSnapshot"]["questionId"] == _QUESTION_ID
        return {
            "runId": kwargs["workflow_run_id"],
            "teamId": kwargs["team_id"],
            "factChainHash": "f" * 64,
            "packageId": package_id,
            "packageRef": "research-result-package:" + ("a" * 64),
            "contentHash": "a" * 64,
        }

    return build


def _patch_builder(monkeypatch: pytest.MonkeyPatch, package_id: str) -> None:
    import core.web.services.team_workflow.research_runtime.result_package_v2 as result_package_v2_module

    monkeypatch.setattr(
        result_package_v2_module,
        "build_challenge_result_package_v2",
        _fake_v2_builder(package_id),
    )


def test_reseal_appends_fresh_artifact_that_delivery_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retry reads the resealed authority, not the stale package."""
    _patch_challenge_index(monkeypatch, tmp_path, records=[])
    _patch_builder(monkeypatch, "rrp-v2:resealed")

    # A canvas-era run record exists in the run store; the reseal mirrors the
    # build_package projection onto it.  A ledger-era run without a record
    # simply skips this projection — the resealed artifact stays the authority.
    from core.web.services.team_workflow.research_runtime.store import (
        WorkflowRunStore,
    )

    run_store = WorkflowRunStore()
    run_store.create_run({"runId": _RUN_ID, "teamId": _TEAM_ID})

    run = _run_record()
    reseal = chain._reseal_terminal_program_package(
        _TEAM_ID, run=run, idempotency_key=_RESEAL_KEY
    )

    assert reseal is not None
    assert reseal["artifactIdentity"] == f"{_RUN_ID}:reseal:{_RESEAL_KEY}"
    assert reseal["packageId"] == "rrp-v2:resealed"

    # The exact read channel the delivery orchestration uses
    # (``load_scoped_artifact_payload`` → latest scoped record).
    envelope = load_workflow_artifact_payload(
        "research_result_package",
        team_id=_TEAM_ID,
        authority_run_id="sc-formal-side",
        workflow_run_id=_RUN_ID,
    )
    assert envelope is not None
    assert envelope["payload"]["package"]["packageId"] == "rrp-v2:resealed"
    assert envelope["payload"]["sourceCollectionRunId"] == "sc-formal-side"

    projected = run_store.get_run(_RUN_ID)
    assert projected is not None
    assert projected["resultPackage"]["packageId"] == "rrp-v2:resealed"
    assert projected["resultPackageRef"] == f"{_RUN_ID}:reseal:{_RESEAL_KEY}"


def test_reseal_skips_runs_the_program_already_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing immutable program binding must never be re-sealed over."""
    _patch_challenge_index(
        monkeypatch,
        tmp_path,
        records=[{"questionId": _QUESTION_ID, "runId": _RUN_ID}],
    )
    _patch_builder(monkeypatch, "rrp-v2:must-not-build")

    reseal = chain._reseal_terminal_program_package(
        _TEAM_ID, run=_run_record(), idempotency_key=_RESEAL_KEY
    )

    assert reseal is None
    assert (
        load_workflow_artifact_payload(
            "research_result_package",
            team_id=_TEAM_ID,
            authority_run_id="sc-formal-side",
            workflow_run_id=_RUN_ID,
        )
        is None
    )


def test_reseal_failure_falls_back_to_the_existing_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rebuild failure never breaks the retry: the old package stays read."""
    _patch_challenge_index(monkeypatch, tmp_path, records=[])

    stale_package = {
        "runId": _RUN_ID,
        "teamId": _TEAM_ID,
        "factChainHash": "0" * 64,
        "packageId": "rrp-v2:stale",
        "packageRef": "research-result-package:" + ("0" * 64),
        "contentHash": "0" * 64,
    }
    put_workflow_artifact(
        _TEAM_ID,
        kind="research_result_package",
        workflow_run_id=_RUN_ID,
        source_collection_run_id="sc-formal-side",
        payload={
            "teamId": _TEAM_ID,
            "workflowRunId": _RUN_ID,
            "sourceCollectionRunId": "sc-formal-side",
            "package": stale_package,
        },
    )

    import core.web.services.team_workflow.research_runtime.result_package_v2 as result_package_v2_module

    def broken_builder(**_kwargs):
        raise result_package_v2_module.ResultPackageV2Error(
            "canonical Challenge Question v2 output is invalid: boom"
        )

    monkeypatch.setattr(
        result_package_v2_module, "build_challenge_result_package_v2", broken_builder
    )

    reseal = chain._reseal_terminal_program_package(
        _TEAM_ID, run=_run_record(), idempotency_key=_RESEAL_KEY
    )

    assert reseal is None
    envelope = load_workflow_artifact_payload(
        "research_result_package",
        team_id=_TEAM_ID,
        authority_run_id="sc-formal-side",
        workflow_run_id=_RUN_ID,
    )
    assert envelope is not None
    # The delivery channel still reads the pre-existing sealed package.
    assert envelope["payload"]["package"]["packageId"] == "rrp-v2:stale"


def test_reseal_gates_on_terminal_stage_one_proposal_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only succeeded stage-one proposal-only runs qualify."""
    _patch_challenge_index(monkeypatch, tmp_path, records=[])
    _patch_builder(monkeypatch, "rrp-v2:must-not-build")

    assert (
        chain._reseal_terminal_program_package(
            _TEAM_ID,
            run=_run_record(status="running"),
            idempotency_key=_RESEAL_KEY,
        )
        is None
    )
    assert (
        chain._reseal_terminal_program_package(
            _TEAM_ID,
            run=_run_record(
                workflow_version_id="challenge-cup@2.1",
            ),
            idempotency_key=_RESEAL_KEY,
        )
        is None
    )
    assert (
        load_workflow_artifact_payload(
            "research_result_package",
            team_id=_TEAM_ID,
            authority_run_id="sc-formal-side",
            workflow_run_id=_RUN_ID,
        )
        is None
    )
