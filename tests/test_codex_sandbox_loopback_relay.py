"""Loopback relay unit tests: local fake upstream, no real network.

覆盖面（对应在线档安全模型）：
- 路由改写：/{service}/{rest} → 上游 {rest}，Host 重写为 allowlist 主机，
  方法/体/头透传，hop-by-hop 头剥除。
- 拒绝面：未知 service、空 service、绝对 URI 形式、未列方法一律 403。
- 重定向手动逐跳：目标 host 在允许集内才跟随；不允许的目标 403 且不外连；
  跳数上限 502。
- /__relay_probe 200 "ok"；stop 幂等；并发请求；体积上限；上游故障 502。
- 上游连接走本进程 TLS 默认上下文（HTTPSConnection + create_default_context）。
"""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.infrastructure.codex_sandbox import loopback_relay
from core.infrastructure.codex_sandbox.loopback_relay import (
    DEFAULT_MAX_BODY_BYTES,
    MAX_REDIRECT_HOPS,
    RELAY_ERROR_HEADER,
    RELAY_PROBE_PATH,
    LoopbackRelay,
    get_or_start_relay,
    stop_relay,
)

HOST_A = "relay-upstream-a.test"
HOST_B = "relay-upstream-b.test"


class _FakeUpstreamHandler(BaseHTTPRequestHandler):
    """Deterministic fake upstream: echoes or redirects per path."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002 - stdlib API
        pass

    def _record(self):
        received = self.server.received
        received.append(
            {
                "method": self.command,
                "path": self.path,
                "host": self.headers.get("Host") or "",
                "headers": {k.lower(): v for k, v in self.headers.items()},
            }
        )

    def _respond(self, status, body=b"", headers=None):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _handle(self):
        self._record()
        path = self.path.split("?")[0]
        if path == "/ok":
            self._respond(200, b"fake-ok", {"X-Fake": "yes"})
            return
        if path == "/echo":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            payload = json.dumps(
                {
                    "method": self.command,
                    "path": self.path,
                    "body": body.decode("utf-8", "replace"),
                    "contentType": self.headers.get("Content-Type") or "",
                    "connection": self.headers.get("Connection") or "",
                    "te": self.headers.get("TE") or "",
                }
            ).encode("utf-8")
            self._respond(200, payload, {"Content-Type": "application/json"})
            return
        if path == "/redirect-allowed":
            self._respond(302, b"moved", {"Location": f"http://{HOST_B}/final"})
            return
        if path == "/redirect-disallowed":
            self._respond(302, b"moved", {"Location": "http://relay-evil.test/steal"})
            return
        if path == "/redirect-relative-allowed":
            self._respond(307, b"moved", {"Location": "/final"})
            return
        if path == "/redirect-loop":
            self._respond(302, b"loop", {"Location": "/redirect-loop"})
            return
        if path == "/final":
            self._respond(200, b"fake-final-ok")
            return
        if path == "/big":
            self._respond(200, b"x" * 4096)
            return
        if path == "/gone":
            # Abrupt upstream death mid-request.
            self.close_connection = True
            self.wfile.close()
            return
        self._respond(404, b"not-found")

    do_GET = _handle
    do_POST = _handle
    do_HEAD = _handle
    do_PUT = _handle
    do_PATCH = _handle
    do_DELETE = _handle


class _FakeUpstream:
    def __init__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstreamHandler)
        self.server.received = []
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    @property
    def received(self):
        return self.server.received


@pytest.fixture
def fake_upstream():
    upstream = _FakeUpstream()
    upstream.start()
    try:
        yield upstream
    finally:
        upstream.stop()


@pytest.fixture(autouse=True)
def clean_relay_singleton():
    stop_relay()
    yield
    stop_relay()


def _make_relay(fake_upstream, **kwargs) -> LoopbackRelay:
    services = kwargs.pop("services", {"svc-a": HOST_A, "svc-b": HOST_B})
    relay = LoopbackRelay(
        services,
        upstream_tls=False,
        connect_overrides={
            HOST_A: ("127.0.0.1", fake_upstream.port),
            HOST_B: ("127.0.0.1", fake_upstream.port),
        },
        **kwargs,
    )
    relay.start()
    return relay


def _request(port, method, target, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, target, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        return response.status, dict(response.getheaders()), data
    finally:
        connection.close()


# ---------------------------------------------------------------- routing


def test_probe_returns_ok(fake_upstream):
    relay = _make_relay(fake_upstream)
    status, headers, body = _request(relay.port, "GET", RELAY_PROBE_PATH)
    assert status == 200
    assert body == b"ok"


def test_route_rewrites_path_and_host(fake_upstream):
    relay = _make_relay(fake_upstream)
    status, headers, body = _request(relay.port, "GET", "/svc-a/ok?x=1")
    assert status == 200
    assert body == b"fake-ok"
    assert headers.get("X-Fake") == "yes"
    seen = fake_upstream.received[-1]
    assert seen["host"] == HOST_A
    assert seen["path"] == "/ok?x=1"


def test_service_root_maps_to_upstream_root(fake_upstream):
    relay = _make_relay(fake_upstream)
    status, _headers, body = _request(relay.port, "GET", "/svc-a")
    assert status == 404  # upstream "/" has no handler → fake 404 passthrough
    assert body == b"not-found"
    assert fake_upstream.received[-1]["path"] == "/"


def test_methods_and_body_passthrough(fake_upstream):
    relay = _make_relay(fake_upstream)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        status, _headers, body = _request(
            relay.port,
            method,
            "/svc-a/echo",
            body=b"payload-123",
            headers={"Content-Type": "text/plain"},
        )
        assert status == 200
        echo = json.loads(body)
        assert echo["method"] == method
        assert echo["body"] == "payload-123"
        assert echo["contentType"] == "text/plain"
    status, _headers, body = _request(relay.port, "HEAD", "/svc-a/ok")
    assert status == 200
    assert body == b""


def test_hop_by_hop_headers_stripped(fake_upstream):
    relay = _make_relay(fake_upstream)
    status, _headers, body = _request(
        relay.port,
        "GET",
        "/svc-a/echo",
        headers={"Connection": "keep-alive", "TE": "trailers", "X-Keep": "yes"},
    )
    assert status == 200
    echo = json.loads(body)
    assert echo["connection"] == ""  # hop-by-hop stripped before upstream
    assert echo["te"] == ""
    assert fake_upstream.received[-1]["headers"].get("x-keep") == "yes"


# ---------------------------------------------------------------- refusals


def test_unknown_service_id_403(fake_upstream):
    relay = _make_relay(fake_upstream)
    status, headers, _body = _request(relay.port, "GET", "/nope/ok")
    assert status == 403
    assert headers.get(RELAY_ERROR_HEADER) == "unknown_service_id"
    assert not fake_upstream.received


def test_empty_service_id_403(fake_upstream):
    relay = _make_relay(fake_upstream)
    status, headers, _body = _request(relay.port, "GET", "/")
    assert status == 403
    assert headers.get(RELAY_ERROR_HEADER) == "empty_service_id"


def test_absolute_uri_form_403(fake_upstream):
    relay = _make_relay(fake_upstream)
    status, headers, _body = _request(relay.port, "GET", "http://relay-evil.test/x")
    assert status == 403
    assert headers.get(RELAY_ERROR_HEADER) == "absolute_uri_unsupported"
    # Raw proxy-style request line (what sandbox curl sends to a proxy).
    with socket.create_connection(("127.0.0.1", relay.port), timeout=5) as sock:
        sock.sendall(
            b"GET http://relay-evil.test/x HTTP/1.1\r\n"
            b"Host: relay-evil.test\r\nConnection: close\r\n\r\n"
        )
        raw = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
    first_line = raw.split(b"\r\n", 1)[0].decode("latin-1")
    assert " 403 " in first_line
    assert RELAY_ERROR_HEADER.encode("latin-1") in raw
    assert not fake_upstream.received


def test_unlisted_method_403(fake_upstream):
    relay = _make_relay(fake_upstream)
    status, headers, _body = _request(relay.port, "OPTIONS", "/svc-a/ok")
    assert status in {403, 501}
    assert headers.get(RELAY_ERROR_HEADER) in {"method_not_allowed", None}


def test_invalid_service_config_rejected():
    with pytest.raises(ValueError):
        LoopbackRelay({"bad id": HOST_A})
    with pytest.raises(ValueError):
        LoopbackRelay({"": HOST_A})
    with pytest.raises(ValueError):
        LoopbackRelay({"svc": "host/path"})


# ---------------------------------------------------------------- redirects


def test_redirect_to_allowed_host_followed(fake_upstream):
    relay = _make_relay(fake_upstream)
    status, _headers, body = _request(relay.port, "GET", "/svc-a/redirect-allowed")
    assert status == 200
    assert body == b"fake-final-ok"
    assert fake_upstream.received[-1]["host"] == HOST_B
    assert fake_upstream.received[-1]["path"] == "/final"


def test_redirect_post_303_downgrades_to_get(fake_upstream):
    relay = _make_relay(fake_upstream)
    status, _headers, body = _request(
        relay.port, "POST", "/svc-a/redirect-allowed", body=b"data"
    )
    assert status == 200
    assert fake_upstream.received[-1]["method"] == "GET"
    assert body == b"fake-final-ok"


def test_redirect_relative_preserves_method_307(fake_upstream):
    relay = _make_relay(fake_upstream)
    status, _headers, _body = _request(
        relay.port, "POST", "/svc-a/redirect-relative-allowed", body=b"keep"
    )
    assert status == 200
    seen = fake_upstream.received[-1]
    assert seen["method"] == "POST"
    assert seen["path"] == "/final"


def test_redirect_to_disallowed_host_refused_without_connecting(fake_upstream):
    relay = _make_relay(fake_upstream)
    status, headers, _body = _request(relay.port, "GET", "/svc-a/redirect-disallowed")
    assert status == 403
    assert headers.get(RELAY_ERROR_HEADER) == "redirect_target_not_allowed"
    # Only the initial hop reached the fake upstream; evil host was never tried.
    assert len(fake_upstream.received) == 1
    assert fake_upstream.received[0]["path"] == "/redirect-disallowed"


def test_redirect_hop_limit_returns_502(fake_upstream):
    relay = _make_relay(fake_upstream)
    status, headers, _body = _request(relay.port, "GET", "/svc-a/redirect-loop")
    assert status == 502
    assert headers.get(RELAY_ERROR_HEADER) == "redirect_hop_limit_exceeded"
    assert len(fake_upstream.received) == MAX_REDIRECT_HOPS + 1


# ---------------------------------------------------------------- limits


def test_response_body_cap_returns_502(fake_upstream):
    relay = _make_relay(fake_upstream, max_body_bytes=1024)
    status, headers, _body = _request(relay.port, "GET", "/svc-a/big")
    assert status == 502
    assert headers.get(RELAY_ERROR_HEADER) == "response_body_too_large"


def test_request_body_cap_returns_413(fake_upstream):
    relay = _make_relay(fake_upstream, max_body_bytes=16)
    status, headers, _body = _request(
        relay.port, "POST", "/svc-a/echo", body=b"x" * 64
    )
    assert status == 413
    assert headers.get(RELAY_ERROR_HEADER) == "request_body_too_large"


def test_upstream_connection_failure_502():
    relay = LoopbackRelay({"dead": HOST_A}, upstream_tls=False)
    # Reserve then close a port so nothing listens there.
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    dead_port = int(probe.getsockname()[1])
    probe.close()
    relay._connect_overrides[HOST_A] = ("127.0.0.1", dead_port)
    relay.start()
    status, headers, _body = _request(relay.port, "GET", "/dead/ok")
    assert status == 502
    reason = headers.get(RELAY_ERROR_HEADER) or ""
    assert reason.startswith("upstream_")


# ---------------------------------------------------------------- lifecycle


def test_stop_is_idempotent_and_releases_port(fake_upstream):
    relay = _make_relay(fake_upstream)
    port = relay.port
    status, _headers, _body = _request(port, "GET", RELAY_PROBE_PATH)
    assert status == 200
    relay.stop()
    relay.stop()
    assert relay.is_running is False
    with pytest.raises(OSError):
        _request(port, "GET", RELAY_PROBE_PATH)


def test_concurrent_requests(fake_upstream):
    relay = _make_relay(fake_upstream)
    results: list = []
    lock = threading.Lock()

    def _hit():
        status, _headers, body = _request(relay.port, "GET", "/svc-a/ok")
        with lock:
            results.append((status, body))

    threads = [threading.Thread(target=_hit) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert len(results) == 8
    assert all(status == 200 and body == b"fake-ok" for status, body in results)


def test_singleton_merges_services_and_keeps_port(fake_upstream):
    overrides = {
        HOST_A: ("127.0.0.1", fake_upstream.port),
        HOST_B: ("127.0.0.1", fake_upstream.port),
    }
    handle_a = get_or_start_relay(
        {"svc-a": HOST_A}, upstream_tls=False, connect_overrides=overrides
    )
    # Second call: only service entries merge; connection settings and the
    # verified port stay fixed.
    handle_b = get_or_start_relay({"svc-b": HOST_B})
    assert handle_b.port == handle_a.port
    status_a, _h, body_a = _request(handle_a.port, "GET", "/svc-a/ok")
    status_b, _h, body_b = _request(handle_b.port, "GET", "/svc-b/ok")
    assert (status_a, body_a) == (200, b"fake-ok")
    assert (status_b, body_b) == (200, b"fake-ok")


def test_upstream_tls_uses_default_verification_context(monkeypatch):
    # NOTE: patching http.client.HTTPSConnection itself is off-limits here —
    # stdlib's HTTPSConnection.__init__ resolves `super(HTTPSConnection, self)`
    # via the module global and would self-dispatch into the patched subclass.
    # Instead, observe the TLS context built on the relay's upstream path.
    context_calls: list = []
    real_create = ssl.create_default_context

    def _recording_create(*args, **kwargs):
        context_calls.append(kwargs)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(loopback_relay.ssl, "create_default_context", _recording_create)
    relay = LoopbackRelay({"pypi": "pypi.org"})
    connection = relay._build_upstream_connection("pypi.org")
    assert isinstance(connection, http.client.HTTPSConnection)
    assert context_calls, "upstream TLS must build its context via ssl.create_default_context"
    context = connection._context
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    plain = LoopbackRelay({"pypi": "pypi.org"}, upstream_tls=False)
    plain_connection = plain._build_upstream_connection("pypi.org")
    assert isinstance(plain_connection, http.client.HTTPSConnection) is False
    assert isinstance(plain_connection, http.client.HTTPConnection)
    stop_relay()
    assert DEFAULT_MAX_BODY_BYTES == 64 * 1024 * 1024
