"""memory.* path fields are retired; WorkspaceManager owns the paths.

The three path fields looked authoritative on the config panel, but
tools/memory_tools.py resolves through WorkspaceManager and the
VIBELUTION_MEMORY_INDEX_PATH override. Wiring the fields would silently
move persisted memory, so the contract is retirement plus a precedence
test that pins the real authority.
"""

from __future__ import annotations

import importlib

from config.models import MemoryConfig

memory_tools = importlib.import_module("tools.memory_tools")


def test_path_fields_are_marked_retired():
    for name in ("storage_dir", "memory_file", "archive_dir"):
        description = MemoryConfig.model_fields[name].description or ""
        assert "已退役" in description, name


def test_history_persistence_is_marked_retired():
    description = MemoryConfig.model_fields["history_persistence"].description or ""
    assert "已退役" in description


def test_env_override_wins_over_config(monkeypatch, tmp_path):
    target = tmp_path / "custom-memory.json"
    monkeypatch.setenv("VIBELUTION_MEMORY_INDEX_PATH", str(target))

    assert memory_tools._get_memory_index_path() == str(target)
