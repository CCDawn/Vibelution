"""Session query sort contract: whitelist accepts createdAt and passes through."""

from __future__ import annotations

from core.web.services import session_service


def test_session_query_sort_whitelist_accepts_created_at():
    assert session_service._normalize_session_query_sort("createdAt_desc") == "createdAt_desc"
    assert session_service._normalize_session_query_sort("createdAt_asc") == "createdAt_asc"
    assert session_service._normalize_session_query_sort("updatedAt_desc") == "updatedAt_desc"
    assert session_service._normalize_session_query_sort("title_asc") == "title_asc"


def test_session_query_sort_whitelist_rejects_unknown_values():
    assert session_service._normalize_session_query_sort("bogus") == "updatedAt_desc"
    assert session_service._normalize_session_query_sort("") == "updatedAt_desc"
    assert session_service._normalize_session_query_sort("createdAt_desc; drop") == "updatedAt_desc"


def test_session_query_sort_key_orders_by_created_at():
    items = [
        {"id": "old", "createdAt": "2026-01-01T00:00:00+00:00", "updatedAt": "2026-03-01T00:00:00+00:00"},
        {"id": "new", "createdAt": "2026-02-01T00:00:00+00:00", "updatedAt": "2026-01-15T00:00:00+00:00"},
    ]
    ascending = sorted(items, key=session_service._session_query_sort_key("createdAt_asc"))
    assert [item["id"] for item in ascending] == ["old", "new"]
    descending = sorted(
        items,
        key=session_service._session_query_sort_key("createdAt_desc"),
        reverse=True,
    )
    assert [item["id"] for item in descending] == ["new", "old"]
