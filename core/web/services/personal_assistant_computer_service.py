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
from .i18n import get_web_language, text_for

_lock = threading.RLock()
_execution = threading.Lock()
_selection: dict[str, dict] = {}
_observations: OrderedDict[str, dict] = OrderedDict()
_grant: dict | None = None
_active = None
_quarantine = None
_epoch = 0
_status = "idle"
_message = ("请选择单个窗口并授权，助理才可以读取和操作。", "Select and authorize a single window before the assistant can read or control it.")
_pending: dict | None = None
GRANT_SECONDS = 1200
OBSERVATION_SECONDS = 90
CONFIRM_SECONDS = 60


def _text(zh: str, en: str) -> str:
    return text_for(get_web_language(), zh=zh, en=en)


def _canonical() -> dict:
    row = assistant.get_personal_assistant().get("assistant")
    if not row or row.get("setupStatus") != "ready":
        raise adapter.ComputerBlocked("请先初始化并打开个人助理会话。", "Initialize and open the personal assistant session first.")
    return row


def _configuration(agent_id: str) -> tuple:
    agent = directory.get_agent(agent_id)
    if not agent or agent.get("status") != "active" or not agent.get("configHash"):
        raise adapter.ComputerBlocked("助理配置身份无法确认。", "The assistant configuration identity could not be verified.")
    return agent.get("configRevision"), agent["configHash"]


def _owner(owner: tuple[str, str, str]) -> None:
    if not isinstance(owner, tuple) or len(owner) != 3 or not all(isinstance(v, str) and v for v in owner):
        raise adapter.ComputerBlocked("缺少个人助理原生轮次身份。", "The personal assistant native turn identity is missing.")
    row = _canonical()
    if (row["agentId"], row["directSessionId"]) != owner[:2]:
        raise adapter.ComputerBlocked("电脑操作只允许当前个人助理原生会话使用。", "Computer control is only available to the current personal assistant native session.")


def _event(action: str, outcome: str) -> None:
    # No titles, text, images, paths or driver payload in runtime evidence.
    from .runtime_scene_service import record_runtime_scene_event_quietly
    record_runtime_scene_event_quietly("personal_assistant", "computer", f"computer.{action}", outcome=outcome,
                                     fields={"action": action, "scope": "single_window"})


def _public_window(window: dict) -> dict:
    return {key: window[key] for key in ("selectionId", "title", "appName")}


def _invalidate(status: str, message: tuple[str, str], *, end: bool = False) -> None:
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
            _invalidate("ended", ("窗口、助理配置或授权期限已变化，请重新选择。", "The window, assistant configuration, or authorization period has changed. Select the window again."), end=True)


def get_state() -> dict:
    with _lock:
        _check_grant()
        try:
            adapter.driver_binary()
            available, reason = True, _text(*_message)
        except (ValueError, OSError, TypeError):
            available, reason = False, _text("电脑操作驱动尚未就绪，请配置固定版 cua-driver 0.36.0。", "The computer control driver is not ready. Configure the pinned cua-driver 0.36.0.")
        return {"available": available, "status": _status, "message": reason,
                "grantId": _grant["id"] if _grant else None,
                "window": _public_window(_grant["window"]) if _grant else None,
                "pending": {key: _pending[key] for key in ("id", "action", "targetLabel", "text")} if _pending else None}


def list_windows() -> dict:
    """Operator-only metadata; no unselected window content goes to the model."""
    _canonical()
    with _lock:
        if _quarantine is not None:
            raise adapter.ComputerBlocked("上次输入执行器未确认退出，请先结束授权。", "The previous input executor has not been confirmed to have exited. End the authorization first.")
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
            raise adapter.ComputerBlocked("授权未生效：请重新选择仍打开的窗口，并同意读取窗口画面。", "Authorization was not granted. Select an open window again and consent to reading its image.")
        adapter.driver_binary()
        configuration = _configuration(row["agentId"])
        _invalidate("ready", ("已授权此窗口，收到任务后开始；所有输入前都会显示具体操作供你确认。", "This window is authorized. The assistant will start when given a task; each input action will be shown for your confirmation."))
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
                raise adapter.ComputerBlocked("授权已变化，请刷新后重试。", "The authorization has changed. Refresh and try again.")
        if action == "pause":
            _invalidate("paused", ("已暂停输入；继续后须重新观察。", "Input is paused. The window must be observed again after resuming."))
        elif action == "takeover":
            _invalidate("manual", ("控制权已交给你，助理不会继续输入。", "You have control. The assistant will not send further input."))
        elif action in {"resume", "return"}:
            if (_status not in {"paused", "manual"} or _quarantine is not None
                    or _active is not None or _execution.locked()):
                raise adapter.ComputerBlocked("输入执行器尚未停止，暂时不能交回。", "The input executor has not stopped. Control cannot be returned yet.")
            _invalidate("ready", ("已交回助理，下一步将重新观察窗口。", "Control has been returned to the assistant. It will observe the window again next."))
        elif action == "end":
            _invalidate("ended", ("本次授权已结束，窗口与未保存内容保留。", "This authorization has ended. The window and unsaved content are preserved."), end=True)
        else:
            raise adapter.ComputerBlocked("不支持该控制操作。", "This control action is not supported.")
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
                _invalidate("error", ("执行器退出尚未确认，已拒绝继续输入；请再次结束授权。", "The executor has not been confirmed to have exited. Further input is blocked; end the authorization again."))
    _event(action, "accepted")
    return get_state()


def confirm(grant_id: str, pending_id: str, approved: bool) -> dict:
    with _lock:
        _check_grant()
        if (not _grant or _grant["id"] != grant_id or not _pending or _pending["id"] != pending_id
                or _pending["event"].is_set() or time.monotonic() >= _pending["expires"]):
            raise adapter.ComputerBlocked("这次确认已失效，没有执行操作，请让助理重新观察。", "This confirmation has expired. No action was taken; ask the assistant to observe again.")
        _pending["approved"] = approved is True
        _pending["event"].set()
    return get_state()


def _checker(owner, epoch, cancel_checker, input_tick=None):
    def check():
        try:
            reason = cancel_checker()
            if reason:
                return _text("原生轮次已停止。", "The native turn has stopped.")
            _owner(owner)
            with _lock:
                _check_grant()
                if _epoch != epoch or not _grant or _status not in {"ready", "working", "waiting_confirmation"}:
                    return _text("窗口控制已暂停或授权变化。", "Window control is paused or the authorization has changed.")
                if input_tick is not None and adapter.last_input_tick() != input_tick:
                    _invalidate("manual", ("检测到鼠标或键盘操作，已交还控制；完成后可交回助理。", "Mouse or keyboard activity was detected, and control has been returned to you. Return it to the assistant when finished."))
                    return _text("人工接管。", "Manual takeover.")
            return ""
        except Exception:
            return _text("无法核对当前身份或控制状态。", "The current identity or control state could not be verified.")
    return check


def _require(check):
    if check():
        raise CuaDriverCancelledError(_text("电脑操作已停止。", "Computer control has stopped."))


def _observe(owner, snapshot, window):
    token = secrets.token_urlsafe(24)
    _observations[token] = {"owner": owner, "epoch": _epoch, "created": time.monotonic(),
                            "fingerprint": snapshot["fingerprint"],
                            "targets": [str(row.get("label") or row.get("role") or _text("未命名控件", "Unnamed control"))[:240]
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
        return {"ok": False, "status": "blocked", "message": _text("已有电脑操作正在等待或执行。", "A computer action is already waiting or running.")}
    connection = None
    grant_ref = None
    try:
        _owner(owner)
        if not callable(cancel_checker):
            raise adapter.ComputerBlocked("缺少原生轮次停止检查器。", "The native turn stop checker is missing.")
        if action not in {"observe", "click", "set_value", "type_text", "scroll"}:
            raise adapter.ComputerBlocked("不支持该电脑操作。", "This computer action is not supported.")
        if not isinstance(text, str) or len(text) > 2000 or any(ord(c) < 32 and c not in "\n\r\t" for c in text):
            raise adapter.ComputerBlocked("输入限 2000 字普通文本。", "Input is limited to 2000 characters of plain text.")
        if action == "scroll" and text not in {"up", "down", "left", "right"}:
            raise adapter.ComputerBlocked("滚动方向无效。", "The scroll direction is invalid.")
        with _lock:
            _check_grant()
            if (not _grant or (_grant["agentId"], _grant["sessionId"]) != owner[:2]
                    or _status != "ready" or _quarantine is not None):
                raise adapter.ComputerBlocked("请先授权窗口，或等待你交回控制。", "Authorize a window first, or return control to the assistant.")
            epoch, window = _epoch, dict(_grant["window"])
            grant_ref = _grant
            old = None
            if action != "observe":
                old = _observations.pop(observation_id, None)
                if (not old or old["owner"] != owner or old["epoch"] != epoch
                        or time.monotonic() - old["created"] > OBSERVATION_SECONDS):
                    raise adapter.ComputerBlocked("观察凭据已过期、已用或不属于本轮，请重新观察。", "The observation token has expired, was already used, or belongs to another turn. Observe again.")
                if action != "scroll" and (not isinstance(element_id, str) or not element_id.isdecimal()):
                    raise adapter.ComputerBlocked("请使用本次观察返回的控件编号。", "Use a control ID returned by this observation.")
                if action != "scroll" and int(element_id) >= len(old["targets"]):
                    raise adapter.ComputerBlocked("目标控件编号无效，请重新观察。", "The target control ID is invalid. Observe again.")
                _pending = {"id": secrets.token_urlsafe(24), "action": action,
                            "targetLabel": f"{window['appName']} · {old['targets'][int(element_id)]}" if action != "scroll" else window["appName"],
                            "text": text if action in {"set_value", "type_text"} else text or None,
                            "expires": time.monotonic() + CONFIRM_SECONDS,
                            "event": threading.Event(), "approved": False}
                pending = _pending
                _status, _message = "waiting_confirmation", ("请核对具体动作；确认只允许执行这一步。", "Check the specific action. Confirmation authorizes only this step.")
        check = _checker(owner, epoch, cancel_checker)
        if action != "observe":
            while not pending["event"].wait(.05):
                _require(check)
                if time.monotonic() >= pending["expires"]:
                    raise adapter.ComputerBlocked("确认超时，没有发送输入。", "Confirmation timed out. No input was sent.")
            _require(check)
            if not pending["approved"]:
                raise adapter.ComputerBlocked("你已取消这一步，没有发送输入。", "You cancelled this step. No input was sent.")
        with _lock:
            _require(check)
            _pending = None
            _status, _message = "working", ("正在观察并核对已授权窗口。", "Observing and checking the authorized window.")
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
                raise adapter.ComputerBlocked("窗口画面未能安全读取，没有向模型提供其他窗口。", "The window image could not be read safely. No other window was provided to the model.")
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
                _status, _message = "ready", ("已完成本次观察；下一步仍需核对窗口。", "This observation is complete. The window must still be checked before the next step.")
            result.update(modality="window_screenshot_and_uia", visualDescription=description)
        else:
            if before["fingerprint"] != old["fingerprint"] or before["incomplete"]:
                raise adapter.ComputerBlocked("窗口内容已变化或控件信息不完整，没有执行，请重新观察。", "The window content has changed or control information is incomplete. No action was taken; observe again.")
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
                _status, _message = "ready", ("本次输入已结束；下一步仍需核对窗口。", "This input has finished. The window must still be checked before the next step.")
            result.update(status="completed" if verified else "unverified", verified=verified,
                          message=_text("文本已读取核对。", "The text was read back and verified.") if verified else _text("输入已送达，业务效果仍须根据窗口重新核对；未自动重试。", "Input was delivered. Its effect must still be checked against the window; no automatic retry was attempted."))
        _event(action, result["status"])
        return result
    except (CuaDriverCancelledError, LLMCancelledError):
        with _lock:
            if _status in {"working", "waiting_confirmation"}:
                _invalidate("paused", ("电脑操作已停止；已送达的输入需要重新核对。", "Computer control has stopped. Any input already delivered must be checked again."))
        return {"ok": False, "status": "cancelled", "message": _text("电脑操作已停止，未自动重试。", "Computer control has stopped. No automatic retry was attempted.")}
    except (ValueError, OSError, IndexError, KeyError, TypeError, TimeoutError, CuaDriverError) as exc:
        message = exc.message_pair if isinstance(exc, adapter.ComputerBlocked) else ("电脑操作未确认完成，已停止；请重新观察，勿盲目重试。", "Computer control could not be confirmed complete and has stopped. Observe again before retrying.")
        with _lock:
            if _status in {"working", "waiting_confirmation"}:
                _invalidate("paused", message)
        _event(action, "blocked")
        return {"ok": False, "status": "blocked", "message": _text(*message)}
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
                    _invalidate("error", ("输入执行器未确认退出，拒绝继续输入；请结束授权重试清理。", "The input executor has not been confirmed to have exited. Further input is blocked; end the authorization to retry cleanup."))
        with _lock:
            _active = None
        _execution.release()
        if retirement_failed:
            return {"ok": False, "status": "unknown", "message": _text("执行器退出尚未确认；已保留桌面锁并拒绝新输入，请结束授权重试清理。", "The executor has not been confirmed to have exited. The desktop lock is retained and new input is blocked; end the authorization to retry cleanup.")}
