"""End-to-end chat stream tests: submit -> real turn -> SSE frames -> persisted detail.

层间焊点回归：submit/turn 执行、SSE 端点、stream_capture、stream_transport_delta
此前各有单点测试，但没有一条测试从 TestClient POST 出发、穿过真实 worker turn
执行（capture 订阅 event bus、live output 投影、subscriber 队列推送）、到达 SSE
帧与最终落盘。本文件贯穿这条链：fake 只注入在 agent 边界（turn 执行中发布真实
event bus 工具事件 + 返回 canonical 终态 dict），其余全部走生产代码。

用例覆盖三条最常断的焊点：
1. 在线流：POST 后 assistant_delta 帧实时到达订阅者，终态 done 落盘一致；
2. 重连流：turn 完成后新连接拿到全量 session_detail 快照（reconnect 不吃增量压缩）；
3. 失败流：provider 失败轮在流/详情可见，再次提交成功后历史两轮共存。
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.infrastructure.event_bus import EventNames, get_event_bus
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service, session_service
from tests.helpers.web_chat_state import (
    _bind_seeded_session_agent,
    _bind_seeded_submittable_agent,
    _seed_chat_state,
)

pytestmark = pytest.mark.serial

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

_STREAM_DRAIN_TIMEOUT_S = 30.0


@pytest.fixture(autouse=True)
def _isolate_live_state():
    """与 test_web_app 相同的运行态隔离：清 supervised/self-evolution 活动状态。"""
    from core.web.services import self_evolution_control_service, supervised_control_service

    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
    yield
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None


class _E2EChatAgent:
    """Agent 边界 fake：turn 执行中发布真实 event bus 工具事件，然后返回 canonical 终态。"""

    def __init__(self, *, result: dict, tool_script: list[tuple[str, dict]] | None = None):
        self._result = result
        self._tool_script = tool_script or []

    def seed_chat_history(self, messages):
        self.messages = list(messages)

    def run_single_turn(self, initial_prompt=None):
        from core.web.services.session.stream_capture import (
            _SESSION_UI_CAPTURE_CONTEXT,
        )

        context = _SESSION_UI_CAPTURE_CONTEXT.get({})
        capture = context.get("capture") if isinstance(context, dict) else None
        session_id = str(context.get("sessionId") or "") if isinstance(context, dict) else ""
        turn_id = str(getattr(capture, "turn_id", "") or "")
        bus = get_event_bus()
        for event_name, data in self._tool_script:
            bus.publish(
                event_name,
                {
                    "sessionId": session_id,
                    "turnId": turn_id,
                    **data,
                },
            )
        return dict(self._result)


def _completed_turn_result(*, text: str, reasoning: str) -> dict:
    return {
        "status": "completed",
        "summary": text,
        "raw_output": text,
        "reasoning_content": reasoning,
        "outcome": "done",
        "tool_call_count": 1,
        "tool_trace": [
            {"name": "read_file_tool"},
        ],
    }


def _seed_streamed_session(tmp_path, monkeypatch, agent: _E2EChatAgent) -> None:
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="done")
    _bind_seeded_submittable_agent(tmp_path)
    _bind_seeded_submittable_agent(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    primary_profile = base_config.llm.get_profile(role="primary")
    dialogue_model_id = primary_profile.model_ref
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    session_agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="流式会话",
        llm_bindings={"dialogue": {"modelId": dialogue_model_id}},
        prompt_template_id="prompt-chat-default",
    )
    _bind_seeded_session_agent(tmp_path, session_agent)
    session_service._invalidate_session_list_cache()
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: agent)
    # 同步执行 turn：POST 请求线程内完成全部 capture/投影/落盘，帧经 subscriber 队列出去。
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )


def _submit_message(content: str, *, submission_id: str):
    return client.post(
        "/api/sessions/session-live/messages",
        json={"clientSubmissionId": submission_id, "content": content},
    )


class _SseFrameLog:
    """后台线程消费一条 session SSE 流，把完整帧记入共享 deque 供主线程断言。

    为什么不走 TestClient.stream：httpx 的 ASGITransport 会缓冲整个响应体，
    无限 SSE 流在 HTTP 层永远等不到第一块。真实链路里传输层由 uvicorn 承担
    （端点级已有 test_web_app 覆盖），这里从 service 的流生成器消费——
    POST 提交、turn 执行、capture 投影、subscriber 队列、SSE 编码全部真实。
    """

    def __init__(self, *, initial: str = "full"):
        self.frames: deque[tuple[str, dict]] = deque()
        self.first_frame = threading.Event()
        self.error: BaseException | None = None
        self._initial = initial
        self._thread: threading.Thread | None = None
        self._generator = None

    def start(self) -> "_SseFrameLog":
        self._generator = session_service.stream_session_events(
            "session-live",
            initial=self._initial,
        )
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        deadline = time.monotonic() + _STREAM_DRAIN_TIMEOUT_S
        try:
            while time.monotonic() < deadline:
                raw = next(self._generator)
                if not raw:
                    continue
                event_name = ""
                data_lines: list[str] = []
                for line in str(raw).splitlines():
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line.split(":", 1)[1].strip())
                if event_name and data_lines:
                    payload = json.loads("\n".join(data_lines))
                    self.frames.append((event_name, payload))
                    self.first_frame.set()
        except StopIteration:
            pass
        except BaseException as exc:  # noqa: BLE001 - 线程异常必须带回主线程
            self.error = exc
        finally:
            self.first_frame.set()

    def close(self) -> None:
        generator = self._generator
        if generator is not None:
            try:
                generator.close()
            except Exception:  # noqa: BLE001 - 关闭路径不掩盖断言
                pass

    def wait_first_frame(self, timeout_s: float = 10.0) -> None:
        if not self.first_frame.wait(timeout_s):
            raise AssertionError("SSE 流在超时内没有产出首帧（订阅者可能未注册）")
        if self.error is not None:
            raise self.error

    def wait_frames(self, predicate, *, timeout_s: float = 20.0) -> dict:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for _name, payload in list(self.frames):
                if predicate(payload):
                    return payload
            if self.error is not None:
                raise self.error
            if self._thread is not None and not self._thread.is_alive() and self.first_frame.is_set():
                break
            time.sleep(0.05)
        raise AssertionError(f"超时未等到目标帧；已收到 {len(self.frames)} 帧: {[name for name, _ in self.frames]}")


def _assistant_delta_frames(log: _SseFrameLog) -> list[dict]:
    return [payload for name, payload in log.frames if name == "assistant_delta"]


def test_posted_turn_streams_tool_and_text_frames_then_persists(tmp_path, monkeypatch):
    """POST -> 同步 turn 执行 -> SSE 实时帧（工具条目 + 终态 done）-> 落盘一致。"""
    agent = _E2EChatAgent(
        result=_completed_turn_result(text="已完成流式端到端验证。", reasoning="先确认订阅顺序，再验证落盘。"),
        tool_script=[
            (EventNames.TOOL_START, {"name": "read_file_tool", "callId": "call-e2e-read", "args": {"path": "web/src/routes/ChatCodingRoute.tsx"}}),
            (EventNames.TOOL_SUCCESS, {"name": "read_file_tool", "callId": "call-e2e-read", "result": "export {};", "summary": "读取文件"}),
        ],
    )
    _seed_streamed_session(tmp_path, monkeypatch, agent)

    log = _SseFrameLog().start()
    try:
        log.wait_first_frame()

        response = _submit_message("请读取 ChatCodingRoute 并总结", submission_id="submission-stream-e2e-1")
        assert response.status_code == 202

        done_frame = log.wait_frames(lambda p: p.get("type") == "assistant_delta" and p.get("done"))
    finally:
        log.close()

    deltas = _assistant_delta_frames(log)
    assert deltas, "turn 执行期间必须产生 assistant_delta 帧"
    tool_items = [
        item
        for frame in deltas
        for item in frame.get("turnItems", [])
        if item.get("type") == "tool_call"
    ]
    assert any(item.get("callId") == "call-e2e-read" and item.get("status") in {"running", "done", "completed"} for item in tool_items), (
        "事件总线工具事件必须投影为流内 tool_call 条目"
    )
    assert done_frame.get("turnId"), "终态帧必须携带 turn 身份"

    detail = client.get("/api/sessions/session-live").json()
    assistant_messages = [m for m in detail["messages"] if m.get("role") == "assistant"]
    assert assistant_messages, "turn 完成后必须落盘 assistant 消息"
    items = list(assistant_messages[-1].get("turnItems") or [])
    reasoning = [i for i in items if str(i.get("type") or "") == "reasoning"]
    assert reasoning and reasoning[-1].get("text") == "先确认订阅顺序，再验证落盘。"
    tools = [i for i in items if str(i.get("type") or "") == "tool_call"]
    assert any(str(i.get("toolName") or "") == "read_file_tool" and i.get("status") == "completed" for i in tools)
    text_items = [i for i in items if str(i.get("type") or "") in {"agent_message", "error"}]
    assert any("已完成流式端到端验证" in str(i.get("text") or "") for i in text_items)


def test_reopened_stream_replays_full_snapshot_after_completed_turn(tmp_path, monkeypatch):
    """turn 完成后重连：新流首帧必须是全量 session_detail，携带该轮全部条目。"""
    agent = _E2EChatAgent(
        result=_completed_turn_result(text="重连前已完成的一轮。", reasoning="等待重连验证。"),
    )
    _seed_streamed_session(tmp_path, monkeypatch, agent)

    response = _submit_message("先完成一轮", submission_id="submission-stream-e2e-reconnect")
    assert response.status_code == 202

    log = _SseFrameLog(initial="full").start()
    try:
        log.wait_first_frame()
        detail_frame = log.wait_frames(lambda p: p.get("type") == "session_detail")
    finally:
        log.close()

    assistant_messages = [
        m for m in detail_frame["detail"]["messages"] if m.get("role") == "assistant"
    ]
    assert assistant_messages, "重连快照必须包含已完成的 assistant 消息"
    items = list(assistant_messages[-1].get("turnItems") or [])
    assert any(str(i.get("type") or "") == "reasoning" for i in items), "重连快照必须带完整 reasoning 条目"


def test_provider_failed_turn_is_visible_and_next_submit_recovers(tmp_path, monkeypatch):
    """provider 失败轮可见且不阻断后续提交：失败信号落盘、历史两轮共存。"""
    from tests.helpers.web_chat_state import _read_next_state_signals

    outcomes = iter(["failed", "completed"])
    holder: dict[str, _E2EChatAgent] = {}

    class _SwitchableAgent(_E2EChatAgent):
        def run_single_turn(self, initial_prompt=None):
            outcome = next(outcomes, "completed")
            if outcome == "failed":
                return {
                    "status": "failed",
                    "summary": "litellm.BadGatewayError: Upstream request failed",
                    "raw_output": "litellm.BadGatewayError: Upstream request failed",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            return _completed_turn_result(text="失败后恢复的一轮。", reasoning="第二次提交成功。")

    agent = _SwitchableAgent(result={})
    holder["agent"] = agent
    _seed_streamed_session(tmp_path, monkeypatch, agent)

    failed = _submit_message("触发上游失败", submission_id="submission-stream-e2e-fail")
    assert failed.status_code == 202
    signals = _read_next_state_signals(tmp_path, session_id="session-live")
    assert any(item["kind"] == "provider_failure" for item in signals), "失败轮必须产出 provider_failure 信号"

    recovered = _submit_message("重新提交恢复", submission_id="submission-stream-e2e-recover")
    assert recovered.status_code == 202
    payload = recovered.json()
    assistant_messages = [m for m in payload["messages"] if m.get("role") == "assistant"]
    assert assistant_messages, "恢复轮必须返回 assistant 消息"
    items = list(assistant_messages[-1].get("turnItems") or [])
    assert any(
        "失败后恢复的一轮" in str(i.get("text") or "")
        for i in items
        if str(i.get("type") or "") in {"agent_message", "error"}
    )

    detail = client.get("/api/sessions/session-live").json()
    assistant_all = [m for m in detail["messages"] if m.get("role") == "assistant"]
    assert len(assistant_all) >= 2, "失败轮与恢复轮都必须保留在历史中"
