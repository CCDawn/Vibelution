"""Narrow byte-based adapter for the native Session attachment stores."""

from __future__ import annotations

from pathlib import Path

from core.web.services.session import document_attachments, image_attachments


def store(sessions, session_id: str, payload: bytes, *, filename: str, content_type: str) -> dict:
    if not isinstance(payload, bytes) or not isinstance(filename, str) or not isinstance(content_type, str):
        raise sessions.SessionValidationError("Invalid attachment payload.")
    if len(payload) > sessions.SESSION_USER_IMAGE_MAX_BYTES:
        raise sessions.SessionValidationError("Attachment is too large.")
    image = bool(sessions._sniff_image_extension(payload) or content_type.lower().startswith("image/"))
    from .migration_io import pinned_target_directory
    root = sessions.developer_sandbox.sandboxed_workspace_path(sessions.PROJECT_ROOT, "sessions")
    directory = Path(root) / sessions._safe_session_workspace_token(session_id) / "artifacts" / ("images" if image else "documents")
    # Pin the session namespace before the shared store resolves it; otherwise
    # a replaced directory could redirect a write to another session.
    validation_error = None
    with pinned_target_directory(directory, create=True):
        try:
            if image:
                result = image_attachments.store_session_user_image_attachment(
                    session_id, payload, filename=filename, content_type=content_type,
                )
            else:
                result = document_attachments.store_session_user_document_attachment(
                    session_id, payload, filename=filename, content_type=content_type,
                )
        except sessions.SessionValidationError as error:
            validation_error = error
    if validation_error is not None:
        raise validation_error
    # Renderer must never receive filesystem paths or Workbench session URLs.
    return {key: result[key] for key in ("artifactId", "filename", "contentType", "sizeBytes", "kind", "status")}


def resolve(session_id: str, artifact_id: str):
    if not isinstance(artifact_id, str) or not artifact_id or artifact_id != artifact_id.strip():
        raise FileNotFoundError("invalid attachment")
    try:
        resolved, content_type = image_attachments.resolve_session_image_artifact(session_id, artifact_id)
        category = "images"
    except FileNotFoundError:
        resolved, content_type = document_attachments.resolve_session_document_artifact(session_id, artifact_id)
        category = "documents"
    # The shared resolver resolves its artifact directory before checking the
    # leaf. For this private bridge, reject a replaced workspace or artifact
    # directory as well; the renderer never supplies a filesystem path.
    from core.web.services import session_service as sessions
    from .migration_io import MigrationIOError, check_path
    root = sessions.developer_sandbox.sandboxed_workspace_path(sessions.PROJECT_ROOT, "sessions")
    expected = Path(root) / sessions._safe_session_workspace_token(session_id) / "artifacts" / category / artifact_id
    try:
        check_path(expected)
        if expected.resolve() != resolved:
            raise MigrationIOError("source_changed")
    except (OSError, ValueError):
        raise FileNotFoundError("attachment unavailable") from None
    return expected, content_type


def validate_ids(sessions, session_id: str, attachment_ids: list[str]) -> None:
    if not isinstance(attachment_ids, list) or any(not isinstance(item, str) for item in attachment_ids):
        raise sessions.SessionValidationError("Invalid attachment IDs.")
    for artifact_id in attachment_ids:
        try:
            resolve(session_id, artifact_id)
        except (FileNotFoundError, OSError):
            raise sessions.SessionValidationError("Attachment not found.") from None
