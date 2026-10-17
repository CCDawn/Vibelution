"""Opt-in Notepad evaluation profile; never a general desktop/MCP escape hatch.

Only an operator-approved Notepad window is exposed. This is window consent,
not file isolation: testFile is the disk read-back target, not a file sandbox.
UIA values are untrusted data; screenshots/other tabs/arbitrary keys are omitted.
Each call owns and closes its driver. An OS lock serializes calls across branch
instances on the same desktop; observations are single-use and turn-bound.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time
from typing import Callable

from core.infrastructure.cua_driver_client import CuaDriverClient, CuaDriverError, CuaDriverCancelledError
from core.infrastructure.file_lock import locked_sidecar
from scripts.windowless_subprocess import no_window_subprocess_kwargs

OBSERVATION_SECONDS = 90.0
_MAX_TEXT = 2000
_guard = threading.Lock()
_observations: OrderedDict[str, dict] = OrderedDict()
_retired: OrderedDict[tuple, float] = OrderedDict()
_quarantine: tuple[tuple, object, object] | None = None


class DesktopBlocked(ValueError):
    pass


class DesktopCancelled(DesktopBlocked):
    pass


@dataclass(frozen=True)
class Scope:
    binary: Path
    document: Path
    pid: int
    window_id: int
    process_birth: float


def _lock_path() -> Path:
    # Shared across worktrees/data homes; never allow per-Agent lock namespaces.
    return Path(tempfile.gettempdir()) / "Vibelution-desktop-cua" / "control.lock"


def _load_scope() -> Scope:
    raw = os.environ.get("VIBELUTION_DESKTOP_CUA_CONFIG", "")
    if not raw:
        # Launcher gives each checkout its own data home. This opt-in file does
        # not touch shared operator config or depend on an inherited shell env.
        data_home = os.environ.get("VIBELUTION_DATA_HOME", "")
        if data_home and Path(data_home).is_absolute():
            raw = str(Path(data_home) / "runtime" / "desktop-cua-scope.json")
    if not raw or not Path(raw).is_absolute():
        raise DesktopBlocked("桌面试验未启用：需要操作者配置 VIBELUTION_DESKTOP_CUA_CONFIG。")
    config = Path(raw)
    if config.stat().st_size > 16000:
        raise DesktopBlocked("桌面试验配置无效。")
    data = json.loads(config.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"enabled", "binaryPath", "testFile", "window"} or data["enabled"] is not True:
        raise DesktopBlocked("桌面试验未启用或配置字段无效。")
    window = data["window"]
    if (not isinstance(window, dict) or set(window) != {"pid", "windowId", "processCreateTime"}
            or type(window["pid"]) is not int or window["pid"] <= 0
            or type(window["windowId"]) is not int or window["windowId"] <= 0
            or type(window["processCreateTime"]) not in {int, float}
            or not 0 < window["processCreateTime"] < float("inf")):
        raise DesktopBlocked("需要操作者明确绑定独立测试窗口与进程创建时间。")
    binary, document = Path(data["binaryPath"]), Path(data["testFile"])
    if (not binary.is_absolute() or not binary.is_file() or binary.name.lower() != "cua-driver.exe"
            or not document.is_absolute() or document.resolve() != document.absolute()
            or not document.name.startswith("vibelution-cua-") or document.suffix != ".txt"):
        raise DesktopBlocked("仅允许已配置的 cua-driver.exe 与 vibelution-cua-*.txt 测试文件。")
    _file_signature(document)
    return Scope(binary.resolve(), document.resolve(), window["pid"], window["windowId"], window["processCreateTime"])


def _file_signature(path: Path) -> tuple:
    if path.resolve() != path.absolute() or not path.is_file():
        raise DesktopBlocked("测试文件已移动或成为链接。")
    stat = path.stat()
    if stat.st_nlink != 1 or stat.st_size > 32768:
        raise DesktopBlocked("测试文件必须是单链接的小型文本文件。")
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _is_notepad(pid: int) -> bool:
    import psutil
    try:
        executable = Path(psutil.Process(pid).exe()).resolve()
        system = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "notepad.exe"
        apps = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WindowsApps"
        return (executable == system.resolve() or (
            executable.name.lower() == "notepad.exe" and executable.is_relative_to(apps)
            and executable.relative_to(apps).parts[0].startswith("Microsoft.WindowsNotepad_")
        ))
    except (OSError, ValueError, psutil.Error):
        return False


def _process_birth(pid: int) -> float:
    import psutil
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error:
        raise DesktopBlocked("已授权的进程不再存在。") from None


def _launch(document: Path) -> None:
    binary = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "notepad.exe"
    if os.name != "nt" or not binary.is_file():
        raise DesktopBlocked("桌面试验仅支持 Windows 记事本。")
    # Fixed GUI program/one configured file. It is outside the driver's Job so
    # cancelling input never kills the user's Notepad or discards its buffers.
    process = subprocess.Popen([str(binary), str(document)], shell=False,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, **no_window_subprocess_kwargs())
    threading.Thread(target=process.wait, name="cua-notepad-reap", daemon=True).start()


def _title_matches(title: str, document: Path) -> bool:
    clean = title.removeprefix("*").lstrip()
    return clean in {document.name, document.name + " - Notepad", document.name + " - 记事本"}


def _normalize(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


class Call:
    def __init__(self, driver, checker, owner):
        self.driver, self.checker, self.owner = driver, checker, owner
        self.session = "pa-" + secrets.token_hex(8)
        self.deadline = time.monotonic() + 70

    def check(self):
        try:
            stopped = self.checker()
        except Exception:
            stopped = "cancel_check_failed"
        if stopped or time.monotonic() >= self.deadline:
            _retire(self.owner)
            self.driver.close()
            raise DesktopCancelled("桌面操作已停止；输入执行器已关闭。")

    def rpc(self, name, *, allow_menu_refusal=False, **args):
        self.check()
        raw = self.driver.call(name, {**args, "session": self.session}, cancel_checker=self.checker)
        self.check()
        data = raw.get("structuredContent")
        if (allow_menu_refusal and isinstance(data, dict)
                and (data.get("refusal") or {}).get("code") in {"menu_path_unavailable", "background_unavailable"}):
            return {"refused": True}
        if raw.get("isError") or not isinstance(data, dict) or data.get("isError") or data.get("ok") is False:
            raise DesktopBlocked("驱动拒绝操作或未返回可核对结果；未自动重试。")
        return data

    def snapshot(self, scope: Scope, target: tuple | None = None) -> dict:
        if _process_birth(scope.pid) != scope.process_birth:
            raise DesktopBlocked("已授权的进程身份已变化，需要操作者重新绑定窗口。")
        windows = self.rpc("list_windows", app="notepad").get("windows", [])
        matches = [w for w in windows if isinstance(w, dict)
                   and w.get("pid") == scope.pid and w.get("window_id") == scope.window_id
                   and _title_matches(str(w.get("title", "")), scope.document)
                   and _is_notepad(w.get("pid", 0))]
        if len(matches) != 1:
            raise DesktopBlocked("未找到唯一的已授权测试文档窗口，请在记事本中选中该测试文档。")
        window = matches[0]
        identity = (window["pid"], window["window_id"])
        if target is not None and identity != target:
            raise DesktopBlocked("目标窗口已经改变，请重新观察。")
        state = self.rpc("get_window_state", pid=identity[0], window_id=identity[1],
                         tree_format="elements", include_screenshot=False,
                         max_elements=160, timeout_ms=3000)
        if not _title_matches(str(state.get("window_title", "")), scope.document):
            raise DesktopBlocked("活动文档已经改变，已拒绝输入。")
        # On Windows 0.36.0, elements_complete=false also denotes an inherently
        # non-exhaustive platform walk, even when all 36/36 rows were returned.
        # Refuse an actually cut response, rather than rejecting that platform.
        if (state.get("truncated") is True or
                (isinstance(state.get("returned_element_count"), int)
                 and isinstance(state.get("total_element_count"), int)
                 and state["returned_element_count"] < state["total_element_count"])):
            raise DesktopBlocked("窗口控件信息不完整，已拒绝输入。")
        elements = state.get("elements", [])
        editors = [e for e in elements if isinstance(e, dict)
                   and str(e.get("role", "")).lower() in {"textinput", "edit", "document"}
                   and e.get("element_token")]
        if len(editors) != 1:
            raise DesktopBlocked("无法唯一确认测试文档编辑器或内容超过试验上限。")
        editor = editors[0]
        value = editor.get("value")
        # The pinned driver omits empty UIA values. Treat missing as empty only
        # when Notepad's same-window character-count status explicitly says 0.
        if (value is None and editor.get("role") == "Document" and "set_value" in editor.get("actions", [])
                and any(e.get("role") == "Text" and e.get("label") in {"0 个字符", "0 characters"}
                        for e in elements if isinstance(e, dict))):
            value = ""
        if not isinstance(value, str) or len(value) > 8000:
            raise DesktopBlocked("编辑器未提供可核对文本，已拒绝输入。")
        value = _normalize(value)
        menus = {e.get("label") for e in elements if isinstance(e, dict) and e.get("role") == "MenuItem"}
        save_path = ["文件", "保存"] if "文件" in menus else ["File", "Save"] if "File" in menus else None
        return {"target": identity, "processBirth": scope.process_birth,
                "value": value, "token": editor["element_token"], "savePath": save_path,
                "fingerprint": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                "file": _file_signature(scope.document)}


def _retire(owner):
    _retired[owner] = time.monotonic()
    while len(_retired) > 1024:
        _retired.popitem(last=False)
    for key in list(_observations):
        if _observations[key]["owner"] == owner:
            del _observations[key]


def _observed(owner, scope, state):
    token = secrets.token_urlsafe(24)
    _observations[token] = {**state, "owner": owner, "document": str(scope.document),
                            "created": time.monotonic()}
    while len(_observations) > 64:
        _observations.popitem(last=False)
    return {"ok": True, "status": "observed", "observationId": token,
            "document": scope.document.name, "text": state["value"][:_MAX_TEXT],
            "window": {"pid": scope.pid, "windowId": scope.window_id,
                       "processCreateTime": scope.process_birth}, "authorizationScope": "window",
            "textTruncated": len(state["value"]) > _MAX_TEXT, "modality": "uia",
            "contentTrust": "untrusted_document_data"}


def _saved(scope: Scope, value: str) -> bool:
    _file_signature(scope.document)
    return _normalize(scope.document.read_text(encoding="utf-8-sig")) == value


def execute(owner: tuple[str, str, str], *, action: str, observation_id: str = "", text: str = "",
            cancel_checker: Callable[[], str] | None = None) -> dict:
    """Called after native authorization and canonical personal identity checks."""
    global _quarantine
    if not _guard.acquire(blocking=False):
        return {"ok": False, "status": "blocked", "message": "桌面正由另一个操作使用。"}
    driver = None
    lease = None
    try:
        if (not isinstance(owner, tuple) or len(owner) != 3 or not all(isinstance(v, str) and v for v in owner)
                or not callable(cancel_checker)):
            raise DesktopBlocked("缺少原生轮次身份或停止检查器。")
        if action not in {"observe", "launch", "type_text", "save", "save_foreground", "end"}:
            raise DesktopBlocked("不支持该桌面操作。")
        if not isinstance(text, str) or len(text) > _MAX_TEXT or any(ord(c) < 32 and c not in "\r\n\t" for c in text):
            raise DesktopBlocked("输入必须是 2000 字以内的普通文本。")
        if action != "type_text" and text:
            raise DesktopBlocked("此操作不接受 text 参数。")
        if action == "end":
            if _quarantine is not None:
                if _quarantine[0][:2] != owner[:2]:
                    raise DesktopBlocked("上一个桌面执行器等待所属会话清理。")
                try:
                    _quarantine[1].close()
                    _quarantine[2].__exit__(None, None, None)
                except Exception:
                    return {"ok": False, "status": "unknown", "message": "执行器尚未确认退出，继续拒绝新输入。"}
                _quarantine = None
            _retire(owner)
            return {"ok": True, "status": "completed", "message": "本轮桌面输入已关闭；应用和文档保留。"}
        if _quarantine is not None:
            raise DesktopBlocked("上一个桌面执行器尚未确认退出，仅允许 end 重试清理。")
        if owner in _retired:
            raise DesktopBlocked("此轮次的桌面控制已结束，请开启新轮次。")
        scope = _load_scope()
        desktop_lease = locked_sidecar(_lock_path(), lock_path=_lock_path(), timeout=0)
        desktop_lease.__enter__()
        lease = desktop_lease
        driver = CuaDriverClient(scope.binary, timeout_seconds=12)
        call = Call(driver, cancel_checker, owner)
        call.check()
        if action == "launch":
            if observation_id:
                raise DesktopBlocked("launch 不接受旧窗口凭据。")
            _launch(scope.document)
            call.check()
            return {"ok": True, "status": "accepted", "message": "已请求打开测试文档；须观察窗口确认打开结果。"}
        if action == "observe":
            if observation_id:
                raise DesktopBlocked("observe 不接受旧窗口凭据。")
            result = _observed(owner, scope, call.snapshot(scope))
        else:
            previous = _observations.pop(observation_id, None)
            if (not previous or previous["owner"] != owner
                    or previous["document"] != str(scope.document)
                    or time.monotonic() - previous["created"] > OBSERVATION_SECONDS):
                raise DesktopBlocked("观察凭据已过期、已使用或不属于当前轮次，请重新观察。")
            if action == "save_foreground" and not previous.get("foregroundEligible"):
                raise DesktopBlocked("必须先核对后台保存未生效，才能单独审批前台保存。")
            before = call.snapshot(scope, previous["target"])
            if (before["processBirth"] != previous["processBirth"]
                    or before["fingerprint"] != previous["fingerprint"] or before["file"] != previous["file"]):
                raise DesktopBlocked("文档已被改变，已拒绝输入，请重新观察。")
            args = {"pid": before["target"][0], "window_id": before["target"][1],
                    "element_token": before["token"], "delivery_mode": "background"}
            if action == "type_text":
                # type_text may fall back to cursor insertion on Notepad. Only
                # the AX/UIA set_value contract performs an exact replacement.
                call.rpc("set_value", **args, value=text)
            elif action == "save":
                # Background WM_CHAR shortcuts can insert a literal 's'. Use
                # an exact native menu path or refuse, never synthetic keys.
                if before["savePath"]:
                    call.rpc("invoke_menu", pid=args["pid"], window_id=args["window_id"],
                             path=before["savePath"], allow_menu_refusal=True)
            else:
                if action == "save_foreground":
                    args["delivery_mode"] = "foreground"
                call.rpc("press_key", **args, key="s", modifiers=["ctrl"])
            after = call.snapshot(scope, before["target"])
            verified = (after["value"] == _normalize(text) if action == "type_text"
                        else after["value"] == before["value"] and _saved(scope, before["value"]))
            result = _observed(owner, scope, after)
            result.update(ok=verified, status="completed" if verified else "unverified")
            if not verified:
                result["message"] = "输入已送达，但实际效果未确认；没有自动重试或切换前台。"
                if action == "save" and after["value"] == before["value"] and after["file"] == before["file"]:
                    _observations[result["observationId"]]["foregroundEligible"] = True
                    result["foregroundSaveAvailable"] = True
        call.check()
        return result
    except DesktopCancelled as exc:
        return {"ok": False, "status": "cancelled", "message": str(exc)}
    except CuaDriverCancelledError:
        _retire(owner)
        return {"ok": False, "status": "cancelled", "message": "桌面输入执行器已停止，实际文档效果须重新核对。"}
    except (CuaDriverError, TimeoutError):
        if driver is None:
            return {"ok": False, "status": "blocked", "message": "另一实例正在使用桌面，请稍后重新观察。"}
        _retire(owner)
        return {"ok": False, "status": "unknown", "message": "桌面执行器已关闭，结果未确认；不得盲目重复输入。"}
    except DesktopBlocked as exc:
        return {"ok": False, "status": "blocked", "message": str(exc)}
    except (OSError, ValueError, TypeError, KeyError):
        return {"ok": False, "status": "blocked", "message": "桌面操作未获准或目标已变化；请核对试验配置与窗口后重新观察。"}
    finally:
        try:
            if driver is not None:
                try:
                    driver.close()
                except Exception:
                    # Retain the OS lease across calls and processes until the
                    # owned execution tree has positively finished retiring.
                    _quarantine = (owner, driver, lease)
                    lease = None
                    _retire(owner)
                    return {"ok": False, "status": "unknown", "message": "执行器退出尚未确认，已拒绝新输入；仅允许 end 重试清理。"}
        finally:
            try:
                if lease is not None:
                    lease.__exit__(None, None, None)
            finally:
                _guard.release()
