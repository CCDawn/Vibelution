"""Structure pack guards for team_knowledge_service pure extracts."""

from __future__ import annotations

from core.web.services import team_knowledge_service as facade
from core.web.services.team_knowledge import constants, search_ranking, store


def test_facade_reexports_constants() -> None:
    assert facade.SCHEMA_VERSION is constants.SCHEMA_VERSION
    assert facade.SOURCE_TYPES is constants.SOURCE_TYPES
    assert facade.INGESTION_ADAPTERS is constants.INGESTION_ADAPTERS
    assert facade.KNOWLEDGE_OWNER_TYPES is constants.KNOWLEDGE_OWNER_TYPES
    assert facade.KNOWLEDGE_SEARCH_MODES is constants.KNOWLEDGE_SEARCH_MODES
    assert facade.BM25_K1 is constants.BM25_K1
    assert facade.BM25_B is constants.BM25_B
    assert facade._SAFE_ID_FRAGMENT is constants._SAFE_ID_FRAGMENT
    assert facade._SEARCH_TOKEN_PATTERN is constants._SEARCH_TOKEN_PATTERN
    # Mutable lock remains on the facade for monkeypatch / concurrency.
    assert hasattr(facade, "_LOCK")
    assert facade.PROJECT_ROOT is not None


def test_facade_reexports_search_ranking() -> None:
    assert facade._search_text_for_payload is search_ranking._search_text_for_payload
    assert facade._tokenize_search_text is search_ranking._tokenize_search_text
    assert facade._tokenize_bm25_text is search_ranking._tokenize_bm25_text
    assert facade._rank_bm25_search_results is search_ranking._rank_bm25_search_results
    assert facade._bm25_text_for_result is search_ranking._bm25_text_for_result
    assert facade._semantic_match_score is search_ranking._semantic_match_score
    assert facade._search_match_reason is search_ranking._search_match_reason
    assert facade._item_matches_filters is search_ranking._item_matches_filters


def test_search_ranking_bm25_prefers_title_overlap() -> None:
    results = search_ranking._rank_bm25_search_results(
        [
            {
                "title": "Privacy policy",
                "summary": "legal",
                "content": "",
                "tags": [],
                "sourceSummaries": [],
                "updatedAt": "2026-01-01T00:00:00+00:00",
            },
            {
                "title": "AI model release",
                "summary": "model notes",
                "content": "new model",
                "tags": ["ai"],
                "sourceSummaries": [],
                "updatedAt": "2026-01-02T00:00:00+00:00",
            },
        ],
        "AI model",
    )
    assert results
    assert "model" in str(results[0].get("title") or "").lower()
    assert float(results[0].get("bm25Score") or 0) > 0


def test_facade_reexports_store() -> None:
    assert facade._read_jsonl is store._read_jsonl
    assert facade._write_jsonl is store._write_jsonl
    assert facade._write_json is store._write_json
    assert facade._owner_context is store._owner_context
    assert facade._coerce_owner_context is store._coerce_owner_context
    assert facade._knowledge_root_for_owner is store._knowledge_root_for_owner
    assert facade._load_bases_state_for_owner is store._load_bases_state_for_owner
    assert facade._save_bases_state_for_owner is store._save_bases_state_for_owner
    assert facade._project_root is store._project_root
    assert facade._safe_token is store._safe_token
    assert facade._new_event_id is store._new_event_id
    assert facade._unique_strings is store._unique_strings
    assert facade._central_source_registry_path is store._central_source_registry_path
    # Shared mutable lock and project root remain on the facade.
    assert hasattr(facade, "_LOCK")
    assert facade.PROJECT_ROOT is not None


def test_store_safe_token_and_unique_strings() -> None:
    assert store._safe_token("Hello World!!", default="x", max_length=32) == "Hello-World"
    assert store._unique_strings(["a", "a", "b"]) == ["a", "b"]
    assert store._bounded_dict({"k" * 100: 1, "ok": 2})  # keys truncated
