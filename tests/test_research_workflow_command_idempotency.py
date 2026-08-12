"""T3 RED: command idempotency — same key+hash replays the original result,
same key+different hash conflicts, and the idempotency hit is checked
before expectedRunVersion."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.ledger import IdempotencyConflictError
from tests._support.command_helpers import CommandHarness


def test_same_key_same_request_returns_original_receipt(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        request = harness.request(idempotency_key="ui:key-1")
        first = harness.service.submit(request)
        second = harness.service.submit(request)
        assert first.command_id == second.command_id
        assert first.accepted_run_version == second.accepted_run_version
        assert second.idempotency_key == "ui:key-1"
        assert len(harness.store.list_attempts("run-test")) == 1
    finally:
        harness.close()


def test_same_key_different_request_conflicts(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1", payload={"a": 1}))
        with pytest.raises(IdempotencyConflictError):
            harness.service.submit(harness.request(idempotency_key="ui:key-1", payload={"a": 2}))
        # 冲突不产生任何新行。
        assert len(harness.store.list_attempts("run-test")) == 1
    finally:
        harness.close()


def test_idempotency_hit_beats_stale_version(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        request = harness.request(idempotency_key="ui:key-1", expected_run_version=1)
        first = harness.service.submit(request)
        # 相同请求体重放：此时 run 版本已推进，但幂等命中必须先于版本检查返回原结果。
        replay = harness.request(idempotency_key="ui:key-1", expected_run_version=1)
        second = harness.service.submit(replay)
        assert second.command_id == first.command_id
        assert second.accepted_run_version == 2
        assert len(harness.store.list_attempts("run-test")) == 1
    finally:
        harness.close()


def test_idempotency_is_per_run_scope(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-a")
        harness.seed_run(run_id="run-b")
        harness.service.submit(harness.request(run_id="run-a", idempotency_key="ui:shared"))
        receipt_b = harness.service.submit(
            harness.request(run_id="run-b", idempotency_key="ui:shared")
        )
        assert receipt_b.accepted_run_version == 2
        assert len(harness.store.list_attempts("run-a")) == 1
        assert len(harness.store.list_attempts("run-b")) == 1
    finally:
        harness.close()
