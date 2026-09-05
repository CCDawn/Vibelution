"""Discover native CDP for the live shared desktop shell; never start or stop it."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from core.launcher.desktop_shell import resolve_desktop_shell_launch_roots
from core.launcher.desktop_shell_owner import _identity_status, desktop_shell_owner_path, read_desktop_shell_owner


def discover_desktop_debug(project_root: Path) -> dict:
    shell_root, _ = resolve_desktop_shell_launch_roots(project_root)
    owner = read_desktop_shell_owner(shell_root)
    if not owner or owner.get("owner") != "electron" or _identity_status(owner) != "match":
        raise RuntimeError("No verified live Electron desktop shell. Start it through Launcher.")
    path = desktop_shell_owner_path(shell_root).with_name("desktop_debug.json")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Desktop debugging is unavailable. A full shell restart is required after enabling it.") from exc
    if any(record.get(key) != owner.get(key) for key in ("pid", "executable")) or abs(float(record.get("createTime", 0)) - float(owner.get("createTime", 0))) > 2:
        raise RuntimeError("Desktop debugging record belongs to a previous shell process.")
    if Path(record.get("workspaceRoot", "")).resolve() != shell_root.resolve():
        raise RuntimeError("Desktop debugging workspace identity mismatch.")
    endpoint = str(record.get("httpEndpoint", ""))
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise RuntimeError("Desktop debugging endpoint must be a loopback HTTP origin.")
    # Ignore machine HTTP proxies for this local-only protocol.
    opener = build_opener(ProxyHandler({}))
    with opener.open(endpoint + "/json/version", timeout=3) as response:
        version = json.load(response)
    if version.get("webSocketDebuggerUrl") != record.get("webSocketDebuggerUrl"):
        raise RuntimeError("Desktop debugging endpoint changed. Discover it again.")
    with opener.open(endpoint + "/json/list", timeout=3) as response:
        targets = json.load(response)
    return {**record, "browser": version.get("Browser"), "targets": [
        {key: target.get(key, "") for key in ("id", "type", "title", "url", "webSocketDebuggerUrl")}
        for target in targets if target.get("type") == "page"
    ]}
