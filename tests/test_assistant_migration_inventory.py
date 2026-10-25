"""A source inventory is evidence, never a cutover or a transcript importer."""
import hashlib
import json
from pathlib import Path

import pytest

from core.assistant_runtime.migration_inventory import InventoryError, inventory_sources


AGENT = "agent-source"
SESSION = "session-source"


def source(tmp_path):
    workspace = tmp_path / "data/workspace"
    registry = workspace / "agents/agents.json"
    registry.parent.mkdir(parents=True)
    row = {"agentId": AGENT, "directSessionId": SESSION, "roleKey": "personal_assistant", "status": "active",
           "metadata": {"personalAssistantProfile": "personal_assistant_v1"}, "toolPolicy": {"allowedTools": []}}
    registry.write_text(json.dumps({"agents": [row]}), encoding="utf-8")
    journal = workspace / "sessions" / SESSION / "turn_journal.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text('{"private_prompt":"NEVER_EXPOSE_THIS"}\n', encoding="utf-8")
    memory = workspace / "agents" / AGENT / "memory/private.jsonl"
    memory.parent.mkdir(parents=True)
    memory.write_text('{"text":"PRIVATE_MEMORY_BODY"}\n', encoding="utf-8")
    episodes = workspace / "agents" / AGENT / "events/episodic_events.jsonl"
    episodes.parent.mkdir(parents=True)
    episodes.write_text('{"text":"PRIVATE_EPISODIC_BODY"}\n', encoding="utf-8")
    return workspace, registry, row, journal


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def inspect(tmp_path, workspace, **kwargs):
    return inventory_sources(project_root=tmp_path, workspace=workspace,
        project_id="project", instance_id="instance", **kwargs)


def test_inventory_hashes_only_selected_sources_without_any_write(tmp_path):
    workspace, _, _, journal = source(tmp_path)
    other = workspace / "agents/agent-other/memory/private.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text("OTHER_AGENT_BODY", encoding="utf-8")
    before = snapshot(tmp_path)
    report = inspect(tmp_path, workspace)
    assert snapshot(tmp_path) == before
    assert report["stage"] == "inventory"
    assert report["readyForCutover"] is False and report["sourceQuiesced"] is False
    candidate = report["candidates"][0]
    assert candidate["agentId"] == AGENT and candidate["sessionId"] == SESSION
    assert candidate["files"]["journal"]["entries"][0]["sha256"] == hashlib.sha256(journal.read_bytes()).hexdigest()
    assert len(candidate["files"]["episodic_memory"]["entries"]) == 1
    serialized = json.dumps(report)
    assert all(text not in serialized for text in ("NEVER_EXPOSE_THIS", "PRIVATE_MEMORY_BODY", "PRIVATE_EPISODIC_BODY", "OTHER_AGENT_BODY", "agent-other"))
    assert "legacy_dispatch_handoff" in report["pendingChecks"]


def test_no_silent_selection_when_two_active_assistants_exist(tmp_path):
    workspace, registry, row, _ = source(tmp_path)
    second = {**row, "agentId": "agent-second", "directSessionId": "session-second"}
    registry.write_text(json.dumps({"agents": [row, second]}), encoding="utf-8")
    report = inspect(tmp_path, workspace)
    assert report["selectionRequired"] is True
    assert len(report["candidates"]) == 2
    assert report["readyForCutover"] is False


@pytest.mark.parametrize("field,value", [("agentId", "../other"), ("directSessionId", "../session"),
    ("agentId", ""), ("metadata", []), ("toolPolicy", []), ("status", {"prompt": "PRIVATE_STATUS_BODY"}),
    ("status", "PRIVATE_STATUS_BODY")])
def test_malformed_identity_denies_before_traversing_private_sources(tmp_path, field, value):
    workspace, registry, row, _ = source(tmp_path)
    registry.write_text(json.dumps({"agents": [{**row, field: value}]}), encoding="utf-8")
    with pytest.raises(InventoryError):
        inspect(tmp_path, workspace)


def test_missing_corrupt_registry_and_missing_journal_never_mean_empty_history(tmp_path):
    workspace, registry, _, journal = source(tmp_path)
    journal.unlink()
    report = inspect(tmp_path, workspace)
    assert report["candidates"][0]["files"]["journal"]["available"] is False
    registry.write_text("broken", encoding="utf-8")
    with pytest.raises(InventoryError):
        inspect(tmp_path, workspace)
    registry.unlink()
    with pytest.raises(InventoryError):
        inspect(tmp_path, workspace)


def test_limits_and_links_are_explicitly_incomplete(tmp_path):
    workspace, _, _, _ = source(tmp_path)
    report = inspect(tmp_path, workspace, max_file_bytes=4)
    assert any(r["code"] == "file_too_large" for r in report["candidates"][0]["files"]["journal"]["issues"])
    assert report["candidates"][0]["inventoryComplete"] is False
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("OUTSIDE", encoding="utf-8")
    link = workspace / "agents" / AGENT / "memory/link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("native symlink privilege unavailable")
    report = inspect(tmp_path, workspace)
    assert any(r["code"] == "linked_source" for r in report["candidates"][0]["files"]["memory"]["issues"])
    assert "secret.txt" not in json.dumps(report)


def test_source_change_during_hash_is_detected(tmp_path, monkeypatch):
    from core.assistant_runtime import migration_inventory as owner
    workspace, _, _, journal = source(tmp_path)
    original = owner._hash_file
    def changing(path, size):
        digest = original(path, size)
        if path == journal:
            path.write_text("changed", encoding="utf-8")
        return digest
    monkeypatch.setattr(owner, "_hash_file", changing)
    report = inspect(tmp_path, workspace)
    assert report["candidates"][0]["inventoryComplete"] is False
    assert any(r["code"] == "source_changed" for r in report["candidates"][0]["files"]["journal"]["issues"])


def test_registry_session_conflict_is_not_a_license_to_read_other_agents(tmp_path):
    workspace, registry, row, _ = source(tmp_path)
    registry.write_text(json.dumps({"agents": [row, {"agentId": "other", "directSessionId": SESSION}]}), encoding="utf-8")
    with pytest.raises(InventoryError):
        inspect(tmp_path, workspace)


def test_hash_is_bounded_when_a_live_source_grows(tmp_path):
    from core.assistant_runtime import migration_inventory as owner
    path = tmp_path / "growing.jsonl"
    path.write_bytes(b"123456")
    with pytest.raises(InventoryError, match="source_changed"):
        owner._hash_file(path, 3)
    with pytest.raises(InventoryError, match="source_changed"):
        owner._hash_file(path, 9)


def test_invalid_files_count_towards_inventory_bound(tmp_path):
    workspace, _, _, _ = source(tmp_path)
    memory = workspace / "agents" / AGENT / "memory"
    for number in range(7):
        (memory / f"large-{number}.jsonl").write_bytes(b"12345")
    result = inspect(tmp_path, workspace, max_file_bytes=4, max_files=2)["candidates"][0]["files"]["memory"]
    assert len(result["issues"]) <= 3
    assert any(issue["code"] == "file_limit" for issue in result["issues"])


def test_registry_growth_read_is_capped(tmp_path, monkeypatch):
    import io
    workspace, registry, _, _ = source(tmp_path)
    original = Path.open
    class Growing(io.BytesIO):
        def read(self, size=-1):
            assert size == 16 * 1024 * 1024 + 1
            return b"x" * size
    def opening(path, *args, **kwargs):
        return Growing() if path == registry else original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", opening)
    with pytest.raises(InventoryError):
        inspect(tmp_path, workspace)


def test_journal_directory_is_not_an_available_native_history(tmp_path):
    workspace, _, _, journal = source(tmp_path)
    journal.unlink()
    journal.mkdir()
    result = inspect(tmp_path, workspace)["candidates"][0]
    assert result["inventoryComplete"] is False
    assert result["files"]["journal"]["issues"][0]["code"] == "source_type_mismatch"
