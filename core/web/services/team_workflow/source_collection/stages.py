"""Source-collection stage session tasks: seed, start, writeback, context, reconcile.

Clarity B6: implementations live in ``stage_session`` + ``stage_writeback``.
This module re-exports the public surface for stable import paths.
"""

from __future__ import annotations

from .stage_session import (
    assert_source_collection_stage_advance_ready,
    seed_source_collection_agent_session_context,
    start_source_collection_stage_session_task,
)
from .stage_writeback import (
    get_source_collection_stage_task_context,
    reconcile_source_collection_stage_session_task_after_turn,
    writeback_source_collection_stage_session_task,
)

__all__ = [
    "assert_source_collection_stage_advance_ready",
    "get_source_collection_stage_task_context",
    "reconcile_source_collection_stage_session_task_after_turn",
    "seed_source_collection_agent_session_context",
    "start_source_collection_stage_session_task",
    "writeback_source_collection_stage_session_task",
]
