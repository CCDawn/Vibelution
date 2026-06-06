# -*- coding: utf-8 -*-
"""Tiny local Computer Use bridge for Vibelution's v1 sandbox browser path.

This bridge provides the same /v1/predict shape expected by Vibelution while
network access to Open Computer Use / Coasty is unavailable. It opens a URL in
Edge headless, captures a screenshot, and returns a bounded task result.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import shlex
import socket
import struct
import subprocess
import tempfile
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.parse import urlparse


DEFAULT_EDGE_CANDIDATES = (
    Path(os.environ.get("ProgramFiles", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    Path(os.environ.get("LocalAppData", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
)
HIGH_RISK_ACTION_TOKENS = {"submit", "send", "delete", "pay", "purchase", "download", "upload", "login", "confirm"}
SUPPORTED_ACTIONS = {"click", "type", "fill", "press", "scroll", "wait", "navigate", "screenshot", "wait_for_selector"}
ACTION_ALIASES = {"goto": "navigate", "open": "navigate", "sleep": "wait", "input": "type"}


def resolve_edge() -> Path:
    for candidate in DEFAULT_EDGE_CANDIDATES:
        if candidate.exists():
            return candidate.resolve()
    raise RuntimeError("Microsoft Edge was not found.")


def normalize_domains(value: Any) -> list[str]:
    if isinstance(value, list):
        items = value
    else:
        items = str(value or "").replace(";", ",").split(",")
    domains: list[str] = []
    for item in items:
        domain = str(item or "").strip().lower()
        if not domain:
            continue
        if "://" in domain:
            domain = str(urlparse(domain).hostname or "").lower()
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def is_allowed_url(url: str, allowed_domains: list[str]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return host in allowed_domains


def normalize_action_name(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    return ACTION_ALIASES.get(raw, raw)


def coerce_actions(value: Any, *, max_steps: int) -> list[dict[str, Any]]:
    if value in (None, "", []):
        return []
    if isinstance(value, dict):
        nested = value.get("actions")
        raw_items = nested if isinstance(nested, list) else [value]
    elif isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            raw_items = [parse_action_dsl_line(line) for line in stripped.replace(";", "\n").splitlines() if line.strip()]
        else:
            if isinstance(parsed, dict):
                nested = parsed.get("actions")
                raw_items = nested if isinstance(nested, list) else [parsed]
            elif isinstance(parsed, list):
                raw_items = parsed
            else:
                raw_items = []
    else:
        raw_items = []

    actions: list[dict[str, Any]] = []
    for raw in list(raw_items)[:max_steps]:
        action = normalize_action(raw)
        if action:
            actions.append(action)
    return actions


def parse_action_dsl_line(line: str) -> dict[str, Any]:
    try:
        parts = shlex.split(line)
    except ValueError:
        return {}
    if not parts:
        return {}
    result: dict[str, Any] = {"action": parts[0]}
    positionals: list[str] = []
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            result[camel_to_snake(key.strip())] = value
        else:
            positionals.append(part)
    action = normalize_action_name(parts[0])
    if action in {"click", "wait_for_selector"} and positionals:
        result.setdefault("selector", positionals[0])
    elif action in {"type", "fill"}:
        if positionals:
            result.setdefault("selector", positionals[0])
        if len(positionals) > 1:
            result.setdefault("text", " ".join(positionals[1:]))
    elif action == "press" and positionals:
        result.setdefault("key", positionals[0])
    elif action == "scroll" and positionals:
        result.setdefault("y", positionals[0])
    elif action == "wait" and positionals:
        result.setdefault("ms", positionals[0])
    elif action == "navigate" and positionals:
        result.setdefault("url", positionals[0])
    return result


def normalize_action(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = parse_action_dsl_line(raw)
    if not isinstance(raw, dict):
        return {}
    action = normalize_action_name(raw.get("action") or raw.get("type"))
    if action not in SUPPORTED_ACTIONS:
        return {"action": action or "unknown", "unsupported": True}
    result: dict[str, Any] = {"action": action}
    for source, target in (
        ("selector", "selector"),
        ("css", "selector"),
        ("target", "selector"),
        ("text", "text"),
        ("value", "text"),
        ("url", "url"),
        ("target_url", "url"),
        ("targetUrl", "url"),
        ("key", "key"),
    ):
        if source in raw and str(raw.get(source) or "").strip():
            result[target] = str(raw.get(source) or "").strip()
    for source, target in (
        ("x", "x"),
        ("y", "y"),
        ("delta_x", "deltaX"),
        ("deltaX", "deltaX"),
        ("delta_y", "deltaY"),
        ("deltaY", "deltaY"),
        ("ms", "ms"),
        ("timeout_ms", "timeoutMs"),
        ("timeoutMs", "timeoutMs"),
    ):
        if source in raw:
            result[target] = bounded_int(raw.get(source), default=0, minimum=-100000, maximum=100000)
    if raw.get("requiresConfirmation") or raw.get("requires_confirmation"):
        result["requiresConfirmation"] = True
    return result


def validate_action_domains(actions: list[dict[str, Any]], allowed_domains: list[str]) -> str:
    for index, action in enumerate(actions, start=1):
        if action.get("unsupported"):
            return f"Unsupported browser action: {action.get('action')}"
        shape_error = validate_action_shape(action, index=index)
        if shape_error:
            return shape_error
        if action.get("action") == "navigate" and not is_allowed_url(str(action.get("url") or ""), allowed_domains):
            return "Action navigates outside allowed_domains."
    return ""


def validate_action_shape(action: dict[str, Any], *, index: int) -> str:
    name = str(action.get("action") or "")
    if name in {"click", "wait_for_selector"} and not action.get("selector") and not ("x" in action and "y" in action):
        return f"Action {index} ({name}) requires selector or x/y coordinates."
    if name in {"type", "fill"} and not action.get("text"):
        return f"Action {index} ({name}) requires text."
    if name == "press" and not action.get("key"):
        return f"Action {index} (press) requires key."
    if name == "navigate" and not action.get("url"):
        return f"Action {index} (navigate) requires url."
    return ""


def public_action_summary(action: dict[str, Any], *, index: int) -> dict[str, Any]:
    summary: dict[str, Any] = {"index": index, "action": str(action.get("action") or "")}
    for key in ("selector", "url", "key", "x", "y", "deltaX", "deltaY", "ms", "timeoutMs", "requiresConfirmation"):
        if key in action:
            summary[key] = safe_url_summary(str(action[key])) if key == "url" else action[key]
    if "text" in action:
        summary["textLength"] = len(str(action.get("text") or ""))
    return summary


def safe_url_summary(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        return ""
    return f"{parsed.scheme}://{parsed.hostname}{parsed.path or ''}"


def bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


def camel_to_snake(value: str) -> str:
    result = []
    for char in value:
        if char.isupper() and result:
            result.append("_")
        result.append(char.lower())
    return "".join(result)


def contains_high_risk_action(actions: list[dict[str, Any]]) -> bool:
    for action in actions:
        if is_high_risk_action(action):
            return True
    return False


def is_high_risk_action(action: dict[str, Any]) -> bool:
    if action.get("requiresConfirmation"):
        return True
    joined = " ".join(str(action.get(key) or "").lower() for key in ("action", "selector", "url"))
    return any(token in joined for token in HIGH_RISK_ACTION_TOKENS)


def run_browser_task(payload: dict[str, Any], *, edge: Path, timeout: int) -> dict[str, Any]:
    task = str(payload.get("task") or "").strip()
    target_url = str(payload.get("target_url") or payload.get("targetUrl") or "").strip()
    allowed_domains = normalize_domains(payload.get("allowed_domains") or payload.get("allowedDomains"))
    max_steps = bounded_int(payload.get("max_steps") or payload.get("maxSteps"), default=20, minimum=1, maximum=30)
    actions = coerce_actions(payload.get("actions"), max_steps=max_steps)
    if target_url:
        host = str(urlparse(target_url).hostname or "").lower()
        if host and host not in allowed_domains:
            allowed_domains.append(host)
    if not task:
        return {"status": "failed", "summary": "task is required.", "steps": [], "error": "MISSING_TASK"}
    if not target_url or not is_allowed_url(target_url, allowed_domains):
        return {
            "status": "blocked",
            "summary": "target_url is outside allowed_domains.",
            "steps": [],
            "error": "DOMAIN_BLOCKED",
        }
    action_domain_error = validate_action_domains(actions, allowed_domains)
    if action_domain_error:
        return {
            "status": "blocked",
            "summary": action_domain_error,
            "steps": [],
            "error": "DOMAIN_BLOCKED",
            "requestedActions": [public_action_summary(action, index=index) for index, action in enumerate(actions, start=1)],
        }
    if actions:
        return run_cdp_browser_task(
            payload,
            edge=edge,
            timeout=timeout,
            target_url=target_url,
            allowed_domains=allowed_domains,
            actions=actions,
        )

    tmp = Path(tempfile.mkdtemp(prefix="vibelution-cu-"))
    try:
        screenshot_path = tmp / "screenshot.png"
        profile_dir = tmp / "profile"
        command = [
            str(edge),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}",
            "--window-size=1366,900",
            f"--screenshot={screenshot_path}",
            target_url,
        ]
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        if completed.returncode != 0:
            return {
                "status": "failed",
                "summary": "Edge headless screenshot failed.",
                "steps": [{"action": "open", "summary": target_url, "status": "failed"}],
                "error": (completed.stderr or completed.stdout or "").strip()[:500],
                "durationMs": duration_ms,
            }
        if not screenshot_path.exists():
            return {
                "status": "failed",
                "summary": "Edge did not produce a screenshot.",
                "steps": [{"action": "open", "summary": target_url, "status": "failed"}],
                "error": "SCREENSHOT_MISSING",
                "durationMs": duration_ms,
            }
        return {
            "status": "completed",
            "summary": "Sandbox browser opened the target URL and captured a screenshot.",
            "steps": [
                {"action": "open", "summary": target_url, "status": "completed"},
                {"action": "screenshot", "summary": "Captured sandbox browser screenshot.", "status": "completed"},
            ],
            "screenshot_b64": base64.b64encode(screenshot_path.read_bytes()).decode("ascii"),
            "durationMs": duration_ms,
            "bridgeSessionId": str(payload.get("session_id") or uuid.uuid4().hex),
        }
    finally:
        cleanup_temp_dir(tmp)


def run_cdp_browser_task(
    payload: dict[str, Any],
    *,
    edge: Path,
    timeout: int,
    target_url: str,
    allowed_domains: list[str],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    started = time.perf_counter()
    steps: list[dict[str, Any]] = []
    screenshot_b64 = ""
    browser: subprocess.Popen[str] | None = None
    require_confirmation = bool(payload.get("require_confirmation", payload.get("requireConfirmation", True)))
    tmp = Path(tempfile.mkdtemp(prefix="vibelution-cu-"))
    try:
        profile_dir = tmp / "profile"
        remote_port = free_tcp_port()
        command = [
            str(edge),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}",
            "--window-size=1366,900",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={remote_port}",
            target_url,
        ]
        try:
            browser = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            ws_url = wait_for_cdp_websocket(remote_port, timeout_seconds=min(timeout, 30))
            with CdpClient(ws_url, timeout=min(timeout, 30)) as cdp:
                cdp.command("Page.enable")
                cdp.command("Runtime.enable")
                cdp.command("Page.navigate", {"url": target_url})
                wait_for_location(cdp, target_url, timeout_seconds=min(timeout, 20))
                steps.append({"action": "open", "summary": target_url, "status": "completed"})
                for index, action in enumerate(actions, start=1):
                    if require_confirmation and is_high_risk_action(action):
                        steps.append(
                            {
                                "index": index,
                                "action": str(action.get("action") or ""),
                                "summary": "High-risk browser action requires user confirmation before execution.",
                                "status": "ready",
                                "requiresConfirmation": True,
                            }
                        )
                        screenshot_b64 = capture_screenshot(cdp)
                        return {
                            "status": "need_confirmation",
                            "summary": "Sandbox browser paused before a high-risk action.",
                            "steps": steps,
                            "screenshot_b64": screenshot_b64,
                            "durationMs": int((time.perf_counter() - started) * 1000),
                            "bridgeSessionId": str(payload.get("session_id") or uuid.uuid4().hex),
                            "requestedActions": [
                                public_action_summary(item, index=item_index)
                                for item_index, item in enumerate(actions, start=1)
                            ],
                        }
                    step = execute_cdp_action(cdp, action, allowed_domains=allowed_domains, index=index)
                    steps.append(step)
                    if step.get("status") != "completed":
                        screenshot_b64 = capture_screenshot(cdp)
                        return {
                            "status": "blocked" if step.get("error") == "DOMAIN_BLOCKED" else "failed",
                            "summary": str(step.get("summary") or "Browser action failed."),
                            "steps": steps,
                            "screenshot_b64": screenshot_b64,
                            "error": str(step.get("error") or ""),
                            "durationMs": int((time.perf_counter() - started) * 1000),
                            "bridgeSessionId": str(payload.get("session_id") or uuid.uuid4().hex),
                        }
                screenshot_b64 = capture_screenshot(cdp)
        finally:
            stop_browser_process(browser)
    finally:
        cleanup_temp_dir(tmp)
    steps.append({"action": "screenshot", "summary": "Captured sandbox browser screenshot.", "status": "completed"})
    return {
        "status": "completed",
        "summary": f"Sandbox browser executed {len(actions)} action(s) and captured a screenshot.",
        "steps": steps,
        "screenshot_b64": screenshot_b64,
        "durationMs": int((time.perf_counter() - started) * 1000),
        "bridgeSessionId": str(payload.get("session_id") or uuid.uuid4().hex),
        "requestedActions": [public_action_summary(action, index=index) for index, action in enumerate(actions, start=1)],
    }


class CdpClient:
    def __init__(self, websocket_url: str, *, timeout: int) -> None:
        self.websocket_url = websocket_url
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.next_id = 1

    def __enter__(self) -> "CdpClient":
        parsed = urlparse(self.websocket_url)
        if parsed.scheme != "ws" or not parsed.hostname or not parsed.port:
            raise RuntimeError("Invalid CDP websocket URL.")
        raw_sock = socket.create_connection((parsed.hostname, parsed.port), timeout=self.timeout)
        raw_sock.settimeout(self.timeout)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        raw_sock.sendall(request.encode("ascii"))
        response = recv_until(raw_sock, b"\r\n\r\n")
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError("CDP websocket upgrade failed.")
        self.sock = raw_sock
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                return

    def command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.sock:
            raise RuntimeError("CDP websocket is not connected.")
        message_id = self.next_id
        self.next_id += 1
        send_ws_json(self.sock, {"id": message_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            message = recv_ws_json(self.sock)
            if int(message.get("id") or 0) != message_id:
                continue
            if "error" in message:
                raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
            return message.get("result") if isinstance(message.get("result"), dict) else {}
        raise TimeoutError(f"Timed out waiting for CDP command: {method}")


def recv_until(sock: socket.socket, marker: bytes) -> bytes:
    chunks = bytearray()
    while marker not in chunks:
        chunk = sock.recv(4096)
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def send_ws_json(sock: socket.socket, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    mask = os.urandom(4)
    header = bytearray([0x81])
    length = len(data)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.extend([0x80 | 126])
        header.extend(struct.pack("!H", length))
    else:
        header.extend([0x80 | 127])
        header.extend(struct.pack("!Q", length))
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
    sock.sendall(bytes(header) + mask + masked)


def recv_ws_json(sock: socket.socket) -> dict[str, Any]:
    while True:
        first = recv_exact(sock, 2)
        opcode = first[0] & 0x0F
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", recv_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", recv_exact(sock, 8))[0]
        masked = bool(first[1] & 0x80)
        mask = recv_exact(sock, 4) if masked else b""
        data = recv_exact(sock, length) if length else b""
        if masked:
            data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        if opcode == 0x8:
            raise RuntimeError("CDP websocket closed.")
        if opcode == 0x9:
            continue
        if opcode == 0x1:
            return json.loads(data.decode("utf-8"))


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise RuntimeError("CDP websocket closed unexpectedly.")
        chunks.extend(chunk)
    return bytes(chunks)


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_cdp_websocket(port: int, *, timeout_seconds: int) -> str:
    endpoint = f"http://127.0.0.1:{port}/json/list"
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urlrequest.urlopen(endpoint, timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, list):
                for target in payload:
                    if not isinstance(target, dict):
                        continue
                    if target.get("type") != "page":
                        continue
                    ws_url = str(target.get("webSocketDebuggerUrl") or "")
                    if ws_url:
                        return ws_url
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.1)
    raise TimeoutError(f"Edge CDP endpoint did not become ready: {last_error}")


def wait_for_page_ready(cdp: CdpClient, *, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            result = cdp.command("Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True})
            state = str(result.get("result", {}).get("value") or "")
            if state in {"interactive", "complete"}:
                return
        except Exception:
            pass
        time.sleep(0.1)


def wait_for_location(cdp: CdpClient, expected_url: str, *, timeout_seconds: int) -> None:
    expected = expected_url.rstrip("/")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            result = cdp.command(
                "Runtime.evaluate",
                {
                    "expression": "({href: location.href, readyState: document.readyState})",
                    "returnByValue": True,
                },
            )
            value = result.get("result", {}).get("value")
            if isinstance(value, dict):
                href = str(value.get("href") or "").rstrip("/")
                ready_state = str(value.get("readyState") or "")
                if href == expected and ready_state in {"interactive", "complete"}:
                    return
        except Exception:
            pass
        time.sleep(0.1)


def execute_cdp_action(cdp: CdpClient, action: dict[str, Any], *, allowed_domains: list[str], index: int) -> dict[str, Any]:
    name = str(action.get("action") or "")
    try:
        if name == "click":
            click_action(cdp, action)
        elif name in {"type", "fill"}:
            type_action(cdp, action, clear=name == "fill")
        elif name == "press":
            press_action(cdp, str(action.get("key") or ""))
        elif name == "scroll":
            scroll_action(cdp, action)
        elif name == "wait":
            time.sleep(max(0, min(int(action.get("ms") or 1000), 10000)) / 1000)
        elif name == "navigate":
            url = str(action.get("url") or "")
            if not is_allowed_url(url, allowed_domains):
                return {"index": index, "action": name, "summary": "Navigation outside allowed_domains blocked.", "status": "blocked", "error": "DOMAIN_BLOCKED"}
            cdp.command("Page.navigate", {"url": url})
            wait_for_page_ready(cdp, timeout_seconds=15)
        elif name == "wait_for_selector":
            wait_for_selector(cdp, str(action.get("selector") or ""), timeout_ms=int(action.get("timeoutMs") or 10000))
        elif name == "screenshot":
            capture_screenshot(cdp)
        else:
            return {"index": index, "action": name, "summary": f"Unsupported action: {name}", "status": "failed", "error": "UNSUPPORTED_ACTION"}
    except Exception as exc:
        return {"index": index, "action": name, "summary": f"{name} failed.", "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    return {"index": index, "action": name, "summary": action_step_summary(action), "status": "completed"}


def action_step_summary(action: dict[str, Any]) -> str:
    name = str(action.get("action") or "")
    if action.get("selector"):
        return f"{name} {action.get('selector')}"
    if action.get("url"):
        return f"{name} {safe_url_summary(str(action.get('url') or ''))}"
    if action.get("key"):
        return f"{name} {action.get('key')}"
    return name


def js_string(value: str) -> str:
    return json.dumps(value)


def element_box(cdp: CdpClient, selector: str) -> dict[str, float]:
    expression = (
        "(() => {"
        f"const el = document.querySelector({js_string(selector)});"
        "if (!el) return null;"
        "el.scrollIntoView({block:'center', inline:'center'});"
        "const r = el.getBoundingClientRect();"
        "return {x:r.left + r.width/2, y:r.top + r.height/2, width:r.width, height:r.height};"
        "})()"
    )
    result = cdp.command("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    value = result.get("result", {}).get("value")
    if not isinstance(value, dict):
        raise RuntimeError(f"Selector not found: {selector}")
    return {key: float(value.get(key) or 0) for key in ("x", "y", "width", "height")}


def click_action(cdp: CdpClient, action: dict[str, Any]) -> None:
    if action.get("selector"):
        box = element_box(cdp, str(action.get("selector") or ""))
        x = box["x"]
        y = box["y"]
    else:
        x = float(action.get("x") or 0)
        y = float(action.get("y") or 0)
    cdp.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    cdp.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})


def type_action(cdp: CdpClient, action: dict[str, Any], *, clear: bool) -> None:
    selector = str(action.get("selector") or "")
    text = str(action.get("text") or "")
    if selector:
        click_action(cdp, {"selector": selector})
    if clear:
        press_action(cdp, "Control+A")
    cdp.command("Input.insertText", {"text": text})


def press_action(cdp: CdpClient, key: str) -> None:
    normalized = key.strip()
    if not normalized:
        raise RuntimeError("key is required.")
    modifiers = 0
    parts = [part.strip() for part in normalized.replace("+", " ").split() if part.strip()]
    final_key = parts[-1]
    for modifier in parts[:-1]:
        lowered = modifier.lower()
        if lowered in {"control", "ctrl"}:
            modifiers |= 2
        elif lowered == "alt":
            modifiers |= 1
        elif lowered == "shift":
            modifiers |= 8
        elif lowered in {"meta", "cmd", "command"}:
            modifiers |= 4
    key_name, code, key_code = key_metadata(final_key)
    params = {"key": key_name, "code": code, "windowsVirtualKeyCode": key_code, "nativeVirtualKeyCode": key_code, "modifiers": modifiers}
    cdp.command("Input.dispatchKeyEvent", {"type": "keyDown", **params})
    cdp.command("Input.dispatchKeyEvent", {"type": "keyUp", **params})


def key_metadata(value: str) -> tuple[str, str, int]:
    lowered = value.lower()
    named = {
        "enter": ("Enter", "Enter", 13),
        "tab": ("Tab", "Tab", 9),
        "escape": ("Escape", "Escape", 27),
        "esc": ("Escape", "Escape", 27),
        "backspace": ("Backspace", "Backspace", 8),
        "delete": ("Delete", "Delete", 46),
        "arrowdown": ("ArrowDown", "ArrowDown", 40),
        "arrowup": ("ArrowUp", "ArrowUp", 38),
        "arrowleft": ("ArrowLeft", "ArrowLeft", 37),
        "arrowright": ("ArrowRight", "ArrowRight", 39),
    }
    if lowered in named:
        return named[lowered]
    if len(value) == 1:
        upper = value.upper()
        return value, f"Key{upper}", ord(upper)
    return value, value, 0


def scroll_action(cdp: CdpClient, action: dict[str, Any]) -> None:
    delta_x = float(action.get("deltaX") or action.get("x") or 0)
    delta_y = float(action.get("deltaY") or action.get("y") or 600)
    cdp.command(
        "Input.dispatchMouseEvent",
        {"type": "mouseWheel", "x": 600, "y": 400, "deltaX": delta_x, "deltaY": delta_y},
    )


def wait_for_selector(cdp: CdpClient, selector: str, *, timeout_ms: int) -> None:
    deadline = time.monotonic() + max(1, min(timeout_ms, 30000)) / 1000
    while time.monotonic() < deadline:
        result = cdp.command(
            "Runtime.evaluate",
            {
                "expression": f"Boolean(document.querySelector({js_string(selector)}))",
                "returnByValue": True,
            },
        )
        if bool(result.get("result", {}).get("value")):
            return
        time.sleep(0.1)
    raise TimeoutError(f"Selector did not appear: {selector}")


def capture_screenshot(cdp: CdpClient) -> str:
    result = cdp.command("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
    return str(result.get("data") or "")


def stop_browser_process(browser: subprocess.Popen[str] | None) -> None:
    if browser is None:
        return
    if browser.poll() is None:
        browser.terminate()
        try:
            browser.wait(timeout=5)
        except subprocess.TimeoutExpired:
            browser.kill()
            try:
                browser.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


def cleanup_temp_dir(path: Path) -> None:
    for attempt in range(5):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == 4:
                shutil.rmtree(path, ignore_errors=True)
                return
            time.sleep(0.1 * (attempt + 1))


class Handler(BaseHTTPRequestHandler):
    edge_path: Path
    task_timeout: int

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json({"status": "ok", "edge": str(self.edge_path)})
            return
        self._json({"detail": "Not Found"}, status=404)

    def do_POST(self) -> None:
        if self.path != "/v1/predict":
            self._json({"detail": "Not Found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            if not isinstance(payload, dict):
                payload = {}
            result = run_browser_task(payload, edge=self.edge_path, timeout=self.task_timeout)
            self._json(result)
        except subprocess.TimeoutExpired:
            self._json({"status": "timeout", "summary": "Sandbox browser task timed out.", "steps": []}, status=408)
        except Exception as exc:
            self._json({"status": "failed", "summary": "Bridge request failed.", "error": f"{type(exc).__name__}: {exc}"}, status=500)

    def _json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    handler = type("ComputerUseBridgeHandler", (Handler,), {"edge_path": resolve_edge(), "task_timeout": args.timeout})
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Computer Use bridge listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
