"""Projection keeps the user_secret privacy mask rows for reloaded bubbles.

The generic attachment normalizer drops metadata-only rows (no artifactId or
url); the message projection must still surface the value-free
``{attachmentId, kind: "user_secret", label?}`` rows so a reloaded chat can
render the privacy chip. Ordinary sessions never journal such rows, so their
projection output stays byte-identical.
"""

from __future__ import annotations

import json

from core.web.services import session_service
from core.web.services.session import projection


def _normalize(raw_messages):
    return session_service._normalize_messages(
        "session-secret-projection",
        raw_messages,
        transcript_scope="window",
    )


def test_user_secret_row_helper_is_strict() -> None:
    rows = projection._user_secret_attachment_rows([
        {"attachmentId": "sec_one", "kind": "user_secret", "label": "Provider Key"},
        {"artifactId": "sec_two", "kind": "user_secret"},
        # Unexpected extra fields never leak: reconstruction is a whitelist.
        {"attachmentId": "sec_three", "kind": "user_secret", "secretValue": "plaintext"},
        # Not a user_secret kind, missing id, or not a dict -> dropped.
        {"attachmentId": "img", "kind": "user_image"},
        {"kind": "user_secret"},
        "not-a-dict",
        {"attachmentId": "sec_one", "kind": "user_secret"},  # duplicate id
    ])
    assert rows == [
        {"attachmentId": "sec_one", "kind": "user_secret", "label": "Provider Key"},
        {"attachmentId": "sec_two", "kind": "user_secret"},
        {"attachmentId": "sec_three", "kind": "user_secret"},
    ]
    assert projection._user_secret_attachment_rows([]) == []
    assert projection._user_secret_attachment_rows(None) == []


def test_projection_keeps_secret_rows_and_drops_unexpected_fields() -> None:
    token = "sec_abc123"
    messages = _normalize([
        {
            "role": "user",
            "content": "帮我把这个 key 配置到 provider",
            "timestamp": "2026-11-05T10:00:00Z",
            "attachments": [
                {
                    "artifactId": "artifact-1",
                    "filename": "shot.png",
                    "contentType": "image/png",
                    "kind": "user_image",
                    "status": "ready",
                },
                {
                    "attachmentId": token,
                    "kind": "user_secret",
                    "label": "Provider Key",
                },
            ],
        },
    ])
    entry = next(item for item in messages if item["role"] == "user")
    attachments = entry["attachments"]
    image_rows = [row for row in attachments if row.get("kind") == "user_image"]
    secret_rows = [row for row in attachments if row.get("kind") == "user_secret"]
    # Other kinds are untouched by the change.
    assert len(image_rows) == 1
    assert image_rows[0]["artifactId"] == "artifact-1"
    # The mask row survives with exactly the contract fields.
    assert secret_rows == [
        {"attachmentId": token, "kind": "user_secret", "label": "Provider Key"},
    ]
    assert "plaintext" not in json.dumps(entry, ensure_ascii=False, default=str)


def test_projection_keeps_secret_only_message_visible() -> None:
    token = "sec_only456"
    messages = _normalize([
        {
            "role": "user",
            # Empty text with only a privacy attachment: the bubble must not
            # be dropped as an empty row after reload.
            "content": "",
            "timestamp": "2026-11-05T10:01:00Z",
            "attachments": [{"attachmentId": token, "kind": "user_secret"}],
        },
    ])
    entries = [item for item in messages if item["role"] == "user"]
    assert len(entries) == 1
    assert entries[0]["attachments"] == [
        {"attachmentId": token, "kind": "user_secret"},
    ]


def test_projection_ordinary_messages_stay_free_of_secret_rows() -> None:
    """Ordinary sessions never journal secret rows: zero projection diff."""

    raw_messages = [
        {
            "role": "user",
            "content": "普通会话消息",
            "timestamp": "2026-11-05T10:02:00Z",
            "attachments": [
                {
                    "artifactId": "artifact-2",
                    "filename": "note.txt",
                    "contentType": "text/plain",
                    "kind": "user_document",
                    "status": "ready",
                },
            ],
        },
        {
            # Defense in depth: a malformed mask row without an id must not
            # surface even if a foreign payload carried one.
            "role": "user",
            "content": "另一条消息",
            "timestamp": "2026-11-05T10:03:00Z",
            "attachments": [{"kind": "user_secret", "label": "无 id"},
                            {"artifactId": "artifact-3", "kind": "user_image"}],
        },
    ]
    messages = _normalize(raw_messages)
    for entry in [item for item in messages if item["role"] == "user"]:
        attachments = entry["attachments"]
        assert all(row.get("kind") != "user_secret" for row in attachments)
        assert all("attachmentId" not in row for row in attachments)
    first = messages[0]["attachments"]
    assert len(first) == 1
    assert first[0]["artifactId"] == "artifact-2"
    second = messages[1]["attachments"]
    assert len(second) == 1
    assert second[0]["artifactId"] == "artifact-3"
