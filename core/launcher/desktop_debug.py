"""Discover native CDP for the live shared desktop shell; never start or stop it."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from core.launcher.desktop_shell import resolve_desktop_shell_launch_roots
from core.launcher.desktop_shell_owner import (
    _identity_status,
    desktop_shell_owner_path,
    read_desktop_shell_owner,
)


class DesktopDebugError(RuntimeError):
    """A fixed discovery message safe for the command's public JSON result."""


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise DesktopDebugError("Desktop debugging endpoint must not redirect.")


def _read_json(stream, limit: int):
    content = stream.read(limit + 1)
    if len(content) > limit:
        raise DesktopDebugError("Desktop debugging discovery data is too large.")
    return json.loads(content)


def _read_record(path: Path) -> dict:
    try:
        with path.open("rb") as stream:
            record = _read_json(stream, 64 * 1024)
        if not isinstance(record, dict):
            raise DesktopDebugError("Desktop debugging discovery record is invalid.")
        return record
    except (OSError, ValueError) as exc:
        raise DesktopDebugError("Desktop debugging is unavailable. A full shell restart is required after enabling it.") from exc


def discover_desktop_debug(project_root: Path) -> dict:
    shell_root, _ = resolve_desktop_shell_launch_roots(project_root)
    owner = read_desktop_shell_owner(shell_root)
    if not owner or owner.get("owner") != "electron" or _identity_status(owner) != "match":
        raise DesktopDebugError("No verified live Electron desktop shell. Start it through Launcher.")
    path = desktop_shell_owner_path(shell_root).with_name("desktop_debug.json")
    record = _read_record(path)
    if any(record.get(key) != owner.get(key) for key in ("pid", "executable")) or abs(float(record.get("createTime", 0)) - float(owner.get("createTime", 0))) > 2:
        raise DesktopDebugError("Desktop debugging record belongs to a previous shell process.")
    if Path(record.get("workspaceRoot", "")).resolve() != shell_root.resolve():
        raise DesktopDebugError("Desktop debugging workspace identity mismatch.")
    return _discover_record(record)


def discover_assistant_debug(user_data_root: Path) -> dict:
    """Read only the independent Launcher's fixed, native-identity-bound record."""
    root = Path(user_data_root)
    if not root.is_absolute():
        raise DesktopDebugError("Launcher assistant user data path must be absolute.")
    record = _read_record(root / "assistant" / "desktop_debug.json")
    create_time = record.get("createTime")
    executable = record.get("executable")
    if (type(record.get("schemaVersion")) is not int or record["schemaVersion"] != 1
        or record.get("kind") != "launcher_assistant" or record.get("workspaceRoot") != ""
        or type(record.get("pid")) is not int or not 0 < record["pid"] <= 0xFFFFFFFF
        or type(create_time) not in {int, float} or not 0 < create_time < 1e12 or not math.isfinite(create_time)
        or not isinstance(executable, str) or len(executable) > 32767 or not Path(executable).is_absolute()):
        raise DesktopDebugError("Launcher assistant debugging record has invalid identity.")
    if _identity_status(record) != "match":
        raise DesktopDebugError("No verified live Launcher assistant desktop.")
    return _discover_record(record)


def _discover_record(record: dict) -> dict:
    """One loopback/Chromium nonce handshake for both discovery principals."""
    endpoint = str(record.get("httpEndpoint", ""))
    try:
        parsed = urlsplit(endpoint)
        websocket = urlsplit(str(record.get("webSocketDebuggerUrl", "")))
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
            or parsed.username is not None or parsed.password is not None or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("origin")
        if (websocket.scheme != "ws" or websocket.hostname != "127.0.0.1" or websocket.port != parsed.port
            or websocket.username is not None or websocket.password is not None or websocket.query or websocket.fragment
            or not re.fullmatch(r"/devtools/browser/[A-Za-z0-9_-]+", websocket.path)):
            raise ValueError("nonce")
    except ValueError as exc:
        raise DesktopDebugError("Desktop debugging endpoint must be a loopback HTTP origin with a Chromium nonce.") from exc
    # Ignore machine HTTP proxies for this local-only protocol.
    opener = build_opener(ProxyHandler({}), _RejectRedirects())
    try:
        with opener.open(endpoint + "/json/version", timeout=3) as response:
            version = _read_json(response, 1024 * 1024)
        if not isinstance(version, dict):
            raise DesktopDebugError("Desktop debugging version data is invalid.")
        if version.get("webSocketDebuggerUrl") != record.get("webSocketDebuggerUrl"):
            raise DesktopDebugError("Desktop debugging endpoint changed. Discover it again.")
        with opener.open(endpoint + "/json/list", timeout=3) as response:
            targets = _read_json(response, 1024 * 1024)
        if not isinstance(targets, list) or len(targets) > 256:
            raise DesktopDebugError("Desktop debugging target data is invalid.")
    except (OSError, ValueError) as exc:
        raise DesktopDebugError("Desktop debugging endpoint is unavailable or returned invalid data.") from exc
    public_record = {key: record[key] for key in ("schemaVersion", "kind", "owner", "pid", "createTime", "executable",
                                                "workspaceRoot", "httpEndpoint", "webSocketDebuggerUrl") if key in record}
    return {**public_record, "browser": version.get("Browser"), "targets": [
        {key: target.get(key, "") for key in ("id", "type", "title", "url", "webSocketDebuggerUrl")}
        for target in targets if isinstance(target, dict) and target.get("type") == "page"
    ]}
