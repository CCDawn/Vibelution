# -*- coding: utf-8 -*-
"""Turn-level TTFT segment derivation tests (pure functions + chain context)."""

import time

from core.llm.ttft_breakdown import (
    build_llm_ttft_breakdown_fields,
    current_llm_ttft_chain,
    format_llm_ttft_summary,
    llm_ttft_chain_context,
)


def test_build_breakdown_fields_derives_all_segments_from_anchors():
    accepted_at = 1000.0
    worker_started_at = accepted_at + 0.25  # 250ms queue wait
    request_started_at = worker_started_at + 0.75  # 750ms context build
    first_chunk_at = accepted_at + 2.0  # 2000ms total TTFT

    fields = build_llm_ttft_breakdown_fields(
        chain={
            "acceptedAtPerf": accepted_at,
            "workerStartedAtPerf": worker_started_at,
            "queueWaitMs": 250,
        },
        request_started_perf=request_started_at,
        first_chunk_perf=first_chunk_at,
        payload_build_ms=120,
        route_gate_wait_ms=30,
        stream_open_ms=400,
        first_raw_chunk_ms=900,
        first_projected_chunk_ms=950,
        first_chunk_ms=980,
    )

    assert fields == {
        "queueWaitMs": 250,
        "contextBuildMs": 750,
        "routeGateWaitMs": 30,
        "payloadBuildMs": 120,
        "streamOpenMs": 400,
        "firstRawChunkMs": 900,
        "firstProjectedChunkMs": 950,
        "firstChunkMs": 980,
        "ttftTotalMs": 2000,
    }


def test_build_breakdown_fields_omits_missing_segments_without_fabricating():
    fields = build_llm_ttft_breakdown_fields(
        chain={"acceptedAtPerf": 100.0, "workerStartedAtPerf": None, "queueWaitMs": None},
        request_started_perf=100.5,
        first_chunk_perf=101.25,
        payload_build_ms=None,
        route_gate_wait_ms=None,
        stream_open_ms=None,
        first_raw_chunk_ms=None,
        first_projected_chunk_ms=None,
        first_chunk_ms=None,
    )

    assert fields == {"ttftTotalMs": 1250}


def test_build_breakdown_fields_without_chain_returns_empty():
    assert (
        build_llm_ttft_breakdown_fields(
            chain=None,
            request_started_perf=time.perf_counter(),
            first_chunk_perf=time.perf_counter(),
        )
        == {}
    )


def test_build_breakdown_fields_clamps_clock_skew_to_zero():
    fields = build_llm_ttft_breakdown_fields(
        chain={"acceptedAtPerf": 200.0, "workerStartedAtPerf": 199.0, "queueWaitMs": -5},
        request_started_perf=198.0,
        first_chunk_perf=200.5,
    )

    assert fields["contextBuildMs"] == 0
    assert fields["ttftTotalMs"] == 500
    assert "queueWaitMs" not in fields


def test_build_breakdown_fields_rejects_bool_and_nan_anchors():
    fields = build_llm_ttft_breakdown_fields(
        chain={
            "acceptedAtPerf": True,
            "workerStartedAtPerf": float("nan"),
            "queueWaitMs": True,
        },
        request_started_perf=10.0,
        first_chunk_perf=11.0,
    )

    assert fields == {}


def test_chain_context_scopes_state_and_resets():
    assert current_llm_ttft_chain() is None
    with llm_ttft_chain_context(
        accepted_at_perf=1.0,
        worker_started_at_perf=1.5,
        queue_wait_ms=500,
    ) as state:
        chain = current_llm_ttft_chain()
        assert chain is state
        assert chain["acceptedAtPerf"] == 1.0
        assert chain["workerStartedAtPerf"] == 1.5
        assert chain["queueWaitMs"] == 500
        assert chain["breakdownEmitted"] is False
    assert current_llm_ttft_chain() is None


def test_chain_context_tolerates_missing_anchors():
    with llm_ttft_chain_context() as state:
        assert state["acceptedAtPerf"] is None
        assert state["workerStartedAtPerf"] is None
        assert state["queueWaitMs"] is None


def test_format_summary_is_single_machine_grep_line():
    line = format_llm_ttft_summary({"queueWaitMs": 12, "ttftTotalMs": 345})
    assert line == "queueWaitMs=12ms ttftTotalMs=345ms"
