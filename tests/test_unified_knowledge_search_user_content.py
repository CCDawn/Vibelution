from __future__ import annotations

from pathlib import Path

from core.web.services import unified_knowledge_search_service, user_content_markdown_service


def _write_note(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_unified_search_is_formal_only_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(user_content_markdown_service, "PROJECT_ROOT", tmp_path / "project")
    monkeypatch.setattr(
        unified_knowledge_search_service.team_knowledge_service,
        "search_knowledge_items",
        lambda **kwargs: {"summary": {"resultCount": 0, "scannedKnowledgeBaseCount": 0}, "results": []},
    )
    source = tmp_path / "source"
    _write_note(source, "Guide.md", "# Guide\nuser markdown reference")
    user_content_markdown_service.import_markdown_space(str(source), space_name="User Notes")

    payload = unified_knowledge_search_service.search_unified_memory(agent_id="agent-1", query="markdown reference")

    assert all(result["resultType"] != "user_markdown_page" for result in payload["results"])
    assert payload["retrievalPolicy"]["mutatesFormalKnowledge"] is False


def test_unified_search_can_include_user_markdown_results(tmp_path, monkeypatch):
    monkeypatch.setattr(user_content_markdown_service, "PROJECT_ROOT", tmp_path / "project")
    monkeypatch.setattr(
        unified_knowledge_search_service.team_knowledge_service,
        "search_knowledge_items",
        lambda **kwargs: {"summary": {"resultCount": 0, "scannedKnowledgeBaseCount": 0}, "results": []},
    )
    source = tmp_path / "source"
    _write_note(source, "Guide.md", "# Guide\nuser markdown reference")
    imported = user_content_markdown_service.import_markdown_space(str(source), space_name="User Notes")

    payload = unified_knowledge_search_service.search_unified_memory(
        agent_id="agent-1",
        query="markdown reference",
        include_user_content=True,
        allowed_user_content_space_ids=[imported["space"]["spaceId"]],
    )

    assert payload["summary"]["userContentResultCount"] == 1
    assert payload["results"][0]["resultType"] == "user_markdown_page"
    assert payload["citations"][0]["sourceDomain"] == "user_content"
    assert payload["retrievalPolicy"]["honorsUserContentPolicy"] is True


def test_unified_search_can_include_public_catalog_cards_without_bodies(tmp_path, monkeypatch):
    from core.web.services import team_knowledge_service, agent_directory_service

    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        unified_knowledge_search_service.team_knowledge_service,
        "search_knowledge_items",
        lambda **kwargs: {"summary": {"resultCount": 0, "scannedKnowledgeBaseCount": 0}, "results": []},
    )
    source = tmp_path / "docs"
    source.mkdir(parents=True, exist_ok=True)
    (source / "guide.md").write_text("guide body", encoding="utf-8")
    steward_id = agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    team_knowledge_service.upsert_public_card(
        {
            "cardId": "pin-unified-1",
            "kind": "pin",
            "partition": "standards",
            "title": "Unified Search Guide",
            "whenToUse": "Search integration tests",
            "summary": "Unified search guide summary.",
            "stewardWeight": 1,
            "visibility": "agent_visible",
            "source": {"type": "git_path", "locator": "docs/guide.md"},
            "freshnessPolicy": "steward_review",
        },
        actor_agent_id=steward_id,
    )

    payload = unified_knowledge_search_service.search_unified_memory(
        agent_id="agent-1",
        query="Unified Search Guide",
    )
    catalog_hits = [result for result in payload["results"] if result["resultType"] == "public_catalog_card"]
    assert len(catalog_hits) == 1
    hit = catalog_hits[0]
    assert hit["cardId"] == "pin-unified-1"
    assert hit["openRequired"] is True
    assert "content" not in hit
    assert "excerpt" not in hit
    assert hit["locator"] == "docs/guide.md"
    assert hit["summary"] == "Unified search guide summary."
