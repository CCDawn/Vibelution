"""Adapter helpers for routing product messages into the Agent Kernel."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from core.web.services.runtime_scene_service import record_runtime_scene_event


ADAPTER_VERSION = "kernel-adapter-v1"
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class KernelAdapterError(ValueError):
    """Raised when an adapter request cannot be converted into a kernel event."""


def build_agent_message_event(
    *,
    source: str,
    sender: dict[str, Any] | None,
    recipient_agent_ids: list[str],
    content: str,
    correlation_id: str = "",
    causation_id: str = "",
    wake_target: bool = True,
    metadata: dict[str, Any] | None = None,
    source_id: str = "",
    idempotency_key: str = "",
    event_id: str = "",
) -> dict[str, Any]:
    """Build a stable ``agent.message`` kernel event from a product surface."""

    raw_metadata = metadata if isinstance(metadata, dict) else {}
    source_surface = _first_text(source, raw_metadata.get("sourceSurface"))
    if not source_surface:
        raise KernelAdapterError("Kernel adapter source is required.")
    recipients = _normalize_recipients(recipient_agent_ids)
    if not recipients:
        raise KernelAdapterError("Kernel adapter recipients are required.")
    normalized_content = str(content or "").strip()
    if not normalized_content:
        raise KernelAdapterError("Kernel adapter content is required.")

    normalized_sender = _safe_metadata(sender if isinstance(sender, dict) else {}, max_items=16)
    normalized_source_id = _normalize_source_id(
        source_id=source_id,
        event_id=event_id,
        correlation_id=correlation_id,
        metadata=raw_metadata,
        source_surface=source_surface,
        sender=normalized_sender,
        recipients=recipients,
        content=normalized_content,
    )
    recipient_hash = _stable_hash(recipients, size=16)
    content_hash = _stable_hash(normalized_content, size=16)
    source_slug = _safe_slug(source_surface, fallback="source")
    source_id_slug = _safe_slug(normalized_source_id, fallback="source-id")
    generated_idempotency_key = f"kernel-adapter:{source_slug}:{source_id_slug}:{recipient_hash}:{content_hash}"
    resolved_event_id = _safe_event_id(event_id) or _generated_event_id(
        source_slug=source_slug,
        source_id_slug=source_id_slug,
        recipient_hash=recipient_hash,
        content_hash=content_hash,
    )
    normalized_metadata = _adapter_metadata(
        raw_metadata,
        source_surface=source_surface,
        source_id=normalized_source_id,
    )
    sender_agent_id = str(
        normalized_sender.get("agentId")
        or (normalized_sender.get("id") if str(normalized_sender.get("type") or "").strip().lower() == "agent" else "")
        or ""
    ).strip()
    event = {
        "eventId": resolved_event_id,
        "sender": normalized_sender,
        "senderAgentId": sender_agent_id,
        "recipientAgentIds": recipients,
        "semanticType": "agent.message",
        "payload": {
            "content": normalized_content,
            "goal": normalized_content,
        },
        "idempotencyKey": str(idempotency_key or "").strip() or generated_idempotency_key,
        "correlationId": str(correlation_id or normalized_source_id or resolved_event_id).strip(),
        "causationId": str(causation_id or "").strip(),
        "wakeTarget": bool(wake_target),
        "metadata": normalized_metadata,
    }
    _record_adapter_scene_event("kernel.adapter.event_built", event)
    return event


def submit_agent_message_event(
    *,
    source: str,
    sender: dict[str, Any] | None,
    recipient_agent_ids: list[str],
    content: str,
    correlation_id: str = "",
    causation_id: str = "",
    wake_target: bool = True,
    metadata: dict[str, Any] | None = None,
    source_id: str = "",
    idempotency_key: str = "",
    event_id: str = "",
) -> dict[str, Any]:
    """Build and submit an ``agent.message`` event through the kernel loop."""

    event = build_agent_message_event(
        source=source,
        sender=sender,
        recipient_agent_ids=recipient_agent_ids,
        content=content,
        correlation_id=correlation_id,
        causation_id=causation_id,
        wake_target=wake_target,
        metadata=metadata,
        source_id=source_id,
        idempotency_key=idempotency_key,
        event_id=event_id,
    )
    from . import service as kernel_service

    result = kernel_service.handle_kernel_event(event)
    response = dict(result)
    response["adapter"] = {
        "source": str(event.get("metadata", {}).get("sourceSurface") or source).strip(),
        "adapterVersion": ADAPTER_VERSION,
        "eventId": str(event.get("eventId") or "").strip(),
        "idempotencyKey": str(event.get("idempotencyKey") or "").strip(),
    }
    _record_adapter_scene_event("kernel.adapter.event_submitted", event, result=response)
    return response


def _adapter_metadata(raw_metadata: dict[str, Any], *, source_surface: str, source_id: str) -> dict[str, Any]:
    metadata = _safe_metadata(raw_metadata, max_items=32)
    metadata["sourceSurface"] = source_surface
    metadata.setdefault("sourceSessionId", "")
    metadata.setdefault("sourceRoomId", "")
    metadata.setdefault("sourceMessageId", "")
    metadata.setdefault("projectionRef", "")
    metadata["adapterVersion"] = ADAPTER_VERSION
    metadata["sourceId"] = source_id
    return metadata


def _normalize_source_id(
    *,
    source_id: str,
    event_id: str,
    correlation_id: str,
    metadata: dict[str, Any],
    source_surface: str,
    sender: dict[str, Any],
    recipients: list[str],
    content: str,
) -> str:
    candidate = _first_text(
        source_id,
        metadata.get("sourceMessageId"),
        _projection_ref_id(metadata.get("projectionRef")),
        correlation_id,
        event_id,
    )
    if candidate:
        return candidate
    return _stable_hash(
        {
            "sourceSurface": source_surface,
            "sender": sender,
            "recipients": recipients,
            "content": content,
        },
        size=20,
    )


def _normalize_recipients(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        normalized = str(value or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _projection_ref_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or value.get("ref") or value.get("value") or "").strip()
    if isinstance(value, (list, tuple)):
        for item in value:
            candidate = _projection_ref_id(item)
            if candidate:
                return candidate
        return ""
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _safe_event_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    cleaned = _SAFE_ID_RE.sub("-", raw).strip("._-")
    if not cleaned:
        return ""
    if cleaned != raw or len(cleaned) > 120:
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]
        return f"event-{cleaned[:72].strip('._-') or 'id'}-{digest}"
    return cleaned


def _generated_event_id(*, source_slug: str, source_id_slug: str, recipient_hash: str, content_hash: str) -> str:
    event_id = f"event-kernel-adapter-{source_slug}-{source_id_slug}-{recipient_hash[:8]}-{content_hash[:8]}"
    if len(event_id) <= 120:
        return event_id
    digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:12]
    return f"event-kernel-adapter-{source_slug[:24]}-{digest}"


def _safe_slug(value: str, *, fallback: str) -> str:
    cleaned = _SAFE_ID_RE.sub("-", str(value or "").strip()).strip("._-").lower()
    if not cleaned:
        return fallback
    if len(cleaned) <= 48:
        return cleaned
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[:36].strip('._-')}-{digest}"


def _stable_hash(value: Any, *, size: int = 16) -> str:
    if isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[: max(8, size)]


def _safe_metadata(metadata: Any, *, max_items: int = 32) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, value in list(metadata.items())[:max_items]:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[normalized_key] = value
        elif isinstance(value, dict):
            safe[normalized_key] = _safe_metadata(value, max_items=16)
        elif isinstance(value, (list, tuple)):
            safe[normalized_key] = [
                item if isinstance(item, (str, int, float, bool)) or item is None else str(item)
                for item in list(value)[:24]
            ]
        else:
            safe[normalized_key] = str(value)
    return safe


def _record_adapter_scene_event(
    event_code: str,
    event: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
) -> None:
    try:
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        task = result.get("task") if isinstance(result, dict) and isinstance(result.get("task"), dict) else {}
        outcome = result.get("outcome") if isinstance(result, dict) and isinstance(result.get("outcome"), dict) else {}
        record_runtime_scene_event(
            "agent_kernel",
            "runtime",
            event_code,
            message=event_code,
            level="info",
            outcome=str((outcome or {}).get("status") or event.get("status") or "observed"),
            fields={
                "sourceSurface": str(metadata.get("sourceSurface") or "").strip(),
                "eventId": str(event.get("eventId") or "").strip(),
                "taskId": str(task.get("taskId") or "").strip(),
                "outcomeId": str(outcome.get("outcomeId") or "").strip(),
                "recipientCount": len(event.get("recipientAgentIds") or []),
                "reused": bool(result.get("reused")) if isinstance(result, dict) else False,
            },
            lifecycle=True,
        )
    except Exception:
        return
