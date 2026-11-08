"""Model-driven window access for the canonical personal assistant.

Only control state lives here. Native Session/Turn, tool authorization and
transcript remain authoritative. The model selects target windows per call
(case-insensitive substring or selection token); an operator grant is an
optional default-target preference, never a precondition. Human takeover
detection, the cross-instance control lock and quarantine semantics stay in
force for every dispatched input.
"""
from __future__ import annotations

from collections import OrderedDict
import os
from pathlib import Path
import secrets
import shutil
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
_model_windows: dict[str, dict] = {}
_observations: OrderedDict[str, dict] = OrderedDict()
_grant: dict | None = None
_active = None
_quarantine = None
_epoch = 0
_status = "idle"
_message = ("助理可直接观察和操作窗口；也可在此预先授权默认目标窗口。",
            "The assistant can observe and control windows directly. You may still pre-authorize a default target window here.")
GRANT_SECONDS = 1200
OBSERVATION_SECONDS = 90
ACTIONS = {"observe", "click", "set_value", "type_text", "scroll", "click_at", "hotkey", "launch"}
_ELEMENT_ACTIONS = {"click", "set_value", "type_text"}
_OBSERVATION_ACTIONS = {"click", "set_value", "type_text", "scroll", "click_at"}
_LAUNCH_SUFFIXES = {".exe", ".lnk"}
_HOTKEY_MODIFIERS = ("ctrl", "shift", "alt", "win")
_HOTKEY_KEYS = frozenset({"return", "tab", "escape", "up", "down", "left", "right", "space", "delete",
                          "home", "end", "pageup", "pagedown", *(f"f{number}" for number in range(1, 13))})
_FORBIDDEN_PROCESSES = {"cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "conhost.exe",
                        "regedit.exe", "vibelution.exe", "vibelutionlauncher.exe", "credentialuibroker.exe"}
_MAX_COORDINATE = 20000


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


def _event(action: str, outcome: str, **fields) -> None:
    # No titles, text, images, paths or driver payload in runtime evidence.
    from .runtime_scene_service import record_runtime_scene_event_quietly
    payload = {"action": action, "scope": "windows", **fields}
    record_runtime_scene_event_quietly("personal_assistant", "computer", f"computer.{action}", outcome=outcome,
                                       fields=payload)


def _public_window(window: dict) -> dict:
    return {key: window[key] for key in ("selectionId", "title", "appName")}


def _invalidate(status: str, message: tuple[str, str], *, end: bool = False, bump: bool = True) -> None:
    global _status, _message, _epoch, _grant
    if bump:
        # A bump retires in-flight work and old observations. Passive grant
        # (preference) expiry must not abort unrelated model work, so it does
        # not bump; explicit operator control still does.
        _epoch += 1
    _status, _message = status, message
    _observations.clear()
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
            _invalidate("ended", ("窗口、助理配置或授权期限已变化，请重新选择。", "The window, assistant configuration, or authorization period has changed. Select the window again."), end=True, bump=False)


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
                "pending": None}


def _filtered_windows(rows: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """Build selection-token records from driver rows; sensitive processes stay filtered."""
    choices = {}
    visible: list[str] = []
    for row in rows[:256]:
        try:
            pid, hwnd = row["pid"], row["window_id"]
            if type(pid) is not int or type(hwnd) is not int or min(pid, hwnd) <= 0:
                continue
            birth, executable = adapter.process_identity(pid)
            if Path(executable).name.lower() in _FORBIDDEN_PROCESSES or pid == os.getpid():
                continue
            title = str(row.get("title") or "").strip()[:240]
            if not title:
                continue
            token = secrets.token_urlsafe(24)
            choices[token] = {"selectionId": token, "pid": pid, "hwnd": hwnd, "birth": birth,
                              "executable": executable, "title": title,
                              "appName": str(row.get("app_name") or Path(executable).stem)[:80],
                              "created": time.monotonic()}
            if row.get("is_on_screen") is True:
                visible.append(token)
        except (ValueError, OSError, KeyError):
            continue
    return choices, visible


def list_windows() -> dict:
    """Operator metadata for the optional default-window preference."""
    _canonical()
    with _lock:
        if _quarantine is not None:
            raise adapter.ComputerBlocked("上次输入执行器未确认退出，请先结束授权。", "The previous input executor has not been confirmed to have exited. End the authorization first.")
    with adapter.Connection(lambda: "") as connection:
        windows = connection.windows()
    choices, _ = _filtered_windows(windows)
    with _lock:
        _selection.clear()
        _selection.update(choices)
    return {"windows": [_public_window(window) for window in choices.values()]}


def _resolve_model_window(owner: tuple[str, str, str], query: str, connection) -> tuple[dict | None, str, list[dict]]:
    """Resolve the model-selected target window for one call.

    Returns (window, failure_status, candidates). An exact selection token wins,
    then a case-insensitive appName/title substring match; without a query the
    operator's live grant preference applies, then a single on-screen window.
    """
    with _lock:
        _check_grant()
        preference = None
        if (_grant and (_grant["agentId"], _grant["sessionId"]) == owner[:2]
                and _window_alive(_grant["window"])):
            preference = dict(_grant["window"])
    query = query.strip() if isinstance(query, str) else ""
    rows = connection.windows()
    choices, visible_tokens = _filtered_windows(rows)
    with _lock:
        # Model-facing selection tokens stay stable while the same window
        # identity stays enumerable, so a candidate's selectionId from one
        # call resolves on the next call.
        stable = {}
        for record in choices.values():
            reused = False
            for old_token, old in _model_windows.items():
                if (old["pid"], old["hwnd"], old["birth"], old["executable"]) == (
                        record["pid"], record["hwnd"], record["birth"], record["executable"]):
                    record["selectionId"] = old_token
                    stable[old_token] = record
                    reused = True
                    break
            if not reused:
                stable[record["selectionId"]] = record
        _model_windows.clear()
        _model_windows.update(stable)
    if query:
        with _lock:
            exact = _model_windows.get(query)
        if exact is not None:
            return dict(exact), "", []
        lowered = query.lower()
        matches = [row for row in choices.values()
                   if lowered in row["appName"].lower() or lowered in row["title"].lower()]
        if len(matches) == 1:
            return dict(matches[0]), "", []
        if matches:
            return None, "window_ambiguous", [_public_window(row) for row in matches]
        return None, "window_not_found", [_public_window(row) for row in choices.values()]
    if preference is not None and any(row["pid"] == preference["pid"] and row["hwnd"] == preference["hwnd"]
                                     for row in choices.values()):
        return preference, "", []
    if len(choices) == 1:
        return dict(next(iter(choices.values()))), "", []
    if len(visible_tokens) == 1:
        return dict(choices[visible_tokens[0]]), "", []
    return None, "window_unresolved", [_public_window(row) for row in choices.values()]


def _window_candidates_result(action: str, status: str, candidates: list[dict]) -> dict:
    messages = {
        "window_ambiguous": ("匹配到多个窗口，请用更具体的 window 名称或候选中的 selectionId 重试。",
                             "Multiple windows matched. Retry with a more specific window name or a candidate selectionId."),
        "window_not_found": ("没有窗口匹配该名称；以下是当前可选窗口。",
                             "No window matched that name. These windows are currently available."),
        "window_unresolved": ("存在多个窗口，请指定 window 名称或候选中的 selectionId。",
                              "Several windows are open. Specify a window name or a candidate selectionId."),
    }
    _event(action, "blocked")
    return {"ok": False, "status": status, "message": _text(*messages[status]), "candidates": candidates}


def grant_window(selection_id: str, allow_vision: bool, authorization_request_id: str | None = None) -> dict:
    global _grant
    row = _canonical()
    with _lock:
        window = _selection.get(selection_id)
        if (allow_vision is not True or not window or time.monotonic() - window["created"] > 120
                or not _window_alive(window) or _execution.locked() or _active is not None or _quarantine is not None):
            raise adapter.ComputerBlocked("授权未生效：请重新选择仍打开的窗口，并同意读取窗口画面。", "Authorization was not granted. Select an open window again and consent to reading its image.")
        adapter.driver_binary()
        configuration = _configuration(row["agentId"])
        _invalidate("ready", ("已授权此窗口；助理未指定目标窗口时将优先使用它。", "This window is authorized. The assistant will prefer it whenever no target window is specified."))
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
    # Per-step operator confirmation was retired with the authorization gate:
    # actions follow the session's native approval policy. The endpoint stays
    # mounted so the operator panel keeps a stable contract.
    raise adapter.ComputerBlocked("电脑操作已按默认审批策略执行，不再有待确认步骤。",
                                  "Computer actions follow the default approval policy; there is no pending step to confirm.")


def _checker(owner, epoch, cancel_checker, input_tick=None):
    def check():
        try:
            reason = cancel_checker()
            if reason:
                return _text("原生轮次已停止。", "The native turn has stopped.")
            _owner(owner)
            with _lock:
                if _epoch != epoch:
                    return _text("窗口控制已暂停或目标已变化。", "Window control was paused or the target changed.")
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
                            "fingerprint": snapshot["fingerprint"], "window": dict(window),
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


def _launch_target(target: str) -> tuple[str, str]:
    """Resolve an app name or absolute path to a startfile target and its source."""
    raw = target.strip()
    if not raw:
        raise adapter.ComputerBlocked("target 须为应用名或绝对路径。", "The target must be an app name or an absolute path.")
    candidate = Path(raw)
    if candidate.is_absolute():
        if candidate.is_file() and candidate.suffix.lower() in _LAUNCH_SUFFIXES:
            return str(candidate), "path"
        raise adapter.ComputerBlocked("启动目标须是已存在的 .exe 或 .lnk 文件路径。",
                                      "The launch target must be an existing .exe or .lnk file path.")
    lowered = raw.lower()
    exact: list[Path] = []
    partial: list[Path] = []
    roots = []
    for variable in ("APPDATA", "ProgramData"):
        base = os.environ.get(variable, "")
        if base:
            roots.append(Path(base) / "Microsoft" / "Windows" / "Start Menu")
    for root in roots:
        if not root.is_dir():
            continue
        try:
            entries = sorted(root.rglob("*.lnk"), key=lambda item: str(item).lower())
        except OSError:
            continue
        for entry in entries:
            stem = entry.stem.lower()
            if stem == lowered:
                exact.append(entry)
            elif lowered in stem:
                partial.append(entry)
    if exact or partial:
        return str((exact + partial)[0]), "start_menu"
    found = shutil.which(raw)
    if found and Path(found).suffix.lower() == ".exe":
        return str(Path(found)), "path_env"
    raise adapter.ComputerBlocked("未找到可启动的应用；请提供绝对路径或更准确的应用名。",
                                  "No launchable application was found. Provide an absolute path or a more precise app name.")


def _hotkey_keys(text: str) -> list[str]:
    parts = [part.strip().lower() for part in text.split("+")]
    if len(parts) < 2 or len(parts) > 4 or any(not part for part in parts):
        raise adapter.ComputerBlocked("组合键格式如 ctrl+c：至少一个修饰键加一个主键。",
                                      "Combo format is like ctrl+c: at least one modifier plus one key.")
    *modifiers, key = parts
    if any(modifier not in _HOTKEY_MODIFIERS for modifier in modifiers) or len(set(modifiers)) != len(modifiers):
        raise adapter.ComputerBlocked("修饰键只支持 ctrl/shift/alt/win。",
                                      "Modifiers support ctrl/shift/alt/win only.")
    if not (key in _HOTKEY_KEYS or (len(key) == 1 and key.isalnum())):
        raise adapter.ComputerBlocked("不支持该主键；请使用方向键、功能键、字母或数字等。",
                                      "That key is not supported. Use arrows, function keys, letters or digits.")
    return [*modifiers, key]


def _coordinate(value) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_COORDINATE:
        raise adapter.ComputerBlocked("坐标须为窗口内的非负整数像素。",
                                      "Coordinates must be non-negative integer pixels inside the window.")
    return value


def execute(owner, *, action="observe", observation_id="", element_id="", text="",
            window="", target="", x=None, y=None, cancel_checker=None) -> dict:
    global _active, _quarantine, _status, _message, _grant
    if not _execution.acquire(blocking=False):
        return {"ok": False, "status": "blocked", "message": _text("已有电脑操作正在等待或执行。", "A computer action is already waiting or running.")}
    connection = None
    grant_ref = None
    try:
        _owner(owner)
        if not callable(cancel_checker):
            raise adapter.ComputerBlocked("缺少原生轮次停止检查器。", "The native turn stop checker is missing.")
        if action not in ACTIONS:
            raise adapter.ComputerBlocked("不支持该电脑操作。", "This computer action is not supported.")
        if not isinstance(text, str) or len(text) > 2000 or any(ord(c) < 32 and c not in "\n\r\t" for c in text):
            raise adapter.ComputerBlocked("输入限 2000 字普通文本。", "Input is limited to 2000 characters of plain text.")
        if not isinstance(window, str) or len(window) > 200:
            raise adapter.ComputerBlocked("window 参数须为 200 字以内的文本。", "The window parameter must be text of up to 200 characters.")
        if not isinstance(target, str) or len(target) > 500 or any(ord(c) < 32 for c in target):
            raise adapter.ComputerBlocked("target 须为 500 字以内的应用名或绝对路径。", "The target must be an app name or absolute path of up to 500 characters.")
        if not isinstance(observation_id, str) or not isinstance(element_id, str):
            raise adapter.ComputerBlocked("凭据参数无效。", "The credential parameters are invalid.")
        if action == "scroll" and text not in {"up", "down", "left", "right"}:
            raise adapter.ComputerBlocked("滚动方向无效。", "The scroll direction is invalid.")
        with _lock:
            if _quarantine is not None:
                raise adapter.ComputerBlocked("输入执行器未确认退出，已拒绝继续输入；请结束授权重试清理。",
                                              "The input executor has not been confirmed to have exited. Further input is blocked; end the authorization to retry cleanup.")
        if action == "launch":
            if os.name != "nt":
                raise adapter.ComputerBlocked("电脑操作目前仅支持 Windows。", "Computer control currently supports Windows only.")
            resolved, source = _launch_target(target)
            try:
                os.startfile(resolved)
            except OSError:
                raise adapter.ComputerBlocked("系统拒绝打开该目标，没有启动。", "The system refused to open the target. Nothing was launched.") from None
            _event("launch", "accepted", target=target.strip()[:200], resolution=source)
            return {"ok": True, "status": "accepted",
                    "message": _text("已启动应用；请先 observe 等待其窗口出现后再操作。",
                                     "The application was started. Observe first and wait for its window before acting."),
                    "target": target.strip(), "resolution": source}
        if action == "hotkey":
            keys = _hotkey_keys(text)
        if action == "click_at":
            click_x, click_y = _coordinate(x), _coordinate(y)
        with _lock:
            epoch = _epoch
            grant_ref = _grant
        check = _checker(owner, epoch, cancel_checker, adapter.last_input_tick())
        _require(check)
        if action in _OBSERVATION_ACTIONS:
            with _lock:
                old = _observations.pop(observation_id, None)
                if (not old or old["owner"] != owner or old["epoch"] != epoch
                        or time.monotonic() - old["created"] > OBSERVATION_SECONDS):
                    raise adapter.ComputerBlocked("观察凭据已过期、已用或不属于本轮，请重新观察。", "The observation token has expired, was already used, or belongs to another turn. Observe again.")
                if action in _ELEMENT_ACTIONS:
                    if (not element_id.isdecimal() or int(element_id) >= len(old["targets"])):
                        raise adapter.ComputerBlocked("目标控件编号无效，请重新观察。", "The target control ID is invalid. Observe again.")
            window_record = dict(old["window"])
            _require(check)
            connection = adapter.Connection(check)
            connection.__enter__()
            with _lock:
                _active = connection
                _status, _message = "working", ("正在观察并核对目标窗口。", "Observing and checking the target window.")
            _require(check)
            before = connection.snapshot(window_record)
            _require(check)
            if before["fingerprint"] != old["fingerprint"] or before["incomplete"]:
                raise adapter.ComputerBlocked("窗口内容已变化或控件信息不完整，没有执行，请重新观察。", "The window content has changed or control information is incomplete. No action was taken; observe again.")
            element = None if action not in _ELEMENT_ACTIONS else before["elements"][int(element_id)]
            if action == "click_at":
                connection.click_at(window_record, click_x, click_y, before.get("snapshot_id") or "")
            else:
                expected = connection.act(window_record, action, element, text)
            _require(check)
            after = connection.snapshot(window_record)
            _require(check)
            same = [row for row in after["elements"] if isinstance(row, dict) and element is not None and all(
                row.get(key) == element.get(key) for key in ("role", "label", "parent_index", "frame"))]
            verified = (action in {"set_value", "type_text"} and isinstance(expected, str) and len(same) == 1
                        and str(same[0].get("value") or "").replace("\r\n", "\n") == expected.replace("\r\n", "\n"))
            with _lock:
                _require(check)
                result = _observe(owner, after, window_record)
                _status, _message = "ready", ("本次输入已结束；下一步仍需核对窗口。", "This input has finished. The window must still be checked before the next step.")
            result.update(status="completed" if verified else "unverified", verified=verified,
                          message=_text("文本已读取核对。", "The text was read back and verified.") if verified else _text("输入已送达，业务效果仍须根据窗口重新核对；未自动重试。", "Input was delivered. Its effect must still be checked against the window; no automatic retry was attempted."))
        else:
            _require(check)
            connection = adapter.Connection(check)
            connection.__enter__()
            with _lock:
                _active = connection
                _status, _message = "working", ("正在观察并核对目标窗口。", "Observing and checking the target window.")
            _require(check)
            window_record, failure, candidates = _resolve_model_window(owner, window, connection)
            if window_record is None:
                return _window_candidates_result(action, failure, candidates)
            _require(check)
            before = connection.snapshot(window_record, images=action == "observe")
            _require(check)
            if action == "observe":
                images = before["images"]
                if not images:
                    raise adapter.ComputerBlocked("窗口画面未能安全读取，没有向模型提供其他窗口。", "The window image could not be read safely. No other window was provided to the model.")
                # Release the desktop lease during model perception. No input is
                # admitted until its result and the current target are rechecked.
                connection.__exit__(None, None, None)
                with _lock:
                    _active = None
                connection = None
                from .personal_assistant_computer_vision import describe_window
                description = describe_window(images, owner, check)
                with _lock:
                    _require(check)
                    result = _observe(owner, before, window_record)
                    _status, _message = "ready", ("已完成本次观察；下一步仍需核对窗口。", "This observation is complete. The window must still be checked before the next step.")
                result.update(modality="window_screenshot_and_uia", visualDescription=description)
            else:
                connection.hotkey(window_record, keys)
                _require(check)
                after = connection.snapshot(window_record)
                _require(check)
                with _lock:
                    _require(check)
                    result = _observe(owner, after, window_record)
                    _status, _message = "ready", ("本次输入已结束；下一步仍需核对窗口。", "This input has finished. The window must still be checked before the next step.")
                result.update(status="unverified", verified=False,
                              message=_text("组合键已送达，业务效果仍须根据窗口重新核对；未自动重试。", "The key combo was delivered. Its effect must still be checked against the window; no automatic retry was attempted."))
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
        if action == "launch":
            _event(action, "blocked", target=target.strip()[:200])
        else:
            _event(action, "blocked")
        return {"ok": False, "status": "blocked", "message": _text(*message)}
    finally:
        retirement_failed = False
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
