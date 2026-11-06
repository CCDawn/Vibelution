"""Short-lived HTTP loopback listener; request targets and query values are never logged."""

from __future__ import annotations

import hmac
import socket
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .errors import ChatGPTSubscriptionError

CALLBACK_PATH = "/auth/callback"


class _LoopbackServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        # BaseServer's default traceback output is inappropriate for an OAuth callback.
        pass


class CallbackListener:
    def __init__(self, state: str, ttl: float, on_callback: Callable[[dict[str, str]], bool],
                 on_expire: Callable[[], None]):
        self._state = state
        self._deadline = time.monotonic() + ttl
        self._closed = threading.Event()
        self._consume_lock = threading.Lock()
        self._consumed = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5.0)

            def log_message(self, *args):
                pass

            def log_error(self, *args):
                pass

            def send_error(self, code, message=None, explain=None):
                # The stdlib default can echo a malformed request target (including code/state).
                self._reply(code, "无法验证登录回调。")

            def _reply(self, code, message):
                body = message.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def do_GET(self):
                code, message = owner._handle(self.headers.get_all("Host", []), self.path, on_callback)
                self._reply(code, message)
                if owner._consumed:
                    owner.close()

        try:
            self.server = _LoopbackServer(("127.0.0.1", 0), Handler)
            self.server.daemon_threads = True
            self.server.block_on_close = False
        except OSError:
            raise ChatGPTSubscriptionError("callback_unavailable") from None
        self.redirect_uri = f"http://127.0.0.1:{self.server.server_port}{CALLBACK_PATH}"
        self._thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True,
                                        name="chatgpt-oauth-loopback")
        self._thread.start()

        def expire():
            if not self._closed.is_set():
                on_expire()
                self.close()

        self._timer = threading.Timer(ttl, expire)
        self._timer.daemon = True
        self._timer.start()

    def _handle(self, hosts: list[str], target: str, callback: Callable[[dict[str, str]], bool]) -> tuple[int, str]:
        if self._closed.is_set() or time.monotonic() >= self._deadline:
            return 410, "登录已过期，请返回 Vibelution 重试。"
        if hosts != [f"127.0.0.1:{self.server.server_port}"] or len(target) > 8192 or not target.startswith("/"):
            return 400, "无法验证登录回调。"
        try:
            parsed = urlsplit(target)
            if parsed.path != CALLBACK_PATH or parsed.scheme or parsed.netloc or parsed.fragment:
                return 404, "未找到。"
            query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=12)
            if any(len(values) != 1 for values in query.values()):
                return 400, "无法验证登录回调。"
            values = {key: value[0] for key, value in query.items()}
            if not hmac.compare_digest(values.get("state", ""), self._state):
                return 400, "无法验证登录回调。"
        except (ValueError, UnicodeError, TypeError):
            return 400, "无法验证登录回调。"
        with self._consume_lock:
            if self._consumed:
                return 410, "此登录回调已使用。"
            self._consumed = True
        succeeded = callback(values)
        return (200, "ChatGPT 已连接，请返回 Vibelution。") if succeeded else (400, "登录未完成，请返回 Vibelution 查看状态。")

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.cancel()
        self.server.shutdown()
        self.server.server_close()
        self._state = ""
