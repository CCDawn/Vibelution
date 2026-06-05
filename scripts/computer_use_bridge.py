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
import subprocess
import tempfile
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_EDGE_CANDIDATES = (
    Path(os.environ.get("ProgramFiles", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    Path(os.environ.get("LocalAppData", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
)


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


def run_browser_task(payload: dict[str, Any], *, edge: Path, timeout: int) -> dict[str, Any]:
    task = str(payload.get("task") or "").strip()
    target_url = str(payload.get("target_url") or payload.get("targetUrl") or "").strip()
    allowed_domains = normalize_domains(payload.get("allowed_domains") or payload.get("allowedDomains"))
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

    with tempfile.TemporaryDirectory(prefix="vibelution-cu-") as tmp:
        screenshot_path = Path(tmp) / "screenshot.png"
        profile_dir = Path(tmp) / "profile"
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
