# -*- coding: utf-8 -*-
"""Tests: quality ledgers and judge-quality snapshot hook."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services import evaluation_quality_ledger as ledger
from core.web.services import supervised_worktree_evolution_service as swte


# ---------------------------------------------------------------------------
# 台账
# ---------------------------------------------------------------------------

@pytest.fixture()
def ledger_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ledger, "_PROJECT_ROOT", tmp_path)
    return ledger._ledger_path("probe_ledger").parent


def test_ledger_append_read_and_change_throttle(
    ledger_root: Path,
) -> None:
    result = ledger.append_quality_ledger("probe_ledger", {"value": 1})
    assert Path(result["path"]).exists()
    records = ledger.read_quality_ledger("probe_ledger")
    assert len(records) == 1
    assert records[0]["value"] == 1
    assert records[0]["capturedAt"]
    assert records[0]["contentSha256"]

    skipped = ledger.append_quality_ledger_if_changed("probe_ledger", {"value": 1})
    assert skipped.get("skipped") is True
    appended = ledger.append_quality_ledger_if_changed("probe_ledger", {"value": 2})
    assert appended.get("skipped") is None
    assert len(ledger.read_quality_ledger("probe_ledger")) == 2


def test_ledger_read_empty(ledger_root: Path) -> None:
    assert ledger.read_quality_ledger("probe_ledger") == []
    assert ledger.latest_quality_ledger_fingerprint("probe_ledger") == ""


# ---------------------------------------------------------------------------
# 终态快照挂点
# ---------------------------------------------------------------------------

def test_judge_quality_snapshot_hook_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom():
        raise RuntimeError("panel unavailable")

    monkeypatch.setattr(
        "core.web.services.supervised_judge_quality_service.build_supervised_judge_quality_report",
        boom,
    )
    swte._append_judge_quality_snapshot("swte-x", {"status": "failed"})  # 不抛错
