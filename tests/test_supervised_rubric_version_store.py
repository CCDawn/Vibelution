# -*- coding: utf-8 -*-
"""Tests for the supervised rubric version store."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.web.services import supervised_rubric_version_store as store


@pytest.fixture()
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(store, "_PROJECT_ROOT", tmp_path)
    return store._ledger_path().parent


def test_record_and_list_roundtrip(isolated_store: Path) -> None:
    record = store.record_rubric_version(
        {"taskSummary": "probe", "criteria": []},
        source="swte-run-1",
        rubric_hash="abc123",
    )
    assert record["status"] == "shadow"
    assert record["rubricVersionId"].startswith("rv-")
    assert record["contentSha256"]
    records = store.list_rubric_versions()
    assert len(records) == 1
    assert records[0]["rubricHash"] == "abc123"


def test_record_is_idempotent_on_same_hash_and_status(
    isolated_store: Path,
) -> None:
    first = store.record_rubric_version({"a": 1}, source="r1", rubric_hash="h1")
    second = store.record_rubric_version({"a": 1}, source="r2", rubric_hash="h1")
    assert second["rubricVersionId"] == first["rubricVersionId"]
    assert len(store.list_rubric_versions()) == 1


def test_invalid_status_rejected(isolated_store: Path) -> None:
    with pytest.raises(store.RubricVersionStoreError):
        store.record_rubric_version({}, source="r1", rubric_hash="h", status="live")
    with pytest.raises(store.RubricVersionStoreError):
        store.record_rubric_version({}, source="r1", rubric_hash="")


def test_promote_switches_active_and_retires_previous(
    isolated_store: Path,
) -> None:
    v1 = store.record_rubric_version({"v": 1}, source="r1", rubric_hash="h1")
    store.promote_rubric_version(
        v1["rubricVersionId"], evidence={"scoreDelta": 69.0, "kappa": 1.0}
    )
    active = store.latest_active_version()
    assert active is not None
    assert active["rubricHash"] == "h1"
    assert active["evidence"] == {"scoreDelta": 69.0, "kappa": 1.0}
    assert active["supersedesVersionId"] == ""

    v2 = store.record_rubric_version({"v": 2}, source="r2", rubric_hash="h2")
    store.promote_rubric_version(
        v2["rubricVersionId"], evidence={"scoreDelta": 10.0}
    )
    active2 = store.latest_active_version()
    assert active2 is not None
    assert active2["rubricHash"] == "h2"
    assert active2["supersedesVersionId"] == active["rubricVersionId"]
    statuses = [str(r["status"]) for r in store.list_rubric_versions()]
    assert statuses.count("retired") == 1  # 旧 active 已追加退役行


def test_promote_unknown_or_non_shadow_rejected(isolated_store: Path) -> None:
    with pytest.raises(store.RubricVersionStoreError):
        store.promote_rubric_version("rv-missing", evidence={"x": 1})
    v1 = store.record_rubric_version({"v": 1}, source="r1", rubric_hash="h1")
    store.promote_rubric_version(v1["rubricVersionId"], evidence={"x": 1})
    with pytest.raises(store.RubricVersionStoreError):
        store.promote_rubric_version(v1["rubricVersionId"], evidence={"x": 2})
    with pytest.raises(store.RubricVersionStoreError):
        store.promote_rubric_version(v1["rubricVersionId"], evidence={})


def test_empty_ledger_reads(isolated_store: Path) -> None:
    assert store.list_rubric_versions() == []
    assert store.latest_active_version() is None
