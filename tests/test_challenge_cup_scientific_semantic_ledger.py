from __future__ import annotations

import pytest

from core.research.workflow.contracts.challenge_cup_stage_one_v3 import (
    ActivityExecution,
    ScientificSemanticRecord,
)
from core.web.services.team_workflow.research_runtime.scientific_semantic_ledger import (
    ScientificSemanticRecordConflict,
    append_scientific_semantic_record,
    list_scientific_semantic_records,
)
from tests._support.workflow_ledger_helpers import build_run_record, open_ledger_store


@pytest.mark.parametrize(
    "semantic",
    [
        ScientificSemanticRecord(),
        ScientificSemanticRecord(evidenceReviews=(), evidenceRelations=()),
    ],
)
def test_empty_semantic_record_is_rejected_without_ledger_mutation(
    tmp_path, semantic
) -> None:
    store = open_ledger_store(tmp_path / "workflow-ledger.sqlite")
    try:
        run = build_run_record(workflow_id="challenge-cup-research")
        store.submit(
            lambda uow: uow.repository.insert_run(run), force_flush=True
        ).result(timeout=30)
        before = store.get_run(run.run_id)

        with pytest.raises(ValueError, match="must contain at least one object"):
            append_scientific_semantic_record(
                store,
                run_id=run.run_id,
                record_ref="semantic:empty",
                subject_ref="activity-1",
                semantic=semantic,
                actor_type="software_agent",
                actor_ref="agent-source-finder-1",
                recorded_at_ms=1_750_000_000_100,
            )

        assert store.list_events(run.run_id) == []
        assert store.get_run(run.run_id) == before
    finally:
        store.close()


def test_scientific_semantic_records_are_append_only_and_idempotent(tmp_path) -> None:
    store = open_ledger_store(tmp_path / "workflow-ledger.sqlite")
    try:
        run = build_run_record(
            workflow_id="challenge-cup-research",
            workflow_version_id="wv-current-v3",
        )
        store.submit(
            lambda uow: uow.repository.insert_run(run), force_flush=True
        ).result(timeout=30)
        semantic = ScientificSemanticRecord(
            execution=ActivityExecution(status="succeeded")
        )

        first = append_scientific_semantic_record(
            store,
            run_id=run.run_id,
            record_ref="semantic:activity-1:execution:r1",
            subject_ref="activity-1",
            semantic=semantic,
            actor_type="software_agent",
            actor_ref="agent-source-finder-1",
            recorded_at_ms=1_750_000_000_100,
        )
        replay = append_scientific_semantic_record(
            store,
            run_id=run.run_id,
            record_ref="semantic:activity-1:execution:r1",
            subject_ref="activity-1",
            semantic=semantic,
            actor_type="software_agent",
            actor_ref="agent-source-finder-1",
            recorded_at_ms=1_750_000_000_100,
        )

        assert replay == first
        assert list_scientific_semantic_records(store, run.run_id) == [first]
        assert len(store.list_events(run.run_id)) == 1
    finally:
        store.close()


def test_scientific_semantic_record_ref_rejects_conflicting_facts(tmp_path) -> None:
    store = open_ledger_store(tmp_path / "workflow-ledger.sqlite")
    try:
        run = build_run_record(
            workflow_id="challenge-cup-research",
            workflow_version_id="wv-current-v3",
        )
        store.submit(
            lambda uow: uow.repository.insert_run(run), force_flush=True
        ).result(timeout=30)
        append_scientific_semantic_record(
            store,
            run_id=run.run_id,
            record_ref="semantic:activity-1:execution:r1",
            subject_ref="activity-1",
            semantic=ScientificSemanticRecord(
                execution=ActivityExecution(status="succeeded")
            ),
            actor_type="software_agent",
            actor_ref="agent-source-finder-1",
            recorded_at_ms=1_750_000_000_100,
        )

        with pytest.raises(
            ScientificSemanticRecordConflict,
            match="semantic record ref already identifies different facts",
        ):
            append_scientific_semantic_record(
                store,
                run_id=run.run_id,
                record_ref="semantic:activity-1:execution:r1",
                subject_ref="activity-1",
                semantic=ScientificSemanticRecord(
                    execution=ActivityExecution(
                        status="failed", failureReasonCode="provider_error"
                    )
                ),
                actor_type="software_agent",
                actor_ref="agent-source-finder-1",
                recorded_at_ms=1_750_000_000_100,
            )
    finally:
        store.close()


def test_scientific_semantic_ledger_rejects_non_challenge_workflows(tmp_path) -> None:
    store = open_ledger_store(tmp_path / "workflow-ledger.sqlite")
    try:
        run = build_run_record(workflow_id="another-workflow")
        store.submit(
            lambda uow: uow.repository.insert_run(run), force_flush=True
        ).result(timeout=30)

        with pytest.raises(ValueError, match="Challenge Cup workflow"):
            append_scientific_semantic_record(
                store,
                run_id=run.run_id,
                record_ref="semantic:activity-1:execution:r1",
                subject_ref="activity-1",
                semantic=ScientificSemanticRecord(
                    execution=ActivityExecution(status="succeeded")
                ),
                actor_type="software_agent",
                actor_ref="agent-source-finder-1",
                recorded_at_ms=1_750_000_000_100,
            )
    finally:
        store.close()
