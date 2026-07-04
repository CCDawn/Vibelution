from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services import user_content_markdown_service as service


def _write_note(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture()
def routed_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    return tmp_path


def test_preview_import_counts_markdown_links_tasks_and_tags(routed_workspace, tmp_path):
    source = tmp_path / "source"
    _write_note(
        source,
        "Start.md",
        "---\ntags: [alpha, beta]\n---\n# Start\nSee [[Second Page]].\n- [ ] open task\n- [x] done task\n#inline",
    )
    _write_note(source, "Second Page.md", "# Second Page\nBack to [[Start]].")
    _write_note(source, "ignore.txt", "not markdown")

    payload = service.preview_markdown_space_import(str(source))

    assert payload["ok"] is True
    assert payload["summary"]["markdownFileCount"] == 2
    assert payload["summary"]["ignoredFileCount"] == 1
    assert payload["summary"]["wikilinkCount"] == 2
    assert payload["summary"]["taskCount"] == 2
    assert payload["summary"]["tagCount"] == 3
    assert payload["source"]["path"] == str(source.resolve())


def test_import_copies_into_managed_space_and_builds_indexes(routed_workspace, tmp_path):
    source = tmp_path / "source"
    _write_note(source, "Start.md", "# Start\nSee [[Second Page]].\n- [ ] open task\n#alpha")
    _write_note(source, "Second Page.md", "# Second Page\n")

    payload = service.import_markdown_space(str(source), space_name="My Notes")

    assert payload["ok"] is True
    assert payload["space"]["spaceName"] == "My Notes"
    pages_root = Path(payload["space"]["canonicalPagesRoot"])
    assert (pages_root / "Start.md").read_text(encoding="utf-8").startswith("# Start")
    index_root = Path(payload["space"]["indexRoot"])
    page_index = json.loads((index_root / "page_index.json").read_text(encoding="utf-8"))
    assert {item["title"] for item in page_index["pages"]} == {"Start", "Second Page"}
    link_index = json.loads((index_root / "link_index.json").read_text(encoding="utf-8"))
    assert link_index["links"][0]["targetTitle"] == "Second Page"


def test_import_rejects_source_inside_managed_root(routed_workspace):
    managed = service._user_content_root("default")
    nested_source = managed / "incoming"
    nested_source.mkdir(parents=True, exist_ok=True)
    _write_note(nested_source, "Note.md", "# Note")

    with pytest.raises(service.UserContentMarkdownError, match="source_inside_managed_root"):
        service.import_markdown_space(str(nested_source))


def test_search_returns_ranked_excerpts_and_citations(routed_workspace, tmp_path):
    source = tmp_path / "source"
    _write_note(source, "Plan.md", "# Plan\nAgent can use this project reference.\n#agent")
    imported = service.import_markdown_space(str(source), space_name="Reference Notes")

    payload = service.search_user_markdown_spaces(query="agent reference", space_id=imported["space"]["spaceId"], limit=5)

    assert payload["summary"]["resultCount"] == 1
    result = payload["results"][0]
    assert result["resultType"] == "user_markdown_page"
    assert result["sourceDomain"] == "user_content"
    assert result["spaceId"] == imported["space"]["spaceId"]
    assert "Agent can use" in result["excerpt"]
    assert result["citation"]["pageRelativePath"] == "Plan.md"
