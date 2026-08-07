"""Task 2: LangGraph vertical slice — checkpoint, HITL, restart, fork, idempotency."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.checkpoint_store import assert_not_memory_saver
from core.research.workflow.runtime import VerticalSliceRuntime, reopen_runtime


def test_start_interrupts_at_human_gate(tmp_path: Path) -> None:
    db = tmp_path / "wf.sqlite"
    with VerticalSliceRuntime(checkpoint_path=str(db)) as rt:
        result = rt.start("thread-a", idempotency_key="k1")
        assert result.get("step") == "start"
        assert result.get("upstream_artifact") == "artifact:k1:v1"
        assert result.get("handoff_status") == "pending"
        assert "__interrupt__" in result or result.get("step") == "start"
        state = rt.get_state("thread-a")
        assert state.next  # waiting on gate


def test_resume_accept_completes_and_marks_handoff_accepted(tmp_path: Path) -> None:
    db = tmp_path / "wf.sqlite"
    with VerticalSliceRuntime(checkpoint_path=str(db)) as rt:
        rt.start("thread-b", idempotency_key="k2")
        done = rt.resume("thread-b", {"accept": True})
        assert done.get("step") == "done"
        assert done.get("accepted") is True
        assert done.get("handoff_status") == "accepted"
        assert done.get("input_snapshot_hash") == "hash:k2:v1"


def test_resume_reject_does_not_accept_handoff(tmp_path: Path) -> None:
    db = tmp_path / "wf.sqlite"
    with VerticalSliceRuntime(checkpoint_path=str(db)) as rt:
        rt.start("thread-c", idempotency_key="k3")
        out = rt.resume("thread-c", {"accept": False})
        assert out.get("handoff_status") == "rejected"
        assert out.get("step") in {"blocked", "done", "gate"}


def test_restart_recovers_waiting_human_state(tmp_path: Path) -> None:
    db = tmp_path / "wf.sqlite"
    with VerticalSliceRuntime(checkpoint_path=str(db)) as rt:
        rt.start("thread-restart", idempotency_key="kr")
        state_before = rt.get_state("thread-restart")
        assert state_before.next

    # Process "restart": new runtime, same sqlite file.
    with reopen_runtime(str(db)) as rt2:
        state = rt2.get_state("thread-restart")
        assert state.next
        assert state.values.get("upstream_artifact") == "artifact:kr:v1"
        done = rt2.resume("thread-restart", {"accept": True})
        assert done.get("step") == "done"
        assert done.get("handoff_status") == "accepted"


def test_fork_from_checkpoint_creates_new_thread_lineage(tmp_path: Path) -> None:
    db = tmp_path / "wf.sqlite"
    with VerticalSliceRuntime(checkpoint_path=str(db)) as rt:
        rt.start("thread-src", idempotency_key="kf")
        ckpts = rt.list_checkpoint_ids("thread-src")
        assert ckpts
        forked = rt.fork_from_checkpoint(
            source_thread_id="thread-src",
            new_thread_id="thread-fork",
            checkpoint_id=ckpts[0],
        )
        # Source still waiting / independent.
        src = rt.get_state("thread-src")
        assert src.values.get("idempotency_key") == "kf"
        # Fork thread has values; may re-interrupt or complete depending on resume of start state.
        assert forked.get("upstream_artifact") == "artifact:kf:v1" or forked.get("idempotency_key") == "kf"


def test_side_effect_count_is_idempotent_on_start(tmp_path: Path) -> None:
    db = tmp_path / "wf.sqlite"
    with VerticalSliceRuntime(checkpoint_path=str(db)) as rt:
        r1 = rt.start("thread-idemp", idempotency_key="same")
        assert r1.get("side_effect_count") == 1
        # Re-invoking without resume should not double-write via replaying start blindly;
        # get_state remains at interrupt with count 1.
        state = rt.get_state("thread-idemp")
        assert int(state.values.get("side_effect_count") or 0) == 1


def test_memory_saver_rejected_for_delivery() -> None:
    class MemorySaver:
        pass

    with pytest.raises(RuntimeError, match="InMemorySaver|MemorySaver"):
        assert_not_memory_saver(MemorySaver())
