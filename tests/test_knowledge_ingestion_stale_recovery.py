"""Orphan recovery for knowledge-ingestion work-run snapshots.

The ingestion runs on a daemon thread; if the process dies the on-disk
snapshot stays "running" forever. The active check must treat a silent
snapshot as inactive so new runs can start and UI polling can stop.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _snapshot(team_id: str, *, status: str = "running", age_s: float = 0) -> dict:
    updated = (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat()
    return {
        "runId": "run-stale-1",
        "teamId": team_id,
        "status": status,
        "currentPhase": status,
        "updatedAt": updated,
    }


def test_fresh_running_snapshot_is_active() -> None:
    from core.web.services.team_workflow.knowledge_kernel import (
        _knowledge_ingestion_snapshot_is_active,
    )

    assert _knowledge_ingestion_snapshot_is_active(_snapshot("team-a", age_s=30), "team-a") is True


def test_silent_running_snapshot_is_inactive_after_timeout() -> None:
    from core.web.services.team_workflow.knowledge_kernel import (
        _KNOWLEDGE_INGESTION_STALE_ACTIVE_AFTER_S,
        _knowledge_ingestion_snapshot_is_active,
    )

    stale = _snapshot("team-a", age_s=_KNOWLEDGE_INGESTION_STALE_ACTIVE_AFTER_S + 60)
    assert _knowledge_ingestion_snapshot_is_active(stale, "team-a") is False


def test_foreign_team_snapshot_is_inactive() -> None:
    from core.web.services.team_workflow.knowledge_kernel import (
        _knowledge_ingestion_snapshot_is_active,
    )

    assert _knowledge_ingestion_snapshot_is_active(_snapshot("team-a"), "team-b") is False
