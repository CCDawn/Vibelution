"""Real-HTTP SSE transport e2e: uvicorn + httpx streaming against create_app().

传输层焊点回归：TestClient（httpx ASGITransport）会缓冲整个响应体，无限
SSE 流在它下面永远等不到第一块，所以既有测试全部绕过了真实 HTTP 传输层
——而「SSE 断流不可见」正是发生在传输层的事故面。本文件在线程内起真
uvicorn（随机端口、lifespan=off 以避开产品 startup 的重初始化），用真
TCP httpx 流消费验证传输层×服务层的焊点：

1. 实时性：POST 提交后 assistant_delta 帧经真 HTTP 逐块到达直至 done；
2. 断连清理：客户端断开后服务器侧 subscriber 必须注销（不留死队列）；
3. 多流广播：同一会话两条并发流都收到同一轮的帧。

fake 注入与 service-stream e2e（tests/test_session_chat_stream_e2e.py）相同：
agent 边界 + 真实 event bus 事件，其余全走生产代码。
"""

from __future__ import annotations

import threading
import time
from collections import deque

import httpx
import pytest
import uvicorn

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import session_service
from tests.test_session_chat_stream_e2e import (
    _E2EChatAgent,
    _completed_turn_result,
    _seed_streamed_session,
)

pytestmark = pytest.mark.serial

_SERVER_READY_TIMEOUT_S = 15.0
_SUBSCRIBER_DRAIN_TIMEOUT_S = 10.0


@pytest.fixture(scope="module")
def live_server():
    """线程内真 uvicorn：随机端口，lifespan 关闭（测试聚焦传输层，不跑产品 startup）。"""
    config = uvicorn.Config(
        create_app(),
        host="127.0.0.1",
        port=0,
        log_level="warning",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + _SERVER_READY_TIMEOUT_S
    while time.monotonic() < deadline and not server.started:
        time.sleep(0.05)
    if not server.started:
        raise AssertionError("uvicorn 未在超时内就绪")
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10.0)


@pytest.fixture
def auth_headers():
    return {CONTROL_TOKEN_HEADER: get_control_token()}


@pytest.fixture(autouse=True)
def _no_stream_subscriber_leftover():
    yield
    with session_service._SESSION_STREAM_SUBSCRIBERS_LOCK:
        leftover = list(session_service._SESSION_STREAM_SUBSCRIBERS.get("session-live") or [])
    assert not leftover, f"session-live 残留 subscriber: {len(leftover)} 条"


class _HttpSseReader:
    """后台线程用真 httpx 流消费一条 SSE，帧进共享 deque。"""

    def __init__(self, base_url: str, headers: dict):
        self.base_url = base_url
        self.headers = headers
        self.frames: deque[dict] = deque()
        self.first_frame = threading.Event()
        self.error: BaseException | None = None
        self._stop = threading.Event()
        self._response = None
        self._client = None
        self._thread: threading.Thread | None = None

    def start(self) -> "_HttpSseReader":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        event_name = ""
        data_lines: list[str] = []
        try:
            self._client = httpx.Client(timeout=httpx.Timeout(30.0, read=None))
            with self._client.stream(
                "GET",
                f"{self.base_url}/api/sessions/session-live/events",
                params={"initial": "full"},
                headers=self.headers,
            ) as response:
                self._response = response
                if response.status_code != 200:
                    raise AssertionError(f"stream status {response.status_code}")
                for line in response.iter_lines():
                    if self._stop.is_set():
                        break
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip()
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line.split(":", 1)[1].strip())
                        continue
                    if line.strip():
                        continue
                    if event_name and data_lines:
                        import json

                        self.frames.append(
                            {"event": event_name, "data": json.loads("\n".join(data_lines))}
                        )
                        self.first_frame.set()
                    event_name, data_lines = "", []
        except BaseException as exc:  # noqa: BLE001 - 线程异常带回主线程
            self.error = exc
        finally:
            self.first_frame.set()

    def wait_frames(self, predicate, *, timeout_s: float = 20.0) -> dict:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for frame in list(self.frames):
                if predicate(frame["data"]):
                    return frame["data"]
            if self.error is not None:
                raise self.error
            time.sleep(0.05)
        raise AssertionError(f"超时未等到目标帧；已收到 {len(self.frames)} 帧")

    def abort(self) -> None:
        """模拟客户端断连：直接弃掉连接（底层 TCP 随 client 关闭）。"""
        self._stop.set()
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass


def _wait_subscribers_drained(timeout_s: float = _SUBSCRIBER_DRAIN_TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with session_service._SESSION_STREAM_SUBSCRIBERS_LOCK:
            remaining = len(session_service._SESSION_STREAM_SUBSCRIBERS.get("session-live") or [])
        if not remaining:
            return
        time.sleep(0.1)
    raise AssertionError(f"服务器侧 subscriber 未随断连注销（剩 {remaining} 条）")


def test_http_stream_delivers_turn_frames_realtime(live_server, auth_headers, tmp_path, monkeypatch):
    agent = _E2EChatAgent(
        result=_completed_turn_result(text="真 HTTP 流式帧已到达。", reasoning="验证传输层实时性。"),
    )
    _seed_streamed_session(tmp_path, monkeypatch, agent)

    reader = _HttpSseReader(live_server, auth_headers).start()
    try:
        assert reader.first_frame.wait(10.0), "真 HTTP SSE 未在超时内产出首帧"
        assert reader.error is None

        response = httpx.post(
            f"{live_server}/api/sessions/session-live/messages",
            headers=auth_headers,
            json={"clientSubmissionId": "submission-http-e2e-1", "content": "请总结当前进度"},
        )
        assert response.status_code == 202

        done = reader.wait_frames(lambda p: p.get("type") == "assistant_delta" and p.get("done"))
        assert done.get("turnId"), "终态帧必须携带 turn 身份"
        deltas = [f["data"] for f in reader.frames if f["event"] == "assistant_delta"]
        assert deltas, "真 HTTP 流必须实时收到增量帧"
    finally:
        reader.abort()
        _wait_subscribers_drained()


def test_http_stream_disconnect_unregisters_subscriber(live_server, auth_headers, tmp_path, monkeypatch):
    agent = _E2EChatAgent(result=_completed_turn_result(text="断连前的一轮。", reasoning="先完成一轮。"))
    _seed_streamed_session(tmp_path, monkeypatch, agent)

    response = httpx.post(
        f"{live_server}/api/sessions/session-live/messages",
        headers=auth_headers,
        json={"clientSubmissionId": "submission-http-e2e-disc", "content": "先完成一轮"},
    )
    assert response.status_code == 202

    reader = _HttpSseReader(live_server, auth_headers).start()
    try:
        assert reader.first_frame.wait(10.0)
        assert reader.error is None
    finally:
        reader.abort()

    # 客户端断开后，服务器侧必须注销 subscriber——传输层断连清理是「SSE 断流
    # 不可见」事故面的第一道防线。
    _wait_subscribers_drained()


def test_http_two_streams_both_receive_turn_frames(live_server, auth_headers, tmp_path, monkeypatch):
    agent = _E2EChatAgent(
        result=_completed_turn_result(text="双流广播帧已到达。", reasoning="两条连接都要收到。"),
    )
    _seed_streamed_session(tmp_path, monkeypatch, agent)

    first = _HttpSseReader(live_server, auth_headers).start()
    second = _HttpSseReader(live_server, auth_headers).start()
    try:
        assert first.first_frame.wait(10.0)
        assert second.first_frame.wait(10.0)
        assert first.error is None and second.error is None

        response = httpx.post(
            f"{live_server}/api/sessions/session-live/messages",
            headers=auth_headers,
            json={"clientSubmissionId": "submission-http-e2e-fanout", "content": "两条流都收一下"},
        )
        assert response.status_code == 202

        done_predicate = lambda p: p.get("type") == "assistant_delta" and p.get("done")  # noqa: E731
        assert first.wait_frames(done_predicate)["turnId"]
        assert second.wait_frames(done_predicate)["turnId"]
    finally:
        first.abort()
        second.abort()
        _wait_subscribers_drained()
