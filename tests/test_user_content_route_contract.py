"""User markdown-space JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.user_content_models import UserContentMarkdownResponse


def test_user_content_markdown_publishes_known_schema_fields() -> None:
    properties = set(UserContentMarkdownResponse.model_json_schema().get("properties") or {})
    expected = {
        "ok",
        "schemaVersion",
        "userId",
        "spaces",
        "space",
        "pages",
        "page",
        "summary",
        "source",
        "ignoredFiles",
        "query",
        "results",
        "updatedAt",
    }
    assert expected <= properties, (
        f"UserContentMarkdownResponse is missing fields: {sorted(expected - properties)}"
    )


def test_user_content_markdown_keeps_unknown_fields() -> None:
    payload = UserContentMarkdownResponse.model_validate(
        {
            "ok": True,
            "schemaVersion": 1,
            "updatedAt": "2026-08-16T00:00:00Z",
            "content": "# Guide",
            "spaces": [{"spaceId": "docs", "counts": {"pageCount": 2}}],
        }
    ).model_dump()

    assert payload["content"] == "# Guide"
    assert payload["spaces"][0]["counts"] == {"pageCount": 2}


def test_user_content_markdown_keeps_unknown_fields_without_injecting_defaults() -> None:
    payload = UserContentMarkdownResponse.model_validate(
        {
            "ok": True,
            "schemaVersion": 1,
            "spaces": [{"spaceId": "docs"}],
            "futureHint": {"owner": "user_content"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "ok": True,
        "schemaVersion": 1,
        "spaces": [{"spaceId": "docs"}],
        "futureHint": {"owner": "user_content"},
    }
