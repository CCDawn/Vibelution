"""Workspace file tree and preview JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.file_models import FileContentResponse, FileTreeNode


def test_file_route_models_publish_known_schema_fields() -> None:
    expected_properties = {
        FileTreeNode: {"name", "path", "type"},
        FileContentResponse: {"path", "language", "content", "truncated"},
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_file_tree_node_keeps_unknown_fields() -> None:
    payload = FileTreeNode.model_validate(
        {
            "name": "core",
            "path": "core",
            "type": "directory",
            "children": [{"name": "web", "path": "core/web", "type": "directory"}],
        }
    ).model_dump()

    assert payload["children"] == [
        {"name": "web", "path": "core/web", "type": "directory"}
    ]
