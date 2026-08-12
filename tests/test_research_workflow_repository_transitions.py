"""P1-5b RED: repository enforces frozen status transitions.

Direct SQL status writes are guarded by the transition graph: an illegal
attempt/handoff/run transition raises instead of silently corrupting state,
and a conditional update that no longer matches (already terminal) does not
create a resume outbox afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def test_illegal_attempt_transition_raises(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt is not None and attempt.status == "starting"

        # 先推进到 succeeded（starting->dispatching->succeeded 合法链）。
        def to_dispatching(uow):
            uow.repository.update_attempt_status(
                attempt.node_run_id, "dispatching", FIXED_NOW_MS
            )

        harness.store.submit(to_dispatching, force_flush=True).result(timeout=10)

        def to_succeeded(uow):
            uow.repository.update_attempt_status(
                attempt.node_run_id, "succeeded", FIXED_NOW_MS, finished_at_ms=FIXED_NOW_MS
            )

        harness.store.submit(to_succeeded, force_flush=True).result(timeout=10)
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt.status == "succeeded"

        with pytest.raises(ValueError, match="illegal node attempt transition"):
            def bad(uow):
                uow.repository.update_attempt_status(
                    attempt.node_run_id, "starting", FIXED_NOW_MS
                )

            harness.store.submit(bad, force_flush=True).result(timeout=10)
        # 状态未被改动。
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt.status == "succeeded"
    finally:
        harness.close()


def test_illegal_run_transition_raises(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        # created -> archived 非法（不可跳过中间态）。
        with pytest.raises(ValueError, match="illegal run transition"):
            def bad(uow):
                uow.repository.update_run_status(
                    "run-test", "research-team", "archived", FIXED_NOW_MS
                )

            harness.store.submit(bad, force_flush=True).result(timeout=10)
        run = harness.store.get_run("run-test")
        assert run is not None and run.status == "created"
    finally:
        harness.close()


def test_legal_transitions_still_pass(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))
        attempt = harness.store.latest_attempt("run-test", "source_finding")

        # starting -> dispatching -> running -> succeeded 合法链。
        def advance(status: str):
            def mutate(uow):
                uow.repository.update_attempt_status(
                    attempt.node_run_id, status, FIXED_NOW_MS
                )

            harness.store.submit(mutate, force_flush=True).result(timeout=10)

        advance("dispatching")
        advance("running")
        advance("succeeded")
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt.status == "succeeded"

        # 终态 -> stale（retry 谱系）合法。
        def stale(uow):
            uow.repository.update_attempt_status(
                attempt.node_run_id, "stale", FIXED_NOW_MS
            )

        harness.store.submit(stale, force_flush=True).result(timeout=10)
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt.status == "stale"
    finally:
        harness.close()


def test_illegal_handoff_transition_raises(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))
        attempt = harness.store.latest_attempt("run-test", "source_finding")

        def seed_handoff(uow):
            from tests._support.workflow_ledger_helpers import FIXED_NOW_MS as NOW

            uow.repository.insert_handoff(
                handoff_id="ho-1",
                run_id="run-test",
                edge_id="source_finding->source_extraction",
                from_node_run_id=attempt.node_run_id,
                to_node_id="source_extraction",
                to_node_run_id=None,
                gate_kind="auto",
                input_snapshot_hash="a" * 64,
                offered_at_ms=NOW,
            )

        harness.store.submit(seed_handoff, force_flush=True).result(timeout=10)
        # pending -> accepted 非法（必须先 ready/waiting_human）。
        with pytest.raises(ValueError, match="illegal handoff transition"):
            def bad(uow):
                uow.repository.update_handoff_status("ho-1", "accepted", FIXED_NOW_MS)

            harness.store.submit(bad, force_flush=True).result(timeout=10)
    finally:
        harness.close()
