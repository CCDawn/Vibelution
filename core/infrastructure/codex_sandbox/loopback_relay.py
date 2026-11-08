"""Plaintext HTTP loopback relay for the MXC online tier (host-side TLS).

The sandboxed client cannot do TLS itself (measured on the basecontainer
tier: ``import ssl`` fails with a DLL init error and ``curl https`` exits
rc=35), so no CONNECT tunnel / MITM / custom-CA design is viable. The only
workable shape: the sandbox speaks plaintext HTTP to ``127.0.0.1`` and this
relay terminates the upstream TLS inside the host process.

Security model (fail closed everywhere):

- The service map (``{"pypi": "pypi.org"}``) is supplied by the caller; this
  module hard-codes no upstream site.
- Routing is ``/{service_id}/{rest...}`` -> ``https://{upstream}/{rest...}``.
  Unknown service ids, empty service ids, absolute-URI request forms and
  methods outside the explicit allowlist are refused with 403.
- Upstream redirects are followed manually, one hop at a time, and every hop
  target host must still be inside the allowlist. Automatic client redirect
  following is never used, so a redirect cannot bypass the allowlist.
- Request and response bodies are bounded (default 64 MB) and both
  directions carry timeouts (default 30 s); violations fail closed.
- The relay is a pure in-process daemon-thread server: no child process is
  spawned (无控制台红线 §8.0), no persistent state is written, and process
  exit tears everything down.
"""

from __future__ import annotations

import http.client
import logging
import re
import ssl
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_LOG = logging.getLogger(__name__)

RELAY_PROBE_PATH = "/__relay_probe"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_BODY_BYTES = 64 * 1024 * 1024
MAX_REDIRECT_HOPS = 5

RELAY_ERROR_HEADER = "X-Relay-Error"
_ALLOWED_METHODS = frozenset({"GET", "POST", "HEAD", "PUT", "PATCH", "DELETE"})
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_NO_BODY_STATUSES = frozenset({204, 304})
_BODY_DRAIN_CHUNK = 65536
_SERVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _validated_service_map(services: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_key, raw_host in dict(services).items():
        key = str(raw_key).strip()
        host = str(raw_host).strip()
        if not key or not _SERVICE_ID_PATTERN.match(key):
            raise ValueError(f"invalid relay service id: {raw_key!r}")
        if not host or "/" in host or "@" in host or ":" in host:
            raise ValueError(f"invalid relay upstream host: {raw_host!r}")
        result[key] = host.lower()
    return result


class LoopbackRelay:
    """Plaintext loopback HTTP relay; upstream TLS terminates in this process.

    ``services`` maps a sandbox-visible path segment to the upstream host:
    ``GET /pypi/index`` is forwarded to ``https://pypi.org/index``. Only the
    listed upstream hosts are reachable, including across redirects.
    ``connect_overrides`` optionally maps an upstream host to a
    ``(connect_host, connect_port)`` endpoint (test seam for fake upstreams);
    the ``Host`` header always carries the allowlist host.
    """

    def __init__(
        self,
        services: dict,
        *,
        upstream_tls: bool = True,
        connect_overrides: dict | None = None,
        request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        self._services_lock = threading.Lock()
        self._services: dict[str, str] = _validated_service_map(services)
        self.upstream_tls = bool(upstream_tls)
        overrides: dict[str, tuple[str, int]] = {}
        for raw_host, endpoint in dict(connect_overrides or {}).items():
            host = str(raw_host).strip().lower()
            connect_host, connect_port = endpoint
            overrides[host] = (str(connect_host), int(connect_port))
        self._connect_overrides = overrides
        self.request_timeout_s = float(request_timeout_s)
        self.max_body_bytes = int(max_body_bytes)
        self.port: int | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- service registry (shared with request threads) --------------------

    def service_map(self) -> dict[str, str]:
        with self._services_lock:
            return dict(self._services)

    def allowed_hosts(self) -> frozenset:
        with self._services_lock:
            return frozenset(self._services.values())

    def merge_services(self, services: dict) -> None:
        """Merge additional service entries into the live map (thread-safe)."""
        merged = _validated_service_map(services)
        if not merged:
            return
        with self._services_lock:
            self._services.update(merged)

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> int:
        """Bind 127.0.0.1 on an ephemeral port and serve on a daemon thread."""
        if self._server is not None:
            assert self.port is not None
            return self.port
        server = _RelayHTTPServer(("127.0.0.1", 0), self)
        self.port = int(server.server_address[1])
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.2},
            name="mxc-loopback-relay",
            daemon=True,
        )
        self._thread.start()
        _LOG.info(
            "loopback relay listening on 127.0.0.1:%s services=%s",
            self.port,
            sorted(self.service_map()),
        )
        return self.port

    def stop(self) -> None:
        """Stop serving and release the socket (idempotent)."""
        server, self._server = self._server, None
        thread, self._thread = self._thread, None
        if server is None:
            return
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        if thread is not None:
            thread.join(timeout=2.0)

    @property
    def is_running(self) -> bool:
        return self._server is not None

    # -- upstream connection -------------------------------------------------

    def _build_upstream_connection(self, host: str, port: int | None = None) -> http.client.HTTPConnection:
        override = self._connect_overrides.get(str(host).strip().lower())
        if override is not None:
            connect_host, connect_port = override
        else:
            connect_host, connect_port = host, (int(port) if port else 443)
        if self.upstream_tls:
            # The host process terminates upstream TLS with the default,
            # verification-enabled context: sandboxed clients cannot do TLS
            # themselves (measured DLL init failure), so this is the trust
            # boundary — never downgrade to an unverified context.
            return http.client.HTTPSConnection(
                connect_host,
                connect_port,
                timeout=self.request_timeout_s,
                context=ssl.create_default_context(),
            )
        return http.client.HTTPConnection(
            connect_host, connect_port, timeout=self.request_timeout_s
        )


class _RelayHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, relay: LoopbackRelay) -> None:
        self.relay = relay
        super().__init__(server_address, _RelayRequestHandler)


class _RelayRequestHandler(BaseHTTPRequestHandler):
    """Handles one sandboxed-client request at a time (HTTP/1.1, bounded)."""

    protocol_version = "HTTP/1.1"
    server_version = "VibelutionLoopbackRelay/1.0"
    timeout = DEFAULT_REQUEST_TIMEOUT_SECONDS

    # -- plumbing ------------------------------------------------------------

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib API
        _LOG.debug("relay: " + (format % args))

    @property
    def _relay(self) -> LoopbackRelay:
        relay = getattr(self.server, "relay", None)
        if relay is None:  # pragma: no cover - construction guarantees it
            raise RuntimeError("relay server misconfigured")
        return relay

    def _reject(self, status: int, reason: str) -> None:
        self.close_connection = True
        text = reason.encode("utf-8", "replace")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header(RELAY_ERROR_HEADER, reason[:120])
            self.send_header("Content-Length", str(len(text)))
            self.end_headers()
            if self.command != "HEAD" and text:
                self.wfile.write(text)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _send_final(self, status: int, body: bytes, extra_headers: list) -> None:
        try:
            self.send_response(int(status))
            for name, value in extra_headers:
                self.send_header(name, value)
            if status not in _NO_BODY_STATUSES:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD" and body and status not in _NO_BODY_STATUSES:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.close_connection = True

    # -- method dispatch -------------------------------------------------------

    def do_GET(self) -> None:
        self._safe_handle()

    def do_POST(self) -> None:
        self._safe_handle()

    def do_HEAD(self) -> None:
        self._safe_handle()

    def do_PUT(self) -> None:
        self._safe_handle()

    def do_PATCH(self) -> None:
        self._safe_handle()

    def do_DELETE(self) -> None:
        self._safe_handle()

    def _safe_handle(self) -> None:
        try:
            self._handle()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            _LOG.exception("relay handler error for %s %s", self.command, self.path)
            try:
                self._reject(502, "relay_internal_error")
            except Exception:
                self.close_connection = True

    # -- routing -----------------------------------------------------------------

    def _handle(self) -> None:
        if self.command not in _ALLOWED_METHODS:
            self._reject(403, "method_not_allowed")
            return
        relay = self._relay
        split = urllib.parse.urlsplit(self.path)
        # Absolute-URI request forms (proxy style) are never accepted: the
        # sandbox must always address the relay by service path.
        if split.scheme or split.netloc or self.path == "*" or not self.path.startswith("/"):
            self._reject(403, "absolute_uri_unsupported")
            return
        if split.path == RELAY_PROBE_PATH:
            self._send_final(200, b"ok", [])
            return
        remainder = split.path.lstrip("/")
        if not remainder:
            self._reject(403, "empty_service_id")
            return
        service_id, _, rest = remainder.partition("/")
        upstream_host = relay.service_map().get(service_id)
        if upstream_host is None:
            self._reject(403, "unknown_service_id")
            return
        body = self._read_request_body()
        if body is None:
            return
        base_headers = self._upstream_request_headers()
        scheme = "https" if relay.upstream_tls else "http"
        target = f"{scheme}://{upstream_host}/{rest}"
        if split.query:
            target = f"{target}?{split.query}"
        method = self.command
        hop_body = body
        for hop in range(MAX_REDIRECT_HOPS + 1):
            outcome = self._forward_once(target, method, base_headers, hop_body)
            if isinstance(outcome, str):
                self._reject(502, outcome)
                return
            status, response_headers, response_body, location = outcome
            if status not in _REDIRECT_STATUSES:
                self._send_final(status, response_body, response_headers)
                return
            if hop == MAX_REDIRECT_HOPS:
                self._reject(502, "redirect_hop_limit_exceeded")
                return
            if not location:
                self._reject(502, "redirect_missing_location")
                return
            resolved = urllib.parse.urljoin(target, location.strip())
            resolved_split = urllib.parse.urlsplit(resolved)
            if resolved_split.scheme not in {"http", "https"}:
                self._reject(403, "redirect_scheme_unsupported")
                return
            resolved_host = (resolved_split.hostname or "").strip().lower()
            if not resolved_host or resolved_host not in relay.allowed_hosts():
                # Every hop must stay inside the caller's allowlist; a
                # redirect can never widen the reachable host set.
                self._reject(403, "redirect_target_not_allowed")
                return
            target = resolved
            if status == 303 or (
                status in {301, 302} and method in {"POST", "PUT", "PATCH", "DELETE"}
            ):
                if method != "HEAD":
                    method = "GET"
                hop_body = b""
        # pragma: no cover - loop always returns above

    # -- request side ----------------------------------------------------------

    def _upstream_request_headers(self) -> dict:
        headers: dict = {}
        for name, value in self.headers.items():
            lowered = name.lower()
            if lowered in _HOP_BY_HOP_HEADERS or lowered in {"host", "content-length"}:
                continue
            headers[name] = value
        return headers

    def _read_request_body(self) -> bytes | None:
        transfer_encoding = (self.headers.get("Transfer-Encoding") or "").strip().lower()
        if transfer_encoding and transfer_encoding != "identity":
            # No chunked request bodies: Content-Length framing only.
            self._reject(411, "request_body_length_required")
            return None
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return b""
        try:
            length = int(raw_length.strip())
        except ValueError:
            self._reject(400, "bad_content_length")
            return None
        if length < 0:
            self._reject(400, "bad_content_length")
            return None
        if length > self._relay.max_body_bytes:
            self._reject(413, "request_body_too_large")
            return None
        return self.rfile.read(length)

    # -- upstream side -------------------------------------------------------------

    def _read_bounded(self, response: http.client.HTTPResponse, cap: int) -> bytes | None:
        declared = response.headers.get("Content-Length")
        if declared is not None:
            try:
                if int(declared) > cap:
                    return None
            except ValueError:
                pass
        chunks: list = []
        total = 0
        while True:
            chunk = response.read(_BODY_DRAIN_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                return None
            chunks.append(chunk)
        return b"".join(chunks)

    def _forward_once(self, target: str, method: str, base_headers: dict, body: bytes):
        """One upstream hop; returns an error string or the response tuple."""
        relay = self._relay
        split = urllib.parse.urlsplit(target)
        host = (split.hostname or "").strip().lower()
        if not host or host not in relay.allowed_hosts():
            return "target_host_not_allowed"
        path = split.path or "/"
        if split.query:
            path = f"{path}?{split.query}"
        headers = dict(base_headers)
        headers["Host"] = host if not split.port else f"{host}:{split.port}"
        connection = relay._build_upstream_connection(host, split.port)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            location = response.headers.get("Location") or ""
            response_body = self._read_bounded(response, relay.max_body_bytes)
            if response_body is None:
                return "response_body_too_large"
            headers_out = [
                (name, value)
                for name, value in response.getheaders()
                if name.lower() not in _HOP_BY_HOP_HEADERS
                and name.lower() not in {"content-length", "transfer-encoding"}
            ]
            return response.status, headers_out, response_body, location
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            return f"upstream_{type(exc).__name__}"
        finally:
            try:
                connection.close()
            except Exception:
                pass


# --------------------------------------------------------------------------
# Process-wide singleton (sandbox runs share one verified relay port)


class RelayHandle:
    """Port view of the running relay singleton (stop is an ops/test seam)."""

    __slots__ = ("port", "_relay")

    def __init__(self, relay: LoopbackRelay) -> None:
        self._relay = relay
        self.port = int(relay.port or 0)

    @property
    def is_running(self) -> bool:
        return bool(self._relay.is_running)

    def stop(self) -> None:
        stop_relay()


_RELAY_SINGLETON: LoopbackRelay | None = None
_RELAY_SINGLETON_LOCK = threading.Lock()


def get_or_start_relay(
    services: dict,
    *,
    upstream_tls: bool = True,
    connect_overrides: dict | None = None,
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> RelayHandle:
    """Return the process-wide relay, starting it on first use.

    Later calls merge their service entries into the live map so a running
    sandbox never loses its verified port. Connection settings (TLS, connect
    overrides, limits) are fixed by the first start; subsequent differing
    settings are ignored rather than restarting the socket underneath live
    sandboxes.
    """
    global _RELAY_SINGLETON
    with _RELAY_SINGLETON_LOCK:
        relay = _RELAY_SINGLETON
        if relay is None:
            relay = LoopbackRelay(
                services,
                upstream_tls=upstream_tls,
                connect_overrides=connect_overrides,
                request_timeout_s=request_timeout_s,
                max_body_bytes=max_body_bytes,
            )
            relay.start()
            _RELAY_SINGLETON = relay
        else:
            relay.merge_services(services)
        return RelayHandle(relay)


def stop_relay() -> None:
    """Stop and drop the singleton (ops/test seam; idempotent)."""
    global _RELAY_SINGLETON
    with _RELAY_SINGLETON_LOCK:
        relay = _RELAY_SINGLETON
        _RELAY_SINGLETON = None
    if relay is not None:
        relay.stop()
