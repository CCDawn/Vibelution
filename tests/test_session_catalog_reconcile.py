from __future__ import annotations

from pathlib import Path

from core.chat.session_catalog import SessionCatalogStore
from core.web.services.session.catalog_bridge import (
    CatalogReconciler,
    build_catalog_snapshot,
)


def _store(tmp_path: Path) -> SessionCatalogStore:
    store = SessionCatalogStore(
        tmp_path / "catalog" / "session_catalog.sqlite3",
        workspace_key="workspace-test",
    )
    store.initialize()
    return store


def _conversations(title: str = "First"):
    return [
        {
            "conversation_id": "session-a",
            "title": title,
            "task_title": "Task A",
            "task_summary": "Summary A",
            "session_kind": "main",
            "conversationIndexVisibility": "normal",
            "agent_id": "agent-a",
            "agentCode": "A001",
            "agentDisplayName": "Agent A",
            "status": "ready",
            "current_phase": "idle",
            "created_at": "2026-07-27T00:00:00Z",
            "updated_at": "2026-07-27T00:00:01Z",
        }
    ]


def _journal_inventory():
    return {
        "session-a": {
            "journal_rel_path": "sessions/session-a/turn_journal.jsonl",
            "journal_size": 100,
            "journal_mtime_ns": 200,
            "latest_sequence": 3,
            "event_count": 3,
            "message_count": 2,
            "last_turn_status": "completed",
            "open_turn_id": "",
        },
        "orphan-session": {
            "journal_rel_path": "sessions/orphan-session/turn_journal.jsonl",
            "journal_size": 10,
            "journal_mtime_ns": 20,
            "latest_sequence": 1,
            "event_count": 1,
            "message_count": 1,
        },
    }


def test_reconcile_rebuilds_deleted_catalog_from_same_canonical_snapshot(tmp_path):
    snapshot = build_catalog_snapshot(
        _conversations(),
        _journal_inventory(),
        workspace_key="workspace-test",
        indexed_at="2026-07-27T00:00:02Z",
    )
    first_store = _store(tmp_path)
    first = CatalogReconciler(first_store, source_loader=lambda: snapshot).reconcile(
        owner="worker-a",
        now="2026-07-27T00:00:00Z",
        lease_expires_at="2026-07-27T00:05:00Z",
    )
    first_rows = first_store.query_sessions(limit=10)
    first_store.database_path.unlink()

    rebuilt_store = _store(tmp_path)
    second = CatalogReconciler(
        rebuilt_store,
        source_loader=lambda: snapshot,
    ).reconcile(
        owner="worker-b",
        now="2026-07-27T00:06:00Z",
        lease_expires_at="2026-07-27T00:11:00Z",
    )

    assert first.status == "complete"
    assert second.status == "complete"
    assert rebuilt_store.query_sessions(limit=10) == first_rows
    assert [row["session_id"] for row in first_rows] == ["session-a"]


def test_source_change_before_publish_does_not_replace_last_good_rows(tmp_path):
    original = build_catalog_snapshot(
        _conversations("Original"),
        _journal_inventory(),
        workspace_key="workspace-test",
        indexed_at="2026-07-27T00:00:02Z",
    )
    changed = build_catalog_snapshot(
        _conversations("Changed"),
        _journal_inventory(),
        workspace_key="workspace-test",
        indexed_at="2026-07-27T00:00:03Z",
    )
    store = _store(tmp_path)
    CatalogReconciler(store, source_loader=lambda: original).reconcile(
        owner="worker-a",
        now="2026-07-27T00:00:00Z",
        lease_expires_at="2026-07-27T00:05:00Z",
    )
    snapshots = iter((changed, changed, original))
    reconciler = CatalogReconciler(store, source_loader=lambda: next(snapshots))

    result = reconciler.reconcile(
        owner="worker-b",
        now="2026-07-27T00:06:00Z",
        lease_expires_at="2026-07-27T00:11:00Z",
    )

    assert result.status == "source_changed"
    assert store.query_sessions(limit=1)[0]["title"] == "Original"
    assert store.metadata()["source_revision"] == original.source_revision


def test_live_lease_blocks_competitor_and_stale_lease_can_be_taken_over(tmp_path):
    snapshot = build_catalog_snapshot(
        _conversations(),
        _journal_inventory(),
        workspace_key="workspace-test",
        indexed_at="2026-07-27T00:00:02Z",
    )
    store = _store(tmp_path)
    assert store.try_acquire_lease(
        "crashed-worker",
        now="2026-07-27T00:00:00Z",
        expires_at="2026-07-27T00:05:00Z",
    )
    reconciler = CatalogReconciler(store, source_loader=lambda: snapshot)

    blocked = reconciler.reconcile(
        owner="replacement",
        now="2026-07-27T00:01:00Z",
        lease_expires_at="2026-07-27T00:06:00Z",
    )
    recovered = reconciler.reconcile(
        owner="replacement",
        now="2026-07-27T00:05:01Z",
        lease_expires_at="2026-07-27T00:10:00Z",
    )

    assert blocked.status == "lease_busy"
    assert recovered.status == "complete"
    assert store.metadata()["lease_owner"] == ""
    assert store.metadata()["backfill_status"] == "complete"


def test_invalid_candidate_does_not_replace_last_good_catalog(tmp_path):
    good = build_catalog_snapshot(
        _conversations(),
        _journal_inventory(),
        workspace_key="workspace-test",
        indexed_at="2026-07-27T00:00:02Z",
    )
    store = _store(tmp_path)
    CatalogReconciler(store, source_loader=lambda: good).reconcile(
        owner="worker-a",
        now="2026-07-27T00:00:00Z",
        lease_expires_at="2026-07-27T00:05:00Z",
    )
    invalid = build_catalog_snapshot(
        [{**_conversations()[0], "conversation_id": ""}],
        _journal_inventory(),
        workspace_key="workspace-test",
        indexed_at="2026-07-27T00:00:03Z",
    )

    result = CatalogReconciler(store, source_loader=lambda: invalid).reconcile(
        owner="worker-b",
        now="2026-07-27T00:06:00Z",
        lease_expires_at="2026-07-27T00:11:00Z",
    )

    assert result.status == "complete"
    assert result.session_count == 0
    assert store.query_sessions(limit=10) == []
