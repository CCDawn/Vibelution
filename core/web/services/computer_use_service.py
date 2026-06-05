# -*- coding: utf-8 -*-
"""Controlled Computer Use service for sandbox browser automation."""

from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SESSION_ROOT = PROJECT_ROOT / "workspace" / "computer_use_sessions"
ALLOWED_STATUSES = {"completed", "running", "need_confirmation", "blocked", "failed", "timeout", "cancelled"}
HIGH_RISK_ACTIONS = {"submit", "send", "delete", "pay", "purchase", "download", "upload", "login", "confirm"}
MAX_STEPS_LIMIT = 30
MAX_TIMEOUT_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 180
_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9_.-]+")


class ComputerUseError(ValueError):
    """Raised when a Computer Use request is invalid or cannot be served."""


def start_computer_use_task(
    *,
    task: str,
    target_url: str = "",
    allowed_domains: str | list[str] = "",
    max_steps: int = 20,
    require_confirmation: bool = True,
    mode: str = "browser",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Create a sandbox task and run one bounded Open Computer Use request."""

    started = time.perf_counter()
    normalized = _normalize_request(
        task=task,
        target_url=target_url,
        allowed_domains=allowed_domains,
        max_steps=max_steps,
        require_confirmation=require_confirmation,
        mode=mode,
        timeout_seconds=timeout_seconds,
    )
    session_id = _new_session_id()
    session_dir = _session_dir(session_id)
    (session_dir / "screenshots").mkdir(parents=True, exist_ok=True)

    if not _computer_use_enabled():
        payload = _initial_session_payload(session_id, normalized, status="blocked")
        payload.update(
            {
                "summary": "Computer Use is disabled. Set VIBELUTION_COMPUTER_USE_ENABLED=1 to enable sandbox automation.",
                "error": "COMPUTER_USE_DISABLED",
                "durationMs": _duration_ms(started),
            }
        )
        _save_session(payload)
        _append_step(session_id, {"type": "policy", "summary": payload["summary"], "status": "blocked"})
        _record_event("computer_use.task.blocked", payload, outcome="blocked", level="warning")
        return _public_payload(payload)

    payload = _initial_session_payload(session_id, normalized, status="running")
    _save_session(payload)
    _append_step(session_id, {"type": "start", "summary": "Computer Use sandbox task started.", "status": "running"})
    _record_event("computer_use.task.started", payload, outcome="started")

    try:
        provider_payload = _call_open_computer_use(normalized, session_id=session_id)
        result = _normalize_provider_result(provider_payload, session_id=session_id, require_confirmation=require_confirmation)
        payload.update(result)
    except TimeoutError as exc:
        payload.update({"status": "timeout", "summary": "Computer Use task timed out.", "error": str(exc)})
    except Exception as exc:
        payload.update({"status": "failed", "summary": "Computer Use task failed.", "error": f"{type(exc).__name__}: {exc}"})

    payload["durationMs"] = _duration_ms(started)
    _save_session(payload)
    event_code = {
        "completed": "computer_use.task.completed",
        "need_confirmation": "computer_use.task.confirmation_required",
        "blocked": "computer_use.task.blocked",
        "timeout": "computer_use.task.timeout",
        "cancelled": "computer_use.task.cancelled",
    }.get(str(payload.get("status") or ""), "computer_use.task.failed")
    _record_event(
        event_code,
        payload,
        outcome=str(payload.get("status") or "failed"),
        level="warning" if payload.get("status") in {"need_confirmation", "blocked"} else "info",
    )
    return _public_payload(payload)


def get_computer_use_session(session_id: str) -> dict[str, Any]:
    payload = _load_session(_normalize_session_id(session_id))
    return _public_payload(payload)


def confirm_computer_use_session(session_id: str, confirmation: str = "approved") -> dict[str, Any]:
    normalized_id = _normalize_session_id(session_id)
    payload = _load_session(normalized_id)
    if str(payload.get("status") or "") != "need_confirmation":
        raise ComputerUseError("Only sessions waiting for confirmation can be confirmed.")
    payload["status"] = "completed"
    payload["needsConfirmation"] = False
    payload["confirmation"] = str(confirmation or "approved").strip() or "approved"
    payload["summary"] = "Computer Use task confirmed by user."
    payload["updatedAt"] = _now()
    _append_step(normalized_id, {"type": "confirmation", "summary": payload["summary"], "status": "completed"})
    _save_session(payload)
    _record_event("computer_use.task.confirmed", payload, outcome="confirmed")
    return _public_payload(payload)


def cancel_computer_use_session(session_id: str, reason: str = "cancelled_by_user") -> dict[str, Any]:
    normalized_id = _normalize_session_id(session_id)
    payload = _load_session(normalized_id)
    if str(payload.get("status") or "") in {"completed", "cancelled"}:
        return _public_payload(payload)
    payload["status"] = "cancelled"
    payload["needsConfirmation"] = False
    payload["summary"] = "Computer Use task cancelled."
    payload["error"] = str(reason or "cancelled_by_user").strip() or "cancelled_by_user"
    payload["updatedAt"] = _now()
    _append_step(normalized_id, {"type": "cancel", "summary": payload["summary"], "status": "cancelled"})
    _save_session(payload)
    _record_event("computer_use.task.cancelled", payload, outcome="cancelled", level="warning")
    return _public_payload(payload)


def computer_use_screenshot_path(session_id: str, image_id: str) -> Path:
    normalized_id = _normalize_session_id(session_id)
    safe_image_id = _safe_file_token(image_id)
    if not safe_image_id:
        raise FileNotFoundError("Screenshot not found.")
    path = (_session_dir(normalized_id) / "screenshots" / safe_image_id).resolve()
    root = (_session_dir(normalized_id) / "screenshots").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise FileNotFoundError("Screenshot not found.") from exc
    if not path.exists() or not path.is_file():
        raise FileNotFoundError("Screenshot not found.")
    return path


def _normalize_request(**kwargs: Any) -> dict[str, Any]:
    task = str(kwargs.get("task") or "").strip()
    if not task:
        raise ComputerUseError("task is required.")
    mode = str(kwargs.get("mode") or "browser").strip().lower() or "browser"
    if mode != "browser":
        raise ComputerUseError("v1 only supports browser mode; desktop mode is reserved for a later release.")
    target_url = str(kwargs.get("target_url") or "").strip()
    if target_url and not _is_http_url(target_url):
        raise ComputerUseError("target_url must start with http:// or https://.")
    domains = _normalize_allowed_domains(kwargs.get("allowed_domains"))
    if target_url:
        host = str(urlparse(target_url).hostname or "").lower()
        if host and host not in domains:
            domains.append(host)
    if not domains:
        raise ComputerUseError("allowed_domains is required unless target_url contains a host.")
    max_steps = _bounded_int(kwargs.get("max_steps"), default=20, minimum=1, maximum=MAX_STEPS_LIMIT)
    timeout_seconds = _bounded_int(
        kwargs.get("timeout_seconds"),
        default=DEFAULT_TIMEOUT_SECONDS,
        minimum=1,
        maximum=MAX_TIMEOUT_SECONDS,
    )
    return {
        "task": task,
        "targetUrl": target_url,
        "allowedDomains": domains,
        "maxSteps": max_steps,
        "requireConfirmation": bool(kwargs.get("require_confirmation", True)),
        "mode": mode,
        "timeoutSeconds": timeout_seconds,
    }


def _call_open_computer_use(request: dict[str, Any], *, session_id: str) -> dict[str, Any]:
    base_url = str(os.environ.get("VIBELUTION_COMPUTER_USE_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        raise ComputerUseError("VIBELUTION_COMPUTER_USE_BASE_URL is not configured.")
    try:
        import requests
    except Exception as exc:  # pragma: no cover - environment dependent
        raise ComputerUseError("requests is required to call Open Computer Use.") from exc

    endpoint = f"{base_url}/v1/predict"
    headers = {"Content-Type": "application/json"}
    api_key = str(os.environ.get("VIBELUTION_COMPUTER_USE_API_KEY") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key
    response = requests.post(
        endpoint,
        headers=headers,
        json={
            "task": request["task"],
            "target_url": request["targetUrl"],
            "allowed_domains": request["allowedDomains"],
            "mode": request["mode"],
            "max_steps": request["maxSteps"],
            "require_confirmation": request["requireConfirmation"],
            "session_id": session_id,
        },
        timeout=int(request["timeoutSeconds"]),
    )
    if response.status_code == 408:
        raise TimeoutError("Open Computer Use provider returned timeout.")
    if response.status_code >= 400:
        raise ComputerUseError(f"Open Computer Use provider returned {response.status_code}: {response.text[:500]}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ComputerUseError("Open Computer Use provider response was not JSON.") from exc
    return payload if isinstance(payload, dict) else {}


def _normalize_provider_result(payload: dict[str, Any], *, session_id: str, require_confirmation: bool) -> dict[str, Any]:
    raw_status = str(payload.get("status") or payload.get("state") or "completed").strip().lower()
    status = raw_status if raw_status in ALLOWED_STATUSES else "completed"
    summary = str(payload.get("summary") or payload.get("message") or "").strip()
    steps = _normalize_steps(payload.get("steps") or payload.get("actions") or [])
    for step in steps:
        _append_step(session_id, step)
        _record_event("computer_use.task.step_observed", {"sessionId": session_id, **step}, outcome=str(step.get("status") or "observed"))
    high_risk = _contains_high_risk_step(steps)
    if require_confirmation and (high_risk or bool(payload.get("needs_confirmation") or payload.get("needsConfirmation"))):
        status = "need_confirmation"
    image_id, screenshot_url = _store_provider_screenshot(session_id, payload)
    return {
        "status": status,
        "summary": summary or _default_summary(status),
        "steps": steps,
        "screenshotId": image_id,
        "screenshotUrl": screenshot_url,
        "needsConfirmation": status == "need_confirmation",
        "error": str(payload.get("error") or "").strip(),
        "updatedAt": _now(),
    }


def _normalize_steps(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    steps: list[dict[str, Any]] = []
    for index, item in enumerate(rows[:MAX_STEPS_LIMIT], start=1):
        raw = item if isinstance(item, dict) else {"summary": str(item)}
        action = str(raw.get("action") or raw.get("type") or "").strip().lower()
        steps.append(
            {
                "index": int(raw.get("index") or index),
                "action": action,
                "summary": str(raw.get("summary") or raw.get("message") or action or f"Step {index}").strip(),
                "status": str(raw.get("status") or "observed").strip().lower() or "observed",
                "requiresConfirmation": bool(raw.get("requiresConfirmation") or raw.get("requires_confirmation")),
            }
        )
    return steps


def _store_provider_screenshot(session_id: str, payload: dict[str, Any]) -> tuple[str, str]:
    image_b64 = str(payload.get("screenshot_b64") or payload.get("screenshotBase64") or "").strip()
    image_url = str(payload.get("screenshot_url") or payload.get("screenshotUrl") or "").strip()
    if image_url and not image_b64:
        return "", image_url
    if not image_b64:
        return "", ""
    if "," in image_b64 and image_b64.lower().startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(image_b64, validate=True)
    except Exception:
        return "", ""
    if not image_bytes:
        return "", ""
    image_id = f"screenshot-{uuid.uuid4().hex[:12]}.png"
    path = _session_dir(session_id) / "screenshots" / image_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)
    return image_id, f"/api/computer-use/sessions/{session_id}/screenshots/{image_id}"


def _initial_session_payload(session_id: str, request: dict[str, Any], *, status: str) -> dict[str, Any]:
    now = _now()
    return {
        "schemaVersion": 1,
        "sessionId": session_id,
        "status": status,
        "task": request["task"],
        "targetUrl": request["targetUrl"],
        "allowedDomains": request["allowedDomains"],
        "mode": request["mode"],
        "maxSteps": request["maxSteps"],
        "timeoutSeconds": request["timeoutSeconds"],
        "requireConfirmation": request["requireConfirmation"],
        "needsConfirmation": False,
        "summary": "",
        "steps": [],
        "screenshotId": "",
        "screenshotUrl": "",
        "error": "",
        "createdAt": now,
        "updatedAt": now,
        "durationMs": 0,
    }


def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    session_id = str(payload.get("sessionId") or "").strip()
    steps = list(payload.get("steps") or [])
    if not steps and session_id:
        steps = _load_steps(session_id)
    return {
        "status": str(payload.get("status") or "failed"),
        "sessionId": session_id,
        "summary": str(payload.get("summary") or ""),
        "steps": steps,
        "screenshotUrl": str(payload.get("screenshotUrl") or ""),
        "needsConfirmation": bool(payload.get("needsConfirmation")),
        "error": str(payload.get("error") or ""),
        "mode": str(payload.get("mode") or "browser"),
        "targetUrl": str(payload.get("targetUrl") or ""),
        "allowedDomains": list(payload.get("allowedDomains") or []),
        "createdAt": str(payload.get("createdAt") or ""),
        "updatedAt": str(payload.get("updatedAt") or ""),
        "durationMs": int(payload.get("durationMs") or 0),
    }


def _save_session(payload: dict[str, Any]) -> None:
    session_id = _normalize_session_id(payload.get("sessionId"))
    path = _session_dir(session_id) / "session.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_session(session_id: str) -> dict[str, Any]:
    path = _session_dir(session_id) / "session.json"
    if not path.exists():
        raise FileNotFoundError(f"Computer Use session not found: {session_id}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _append_step(session_id: str, step: dict[str, Any]) -> None:
    payload = {**step, "recordedAt": _now()}
    path = _session_dir(session_id) / "steps.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _load_steps(session_id: str) -> list[dict[str, Any]]:
    path = _session_dir(session_id) / "steps.jsonl"
    if not path.exists():
        return []
    steps = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            steps.append(payload)
    return steps


def _record_event(event_code: str, payload: dict[str, Any], *, outcome: str = "observed", level: str = "info") -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "computer_use",
            "task",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={
                "sessionId": str(payload.get("sessionId") or ""),
                "status": str(payload.get("status") or ""),
                "mode": str(payload.get("mode") or ""),
                "targetUrl": str(payload.get("targetUrl") or ""),
                "allowedDomains": list(payload.get("allowedDomains") or []),
                "stepIndex": payload.get("index"),
                "action": str(payload.get("action") or ""),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _computer_use_enabled() -> bool:
    return str(os.environ.get("VIBELUTION_COMPUTER_USE_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_allowed_domains(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[,;\s]+", str(value or ""))
    domains: list[str] = []
    for item in raw_items:
        domain = str(item or "").strip().lower()
        if not domain:
            continue
        if "://" in domain:
            domain = str(urlparse(domain).hostname or "").lower()
        domain = domain.strip("/")
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


def _contains_high_risk_step(steps: list[dict[str, Any]]) -> bool:
    for step in steps:
        if step.get("requiresConfirmation"):
            return True
        action = str(step.get("action") or "").lower()
        summary = str(step.get("summary") or "").lower()
        if any(token in action or token in summary for token in HIGH_RISK_ACTIONS):
            return True
    return False


def _default_summary(status: str) -> str:
    if status == "need_confirmation":
        return "Computer Use task is waiting for user confirmation."
    if status == "completed":
        return "Computer Use task completed."
    return f"Computer Use task status: {status}."


def _session_dir(session_id: str) -> Path:
    return SESSION_ROOT / _normalize_session_id(session_id)


def _normalize_session_id(value: Any) -> str:
    token = _safe_file_token(value)
    if not token:
        raise ComputerUseError("session_id is required.")
    return token


def _safe_file_token(value: Any) -> str:
    return _SAFE_TOKEN.sub("-", str(value or "").strip()).strip(".-_")[:120]


def _new_session_id() -> str:
    return f"cu-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:10]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
