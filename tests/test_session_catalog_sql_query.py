from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from config.models import AppConfig
from core.chat.session_catalog import SessionCatalogStore
from core.web.services import session_service
from core.web.services.session import catalog_bridge
from tests.session_catalog_fixtures import QUERY_SEARCH_FIELDS, build_session_query_summaries


def _store(tmp_path: Path) -> SessionCatalogStore:
    store = SessionCatalogStore(
        tmp_path / "catalog" / "session_catalog.sqlite3",
        workspace_key="workspace-test",
    )
    store.initialize()
    return store


def _catalog_row(
    summary: dict[str, object],
    *,
    source_order: int = 0,
) -> dict[str, object]:
    session_id = str(summary["id"])
    updated_at = str(summary["updatedAt"])
    return {
        "session_id": session_id,
        "title": summary["title"],
        "task_title": summary["taskTitle"],
        "task_summary": summary["taskSummary"],
        "session_kind": summary["sessionKind"],
        "visibility": summary["conversationIndexVisibility"],
        "agent_id": summary["agentId"],
        "agent_code": summary["agentCode"],
        "agent_display_name": summary["agentDisplayName"],
        "dialogue_model_id": summary["dialogueModelId"],
        "status": summary["status"],
        "current_phase": summary["currentPhase"],
        "child_status": summary["childStatus"],
        "created_at": updated_at,
        "updated_at": updated_at,
        "last_active_at": summary["lastActive"],
        "source_order": source_order,
        "updated_at_sort_key": datetime.fromisoformat(
            updated_at.replace("Z", "+00:00")
        ).timestamp(),
        "title_sort_key": str(summary["title"] or "").strip().lower(),
        "latest_sequence": 0,
        "event_count": 0,
        "message_count": 0,
        "journal_rel_path": f"sessions/{session_id}/turn_journal.jsonl",
        "journal_size": 0,
        "journal_mtime_ns": 0,
        "source_revision": f"source-{session_id}",
        "indexed_at": summary["updatedAt"],
    }


def _legacy_query(monkeypatch, summaries, request):
    monkeypatch.setattr(session_service, "get_config", lambda: AppConfig())
    monkeypatch.setattr(
        session_service,
        "_get_cached_session_query_sessions",
        lambda **_kwargs: [dict(item) for item in summaries],
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_list_query_event",
        lambda **_kwargs: None,
    )
    return session_service.query_sessions(**request)


@pytest.mark.parametrize(
    "query_args",
    [
        {"limit": 5},
        {"q": "NEEDLE", "limit": 50},
        {"agent_id": "agent-03", "limit": 50},
        {"session_kind": "child", "limit": 50},
        {"state": "model_request", "limit": 50},
        {"sort": "title_asc", "limit": 50},
        {"cursor": "3", "limit": 4},
        {"cursor": "-3", "limit": 3},
    ],
)
def test_sql_candidate_matches_legacy_query_contract(monkeypatch, tmp_path, query_args):
    summaries = build_session_query_summaries(48)
    store = _store(tmp_path)
    for source_order, summary in enumerate(summaries):
        store.upsert_session(_catalog_row(summary, source_order=source_order))
    provider = catalog_bridge.build_session_catalog_query_provider(store)

    legacy = _legacy_query(monkeypatch, summaries, query_args)
    candidate = provider(query_args)

    assert catalog_bridge.compare_session_query_payloads(legacy, candidate).status == "match"


def test_sql_candidate_searches_every_frozen_metadata_field(monkeypatch, tmp_path):
    store = _store(tmp_path)
    for index, field in enumerate(QUERY_SEARCH_FIELDS):
        summary = build_session_query_summaries(1)[0]
        marker = f"unique-{field.lower()}-{index}"
        summary[field] = marker
        store.upsert_session(_catalog_row(summary))
        provider = catalog_bridge.build_session_catalog_query_provider(store)

        payload = provider({"q": marker.upper(), "limit": 10})

        assert [item["id"] for item in payload["items"]] == [summary["id"]], field


def test_sql_candidate_escapes_like_and_sql_metacharacters(tmp_path):
    store = _store(tmp_path)
    first = build_session_query_summaries(1)[0]
    second = build_session_query_summaries(2)[0]
    marker = "needle%' OR 1=1 --"
    first["title"] = marker
    second["title"] = "ordinary"
    store.upsert_session(_catalog_row(first))
    second["id"] = "session-ordinary"
    store.upsert_session(_catalog_row(second))
    provider = catalog_bridge.build_session_catalog_query_provider(store)

    payload = provider({"q": marker, "limit": 10})

    assert [item["id"] for item in payload["items"]] == [first["id"]]
