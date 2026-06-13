# -*- coding: utf-8 -*-
"""Controlled Computer Use service for sandbox browser automation."""

from __future__ import annotations

import base64
import contextlib
import ipaddress
import json
import os
import re
import shlex
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
SUPPORTED_BROWSER_ACTIONS = {
    "click",
    "type",
    "fill",
    "press",
    "scroll",
    "wait",
    "navigate",
    "screenshot",
    "wait_for_selector",
}
ACTION_ALIASES = {
    "goto": "navigate",
    "open": "navigate",
    "sleep": "wait",
    "input": "type",
}
MAX_STEPS_LIMIT = 30
MAX_TIMEOUT_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 180
RESUMING_STALE_SECONDS = 300
MAX_ACTION_TEXT_CHARS = 2000
BRIDGE_TOKEN_HEADER = "X-Vibelution-Computer-Use-Token"
BRIDGE_TOKEN_PATH = PROJECT_ROOT / ".runtime" / "computer-use" / "bridge.token"
_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9_.-]+")


class ComputerUseError(ValueError):
    """Raised when a Computer Use request is invalid or cannot be served."""


def start_computer_use_task(
    *,
    task: str,
    target_url: str = "",
    allowed_domains: str | list[str] = "",
    actions: str | list[Any] | dict[str, Any] = "",
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
        actions=actions,
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

    if _contains_high_risk_step(normalized.get("actions") or []):
        ready_step = {
            "index": 1,
            "action": "confirmation",
            "summary": "Explicit high-risk browser action requires user confirmation before provider execution.",
            "status": "ready",
            "requiresConfirmation": True,
        }
        payload.update(
            {
                "status": "need_confirmation",
                "summary": "Computer Use task is waiting for user confirmation before executing a high-risk action.",
                "steps": [ready_step],
                "needsConfirmation": True,
                "pendingExecution": _pending_execution_payload(normalized, reason="explicit_high_risk_action"),
                "updatedAt": _now(),
                "durationMs": _duration_ms(started),
            }
        )
        _append_step(session_id, ready_step)
        _save_session(payload)
        _record_event("computer_use.task.confirmation_required", payload, outcome="confirmation_required", level="warning")
        return _public_payload(payload)

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
    if str(payload.get("status") or "") == "resuming":
        if not _resuming_is_stale(payload):
            raise ComputerUseError("Computer Use session is already resuming after confirmation.")
        payload["status"] = "need_confirmation"
        payload["needsConfirmation"] = True
        payload.pop("resumingStartedAt", None)
        _save_session(payload)
        _release_session_lock(normalized_id)
    if str(payload.get("status") or "") != "need_confirmation":
        raise ComputerUseError("Only sessions waiting for confirmation can be confirmed.")
    confirmation_text = str(confirmation or "approved").strip() or "approved"
    pending_request = _pending_request_for_resume(payload)
    if pending_request:
        lock_acquired = False
        try:
            _acquire_session_lock(normalized_id)
            lock_acquired = True
            started = time.perf_counter()
            confirmation_step = {
                "action": "confirmation",
                "summary": "Computer Use task confirmed by user; resuming pending browser actions.",
                "status": "completed",
            }
            payload.update(
                {
                    "status": "running",
                    "needsConfirmation": False,
                    "confirmation": confirmation_text,
                    "summary": "Computer Use task confirmed by user; resuming pending browser actions.",
                    "resumingStartedAt": _now(),
                    "updatedAt": _now(),
                }
            )
            payload["steps"] = list(payload.get("steps") or []) + [confirmation_step]
            _append_step(normalized_id, confirmation_step)
            payload["status"] = "resuming"
            _save_session(payload)
            _record_event("computer_use.task.confirmed", payload, outcome="confirmed")
            payload["status"] = "running"
            payload.pop("pendingExecution", None)
            try:
                provider_payload = _call_open_computer_use(
                    _request_with_confirmation(pending_request, confirmation_text),
                    session_id=normalized_id,
                )
                result = _normalize_provider_result(provider_payload, session_id=normalized_id, require_confirmation=False)
                combined_steps = list(payload.get("steps") or []) + list(result.get("steps") or [])
                payload.update(result)
                payload["steps"] = _reindex_steps(combined_steps)
            except TimeoutError as exc:
                payload.update({"status": "timeout", "summary": "Computer Use task timed out after confirmation.", "error": str(exc)})
            except Exception as exc:
                payload.update(
                    {
                        "status": "failed",
                        "summary": "Computer Use task failed after confirmation.",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            if str(payload.get("status") or "") != "need_confirmation" or not isinstance(payload.get("pendingExecution"), dict):
                payload.pop("pendingExecution", None)
            payload["needsConfirmation"] = str(payload.get("status") or "") == "need_confirmation"
            payload["durationMs"] = _duration_ms(started)
            payload["updatedAt"] = _now()
            payload.pop("resumingStartedAt", None)
            _save_session(payload)
            event_code = {
                "completed": "computer_use.task.confirmed_resumed",
                "need_confirmation": "computer_use.task.confirmation_required",
                "blocked": "computer_use.task.blocked",
                "timeout": "computer_use.task.timeout",
                "cancelled": "computer_use.task.cancelled",
            }.get(str(payload.get("status") or ""), "computer_use.task.failed")
            _record_event(
                event_code,
                payload,
                outcome=str(payload.get("status") or "failed"),
                level="warning" if payload.get("status") in {"need_confirmation", "blocked", "timeout", "failed"} else "info",
            )
            return _public_payload(payload)
        finally:
            if lock_acquired:
                _release_session_lock(normalized_id)

    payload["status"] = "blocked"
    payload["needsConfirmation"] = False
    payload["confirmation"] = confirmation_text
    payload["summary"] = "Computer Use task cannot resume because the provider did not return continuation state."
    payload["error"] = "CONFIRMATION_CONTINUATION_MISSING"
    payload["updatedAt"] = _now()
    payload.pop("pendingExecution", None)
    payload.pop("resumingStartedAt", None)
    _append_step(normalized_id, {"type": "confirmation", "summary": payload["summary"], "status": "blocked"})
    _save_session(payload)
    _record_event("computer_use.task.blocked", payload, outcome="confirmation_continuation_missing", level="warning")
    raise ComputerUseError(payload["summary"])


def cancel_computer_use_session(session_id: str, reason: str = "cancelled_by_user") -> dict[str, Any]:
    normalized_id = _normalize_session_id(session_id)
    payload = _load_session(normalized_id)
    if str(payload.get("status") or "") in {"completed", "cancelled"}:
        return _public_payload(payload)
    payload["status"] = "cancelled"
    payload["needsConfirmation"] = False
    payload.pop("pendingExecution", None)
    payload.pop("resumingStartedAt", None)
    _release_session_lock(normalized_id)
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
    if target_url and not _is_public_internet_url(target_url):
        raise ComputerUseError("target_url must use a public internet host; local, private, link-local, and metadata hosts are blocked.")
    domains = _normalize_allowed_domains(kwargs.get("allowed_domains"))
    if target_url:
        host = str(urlparse(target_url).hostname or "").lower()
        if host and host not in domains:
            domains.append(host)
    if not domains:
        raise ComputerUseError("allowed_domains is required unless target_url contains a host.")
    _validate_allowed_domains_public(domains)
    max_steps = _bounded_int(kwargs.get("max_steps"), default=20, minimum=1, maximum=MAX_STEPS_LIMIT)
    actions = _normalize_actions(kwargs.get("actions"), max_steps=max_steps)
    _validate_action_domains(actions, domains)
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
        "actions": actions,
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
    bridge_token = _bridge_token_for_base_url(base_url)
    if bridge_token:
        headers[BRIDGE_TOKEN_HEADER] = bridge_token
    response = requests.post(
        endpoint,
        headers=headers,
        json={
            "task": request["task"],
            "target_url": request["targetUrl"],
            "allowed_domains": request["allowedDomains"],
            "actions": request["actions"],
            "mode": request["mode"],
            "max_steps": request["maxSteps"],
            "require_confirmation": request["requireConfirmation"],
            "session_id": session_id,
            **_provider_resume_fields(request),
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
    high_risk = _contains_unconfirmed_high_risk_step(steps)
    if high_risk or bool(payload.get("needs_confirmation") or payload.get("needsConfirmation")):
        status = "need_confirmation"
    image_id, screenshot_url = _store_provider_screenshot(session_id, payload)
    result = {
        "status": status,
        "summary": summary or _default_summary(status),
        "steps": steps,
        "screenshotId": image_id,
        "screenshotUrl": screenshot_url,
        "needsConfirmation": status == "need_confirmation",
        "error": str(payload.get("error") or "").strip(),
        "updatedAt": _now(),
    }
    pending = _provider_pending_execution_payload(payload, status=status)
    if pending:
        result["pendingExecution"] = pending
    return result


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
        "actionCount": len(request.get("actions") or []),
        "requestedActions": [_public_action_summary(action, index=index) for index, action in enumerate(request.get("actions") or [], start=1)],
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


def _pending_execution_payload(request: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "kind": "explicit_actions",
        "reason": reason,
        "createdAt": _now(),
        "request": {
            "task": request["task"],
            "targetUrl": request["targetUrl"],
            "allowedDomains": list(request.get("allowedDomains") or []),
            "actions": list(request.get("actions") or []),
            "maxSteps": request["maxSteps"],
            "requireConfirmation": request["requireConfirmation"],
            "mode": request["mode"],
            "timeoutSeconds": request["timeoutSeconds"],
        },
    }


def _provider_pending_execution_payload(payload: dict[str, Any], *, status: str) -> dict[str, Any]:
    if status != "need_confirmation":
        return {}
    continuation = _coerce_provider_continuation(payload)
    if not continuation:
        return {}
    return {
        "kind": "provider_confirmation",
        "reason": "provider_confirmation_required",
        "createdAt": _now(),
        "continuation": continuation,
    }


def _pending_request_for_resume(payload: dict[str, Any]) -> dict[str, Any]:
    pending = payload.get("pendingExecution")
    if not isinstance(pending, dict):
        return {}
    kind = str(pending.get("kind") or "")
    if kind == "explicit_actions":
        request = pending.get("request")
        if not isinstance(request, dict):
            return {}
        return _normalize_request(
            task=request.get("task"),
            target_url=request.get("targetUrl"),
            allowed_domains=request.get("allowedDomains"),
            actions=request.get("actions"),
            max_steps=request.get("maxSteps"),
            require_confirmation=False,
            mode=request.get("mode"),
            timeout_seconds=request.get("timeoutSeconds"),
        )
    if kind == "provider_confirmation":
        continuation = pending.get("continuation")
        if not isinstance(continuation, dict):
            return {}
        request = _normalize_request(
            task=payload.get("task"),
            target_url=payload.get("targetUrl"),
            allowed_domains=payload.get("allowedDomains"),
            actions=[],
            max_steps=payload.get("maxSteps"),
            require_confirmation=False,
            mode=payload.get("mode"),
            timeout_seconds=payload.get("timeoutSeconds"),
        )
        request["providerContinuation"] = continuation
        return request
    return {}


def _coerce_provider_continuation(payload: dict[str, Any]) -> dict[str, Any]:
    continuation: dict[str, Any] = {}
    for source_key, target_key in (
        ("continuation_token", "continuationToken"),
        ("continuationToken", "continuationToken"),
        ("confirmation_token", "confirmationToken"),
        ("confirmationToken", "confirmationToken"),
        ("provider_state", "providerState"),
        ("providerState", "providerState"),
        ("resume_payload", "resumePayload"),
        ("resumePayload", "resumePayload"),
    ):
        if source_key not in payload:
            continue
        value = payload.get(source_key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            continuation[target_key] = value
        elif isinstance(value, (dict, list)):
            continuation[target_key] = value
    return continuation


def _provider_resume_fields(request: dict[str, Any]) -> dict[str, Any]:
    continuation = request.get("providerContinuation")
    if not isinstance(continuation, dict) or not continuation:
        return {}
    fields: dict[str, Any] = {
        "confirmed": True,
        "confirmation": str(request.get("confirmation") or "approved"),
        "provider_continuation": continuation,
    }
    for source, target in (
        ("continuationToken", "continuation_token"),
        ("confirmationToken", "confirmation_token"),
        ("providerState", "provider_state"),
        ("resumePayload", "resume_payload"),
    ):
        if source in continuation:
            fields[target] = continuation[source]
    return fields


def _request_with_confirmation(request: dict[str, Any], confirmation: str) -> dict[str, Any]:
    if not request:
        return {}
    return {**request, "confirmation": str(confirmation or "approved").strip() or "approved"}


def _reindex_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**step, "index": index} for index, step in enumerate(steps, start=1)]


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
        "targetUrl": _safe_url_summary(str(payload.get("targetUrl") or "")),
        "allowedDomains": list(payload.get("allowedDomains") or []),
        "actionCount": int(payload.get("actionCount") or 0),
        "requestedActions": list(payload.get("requestedActions") or []),
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
                "targetUrl": _safe_url_summary(str(payload.get("targetUrl") or "")),
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
        domain = _normalize_host_token(str(item or ""))
        if not domain:
            continue
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def _validate_allowed_domains_public(domains: list[str]) -> None:
    if any(not _is_public_internet_host(domain) for domain in domains):
        raise ComputerUseError("allowed_domains must contain public internet hosts only.")


def _normalize_actions(value: Any, *, max_steps: int) -> list[dict[str, Any]]:
    parsed = _coerce_actions_input(value)
    actions: list[dict[str, Any]] = []
    for index, raw in enumerate(parsed[:max_steps], start=1):
        action = _normalize_action(raw, index=index)
        if action:
            actions.append(action)
    return actions


def _coerce_actions_input(value: Any) -> list[Any]:
    if value in (None, "", []):
        return []
    if isinstance(value, dict):
        nested = value.get("actions")
        if isinstance(nested, list):
            return nested
        return [value]
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [_parse_action_dsl_line(line) for line in re.split(r"[\r\n;]+", stripped) if line.strip()]
        if isinstance(parsed, dict):
            nested = parsed.get("actions")
            return list(nested) if isinstance(nested, list) else [parsed]
        if isinstance(parsed, list):
            return parsed
    raise ComputerUseError("actions must be a JSON list/object, a list, or a short action DSL string.")


def _parse_action_dsl_line(line: str) -> dict[str, Any]:
    try:
        parts = shlex.split(line)
    except ValueError as exc:
        raise ComputerUseError(f"Invalid action DSL: {line[:80]}") from exc
    if not parts:
        return {}
    result: dict[str, Any] = {"action": parts[0]}
    positionals: list[str] = []
    for part in parts[1:]:
        if "=" in part:
            key, raw_value = part.split("=", 1)
            result[_camel_to_snake(key.strip())] = raw_value
        else:
            positionals.append(part)
    action = _normalize_action_name(parts[0])
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


def _normalize_action(raw: Any, *, index: int) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = _parse_action_dsl_line(raw)
    if not isinstance(raw, dict):
        raise ComputerUseError(f"Action {index} must be an object or DSL line.")
    action = _normalize_action_name(raw.get("action") or raw.get("type"))
    if not action:
        raise ComputerUseError(f"Action {index} is missing action.")
    if action not in SUPPORTED_BROWSER_ACTIONS:
        raise ComputerUseError(f"Unsupported browser action: {action}.")

    result: dict[str, Any] = {"action": action}
    selector = _trimmed(raw.get("selector") or raw.get("css") or raw.get("target"))
    text = _trimmed(raw.get("text") or raw.get("value"), limit=MAX_ACTION_TEXT_CHARS)
    url = _trimmed(raw.get("url") or raw.get("target_url") or raw.get("targetUrl"))
    key = _trimmed(raw.get("key"))
    if selector:
        result["selector"] = selector
    if text:
        result["text"] = text
    if url:
        if not _is_http_url(url):
            raise ComputerUseError(f"Action {index} url must start with http:// or https://.")
        result["url"] = url
    if key:
        result["key"] = key
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
            result[target] = _bounded_int(raw.get(source), default=0, minimum=-100000, maximum=100000)
    if raw.get("requiresConfirmation") or raw.get("requires_confirmation"):
        result["requiresConfirmation"] = True

    _validate_action_shape(result, index=index)
    return result


def _normalize_action_name(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    return ACTION_ALIASES.get(raw, raw)


def _validate_action_shape(action: dict[str, Any], *, index: int) -> None:
    name = str(action.get("action") or "")
    if name in {"click", "wait_for_selector"} and not action.get("selector") and not ("x" in action and "y" in action):
        raise ComputerUseError(f"Action {index} ({name}) requires selector or x/y coordinates.")
    if name in {"type", "fill"} and not action.get("text"):
        raise ComputerUseError(f"Action {index} ({name}) requires text.")
    if name == "press" and not action.get("key"):
        raise ComputerUseError(f"Action {index} (press) requires key.")
    if name == "navigate" and not action.get("url"):
        raise ComputerUseError(f"Action {index} (navigate) requires url.")


def _validate_action_domains(actions: list[dict[str, Any]], allowed_domains: list[str]) -> None:
    for index, action in enumerate(actions, start=1):
        if action.get("action") != "navigate":
            continue
        url = str(action.get("url") or "")
        if not _is_public_internet_url(url):
            raise ComputerUseError(f"Action {index} navigates outside public internet boundaries.")
        if not _is_allowed_action_url(url, allowed_domains):
            raise ComputerUseError(f"Action {index} navigates outside allowed_domains.")


def _is_allowed_action_url(url: str, allowed_domains: list[str]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    return parsed.hostname.lower() in set(allowed_domains)


def _public_action_summary(action: dict[str, Any], *, index: int) -> dict[str, Any]:
    name = str(action.get("action") or "")
    summary: dict[str, Any] = {"index": index, "action": name}
    if action.get("selector"):
        summary["selector"] = str(action.get("selector"))
    if action.get("url"):
        summary["url"] = _safe_url_summary(str(action.get("url")))
    if action.get("key"):
        summary["key"] = str(action.get("key"))
    if "text" in action:
        summary["textLength"] = len(str(action.get("text") or ""))
    for key in ("x", "y", "deltaX", "deltaY", "ms", "timeoutMs"):
        if key in action:
            summary[key] = action[key]
    if action.get("requiresConfirmation"):
        summary["requiresConfirmation"] = True
    return summary


def _safe_url_summary(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        return ""
    path = parsed.path or ""
    return f"{parsed.scheme}://{parsed.hostname}{path}"


def _trimmed(value: Any, *, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)([A-Z])", r"_\1", value).lower()


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def _bridge_token_for_base_url(base_url: str) -> str:
    if not _is_loopback_url(base_url):
        return ""
    token = str(os.environ.get("VIBELUTION_COMPUTER_USE_BRIDGE_TOKEN") or "").strip()
    if token:
        return token
    try:
        return BRIDGE_TOKEN_PATH.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""


def _is_loopback_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    return _is_loopback_host(parsed.hostname)


def _is_loopback_host(hostname: str) -> bool:
    host = _normalize_host_token(hostname)
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_public_internet_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    return _is_public_internet_host(parsed.hostname)


def _is_public_internet_host(hostname: str) -> bool:
    host = _normalize_host_token(hostname)
    if not host:
        return False
    if any(char.isspace() for char in host) or any(char in host for char in "*/\\"):
        return False
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        return False
    if host == "metadata.google.internal":
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )
    labels = host.split(".")
    if len(labels) < 2 or all(label.isdigit() for label in labels):
        return False
    hostname_label = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    return all(bool(hostname_label.match(label)) for label in labels)


def _normalize_host_token(value: str) -> str:
    raw = str(value or "").strip().lower().strip("/")
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else f"//{raw}")
        host = parsed.hostname or raw
    except ValueError:
        host = raw
    return str(host or "").strip().strip("[]").lower().rstrip(".")


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
        haystack = " ".join(
            str(step.get(key) or "").lower()
            for key in ("action", "summary", "selector", "url", "key")
        )
        if any(token in haystack for token in HIGH_RISK_ACTIONS):
            return True
    return False


def _contains_unconfirmed_high_risk_step(steps: list[dict[str, Any]]) -> bool:
    for step in steps:
        if step.get("requiresConfirmation"):
            return True
        status = str(step.get("status") or "").strip().lower()
        if status in {"completed", "done", "success", "succeeded"}:
            continue
        if _contains_high_risk_step([step]):
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


def _session_lock_path(session_id: str) -> Path:
    return _session_dir(session_id) / "confirm.lock"


def _acquire_session_lock(session_id: str) -> bool:
    path = _session_lock_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(_now())
    except FileExistsError as exc:
        raise ComputerUseError("Computer Use session is already resuming after confirmation.") from exc
    return True


def _release_session_lock(session_id: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        _session_lock_path(session_id).unlink()


def _resuming_is_stale(payload: dict[str, Any]) -> bool:
    started_at = str(payload.get("resumingStartedAt") or "").strip()
    if not started_at:
        return True
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started).total_seconds() > RESUMING_STALE_SECONDS


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
