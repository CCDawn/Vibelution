"""Pinned Windows CUA adapter. Only background, explicitly addressed input.

Tokens belong to one driver snapshot. The service therefore resolves its own
short-lived element ids against a fresh snapshot before dispatching input.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading

import psutil

from core.infrastructure.cua_driver_client import CuaDriverClient
from core.infrastructure.file_lock import locked_sidecar


class ComputerBlocked(ValueError):
    pass


def driver_binary() -> Path:
    if os.name != "nt":
        raise ComputerBlocked("电脑操作目前仅支持 Windows。")
    raw = os.environ.get("VIBELUTION_COMPUTER_CUA_DRIVER", "")
    if not raw:
        home = Path(os.environ.get("VIBELUTION_DATA_HOME", ""))
        candidates = [home / "runtime" / "computer-cua-driver.json"] if home.is_absolute() else []
        legacy = os.environ.get("VIBELUTION_DESKTOP_CUA_CONFIG", "")
        if legacy:
            candidates.append(Path(legacy))
        elif home.is_absolute():
            candidates.append(home / "runtime" / "desktop-cua-scope.json")
        for config in candidates:
            if config.is_absolute() and config.is_file() and config.stat().st_size <= 16000:
                raw = str(json.loads(config.read_text(encoding="utf-8")).get("binaryPath") or "")
                if raw:
                    break
    binary = Path(raw)
    if (not raw or not binary.is_absolute() or not binary.is_file()
            or binary.name.lower() != "cua-driver.exe" or binary.is_symlink()):
        raise ComputerBlocked("尚未配置固定版 cua-driver 0.36.0，请配置电脑操作驱动后重试。")
    return binary.resolve()


def process_identity(pid: int) -> tuple[float, str]:
    try:
        process = psutil.Process(pid)
        return process.create_time(), process.exe()
    except psutil.Error:
        raise ComputerBlocked("窗口进程已退出或不可访问，请重新选择窗口。") from None


def last_input_tick() -> int:
    """OS-wide human input signal. Background UIA/SendMessage does not inject it."""
    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    value = LastInput()
    value.cbSize = ctypes.sizeof(value)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(value)):
        raise ComputerBlocked("无法确认人工接管状态，已停止电脑输入。")
    return int(value.dwTime)


class Connection:
    def __init__(self, checker):
        self.checker = checker
        self.driver = None
        self.lease = None
        self.session = "assistant-window-" + secrets.token_hex(12)
        self._state = threading.Lock()
        self._retirement = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._closing = False

    def __enter__(self):
        binary = driver_binary()
        lock = Path(tempfile.gettempdir()) / "Vibelution-desktop-cua" / "control.lock"
        self.lease = locked_sidecar(lock, lock_path=lock, timeout=0)
        self.lease.__enter__()
        self.driver = CuaDriverClient(binary, timeout_seconds=12)
        return self

    def __exit__(self, *args):
        # Do not release the desktop lease unless owned input processes exited.
        # A close failure is propagated; the service retains this connection.
        with self._retirement:
            with self._state:
                self._closing = True
            if self.driver is not None:
                self.driver.close()
            # close() can precede an in-flight transport spawn publishing its
            # OwnedProcess. Keep the lease until that call has fully unwound,
            # then close again to positively retire the published owner.
            if not self._idle.wait(timeout=15):
                raise ComputerBlocked("输入调用尚未退出，继续保留桌面锁。")
            if self.driver is not None:
                self.driver.close()
            if self.lease is not None:
                self.lease.__exit__(*args)
                self.lease = None

    def rpc(self, name: str, **args):
        with self._state:
            if self._closing or not self._idle.is_set():
                raise ComputerBlocked("输入执行器已经停止或仍在执行。")
            self._idle.clear()
        try:
            raw = self.driver.call(name, {**args, "session": self.session}, cancel_checker=self.checker)
        finally:
            self._idle.set()
        data = raw.get("structuredContent")
        if (raw.get("isError") or not isinstance(data, dict) or data.get("isError")
                or data.get("ok") is False or data.get("refusal")
                or data.get("status") in {"refused", "blocked", "error"}
                or data.get("effect") == "refused" or data.get("error")):
            raise ComputerBlocked("驱动拒绝操作，可能检测到人工操作或不支持后台输入；没有自动重试或切换前台。")
        return data, raw.get("content", [])

    def windows(self) -> list[dict]:
        data, _ = self.rpc("list_windows")
        return data.get("windows", [])

    def snapshot(self, window: dict, *, images: bool = False) -> dict:
        birth, executable = process_identity(window["pid"])
        if birth != window["birth"] or executable != window["executable"]:
            raise ComputerBlocked("窗口进程身份已变化，本次授权结束。")
        matches = [row for row in self.windows() if row.get("pid") == window["pid"]
                   and row.get("window_id") == window["hwnd"]]
        if len(matches) != 1:
            raise ComputerBlocked("已授权窗口已关闭，本次授权结束。")
        data, content = self.rpc("get_window_state", pid=window["pid"], window_id=window["hwnd"],
                                 tree_format="elements", include_screenshot=images,
                                 max_elements=200, timeout_ms=3000)
        elements = data.get("elements")
        if not isinstance(elements, list):
            raise ComputerBlocked("窗口未提供可核对的控件信息。")
        normalized = [{key: row.get(key) for key in ("role", "label", "value", "actions", "frame")}
                      for row in elements if isinstance(row, dict)]
        fingerprint = hashlib.sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        incomplete = data.get("truncated") is True or data.get("degraded") is True or (
            isinstance(data.get("returned_element_count"), int)
            and isinstance(data.get("total_element_count"), int)
            and data["returned_element_count"] < data["total_element_count"])
        pictures = [block for block in content if isinstance(block, dict) and block.get("type") == "image"]
        if not pictures:
            pictures = [{"type": "image", "mimeType": row.get("mime_type"), "data": row.get("data_base64")}
                        for row in data.get("images", []) if isinstance(row, dict)]
        if images and data.get("screenshot_frame_valid") is False:
            raise ComputerBlocked("窗口截图未通过有效性检查，请重新观察。")
        return {"elements": elements, "fingerprint": fingerprint, "incomplete": incomplete, "images": pictures}

    def act(self, window: dict, action: str, element: dict | None, text: str) -> str | None:
        args = {"pid": window["pid"], "window_id": window["hwnd"], "delivery_mode": "background"}
        if action == "scroll":
            self.rpc("scroll", **args, direction=text, amount=3, by="line")
            return
        token = (element or {}).get("element_token")
        if not isinstance(token, str) or not token:
            raise ComputerBlocked("目标控件无法可靠定位，请重新观察。")
        if action == "click":
            self.rpc("click", **args, element_token=token)
        elif action in {"set_value", "type_text"}:
            if (str(element.get("role", "")).lower() not in {"edit", "textinput", "document"}
                    or "set_value" not in element.get("actions", [])):
                raise ComputerBlocked("仅允许设置可访问性接口支持的文本编辑控件。")
            if action == "type_text":
                value = element.get("value")
                if not isinstance(value, str) or len(value) + len(text) > 8000:
                    raise ComputerBlocked("无法核对原有文本，不会按焦点盲目输入；可使用明确替换文本。")
                text = value + text
            self.rpc("set_value", **args, element_token=token, value=text)
            return text
        else:
            raise ComputerBlocked("不支持该电脑操作。")
