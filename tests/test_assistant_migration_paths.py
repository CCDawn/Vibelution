"""Temporary-source contracts: operator authorization, no repair, no body export."""
import json
import os
from pathlib import Path

import pytest

from core.assistant_runtime import migration_paths as owner
from core.assistant_runtime.migration_io import MigrationIOError


def setup_source(tmp_path):
    project = tmp_path / "project"
    workspace = tmp_path / "data/workspace"
    project.mkdir()
    workspace.mkdir(parents=True)
    row = {"agentId": "pa", "directSessionId": "session", "roleKey": "personal_assistant",
           "metadata": {"personalAssistantProfile": "personal_assistant_v1"}}
    return dict(project_root=project, workspace=workspace, project_id="project", instance_id="instance", agent_row=row)


def write(path, body="PRIVATE_SOURCE_BODY"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def grant(args, category, root, revision=1):
    return {"schemaVersion": 1, "sourceScope": {"projectId": args["project_id"], "instanceId": args["instance_id"],
            "agentId": args["agent_row"]["agentId"]}, "grants": [{"category": category, "root": str(root), "revision": revision}]}


def rows(resolved, category):
    return [row for row in resolved.report["sources"] if row["category"] == category]


def disk(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_native_defaults_and_existing_only_snapshot_never_write_or_export_body(tmp_path):
    args = setup_source(tmp_path)
    memory = write(args["workspace"] / "agents/pa/memory/items.jsonl")
    affairs = write(args["project_root"] / "agents/pa/plugins/personal-affairs/affairs/items.jsonl")
    before = disk(tmp_path)
    resolved = owner.resolve_source_paths(**args)
    result = owner.source_snapshot(resolved)
    assert disk(tmp_path) == before
    assert rows(result, "memory")[0]["entries"][0]["size"] == len(memory.read_bytes())
    assert any(row["root"] == str(affairs.parents[1]) and row["status"] == "available" for row in rows(result, "personal_affairs"))
    assert "PRIVATE_SOURCE_BODY" not in json.dumps(result.report)
    assert result.report["readyForCutover"] is False and result.report["sourceQuiesced"] is False
    assert rows(result, "journal")[0]["status"] == "missing"
    memory_ref = rows(result, "memory")[0]["sourceRef"]
    assert result.snapshots[memory_ref][0].raw == memory.read_bytes()


def test_source_snapshot_is_incomplete_when_available_candidates_conflict(tmp_path):
    first = tmp_path / "first-memory"
    second = tmp_path / "second-memory"
    write(first / "one.jsonl")
    write(second / "two.jsonl")
    candidates = [
        {"sourceRef": "mps-first", "category": "memory", "root": str(first),
         "origins": ["operator_grant"], "status": "available", "issues": []},
        {"sourceRef": "mps-second", "category": "memory", "root": str(second),
         "origins": ["operator_grant"], "status": "available", "issues": []},
    ]
    paths = {row["sourceRef"]: Path(row["root"]) for row in candidates}
    resolved = owner.SourcePaths(
        {"sources": candidates, "categoryStatus": {"memory": "conflict"}, "issues": []},
        paths,
        {ref: owner._identity_chain(path) for ref, path in paths.items()},
    )

    result = owner.source_snapshot(resolved)

    assert result.report["categoryStatus"]["memory"] == "conflict"
    assert result.report["snapshotComplete"] is False
    assert [row["status"] for row in result.report["sources"]] == ["available", "available"]
    assert set(result.snapshots) == set(paths)


def test_declared_and_legacy_workspace_preserve_candidates_and_conflicts(tmp_path):
    args = setup_source(tmp_path)
    write(args["workspace"] / "agents/pa/memory/default.jsonl")
    write(args["project_root"] / "custom-pa/memory/declared.jsonl")
    write(args["project_root"] / "old-pa/memory/old.jsonl")
    args["agent_row"]["workspacePath"] = "custom-pa"
    args["agent_row"]["metadata"]["legacyWorkspacePath"] = "old-pa"
    result = owner.resolve_source_paths(**args)
    assert len(rows(result, "memory")) == 3
    assert result.report["categoryStatus"]["memory"] == "conflict"
    assert args["agent_row"]["workspacePath"] == "custom-pa"
    # Private KB has its own canonical owner, independent of workspacePath.
    assert len(rows(result, "private_knowledge")) == 1


def test_workspace_prefix_uses_explicit_active_workspace_without_seed(tmp_path):
    args = setup_source(tmp_path)
    args["agent_row"]["workspacePath"] = "workspace/agents/pa"
    result = owner.resolve_source_paths(**args)
    assert len(rows(result, "memory")) == 1
    assert rows(result, "memory")[0]["origins"] == ["canonical_workspace", "declared_workspace"]


def test_raw_memory_policy_paths_are_preserved_without_normalization(tmp_path):
    args = setup_source(tmp_path)
    write(args["project_root"] / "custom-memory/a.jsonl")
    event = write(args["project_root"] / "old-events/episodes.jsonl")
    policy = {"policyId": "policy", "privateMemoryRoot": "custom-memory", "episodicEventsPath": str(event)}
    args["agent_row"]["memoryPolicyId"] = "policy"
    result = owner.resolve_source_paths(**args, memory_policy=policy)
    assert any(row["root"] == str(event) and row["status"] == "available" for row in rows(result, "episodic_memory"))
    assert any(row["origins"] == ["memory_policy.privateMemoryRoot"] for row in rows(result, "memory"))
    assert policy["privateMemoryRoot"] == "custom-memory"
    assert owner.resolve_source_paths(**args).report["issues"][0]["code"] == "memory_policy_snapshot_required"


def test_external_declaration_is_not_permission_and_no_unauthorized_stat(tmp_path, monkeypatch):
    args = setup_source(tmp_path)
    outside = tmp_path / "external/memory"
    args["agent_row"]["workspacePath"] = str(outside.parent)
    original = owner._identity_chain
    def checking(path):
        assert not path.is_relative_to(outside.parent)
        return original(path)
    monkeypatch.setattr(owner, "_identity_chain", checking)
    result = owner.resolve_source_paths(**args)
    assert next(row for row in rows(result, "memory") if row["root"] == str(outside))["status"] == "unapproved"


def test_exact_grant_authorizes_only_one_category_and_root(tmp_path):
    args = setup_source(tmp_path)
    external = write(tmp_path / "external/memory/private.jsonl").parent
    args["agent_row"]["workspacePath"] = str(external.parent)
    result = owner.resolve_source_paths(**args, grants=grant(args, "memory", external, 4))
    selected = next(row for row in rows(result, "memory") if row["root"] == str(external))
    assert selected["status"] == "available" and selected["grantRevision"] == 4
    assert any(row["status"] == "unapproved" for row in rows(result, "episodic_memory"))
    assert str(external) in [str(path) for path in result.paths.values()]


def test_operator_can_declare_native_injected_plugin_or_private_kb_source(tmp_path):
    args = setup_source(tmp_path)
    plugin = write(tmp_path / "external/personal-affairs/affairs/items.jsonl").parents[1]
    result = owner.resolve_source_paths(**args, grants=grant(args, "personal_affairs", plugin))
    assert any(row["root"] == str(plugin) and row["origins"] == ["operator_grant"] for row in rows(result, "personal_affairs"))
    kb = write(tmp_path / "private-kb/knowledge_bases.json").parent
    result = owner.resolve_source_paths(**args, grants=grant(args, "private_knowledge", kb))
    assert any(row["root"] == str(kb) and row["status"] == "available" for row in rows(result, "private_knowledge"))


@pytest.mark.parametrize("change", ["extra", "scope", "version", "category", "revision", "relative", "duplicate"])
def test_grants_are_closed_and_bound_to_selected_source(tmp_path, change):
    args = setup_source(tmp_path)
    value = grant(args, "memory", tmp_path / "external")
    if change == "extra": value["arbitrary"] = True
    elif change == "scope": value["sourceScope"]["agentId"] = "other"
    elif change == "version": value["schemaVersion"] = True
    elif change == "category": value["grants"][0]["category"] = "workspace"
    elif change == "revision": value["grants"][0]["revision"] = True
    elif change == "relative": value["grants"][0]["root"] = "relative"
    else: value["grants"].append(dict(value["grants"][0]))
    with pytest.raises(MigrationIOError):
        owner.resolve_source_paths(**args, grants=value)


@pytest.mark.parametrize("raw", ["../outside", "custom/../memory", "custom/./memory", "bad./memory", 42, ["memory"]])
def test_path_aliases_and_malformed_declarations_are_explicitly_unsupported(tmp_path, raw):
    args = setup_source(tmp_path)
    args["agent_row"]["workspacePath"] = raw
    result = owner.resolve_source_paths(**args)
    assert result.report["issues"]
    assert result.report["issues"][0]["origin"] == "declared_workspace"


def test_foreign_agent_or_session_cannot_be_read_even_with_operator_typo(tmp_path):
    args = setup_source(tmp_path)
    foreign = write(args["workspace"] / "agents/other/memory/private.jsonl").parent
    result = owner.resolve_source_paths(**args, grants=grant(args, "memory", foreign))
    selected = next(row for row in rows(result, "memory") if row["root"] == str(foreign))
    assert selected["status"] == "unsupported" and selected["issues"][0]["code"] == "foreign_agent_source"
    other_session = write(args["workspace"] / "sessions/other/turn_journal.jsonl")
    result = owner.resolve_source_paths(**args, grants=grant(args, "journal", other_session))
    assert any(row["issues"] == [{"code": "foreign_session_source"}] for row in rows(result, "journal"))


def test_missing_declared_source_is_retained_and_not_fallen_back(tmp_path):
    args = setup_source(tmp_path)
    args["agent_row"]["workspacePath"] = "deleted-pa"
    result = owner.resolve_source_paths(**args)
    assert len(rows(result, "memory")) == 2
    assert all(row["status"] == "missing" for row in rows(result, "memory"))
    assert not result.paths


def test_linked_source_or_parent_chain_is_rejected(tmp_path):
    args = setup_source(tmp_path)
    outside = write(tmp_path / "outside/a.jsonl").parent
    link = args["project_root"] / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("native symlink privilege unavailable")
    result = owner.resolve_source_paths(**args, memory_policy={"privateMemoryRoot": "link"})
    assert any(row["issues"] == [{"code": "linked_source"}] for row in rows(result, "memory"))


def test_parent_replacement_after_resolution_invalidates_snapshot(tmp_path):
    args = setup_source(tmp_path)
    memory = write(args["workspace"] / "agents/pa/memory/a.jsonl").parent
    resolved = owner.resolve_source_paths(**args)
    memory.rename(memory.with_name("old-memory"))
    write(memory / "a.jsonl", "REPLACEMENT")
    result = owner.source_snapshot(resolved)
    assert rows(result, "memory")[0]["status"] == "unsupported"
    assert "source_changed" in json.dumps(result.report)
    assert "REPLACEMENT" not in json.dumps(result.report)


@pytest.mark.parametrize("budget", [{"max_file_bytes": 2}, {"max_files": 1}, {"max_total_bytes": 2}])
def test_source_budgets_fail_closed(tmp_path, budget):
    args = setup_source(tmp_path)
    write(args["workspace"] / "agents/pa/memory/a.jsonl")
    write(args["workspace"] / "agents/pa/memory/b.jsonl")
    result = owner.source_snapshot(owner.resolve_source_paths(**args), **budget)
    assert result.report["snapshotComplete"] is False
    assert rows(result, "memory")[0]["status"] == "unsupported"


def test_global_file_budget_applies_across_separate_sources(tmp_path):
    args = setup_source(tmp_path)
    write(args["workspace"] / "agents/pa/memory/a.jsonl")
    write(args["workspace"] / "agents/pa/mental_model/b.jsonl")
    result = owner.source_snapshot(owner.resolve_source_paths(**args), max_files=1)
    assert rows(result, "memory")[0]["status"] == "available"
    assert rows(result, "mental_model")[0]["status"] == "unsupported"


def test_changes_during_later_source_scan_invalidate_prior_evidence(tmp_path, monkeypatch):
    args = setup_source(tmp_path)
    memory = write(args["workspace"] / "agents/pa/memory/a.jsonl")
    other = write(args["workspace"] / "agents/pa/mental_model/b.jsonl")
    original = owner.fingerprint_tree
    def changing(path, **kwargs):
        result = original(path, **kwargs)
        if path == other.parent:
            memory.write_text("CHANGED", encoding="utf-8")
        return result
    monkeypatch.setattr(owner, "fingerprint_tree", changing)
    result = owner.source_snapshot(owner.resolve_source_paths(**args))
    assert rows(result, "memory")[0]["status"] == "unsupported"
    assert "entries" not in rows(result, "memory")[0]


def test_hardlinked_file_is_not_a_safe_snapshot(tmp_path):
    args = setup_source(tmp_path)
    memory = write(args["workspace"] / "agents/pa/memory/a.jsonl")
    try:
        os.link(memory, tmp_path / "hardlink.jsonl")
    except OSError:
        pytest.skip("hardlinks unavailable")
    result = owner.source_snapshot(owner.resolve_source_paths(**args))
    assert rows(result, "memory")[0]["status"] == "unsupported"


def test_wrong_native_source_type_is_not_an_available_empty_ledger(tmp_path):
    args = setup_source(tmp_path)
    path = args["workspace"] / "sessions/session/turn_journal.jsonl"
    path.mkdir(parents=True)
    result = owner.resolve_source_paths(**args)
    assert rows(result, "journal")[0]["status"] == "unsupported"
    assert rows(result, "journal")[0]["issues"] == [{"code": "source_type_mismatch"}]


def test_global_traversal_budget_counts_directories_across_roots(tmp_path):
    args = setup_source(tmp_path)
    (args["workspace"] / "agents/pa/memory/empty-child").mkdir(parents=True)
    write(args["workspace"] / "agents/pa/mental_model/a.jsonl")
    result = owner.source_snapshot(owner.resolve_source_paths(**args), max_files=1)
    assert rows(result, "memory")[0]["status"] == "available"
    assert rows(result, "mental_model")[0]["status"] == "unsupported"


def test_empty_source_changes_during_later_scan_are_detected(tmp_path, monkeypatch):
    args = setup_source(tmp_path)
    memory = args["workspace"] / "agents/pa/memory"
    memory.mkdir(parents=True)
    other = write(args["workspace"] / "agents/pa/mental_model/b.jsonl")
    original = owner.fingerprint_tree
    def changing(path, **kwargs):
        result = original(path, **kwargs)
        if path == other.parent:
            write(memory / "late.jsonl")
        return result
    monkeypatch.setattr(owner, "fingerprint_tree", changing)
    result = owner.source_snapshot(owner.resolve_source_paths(**args))
    assert rows(result, "memory")[0]["status"] == "unsupported"
    assert "entries" not in rows(result, "memory")[0]
    assert rows(result, "memory")[0]["sourceRef"] not in result.snapshots


def test_nested_empty_directory_changes_during_later_scan_are_detected(tmp_path, monkeypatch):
    args = setup_source(tmp_path)
    memory = args["workspace"] / "agents/pa/memory"
    nested = memory / "empty/deeper"
    nested.mkdir(parents=True)
    other = write(args["workspace"] / "agents/pa/mental_model/b.jsonl")
    original = owner.fingerprint_tree
    def changing(path, **kwargs):
        result = original(path, **kwargs)
        if path == other.parent:
            write(nested / "late.jsonl")
        return result
    monkeypatch.setattr(owner, "fingerprint_tree", changing)
    result = owner.source_snapshot(owner.resolve_source_paths(**args))
    assert rows(result, "memory")[0]["status"] == "unsupported"
    assert rows(result, "memory")[0]["issues"][-1]["code"] == "source_changed"
    assert rows(result, "memory")[0]["sourceRef"] not in result.snapshots
