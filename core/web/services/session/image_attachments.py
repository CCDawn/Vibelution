"""Session image artifact / attachment store and resolve helpers.

Claim scope: store/resolve session images, attachment metadata, capability
recording, and LLM image attachment payload assembly.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
import secrets
import time
from pathlib import Path
from typing import Any


def _service():
    from core.web.services import session_service

    return session_service


def store_session_image_artifact(
    session_id: str,
    image_bytes: bytes,
    *,
    output_format: str = "png",
    source: str = "image2",
) -> dict[str, Any]:
    """Persist a generated image under the current session workspace."""
    s = _service()

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise s.SessionValidationError("Session id is required for image artifact storage.")
    normalized_format = str(output_format or "png").strip().lower().lstrip(".") or "png"
    if normalized_format not in s._SESSION_IMAGE_ARTIFACT_CONTENT_TYPES:
        raise s.SessionValidationError("Unsupported image artifact format.")
    payload = bytes(image_bytes or b"")
    if not payload:
        raise s.SessionValidationError("Image artifact payload is empty.")

    with s._CHAT_STATE_LOCK:
        s._ensure_session_mutable(normalized_session_id)
        workspace_path = s._ensure_session_workspace(normalized_session_id)
        images_dir = (workspace_path / "artifacts" / "images").resolve()
        artifacts_root = (workspace_path / "artifacts").resolve()
        images_dir.mkdir(parents=True, exist_ok=True)
        if not images_dir.is_relative_to(artifacts_root):
            raise s.SessionValidationError(f"Invalid session image artifact path: {images_dir}")

        artifact_id = f"{source}-{int(time.time() * 1000)}-{secrets.token_hex(4)}.{normalized_format}"
        output_path = (images_dir / artifact_id).resolve()
        if output_path.parent != images_dir:
            raise s.SessionValidationError("Invalid session image artifact filename.")
        output_path.write_bytes(payload)

    url = (
        f"/api/sessions/{s.quote(normalized_session_id, safe='')}"
        f"/artifacts/{s.quote(artifact_id, safe='')}"
    )
    relative_path = f"{s._session_workspace_relative_path(normalized_session_id)}/artifacts/images/{artifact_id}"
    return {
        "artifactId": artifact_id,
        "filename": artifact_id,
        "artifactPath": relative_path,
        "path": str(output_path),
        "url": url,
        "imageUrl": url,
        "downloadUrl": f"{url}?download=1",
        "contentType": s._SESSION_IMAGE_ARTIFACT_CONTENT_TYPES[normalized_format],
        "sizeBytes": len(payload),
        "outputFormat": normalized_format,
    }


def store_session_user_image_attachment(
    session_id: str,
    image_bytes: bytes,
    *,
    filename: str = "",
    content_type: str = "",
) -> dict[str, Any]:
    """Persist a user-uploaded image attachment under the current session workspace."""
    s = _service()

    normalized_content_type = str(content_type or "").split(";", 1)[0].strip().lower()
    original_filename = s._decode_attachment_filename(filename)
    extension = s._session_image_extension_for_upload(original_filename, normalized_content_type)
    if extension not in s._SESSION_IMAGE_ARTIFACT_CONTENT_TYPES:
        raise s.SessionValidationError("Unsupported image attachment format.")
    payload = bytes(image_bytes or b"")
    if not payload:
        raise s.SessionValidationError("Image attachment payload is empty.")
    if len(payload) > s._SESSION_USER_IMAGE_MAX_BYTES:
        raise s.SessionValidationError("Image attachment is too large.")
    sniffed_extension = s._sniff_image_extension(payload)
    if not sniffed_extension:
        raise s.SessionValidationError("Unsupported image attachment format.")
    extension = sniffed_extension
    normalized_content_type = s._SESSION_IMAGE_ARTIFACT_CONTENT_TYPES[extension]

    with s._CHAT_STATE_LOCK:
        s._ensure_session_mutable(session_id)
        artifact = s.store_session_image_artifact(
            session_id,
            payload,
            output_format=extension,
            source="user-image",
        )
        attachment = {
            **artifact,
            "kind": "user_image",
            "status": "ready",
            "filename": original_filename or artifact["filename"],
        }
        s._remember_session_uploaded_attachment(session_id, attachment)
    s._record_session_attachment_event(
        session_id,
        "stored",
        attachment,
        outcome="stored",
    )
    return attachment


def _remember_session_uploaded_attachment(session_id: str, attachment: dict[str, Any]) -> None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        s._materialize_agent_directory_conversation_locked(payload, normalized_session_id, source="s.store_session_user_image_attachment")
        conversation = s._find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            raise s.SessionNotFoundError(f"Session not found: {normalized_session_id}")
        uploaded = list(conversation.get("uploaded_attachments") or [])
        artifact_id = str(attachment.get("artifactId") or "").strip()
        uploaded = [
            item for item in uploaded
            if not isinstance(item, dict) or str(item.get("artifactId") or "").strip() != artifact_id
        ]
        uploaded.append({key: value for key, value in attachment.items() if key != "path"})
        conversation["uploaded_attachments"] = uploaded[-24:]
        conversation["updated_at"] = s._now_timestamp()
        payload["updated_at"] = conversation["updated_at"]
        s.save_chat_state(s.PROJECT_ROOT, payload)


def _decode_attachment_filename(filename: str) -> str:
    s = _service()
    raw = str(filename or "").strip()
    if "%" not in raw:
        return Path(raw).name
    try:
        from urllib.parse import unquote

        return Path(unquote(raw)).name
    except Exception:
        return Path(raw).name


def _session_image_extension_for_upload(filename: str, content_type: str) -> str:
    s = _service()
    extension = Path(str(filename or "")).suffix.lower().lstrip(".")
    if extension == "jpeg":
        extension = "jpg"
    if extension in s._SESSION_IMAGE_ARTIFACT_CONTENT_TYPES:
        return extension
    for known_extension, known_type in s._SESSION_IMAGE_ARTIFACT_CONTENT_TYPES.items():
        if str(content_type or "").lower() == known_type:
            return "jpg" if known_extension == "jpeg" else known_extension
    return extension


def _sniff_image_extension(payload: bytes) -> str:
    s = _service()
    data = bytes(payload or b"")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return ""


def resolve_session_image_artifact(session_id: str, artifact_id: str) -> tuple[Path, str]:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    normalized_artifact_id = str(artifact_id or "").strip()
    if not normalized_session_id or not normalized_artifact_id:
        raise FileNotFoundError("missing session artifact")
    artifact_name = Path(normalized_artifact_id).name
    if artifact_name != normalized_artifact_id or not s._SESSION_IMAGE_ARTIFACT_SAFE_CHARS.fullmatch(artifact_name):
        raise FileNotFoundError("invalid session artifact")
    extension = Path(artifact_name).suffix.lower().lstrip(".")
    content_type = s._SESSION_IMAGE_ARTIFACT_CONTENT_TYPES.get(extension)
    if not content_type:
        raise FileNotFoundError("unsupported session artifact")

    sessions_root = s.developer_sandbox.sandboxed_workspace_path(s.PROJECT_ROOT, "sessions").resolve()
    workspace_path = s._ensure_session_workspace(normalized_session_id).resolve()
    if not workspace_path.is_relative_to(sessions_root):
        raise FileNotFoundError("invalid session artifact path")
    images_dir = (workspace_path / "artifacts" / "images").resolve()
    target_path = (images_dir / artifact_name).resolve()
    if not target_path.is_relative_to(images_dir) or not target_path.exists() or not target_path.is_file():
        raise FileNotFoundError("session artifact not found")
    return target_path, content_type


def _resolve_session_image_attachment(session_id: str, artifact_id: str) -> dict[str, Any]:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    normalized_artifact_id = str(artifact_id or "").strip()
    path, content_type = resolve_session_image_artifact(normalized_session_id, normalized_artifact_id)
    url = (
        f"/api/sessions/{s.quote(normalized_session_id, safe='')}"
        f"/artifacts/{s.quote(Path(normalized_artifact_id).name, safe='')}"
    )
    relative_path = (
        f"{s._session_workspace_relative_path(normalized_session_id)}"
        f"/artifacts/images/{Path(normalized_artifact_id).name}"
    )
    return {
        "artifactId": Path(normalized_artifact_id).name,
        "filename": Path(normalized_artifact_id).name,
        "artifactPath": relative_path,
        "path": str(path),
        "url": url,
        "imageUrl": url,
        "downloadUrl": f"{url}?download=1",
        "contentType": content_type,
        "sizeBytes": path.stat().st_size,
        "kind": "user_image",
        "status": "ready",
    }


def resolve_session_image_attachment_data_url(session_id: str, artifact_id: str) -> dict[str, Any]:
    """Read a session image artifact as a transient data URL for model input."""
    s = _service()

    attachment = s._resolve_session_image_attachment(session_id, artifact_id)
    path = Path(str(attachment.get("path") or ""))
    payload = path.read_bytes()
    if len(payload) > s._SESSION_USER_IMAGE_MAX_BYTES:
        raise s.SessionValidationError("Image attachment is too large for model input.")
    content_type = str(attachment.get("contentType") or "").strip() or "image/png"
    data_url = f"data:{content_type};base64,{base64.b64encode(payload).decode('ascii')}"
    return {
        **{key: value for key, value in attachment.items() if key != "path"},
        "dataUrl": data_url,
    }


def _resolve_session_image_attachments(
    session_id: str,
    attachment_ids: Any,
    *,
    conversation: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    s = _service()
    normalized_ids: list[str] = []
    seen: set[str] = set()
    for raw_id in list(attachment_ids or []):
        artifact_id = str(raw_id or "").strip()
        if not artifact_id or artifact_id in seen:
            continue
        seen.add(artifact_id)
        normalized_ids.append(artifact_id)
    if len(normalized_ids) > s._SESSION_USER_IMAGE_MAX_ATTACHMENTS_PER_TURN:
        raise s.SessionValidationError("Too many image attachments for one turn.")
    attachments: list[dict[str, Any]] = []
    for artifact_id in normalized_ids:
        existing = s._find_session_attachment_metadata(conversation, artifact_id)
        if existing:
            attachments.append(existing)
            continue
        try:
            attachments.append(s._resolve_session_image_attachment(session_id, artifact_id))
        except FileNotFoundError as exc:
            raise s.SessionValidationError(f"Image attachment not found: {artifact_id}") from exc
    return attachments


def _find_session_attachment_metadata(conversation: dict[str, Any] | None, artifact_id: str) -> dict[str, Any]:
    s = _service()
    if not isinstance(conversation, dict):
        return {}
    normalized_artifact_id = str(artifact_id or "").strip()
    if not normalized_artifact_id:
        return {}
    conversation_id = str(conversation.get("conversation_id") or conversation.get("id") or "").strip()
    for message in reversed(s._session_ledger_visible_messages(conversation_id)):
        if not isinstance(message, dict):
            continue
        for attachment in s._normalize_message_attachments(message.get("attachments") or []):
            if str(attachment.get("artifactId") or "").strip() == normalized_artifact_id:
                return dict(attachment)
    for attachment in reversed(list(conversation.get("uploaded_attachments") or [])):
        if not isinstance(attachment, dict):
            continue
        normalized = s._normalize_message_attachments([attachment])
        if normalized and str(normalized[0].get("artifactId") or "").strip() == normalized_artifact_id:
            return dict(normalized[0])
    return {}


def _has_recent_image_attachment_reference(message: str) -> bool:
    s = _service()
    normalized = str(message or "").strip().lower()
    if not normalized:
        return False
    if s._contains_any_attachment_reference_pattern(normalized, s._RECENT_IMAGE_REFERENCE_EXACT_PATTERNS):
        return True
    has_reference = s._contains_any_attachment_reference_pattern(normalized, s._RECENT_IMAGE_REFERENCE_WORDS)
    has_image_target = s._contains_any_attachment_reference_pattern(normalized, s._RECENT_IMAGE_TARGET_WORDS)
    return has_reference and has_image_target


def _find_recent_user_image_attachment(conversation: dict[str, Any] | None) -> dict[str, Any]:
    s = _service()
    if not isinstance(conversation, dict):
        return {}
    conversation_id = str(conversation.get("conversation_id") or conversation.get("id") or "").strip()
    for message in reversed(s._session_ledger_visible_messages(conversation_id)):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        attachments = s._normalize_message_attachments(message.get("attachments") or message.get("imageAttachments") or [])
        for attachment in reversed(attachments):
            if s._is_ready_user_image_attachment(attachment):
                return dict(attachment)
    for attachment in reversed(list(conversation.get("uploaded_attachments") or [])):
        normalized = s._normalize_message_attachments([attachment])
        if normalized and s._is_ready_user_image_attachment(normalized[0]):
            return dict(normalized[0])
    return {}


def _is_ready_user_image_attachment(attachment: dict[str, Any]) -> bool:
    s = _service()
    if not isinstance(attachment, dict):
        return False
    artifact_id = str(attachment.get("artifactId") or "").strip()
    status = str(attachment.get("status") or "ready").strip().lower()
    kind = str(attachment.get("kind") or "user_image").strip().lower()
    content_type = str(attachment.get("contentType") or "").strip().lower()
    return bool(artifact_id) and status == "ready" and kind == "user_image" and (
        not content_type or content_type.startswith("image/")
    )


def _normalize_message_attachments(value: Any) -> list[dict[str, Any]]:
    s = _service()
    return s.normalize_chat_attachments(value)


def _matches_attachment_reference_pattern(normalized: str, pattern: str) -> bool:
    s = _service()
    if not pattern:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9 _'-]*", pattern):
        return re.search(rf"(?<![a-z0-9]){re.escape(pattern)}(?![a-z0-9])", normalized) is not None
    return pattern in normalized


def _contains_any_attachment_reference_pattern(normalized: str, patterns: tuple[str, ...]) -> bool:
    s = _service()
    return any(s._matches_attachment_reference_pattern(normalized, pattern) for pattern in patterns)


def _resolve_image_attachment_capability(
    *,
    agent_instance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    supports_image_input = s._session_agent_supports_image_input(
        agent_instance,
        slot= "dialogue",
    )
    model_id = s._session_agent_llm_slot_model_id(agent_instance, s.SESSION_LLM_SLOT_DIALOGUE)
    model_name = s._session_agent_llm_model_name(
        agent_instance,
        slot= "dialogue",
    )
    return {
        "supports_image_input": supports_image_input,
        "model_name": model_name,
        "model_id": model_id,
        "llm_slot": s.SESSION_LLM_SLOT_DIALOGUE,
    }


def _recent_image_attachment_missing_message(lang: str) -> str:
    s = _service()
    return s.text_for(
        lang,
        zh="我没有在当前会话里找到可重新查看的最近图片附件。请重新发送图片，或在消息里附上要我查看的图片。",
        en="I could not find a recent image attachment in this session to inspect again. Please attach or resend the image.",
    )


def _record_image_attachment_capability_event(
    session_id: str,
    *,
    turn_id: str,
    decision: str,
    reason: str,
    outcome: str,
    agent_id: str,
    attachments: list[dict[str, Any]],
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "image_attachment_capability",
            "conversation.image_attachment.capability_checked",
            level=level,
            outcome=outcome,
            message="Image input capability checked without semantic intent routing.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "decision": str(decision or "").strip(),
                "reason": str(reason or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "attachmentCount": len(s._normalize_message_attachments(attachments or [])),
                "attachments": s._safe_attachment_log_summary(attachments or []),
                **(fields or {}),
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(session_id)}-image-capability.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "turn_id": str(turn_id or "").strip(),
                "decision": str(decision or "").strip(),
                "reason": str(reason or "").strip(),
                "agent_id": str(agent_id or "").strip(),
                "attachment_count": len(s._normalize_message_attachments(attachments or [])),
                "attachments": s._safe_attachment_log_summary(attachments or []),
                **(fields or {}),
            },
            lifecycle=True,
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"runtime scene image attachment capability log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _build_llm_image_attachments(session_id: str, attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = _service()
    prepared: list[dict[str, Any]] = []
    for attachment in s._normalize_message_attachments(attachments):
        artifact_id = str(attachment.get("artifactId") or "").strip()
        if not artifact_id:
            continue
        try:
            prepared.append(resolve_session_image_attachment_data_url(session_id, artifact_id))
        except (FileNotFoundError, OSError, s.SessionValidationError) as exc:
            s._record_session_attachment_event(
                session_id,
                "prepare_failed",
                attachment,
                outcome=type(exc).__name__,
            )
            raise s.SessionValidationError(f"Image attachment could not be prepared: {artifact_id}") from exc
    return prepared


def _record_session_attachment_event(
    session_id: str,
    phase: str,
    attachment: dict[str, Any],
    *,
    outcome: str,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            f"attachment_{phase}",
            f"conversation.attachment.{phase}",
            level="info",
            outcome=outcome,
            message=f"Conversation image attachment {phase}.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "attachment": s._safe_attachment_log_summary([attachment])[0] if attachment else {},
            },
            lifecycle=True,
        )
    except Exception:
        return


def _safe_attachment_log_summary(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = _service()
    summary: list[dict[str, Any]] = []
    for item in s._normalize_message_attachments(attachments):
        summary.append(
            {
                "artifactId": str(item.get("artifactId") or "").strip(),
                "filename": str(item.get("filename") or "").strip(),
                "contentType": str(item.get("contentType") or "").strip(),
                "sizeBytes": s._coerce_nonnegative_int(item.get("sizeBytes") or 0),
                "kind": str(item.get("kind") or "").strip(),
            }
        )
    return summary
