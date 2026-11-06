"""Focused tests for the session image attachment store rollback slice.

Covers ISS-042: when the on-disk artifact lands but the conversation
metadata write fails, the just-written artifact must be rolled back
(best-effort unlink) and the original metadata error must still surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.web.services import session_service
from core.web.services.session import image_attachments

_MINIMAL_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
    b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture()
def seeded_image_session(tmp_path: Path, monkeypatch) -> str:
    from tests.helpers.web_chat_state import (
        _bind_seeded_submittable_agent,
        _reset_seeded_session_runtime,
        _seed_chat_state,
    )

    session_id = "session-image-attachments"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": session_id,
                "title": "图片附件会话",
                "updated_at": "2026-11-06T10:00:00",
                "last_turn_status": "ready",
                "messages": [],
            }
        ],
    )
    _bind_seeded_submittable_agent(tmp_path, session_id=session_id)
    monkeypatch.setattr(session_service, "_record_session_attachment_event", lambda *a, **k: None)
    yield session_id
    _reset_seeded_session_runtime(session_id)


def test_metadata_failure_rolls_back_stored_artifact(seeded_image_session: str, monkeypatch) -> None:
    session_id = seeded_image_session

    def failing_remember(*args, **kwargs):
        raise OSError("simulated metadata write failure")

    monkeypatch.setattr(session_service, "_remember_session_uploaded_attachment", failing_remember)

    with pytest.raises(OSError, match="simulated metadata write failure"):
        image_attachments.store_session_user_image_attachment(
            session_id,
            _MINIMAL_PNG_BYTES,
            filename="rollback.png",
            content_type="image/png",
        )

    images_dir = session_service._ensure_session_workspace(session_id) / "artifacts" / "images"
    assert images_dir.is_dir()
    assert list(images_dir.iterdir()) == []

    # Resolve must not find any orphan artifact either.
    conversation = session_service.load_session_chat_state(session_service.PROJECT_ROOT, session_id)
    assert not (conversation or {}).get("uploaded_attachments")


def test_metadata_failure_with_unlink_error_still_raises_original(seeded_image_session: str, monkeypatch) -> None:
    session_id = seeded_image_session

    def failing_remember(*args, **kwargs):
        raise OSError("simulated metadata write failure")

    monkeypatch.setattr(session_service, "_remember_session_uploaded_attachment", failing_remember)

    real_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self.suffix == ".png" and self.parent.name == "images":
            raise OSError("simulated unlink failure")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises(OSError, match="simulated metadata write failure"):
        image_attachments.store_session_user_image_attachment(
            session_id,
            _MINIMAL_PNG_BYTES,
            filename="stuck.png",
            content_type="image/png",
        )


def test_successful_store_keeps_artifact_and_metadata(seeded_image_session: str) -> None:
    session_id = seeded_image_session
    attachment = image_attachments.store_session_user_image_attachment(
        session_id,
        _MINIMAL_PNG_BYTES,
        filename="kept.png",
        content_type="image/png",
    )
    artifact_path = Path(attachment["path"])
    assert artifact_path.is_file()
    assert artifact_path.read_bytes() == _MINIMAL_PNG_BYTES

    conversation = session_service.load_session_chat_state(session_service.PROJECT_ROOT, session_id)
    uploaded = list((conversation or {}).get("uploaded_attachments") or [])
    assert [item.get("artifactId") for item in uploaded] == [attachment["artifactId"]]
