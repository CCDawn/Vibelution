from __future__ import annotations

from pathlib import Path

from core.research.workflow.ledger import (
    CatalogRunAuthorization,
    WorkflowLedgerStore,
    destroy_team_ledger_reset_stage,
    prepare_team_ledger_reset_stage,
    purge_team_ledger_reset_stage,
    restore_team_ledger_reset_stage,
)


def _authorization(team_id: str, suffix: str) -> CatalogRunAuthorization:
    return CatalogRunAuthorization(
        authorization_id=f"authorization-{suffix}",
        team_id=team_id,
        plan_id=f"plan-{suffix}",
        batch_scope_json='{"questionIds":["SCI-096"]}',
        scope_hash="s" * 64,
        approved_by="operator",
        approved_at_ms=1,
        readiness_report_sha256="r" * 64,
        record_hash="h" * 64,
        created_at_ms=1,
    )


def test_team_ledger_reset_purges_only_staged_team_rows_and_can_restore(tmp_path: Path) -> None:
    store = WorkflowLedgerStore(tmp_path / "workflow-ledger.sqlite")
    store.open()
    research = _authorization("research-team", "research")
    other = _authorization("other-team", "other")
    try:
        for item in (research, other):
            store.submit(
                lambda uow, record=item: uow.repository.insert_catalog_run_authorization(record),
                force_flush=True,
            ).result(timeout=10)

        stage = prepare_team_ledger_reset_stage(store, "research-team", "reset-ledger-1")
        assert stage["runCount"] == 0
        assert stage["recordCount"] == 1

        purged = purge_team_ledger_reset_stage(store, stage, reset_id="reset-ledger-1")
        assert purged["changedRows"] == 1
        assert store.get_catalog_run_authorization(research.authorization_id) is None
        assert store.get_catalog_run_authorization(other.authorization_id) == other

        restored = restore_team_ledger_reset_stage(store, stage, reset_id="reset-ledger-1")
        assert restored["changedRows"] == 1
        assert store.get_catalog_run_authorization(research.authorization_id) == research

        second = prepare_team_ledger_reset_stage(store, "research-team", "reset-ledger-2")
        purge_team_ledger_reset_stage(store, second, reset_id="reset-ledger-2")
        finalized = destroy_team_ledger_reset_stage(second, reset_id="reset-ledger-2")
        assert finalized["status"] == "destroyed"
    finally:
        store.close()
