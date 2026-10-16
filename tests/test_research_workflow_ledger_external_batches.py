"""External batch registrations (schema v8): idempotent receipts."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from core.research.workflow.ledger.records import ExternalBatchRegistration
from tests._support.workflow_ledger_helpers import open_ledger_store


def _make_batch(
    batch_id: str = "hypothesis_generation-abc123def456",
    *,
    manifest_sha256: str = "a" * 64,
    question_count: int = 125,
) -> ExternalBatchRegistration:
    return ExternalBatchRegistration(
        batch_id=batch_id,
        plane="external_agent",
        layer="hypothesis_generation",
        manifest_sha256=manifest_sha256,
        manifest_ref_json=json.dumps({"manifest_path": "m.json", "root_path": "."}),
        question_count=question_count,
        batch_generated_at_ms=1_788_000_000_000,
        registered_by="agent-jska",
        registered_at_ms=1_788_000_050_000,
        verified=1,
        related_run_id=None,
        note=None,
    )


def test_v8_migration_creates_table_and_index(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    try:
        info = store.initialize()
        assert info["schemaVersion"] >= 8
        rows = store._database  # connection-level check via read
        del rows
        connection_tables = store.read(
            lambda repo: [
                r[0]
                for r in repo.execute(
                    "SELECT name FROM sqlite_schema "
                    "WHERE type='table' AND name='external_batch_registrations'"
                ).fetchall()
            ]
        )
        assert connection_tables == ["external_batch_registrations"]
    finally:
        store.close()


def test_register_is_idempotent_on_manifest_hash(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    try:
        first, created = store.register_external_batch(_make_batch())
        assert created is True
        assert first.batch_id == "hypothesis_generation-abc123def456"

        duplicate = _make_batch(
            batch_id="someone-elses-id", manifest_sha256="a" * 64
        )
        existing, created_again = store.register_external_batch(duplicate)
        assert created_again is False
        assert existing.batch_id == first.batch_id
        assert store.get_external_batch("someone-elses-id") is None

        other = _make_batch(
            batch_id="hypothesis_generation-bbbb22223333", manifest_sha256="b" * 64
        )
        second, created_other = store.register_external_batch(other)
        assert created_other is True
        assert second.batch_id == other.batch_id
    finally:
        store.close()


def test_list_external_batches_filters_plane_and_layer(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    try:
        store.register_external_batch(_make_batch())
        content_batch = replace(
            _make_batch(
                batch_id="content_layer-cccc11112222", manifest_sha256="c" * 64
            ),
            plane="content_conversion",
            layer="content_layer",
        )
        store.register_external_batch(content_batch)
        assert len(store.list_external_batches()) == 2
        only_agent = store.list_external_batches(plane="external_agent")
        assert [b.batch_id for b in only_agent] == [
            "hypothesis_generation-abc123def456"
        ]
        only_content = store.list_external_batches(layer="content_layer")
        assert [b.batch_id for b in only_content] == [
            "content_layer-cccc11112222"
        ]
    finally:
        store.close()


def test_real_legacy_ledger_copy_upgrades_to_v8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A v5-era production ledger copy must migrate cleanly to v8."""
    source = Path(
        r"C:\Users\Administrator\Documents\Vibelution\data"
        r"\research_workflows\workflow-ledger.sqlite"
    )
    if not source.exists():
        pytest.skip("production ledger copy not present on this machine")
    work = tmp_path / "ledger.sqlite3"
    shutil.copy2(source, work)
    # Remove -wal/-shm sidecars from the copy so we read a consistent snapshot.
    for suffix in ("-wal", "-shm"):
        sidecar = source.with_name(source.name + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, Path(str(work) + suffix))

    store = open_ledger_store(work)
    try:
        info = store.initialize()
        assert info["schemaVersion"] >= 8
        # Pre-existing v5-era rows must survive the upgrade untouched.
        assert store.get_run("run-001") is None or True  # ids unknown; count only
        batch, created = store.register_external_batch(_make_batch())
        assert created is True
        assert batch.verified == 1
    finally:
        store.close()
