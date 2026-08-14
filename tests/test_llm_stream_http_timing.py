from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import time

import httpx

from core.llm.client import LLMClient
from core.llm.stream_http_timing import (
    StreamHttpTimings,
    capture_stream_http_timings,
    classify_raw_stream_event,
)
from core.web.services.runtime_scene_service import MAX_TELEMETRY_FIELD_ITEMS
from tests.helpers.isolated_config import isolated_settings_config


def make_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.contract", "tool_chat")
    kwargs.setdefault("llm.profiles.primary.streaming", True)
    kwargs.setdefault("llm.profiles.primary.tool_calling_mode", "auto")
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    return isolated_settings_config(**kwargs)


def test_classify_raw_stream_event_kinds():
    assert classify_raw_stream_event({"choices": [{"delta": {"role": "assistant"}}]}) == "role"
    assert classify_raw_stream_event({"choices": [{"delta": {"content": "ok"}}]}) == "content"
    assert classify_raw_stream_event({"choices": [{"delta": {"reasoning_content": "hmm"}}]}) == "reasoning"
    assert classify_raw_stream_event({"choices": [{"delta": {}}]}) == "empty_delta"
    assert classify_raw_stream_event({"id": "x"}) == "object"
    assert classify_raw_stream_event({}) == "empty"
    assert classify_raw_stream_event(None) == "empty"


def test_observe_trace_records_connect_tls_and_actual_proxy_route():
    timings = StreamHttpTimings(origin_host="api.example.com")
    timings.started_at = time.perf_counter() - 0.4
    timings.observe_trace("connection.connect_tcp.started", {"host": b"proxy.example.net"})
    timings.observe_trace("connection.connect_tcp.complete", {"return_value": object()})
    timings.observe_trace("connection.start_tls.complete", {"return_value": object()})
    timings.observe_trace("http11.send_request_body.complete", {"return_value": None})
    timings.observe_trace(
        "http11.receive_response_headers.complete",
        {"return_value": (b"HTTP/1.1", 200, b"OK", [])},
    )
    assert timings.connect_host == "proxy.example.net"
    assert timings.via_proxy is True
    assert timings.proxy_host == "proxy.example.net"
    assert timings.connect_ms is not None
    assert timings.tls_ms is not None
    assert timings.request_body_sent_ms is not None
    assert timings.http_headers_ms is not None
    assert timings.http_status == 200
    assert timings.header_receive_count == 1
    assert timings.connect_ms <= timings.tls_ms <= timings.http_headers_ms


def test_httpx_timing_splits_connect_and_delayed_headers():
    delay_s = 0.3

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            time.sleep(delay_s)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    _host, port = server.server_address
    seen = []

    with capture_stream_http_timings(on_http_headers=lambda item: seen.append(item.http_headers_ms)) as timings:
        with httpx.Client() as client:
            response = client.post(f"http://127.0.0.1:{port}/", json={"ping": True})
            assert response.status_code == 200
            assert response.text == "ok"
    thread.join(timeout=2)
    assert seen and seen[0] is not None
    assert timings.connect_ms is not None
    assert timings.http_headers_ms is not None
    assert timings.http_headers_ms >= 200
    assert timings.connect_ms < timings.http_headers_ms
    assert timings.request_body_sent_ms is not None
    assert timings.request_body_sent_ms <= timings.http_headers_ms
    assert timings.http_status == 200
    assert timings.origin_host == "127.0.0.1"


def test_httpx_timing_reports_no_proxy_when_no_proxy_bypasses_environment_proxy(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    _host, port = server.server_address
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")

    with capture_stream_http_timings(origin_host="127.0.0.1") as timings:
        with httpx.Client() as client:
            response = client.get(f"http://127.0.0.1:{port}/")
            assert response.status_code == 200
    thread.join(timeout=2)
    assert timings.connect_host == "127.0.0.1"
    assert timings.via_proxy is False
    assert timings.proxy_host == ""


def test_stream_records_first_raw_event_and_http_timing(monkeypatch):
    config = make_config(
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "qwen-32b-awq",
        }
    )
    recorded = []

    def backend(_payload):
        return iter(
            [
                {"choices": [{"delta": {"role": "assistant"}}]},
                {"choices": [{"delta": {"content": "ok"}}]},
            ]
        )

    monkeypatch.setattr(
        "core.llm.client._record_llm_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )
    client = LLMClient(config=config, backend=backend)
    events = list(client.stream_events([{"role": "user", "content": "ping"}]))
    assert [event.type for event in events] == ["text_delta", "done"]

    codes = [item[0][1] for item in recorded]
    assert "llm.stream.first_raw_event" in codes
    assert "llm.stream.http_timing" in codes
    assert "llm.stream.http_headers" not in codes

    raw_fields = next(item for item in recorded if item[0][1] == "llm.stream.first_raw_event")[1]["fields"]
    assert raw_fields["eventKind"] == "role"
    assert raw_fields["elapsedMs"] >= 0
    assert raw_fields["httpHeadersMs"] is None
    assert len(raw_fields) <= MAX_TELEMETRY_FIELD_ITEMS

    timing_fields = next(item for item in recorded if item[0][1] == "llm.stream.http_timing")[1]["fields"]
    assert timing_fields["firstRawEventMs"] is not None
    assert timing_fields["firstProjectedChunkMs"] is not None
    assert timing_fields["firstRawEventKind"] == "role"
    assert timing_fields["httpHeadersMs"] is None
    assert timing_fields["firstRawEventMs"] <= timing_fields["firstProjectedChunkMs"]
    assert len(timing_fields) <= MAX_TELEMETRY_FIELD_ITEMS

    first_fields = next(item for item in recorded if item[0][1] == "llm.stream.first_chunk")[1]["fields"]
    assert first_fields["chunkType"] == "text_delta"
    assert first_fields["firstRawEventMs"] is not None
    assert first_fields["httpHeadersMs"] is None
    assert len(first_fields) <= MAX_TELEMETRY_FIELD_ITEMS

    assert codes.index("llm.stream.first_raw_event") < codes.index("llm.stream.first_chunk")
    assert codes.index("llm.stream.http_timing") <= codes.index("llm.stream.succeeded")


def test_timing_ignores_unrelated_origin_host():
    timings = StreamHttpTimings(expected_origin_host="opencode.ai")

    class Other:
        class url:
            host = "raw.githubusercontent.com"

    class Target:
        class url:
            host = "opencode.ai"

    assert timings.tracks_request(Other()) is False
    assert timings.tracks_request(Target()) is True
