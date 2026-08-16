#!/usr/bin/env python3
"""Probe browser user-action telemetry acceptance and runtime-scene persistence."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vibelution_storage import resolve_project_logs_home  # noqa: E402

DEFAULT_EVENT_CODES = (
    "browser.user_action.session_create_started",
    "browser.user_action.session_create_succeeded",
    "browser.user_action.session_delete_started",
    "browser.user_action.session_delete_succeeded",
)


def _request_json(
    method: str,
    base_url: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=payload,
        method=method.upper(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}


def _wait_for_health(base_url: str, *, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    last_error = ""
    while time.time() < deadline:
        try:
            _request_json("GET", base_url, "/api/health")
            return
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            time.sleep(0.5)
    raise RuntimeError(f"Backend health check failed: {last_error}")


def _find_scene_dir(project_root: Path) -> Path | None:
    logs_home = resolve_project_logs_home(project_root)
    candidates = sorted(
        (logs_home / "runtime_scenes").glob("*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "events" / "browser_page.jsonl").exists():
            return candidate
    return None


def _scan_scene_for_codes(scene_dir: Path, event_codes: tuple[str, ...]) -> dict[str, bool]:
    browser_events_path = scene_dir / "events" / "browser_page.jsonl"
    found = {code: False for code in event_codes}
    if not browser_events_path.exists():
        return found
    for line in browser_events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_code = str(payload.get("event_code") or payload.get("eventCode") or "").strip()
        if event_code in found:
            found[event_code] = True
    return found


def _post_probe_user_actions(base_url: str, *, client_operation_id: str) -> list[dict[str, Any]]:
    events = [
        {
            "phase": "user_action",
            "eventCode": "browser.user_action.session_create_started",
            "message": "User action started",
            "level": "info",
            "fields": {
                "action": "session_create",
                "outcome": "started",
                "clientOperationId": client_operation_id,
                "agentId": "probe-agent",
            },
        },
        {
            "phase": "user_action",
            "eventCode": "browser.user_action.session_create_succeeded",
            "message": "User action succeeded",
            "level": "info",
            "fields": {
                "action": "session_create",
                "outcome": "succeeded",
                "clientOperationId": client_operation_id,
                "sessionId": "probe-session",
                "durationMs": 42,
            },
        },
        {
            "phase": "user_action",
            "eventCode": "browser.user_action.session_delete_started",
            "message": "User action started",
            "level": "info",
            "fields": {
                "action": "session_delete",
                "outcome": "started",
                "clientOperationId": client_operation_id,
                "sessionId": "probe-session",
            },
        },
        {
            "phase": "user_action",
            "eventCode": "browser.user_action.session_delete_succeeded",
            "message": "User action succeeded",
            "level": "info",
            "fields": {
                "action": "session_delete",
                "outcome": "succeeded",
                "clientOperationId": client_operation_id,
                "sessionId": "probe-session",
                "durationMs": 120,
                "nextActiveSessionId": "probe-next-session",
                "routeReplaced": True,
            },
        },
    ]
    results: list[dict[str, Any]] = []
    for event in events:
        result = _request_json("POST", base_url, "/api/runtime/browser-telemetry", event)
        results.append(result)
    return results


def run_probe(
    *,
    base_url: str,
    project_root: Path,
    health_timeout_s: float = 20.0,
    settle_s: float = 0.4,
) -> dict[str, Any]:
    _wait_for_health(base_url, timeout_s=health_timeout_s)
    client_operation_id = f"probe-user-action-{int(time.time() * 1000)}"
    post_results = _post_probe_user_actions(base_url, client_operation_id=client_operation_id)
    time.sleep(settle_s)
    scene_dir = _find_scene_dir(project_root)
    if scene_dir is None:
        raise RuntimeError("No runtime scene directory found after posting telemetry")
    found = _scan_scene_for_codes(scene_dir, DEFAULT_EVENT_CODES)
    missing = [code for code, present in found.items() if not present]
    if missing:
        raise RuntimeError(f"Missing browser user-action events in scene: {', '.join(missing)}")
    return {
        "accepted": all(bool(item.get("accepted", True)) for item in post_results),
        "clientOperationId": client_operation_id,
        "sceneDir": str(scene_dir),
        "eventCodes": list(DEFAULT_EVENT_CODES),
        "postResults": post_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--project-root", default=str(REPO_ROOT))
    parser.add_argument("--health-timeout-s", type=float, default=20.0)
    parser.add_argument("--settle-s", type=float, default=0.4)
    args = parser.parse_args(argv)
    report = run_probe(
        base_url=args.base_url,
        project_root=Path(args.project_root).resolve(),
        health_timeout_s=args.health_timeout_s,
        settle_s=args.settle_s,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc
