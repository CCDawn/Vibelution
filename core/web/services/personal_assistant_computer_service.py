"""Operator-owned single-window consent for the canonical assistant.

Only control state lives here. Native Session/Turn, tool authorization and
transcript remain authoritative. A confirmation releases one waiting call;
it never schedules a new turn or silently retries uncertain input.
"""
from __future__ import annotations

from collections import OrderedDict
import os
from pathlib import Path
import secrets
import threading
import time

from core.infrastructure.cua_driver_client import CuaDriverCancelledError, CuaDriverError
from core.llm.client import LLMCancelledError
from . import personal_assistant_computer_driver as adapter
from . import personal_assistant_service as assistant
from . import agent_directory_service as directory

_lock = threading.RLock()
_execution = threading.Lock()
_selection: dict[str, dict] = {}
_observations: OrderedDict[str, dict] = OrderedDict()
_grant: dict | None = None
_active = None
_quarantine = None
_epoch = 0
_status = "idle"
_message = "请选择单个窗口并授权，助理才可以读取和操作。"
_pending: dict | None = None
GRANT_SECONDS = 1200
OBSERVATION_SECONDS = 90
CONFIRM_SECONDS = 60


def _canonical() -> dict:
    row = assistant.get_personal_assistant().get("assistant")
    if not row or row.get("setupStatus") != "ready":
        raise adapter.ComputerBlocked("请先初始化并打开个人助理会话。")
    return row


def _configuration(agent_id: str) -> tuple:
    agent = directory.get_agent(agent_id)
    if not agent or agent.get("status") != "active" or not agent.get("configHash"):
        raise adapter.ComputerBlocked("助理配置身份无法确认。")
    return agent.get("configRevision"), agent["configHash"]


def _owner(owner: tuple[str, str, str]) -> None:
    if not isinstance(owner, tuple) or len(owner) != 3 or not all(isinstance(v, str) and v for v in owner):
        raise adapter.ComputerBlocked("缺少个人助理原生轮次身份。")
    row = _canonical()
    if (row["agentId"], row["directSessionId"]) != owner[:2]:
        raise adapter.ComputerBlocked("电脑操作只允许当前个人助理原生会话使用。")


def _event(action: str, outcome: str) -> None:
    # No titles, text, images, paths or driver payload in runtime evidence.
    from .runtime_scene_service import record_runtime_scene_event_quietly
    record_runtime_scene_event_quietly("personal_assistant", "computer", f"computer.{action}", outcome=outcome,
                                     fields={"action": action, "scope": "single_window"})


def _public_window(window: dict) -> dict:
    return {key: window[key] for key in ("selectionId", "title", "appName")}


def _invalidate(status: str, message: str, *, end: bool = False) -> None:
    global _status, _message, _epoch, _pending, _grant
    _epoch += 1
    _status, _message = status, message
    _observations.clear()
    if _pending:
        _pending["approved"] = False
        _pending["event"].set()
    _pending = None
    if end:
        _grant = None


def _window_alive(window: dict) -> bool:
    try:
        birth, executable = adapter.process_identity(window["pid"])
        if (birth, executable) != (window["birth"], window["executable"]):
            return False
        import ctypes
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(window["hwnd"], ctypes.byref(pid))
        return pid.value == window["pid"]
    except (OSError, ValueError, AttributeError):
        return False


def _check_grant() -> None:
    if _quarantine is not None:
        return  # Preserve the cleanup handle; execution remains closed.
    if _grant:
        try:
            invalid = (time.monotonic() >= _grant["expires"] or not _window_alive(_grant["window"])
                       or _configuration(_grant["agentId"]) != _grant["configuration"])
        except Exception:
            invalid = True
        if invalid:
            _invalidate("ended", "窗口、助理配置或授权期限已变化，请重新选择。", end=True)


def get_state() -> dict:
    with _lock:
        _check_grant()
        try:
            adapter.driver_binary()
            available, reason = True, _message
        except (ValueError, OSError, TypeError):
            available, reason = False, "电脑操作驱动尚未就绪，请配置固定版 cua-driver 0.36.0。"
        return {"available": available, "status": _status, "message": reason,
                "grantId": _grant["id"] if _grant else None,
                "window": _public_window(_grant["window"]) if _grant else None,
                "pending": {key: _pending[key] for key in ("id", "action", "targetLabel", "text")} if _pending else None}


def list_windows() -> dict:
    """Operator-only metadata; no unselected window content goes to the model."""
    _canonical()
    with _lock:
        if _quarantine is not None:
            raise adapter.ComputerBlocked("上次输入执行器未确认退出，请先结束授权。")
    with adapter.Connection(lambda: "") as connection:
        windows = connection.windows()
    choices = {}
    forbidden = {"cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "conhost.exe",
                 "regedit.exe", "vibelution.exe", "vibelutionlauncher.exe", "credentialuibroker.exe"}
    for row in windows[:256]:
        try:
            pid, hwnd = row["pid"], row["window_id"]
            if type(pid) is not int or type(hwnd) is not int or min(pid, hwnd) <= 0:
                continue
            birth, executable = adapter.process_identity(pid)
            if Path(executable).name.lower() in forbidden or pid == os.getpid():
                continue
            title = str(row.get("title") or "").strip()[:240]
            if not title:
                continue
            token = secrets.token_urlsafe(24)
            choices[token] = {"selectionId": token, "pid": pid, "hwnd": hwnd, "birth": birth,
                              "executable": executable, "title": title,
                              "appName": str(row.get("app_name") or Path(executable).stem)[:80],
                              "created": time.monotonic()}
        except (ValueError, OSError, KeyError):
            continue
    with _lock:
        _selection.clear()
        _selection.update(choices)
    return {"windows": [_public_window(window) for window in choices.values()]}


def grant_window(selection_id: str, allow_vision: bool) -> dict:
    global _grant
    row = _canonical()
    with _lock:
        window = _selection.get(selection_id)
        if (allow_vision is not True or not window or time.monotonic() - window["created"] > 120
                or not _window_alive(window) or _execution.locked() or _active is not None or _quarantine is not None):
            raise adapter.ComputerBlocked("授权未生效：请重新选择仍打开的窗口，并同意读取窗口画面。")
        adapter.driver_binary()
        configuration = _configuration(row["agentId"])
        _invalidate("ready", "已授权此窗口，收到任务后开始；所有输入前都会显示具体操作供你确认。")
        _grant = {"id": secrets.token_urlsafe(24), "window": window, "agentId": row["agentId"],
                  "sessionId": row["directSessionId"], "expires": time.monotonic() + GRANT_SECONDS,
                  "configuration": configuration}
        _selection.clear()
    _event("grant", "accepted")
    return get_state()


def control(grant_id: str, action: str) -> dict:
    global _quarantine, _grant
    with _lock:
        _check_grant()
        previous_grant = _grant
        if action == "end" and _quarantine is not None:
            connection = _quarantine
        else:
            connection = _active
        if not _grant or _grant["id"] != grant_id:
            if not (action == "end" and _quarantine is not None):
                raise adapter.ComputerBlocked("授权已变化，请刷新后重试。")
        if action == "pause":
            _invalidate("paused", "已暂停输入；继续后须重新观察。")
        elif action == "takeover":
            _invalidate("manual", "控制权已交给你，助理不会继续输入。")
        elif action in {"resume", "return"}:
            if (_status not in {"paused", "manual"} or _quarantine is not None
                    or _active is not None or _execution.locked()):
                raise adapter.ComputerBlocked("输入执行器尚未停止，暂时不能交回。")
            _invalidate("ready", "已交回助理，下一步将重新观察窗口。")
        elif action == "end":
            _invalidate("ended", "本次授权已结束，窗口与未保存内容保留。", end=True)
        else:
            raise adapter.ComputerBlocked("不支持该控制操作。")
    if connection is not None:
        try:
            connection.__exit__(None, None, None)
            with _lock:
                if _quarantine is connection:
                    _quarantine = None
        except Exception:
            with _lock:
                _quarantine = connection
                # Retain the operator's cleanup handle even when end failed.
                _grant = previous_grant
                _invalidate("error", "执行器退出尚未确认，已拒绝继续输入；请再次结束授权。")
    _event(action, "accepted")
    return get_state()


def confirm(grant_id: str, pending_id: str, approved: bool) -> dict:
    with _lock:
        _check_grant()
        if (not _grant or _grant["id"] != grant_id or not _pending or _pending["id"] != pending_id
                or _pending["event"].is_set() or time.monotonic() >= _pending["expires"]):
            raise adapter.ComputerBlocked("这次确认已失效，没有执行操作，请让助理重新观察。")
        _pending["approved"] = approved is True
        _pending["event"].set()
    return get_state()


def _checker(owner, epoch, cancel_checker, input_tick=None):
    def check():
        try:
            reason = cancel_checker()
            if reason:
                return "原生轮次已停止。"
            _owner(owner)
            with _lock:
                _check_grant()
                if _epoch != epoch or not _grant or _status not in {"ready", "working", "waiting_confirmation"}:
                    return "窗口控制已暂停或授权变化。"
                if input_tick is not None and adapter.last_input_tick() != input_tick:
                    _invalidate("manual", "检测到鼠标或键盘操作，已交还控制；完成后可交回助理。")
                    return "人工接管。"
            return ""
        except Exception:
            return "无法核对当前身份或控制状态。"
    return check


def _require(check):
    if check():
        raise CuaDriverCancelledError("电脑操作已停止。")


def _observe(owner, snapshot, window):
    token = secrets.token_urlsafe(24)
    _observations[token] = {"owner": owner, "epoch": _epoch, "created": time.monotonic(),
                            "fingerprint": snapshot["fingerprint"],
                            "targets": [str(row.get("label") or row.get("role") or "未命名控件")[:240]
                                        for row in snapshot["elements"]]}
    while len(_observations) > 32:
        _observations.popitem(last=False)
    elements = [{"id": str(index), "role": str(row.get("role") or "")[:40],
                 "label": str(row.get("label") or "")[:100],
                 "value": str(row.get("value") or "")[:200], "actions": row.get("actions", [])}
                for index, row in enumerate(snapshot["elements"])
                if isinstance(row, dict) and row.get("element_token")][:30]
    return {"ok": True, "status": "observed", "observationId": token, "window": _public_window(window),
            "elements": elements, "elementsLimited": len(snapshot["elements"]) > len(elements),
            "incomplete": snapshot["incomplete"], "contentTrust": "untrusted_window_data"}


def execute(owner, *, action="observe", observation_id="", element_id="", text="", cancel_checker=None) -> dict:
    global _active, _quarantine, _pending, _status, _message, _grant
    if not _execution.acquire(blocking=False):
        return {"ok": False, "status": "blocked", "message": "已有电脑操作正在等待或执行。"}
    connection = None
    grant_ref = None
    try:
        _owner(owner)
        if not callable(cancel_checker):
            raise adapter.ComputerBlocked("缺少原生轮次停止检查器。")
        if action not in {"observe", "click", "set_value", "type_text", "scroll"}:
            raise adapter.ComputerBlocked("不支持该电脑操作。")
        if not isinstance(text, str) or len(text) > 2000 or any(ord(c) < 32 and c not in "\n\r\t" for c in text):
            raise adapter.ComputerBlocked("输入限 2000 字普通文本。")
        if action == "scroll" and text not in {"up", "down", "left", "right"}:
            raise adapter.ComputerBlocked("滚动方向无效。")
        with _lock:
            _check_grant()
            if (not _grant or (_grant["agentId"], _grant["sessionId"]) != owner[:2]
                    or _status != "ready" or _quarantine is not None):
                raise adapter.ComputerBlocked("请先授权窗口，或等待你交回控制。")
            epoch, window = _epoch, dict(_grant["window"])
            grant_ref = _grant
            old = None
            if action != "observe":
                old = _observations.pop(observation_id, None)
                if (not old or old["owner"] != owner or old["epoch"] != epoch
                        or time.monotonic() - old["created"] > OBSERVATION_SECONDS):
                    raise adapter.ComputerBlocked("观察凭据已过期、已用或不属于本轮，请重新观察。")
                if action != "scroll" and (not isinstance(element_id, str) or not element_id.isdecimal()):
                    raise adapter.ComputerBlocked("请使用本次观察返回的控件编号。")
                if action != "scroll" and int(element_id) >= len(old["targets"]):
                    raise adapter.ComputerBlocked("目标控件编号无效，请重新观察。")
                _pending = {"id": secrets.token_urlsafe(24), "action": action,
                            "targetLabel": f"{window['appName']} · {old['targets'][int(element_id)]}" if action != "scroll" else window["appName"],
                            "text": text or None, "expires": time.monotonic() + CONFIRM_SECONDS,
                            "event": threading.Event(), "approved": False}
                pending = _pending
                _status, _message = "waiting_confirmation", "请核对具体动作；确认只允许执行这一步。"
        check = _checker(owner, epoch, cancel_checker)
        if action != "observe":
            while not pending["event"].wait(.05):
                _require(check)
                if time.monotonic() >= pending["expires"]:
                    raise adapter.ComputerBlocked("确认超时，没有发送输入。")
            _require(check)
            if not pending["approved"]:
                raise adapter.ComputerBlocked("你已取消这一步，没有发送输入。")
        with _lock:
            _require(check)
            _pending = None
            _status, _message = "working", "正在观察并核对已授权窗口。"
        check = _checker(owner, epoch, cancel_checker, adapter.last_input_tick())
        _require(check)
        connection = adapter.Connection(check)
        connection.__enter__()
        with _lock:
            _active = connection
        _require(check)
        before = connection.snapshot(window, images=action == "observe")
        _require(check)
        if action == "observe":
            images = before["images"]
            if not images:
                raise adapter.ComputerBlocked("窗口画面未能安全读取，没有向模型提供其他窗口。")
            # Release the desktop lease during model perception. No input is
            # admitted until its result and the current grant are rechecked.
            connection.__exit__(None, None, None)
            with _lock:
                _active = None
            connection = None
            from .personal_assistant_computer_vision import describe_window
            description = describe_window(images, owner, check)
            with _lock:
                _require(check)
                result = _observe(owner, before, window)
                _status, _message = "ready", "已完成本次观察；下一步仍需核对窗口。"
            result.update(modality="window_screenshot_and_uia", visualDescription=description)
        else:
            if before["fingerprint"] != old["fingerprint"] or before["incomplete"]:
                raise adapter.ComputerBlocked("窗口内容已变化或控件信息不完整，没有执行，请重新观察。")
            element = None if action == "scroll" else before["elements"][int(element_id)]
            expected = connection.act(window, action, element, text)
            _require(check)
            after = connection.snapshot(window)
            _require(check)
            same = [row for row in after["elements"] if isinstance(row, dict) and element is not None and all(
                row.get(key) == element.get(key) for key in ("role", "label", "parent_index", "frame"))]
            verified = (action in {"set_value", "type_text"} and isinstance(expected, str) and len(same) == 1
                        and str(same[0].get("value") or "").replace("\r\n", "\n") == expected.replace("\r\n", "\n"))
            with _lock:
                _require(check)
                result = _observe(owner, after, window)
                _status, _message = "ready", "本次输入已结束；下一步仍需核对窗口。"
            result.update(status="completed" if verified else "unverified", verified=verified,
                          message="文本已读取核对。" if verified else "输入已送达，业务效果仍须根据窗口重新核对；未自动重试。")
        _event(action, result["status"])
        return result
    except (CuaDriverCancelledError, LLMCancelledError):
        with _lock:
            if _status in {"working", "waiting_confirmation"}:
                _invalidate("paused", "电脑操作已停止；已送达的输入需要重新核对。")
        return {"ok": False, "status": "cancelled", "message": "电脑操作已停止，未自动重试。"}
    except (ValueError, OSError, IndexError, KeyError, TypeError, TimeoutError, CuaDriverError) as exc:
        message = str(exc) if isinstance(exc, adapter.ComputerBlocked) else "电脑操作未确认完成，已停止；请重新观察，勿盲目重试。"
        with _lock:
            if _status in {"working", "waiting_confirmation"}:
                _invalidate("paused", message)
        _event(action, "blocked")
        return {"ok": False, "status": "blocked", "message": message}
    finally:
        retirement_failed = False
        with _lock:
            _pending = None
        if connection is not None:
            try:
                connection.__exit__(None, None, None)
            except Exception:
                retirement_failed = True
                with _lock:
                    _quarantine = connection
                    _grant = grant_ref
                    _invalidate("error", "输入执行器未确认退出，拒绝继续输入；请结束授权重试清理。")
        with _lock:
            _active = None
        _execution.release()
        if retirement_failed:
            return {"ok": False, "status": "unknown", "message": "执行器退出尚未确认；已保留桌面锁并拒绝新输入，请结束授权重试清理。"}
