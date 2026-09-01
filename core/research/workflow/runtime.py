"""Vertical-slice runtime: invoke, resume, restart recovery, fork."""

from __future__ import annotations

import warnings
from typing import Any

from langgraph.types import Command

from .checkpoint_store import assert_not_memory_saver, open_sqlite_checkpointer
from .graph_builder import compile_vertical_slice


class VerticalSliceRuntime:
    """Thin runtime around the 3-node HITL graph with SQLite checkpointer.

    Test-only harness: unlike the production checkpoint lane (pump worker and
    per-operation handles), this object opens one SQLite connection in
    ``__init__`` and holds it for the whole lifetime.  Never attach it to the
    shared product checkpoint store; doing so emits a :class:`RuntimeWarning`.
    """

    def __init__(self, checkpoint_path: str | None = None):
        if checkpoint_path is None:
            warnings.warn(
                "VerticalSliceRuntime is a test-only harness that holds one "
                "SQLite connection for its whole lifetime; pass an isolated "
                "checkpoint_path instead of the shared product store.",
                RuntimeWarning,
                stacklevel=2,
            )
        self._checkpoint_path = checkpoint_path
        self._cm = open_sqlite_checkpointer(checkpoint_path)
        self._checkpointer = self._cm.__enter__()
        assert_not_memory_saver(self._checkpointer)
        self._graph = compile_vertical_slice(self._checkpointer)

    def close(self) -> None:
        self._cm.__exit__(None, None, None)

    def __enter__(self) -> VerticalSliceRuntime:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def thread_config(thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    def start(self, thread_id: str, *, idempotency_key: str = "default") -> dict[str, Any]:
        return self._graph.invoke(
            {"idempotency_key": idempotency_key},
            self.thread_config(thread_id),
        )

    def resume(self, thread_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        return self._graph.invoke(
            Command(resume=decision),
            self.thread_config(thread_id),
        )

    def get_state(self, thread_id: str) -> Any:
        return self._graph.get_state(self.thread_config(thread_id))

    def list_checkpoint_ids(self, thread_id: str) -> list[str]:
        ids: list[str] = []
        for item in self._graph.get_state_history(self.thread_config(thread_id)):
            cfg = item.config.get("configurable") or {}
            ck = cfg.get("checkpoint_id")
            if ck:
                ids.append(str(ck))
        return ids

    def fork_from_checkpoint(
        self,
        *,
        source_thread_id: str,
        new_thread_id: str,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new thread lineage from an existing checkpoint (historical fork)."""
        source_cfg = self.thread_config(source_thread_id)
        if checkpoint_id:
            source_cfg = {
                "configurable": {
                    "thread_id": source_thread_id,
                    "checkpoint_id": checkpoint_id,
                }
            }
        state = self._graph.get_state(source_cfg)
        values = dict(state.values or {})
        # New thread starts with prior values as initial state without mutating source.
        return self._graph.invoke(values, self.thread_config(new_thread_id))


def reopen_runtime(checkpoint_path: str) -> VerticalSliceRuntime:
    """Simulate process restart by opening a new runtime on the same sqlite file."""
    return VerticalSliceRuntime(checkpoint_path=checkpoint_path)
