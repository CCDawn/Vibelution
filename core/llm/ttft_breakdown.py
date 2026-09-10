# -*- coding: utf-8 -*-
"""Turn-level TTFT (time to first token) segment breakdown.

Pure observation: the session worker opens ``llm_ttft_chain_context`` around
the agent run with acceptance/worker-start ``time.perf_counter`` anchors; the
LLM client reads that chain at the first projected stream chunk and derives
one ``llm.stream.ttft_breakdown`` scene event.  Nothing here mutates turn
behavior, and segments whose anchor is missing are omitted (never invented).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Mapping

_TTFT_CHAIN_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "vibelution_llm_ttft_chain_context",
    default=None,
)


def current_llm_ttft_chain() -> Mapping[str, Any] | None:
    """Return the active turn TTFT chain state, if a worker opened one."""

    return _TTFT_CHAIN_CONTEXT.get()


@contextmanager
def llm_ttft_chain_context(
    *,
    accepted_at_perf: float | None = None,
    worker_started_at_perf: float | None = None,
    queue_wait_ms: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Attribute LLM first-chunk timings to one accepted turn.

    ``accepted_at_perf`` / ``worker_started_at_perf`` must be
    ``time.perf_counter`` readings captured in the same process as the LLM
    client (the session worker executor thread qualifies).
    """

    state: dict[str, Any] = {
        "acceptedAtPerf": _clean_perf(accepted_at_perf),
        "workerStartedAtPerf": _clean_perf(worker_started_at_perf),
        "queueWaitMs": _clean_nonnegative_ms(queue_wait_ms),
        "breakdownEmitted": False,
    }
    token = _TTFT_CHAIN_CONTEXT.set(state)
    try:
        yield state
    finally:
        _TTFT_CHAIN_CONTEXT.reset(token)


def _clean_perf(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _clean_nonnegative_ms(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or value != value:
        return None
    return int(value)


def _delta_ms(start: Any, end: Any) -> int | None:
    start_value = _clean_perf(start)
    end_value = _clean_perf(end)
    if start_value is None or end_value is None:
        return None
    return max(0, int((end_value - start_value) * 1000))


def build_llm_ttft_breakdown_fields(
    *,
    chain: Mapping[str, Any] | None,
    request_started_perf: float,
    first_chunk_perf: float,
    payload_build_ms: int | None = None,
    route_gate_wait_ms: int | None = None,
    stream_open_ms: int | None = None,
    first_raw_chunk_ms: int | None = None,
    first_projected_chunk_ms: int | None = None,
    first_chunk_ms: int | None = None,
) -> dict[str, int]:
    """Derive turn-level TTFT segments from anchors; missing segments omitted.

    Segment semantics (all ms integers):
    - ``queueWaitMs``: accept → worker actually started (scheduler/admission).
    - ``contextBuildMs``: worker start → LLM request flow entered (context
      assembly, prompt build; payload build is reported separately).
    - ``payloadBuildMs``: LLM payload construction inside the client.
    - ``routeGateWaitMs``: per-route concurrency gate wait for the winning attempt.
    - ``streamOpenMs``: request sent → HTTP response headers (connect/TLS).
    - ``firstRawChunkMs`` / ``firstProjectedChunkMs``: first provider wire
      event / first normalized chunk relative to the stream timing start.
    - ``firstChunkMs``: first projected chunk relative to the client request start.
    - ``ttftTotalMs``: accept → first projected chunk (user-perceived TTFT).
    """

    if not isinstance(chain, Mapping):
        return {}
    fields: dict[str, int] = {}
    queue_wait_ms = _clean_nonnegative_ms(chain.get("queueWaitMs"))
    if queue_wait_ms is not None:
        fields["queueWaitMs"] = queue_wait_ms
    context_build_ms = _delta_ms(chain.get("workerStartedAtPerf"), request_started_perf)
    if context_build_ms is not None:
        fields["contextBuildMs"] = context_build_ms
    for key, value in (
        ("routeGateWaitMs", route_gate_wait_ms),
        ("payloadBuildMs", payload_build_ms),
        ("streamOpenMs", stream_open_ms),
        ("firstRawChunkMs", first_raw_chunk_ms),
        ("firstProjectedChunkMs", first_projected_chunk_ms),
        ("firstChunkMs", first_chunk_ms),
    ):
        cleaned = _clean_nonnegative_ms(value)
        if cleaned is not None:
            fields[key] = cleaned
    total_ms = _delta_ms(chain.get("acceptedAtPerf"), first_chunk_perf)
    if total_ms is not None:
        fields["ttftTotalMs"] = total_ms
    return fields


def format_llm_ttft_summary(fields: Mapping[str, int]) -> str:
    """One human-readable ``name=123ms`` line for the conversation debug log."""

    return " ".join(f"{key}={value}ms" for key, value in fields.items())


__all__ = [
    "build_llm_ttft_breakdown_fields",
    "current_llm_ttft_chain",
    "format_llm_ttft_summary",
    "llm_ttft_chain_context",
]
