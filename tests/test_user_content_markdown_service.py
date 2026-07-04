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


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation unsupported in this environment: {exc}")


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


def test_overwrite_keeps_backup_hidden_from_lists_and_search(routed_workspace, tmp_path):
    first_source = tmp_path / "source-first"
    second_source = tmp_path / "source-second"
    _write_note(first_source, "Plan.md", "# Plan\nlegacy backup phrase only\n")
    _write_note(second_source, "Plan.md", "# Plan\nfresh canonical phrase only\n")

    first_import = service.import_markdown_space(str(first_source), space_name="Team Notes")
    second_import = service.import_markdown_space(str(second_source), space_name="Team Notes", overwrite=True)

    assert first_import["space"]["spaceId"] == second_import["space"]["spaceId"]

    listed = service.list_markdown_spaces()

    assert listed["summary"]["spaceCount"] == 1
    assert [space["spaceId"] for space in listed["spaces"]] == [second_import["space"]["spaceId"]]

    old_search = service.search_user_markdown_spaces(query="legacy backup phrase", space_id=second_import["space"]["spaceId"], limit=5)
    new_search = service.search_user_markdown_spaces(query="fresh canonical phrase", space_id=second_import["space"]["spaceId"], limit=5)

    assert old_search["summary"]["resultCount"] == 0
    assert new_search["summary"]["resultCount"] == 1
    assert "fresh canonical phrase" in new_search["results"][0]["excerpt"]


def test_import_assigns_distinct_page_ids_for_distinct_relative_paths(routed_workspace, tmp_path):
    source = tmp_path / "source"
    _write_note(source, "a/b.md", "# Nested Page\ncontent from nested path\n")
    _write_note(source, "a-b.md", "# Flat Page\ncontent from flat path\n")

    imported = service.import_markdown_space(str(source), space_name="Collision Check")
    pages_payload = service.list_markdown_space_pages(imported["space"]["spaceId"])
    page_by_path = {page["relativePath"]: page for page in pages_payload["pages"]}

    nested_page = page_by_path["a/b.md"]
    flat_page = page_by_path["a-b.md"]

    assert nested_page["pageId"] != flat_page["pageId"]

    nested_content = service.get_markdown_space_page(imported["space"]["spaceId"], nested_page["pageId"])
    flat_content = service.get_markdown_space_page(imported["space"]["spaceId"], flat_page["pageId"])

    assert nested_content["page"]["relativePath"] == "a/b.md"
    assert "nested path" in nested_content["page"]["content"]
    assert flat_content["page"]["relativePath"] == "a-b.md"
    assert "flat path" in flat_content["page"]["content"]


def test_import_skips_symlinked_markdown_file_pointing_outside_source(routed_workspace, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    leaked = _write_note(outside, "Leaked.md", "# Leaked\noutside secret phrase\n")
    _write_note(source, "Inside.md", "# Inside\nsafe phrase\n")
    _symlink_or_skip(source / "Leaked.md", leaked)

    preview = service.preview_markdown_space_import(str(source))
    imported = service.import_markdown_space(str(source), space_name="Boundary Notes")

    assert preview["summary"]["markdownFileCount"] == 1
    assert any(row["relativePath"] == "Leaked.md" and row["reason"] == "symlink" for row in preview["ignoredFiles"])

    search = service.search_user_markdown_spaces(query="outside secret phrase", space_id=imported["space"]["spaceId"])
    assert search["summary"]["resultCount"] == 0
    pages_payload = service.list_markdown_space_pages(imported["space"]["spaceId"])
    assert [page["relativePath"] for page in pages_payload["pages"]] == ["Inside.md"]


def test_import_does_not_traverse_symlinked_directory_outside_source(routed_workspace, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside-dir"
    _write_note(source, "Inside.md", "# Inside\nsafe phrase\n")
    _write_note(outside, "Nested.md", "# Nested\noutside directory phrase\n")
    _symlink_or_skip(source / "linked", outside, target_is_directory=True)

    preview = service.preview_markdown_space_import(str(source))
    imported = service.import_markdown_space(str(source), space_name="Directory Boundary")

    assert preview["summary"]["markdownFileCount"] == 1
    assert any(row["relativePath"] == "linked" and row["reason"] == "symlink_directory" for row in preview["ignoredFiles"])

    search = service.search_user_markdown_spaces(query="outside directory phrase", space_id=imported["space"]["spaceId"])
    assert search["summary"]["resultCount"] == 0
