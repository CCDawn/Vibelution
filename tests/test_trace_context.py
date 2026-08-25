from __future__ import annotations

from core.logging.trace_context import (
    TraceContext,
    bind_trace_context,
    current_trace_fields,
    get_current_trace_context,
    merge_current_trace_fields,
    new_trace_context,
    parse_traceparent,
)


def test_parse_traceparent_accepts_w3c_ids_and_creates_server_span() -> None:
    trace_id = "1" * 32
    upstream_span_id = "2" * 16

    parsed = parse_traceparent(f"00-{trace_id}-{upstream_span_id}-01")
    context = new_trace_context(
        traceparent=f"00-{trace_id}-{upstream_span_id}-01",
        request_id="request-123",
    )

    assert parsed is not None
    assert parsed.trace_id == trace_id
    assert parsed.parent_span_id == upstream_span_id
    assert parsed.trace_flags == "01"
    assert context.trace_id == trace_id
    assert context.parent_span_id == upstream_span_id
    assert context.span_id != upstream_span_id
    assert len(context.span_id) == 16
    assert context.request_id == "request-123"
    assert context.to_traceparent() == f"00-{trace_id}-{context.span_id}-01"


def test_invalid_or_zero_traceparent_starts_a_new_trace() -> None:
    invalid_headers = (
        "",
        "00-" + ("0" * 32) + "-" + ("2" * 16) + "-01",
        "00-" + ("1" * 32) + "-" + ("0" * 16) + "-01",
        "00-short-parent-01",
        "ff-" + ("1" * 32) + "-" + ("2" * 16) + "-01",
    )

    for header in invalid_headers:
        assert parse_traceparent(header) is None
        context = new_trace_context(traceparent=header)
        assert len(context.trace_id) == 32
        assert context.trace_id != "0" * 32
        assert len(context.span_id) == 16
        assert context.span_id != "0" * 16
        assert context.parent_span_id is None


def test_bound_trace_context_is_scoped_and_explicit_fields_win() -> None:
    context = new_trace_context(request_id="request-scope")

    assert get_current_trace_context() is None
    assert current_trace_fields() == {}

    with bind_trace_context(context):
        assert get_current_trace_context() == context
        assert current_trace_fields() == context.to_fields()
        assert merge_current_trace_fields({"requestId": "explicit-request", "stage": "accepted"}) == {
            **context.to_fields(),
            "requestId": "explicit-request",
            "stage": "accepted",
        }

    assert get_current_trace_context() is None
    assert current_trace_fields() == {}


def test_trace_context_carrier_round_trip_and_child_span() -> None:
    root = new_trace_context(
        traceparent=f"00-{'1' * 32}-{'2' * 16}-01",
        request_id="request-carrier",
    )

    child = root.child_span()
    carrier = child.to_carrier()
    restored = TraceContext.from_carrier(carrier)

    assert restored == child
    assert child.trace_id == root.trace_id
    assert child.parent_span_id == root.span_id
    assert child.span_id != root.span_id
    assert carrier["traceparent"] == child.to_traceparent()
    assert carrier["requestId"] == "request-carrier"
