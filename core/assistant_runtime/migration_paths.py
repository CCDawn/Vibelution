"""Operator-only, existing-source path evidence; never repairs or grants a model access.

Grants JSON has the closed shape {schemaVersion: 1, sourceScope:
{projectId, instanceId, agentId}, grants: [{category, root, revision}]}.
Each root is an exact absolute source, not a recursive permission prefix.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .migration_io import FileSnapshot, MigrationIOError, check_path, fingerprint_tree, path_identity, verify_snapshot

SOURCE_CATEGORIES = (
    "journal", "session_assets", "agent_assets", "memory", "episodic_memory",
    "group_context_events", "dispatch_events", "project_memory_updates", "tool_observations",
    "memory_summaries", "private_knowledge", "mental_model", "inbox", "outbox", "plugins", "personal_affairs",
)
_POLICY_PATHS = {
    "privateMemoryRoot": ("memory", "memory"),
    "episodicEventsPath": ("episodic_memory", "events/episodic_events.jsonl"),
    "groupContextEventsPath": ("group_context_events", "events/group_context_events.jsonl"),
    "agentInboxMessagesPath": ("dispatch_events", "events/agent_inbox_messages.jsonl"),
    "projectMemoryUpdatesPath": ("project_memory_updates", "events/project_memory_updates.jsonl"),
    "toolObservationsPath": ("tool_observations", "events/tool_observations.jsonl"),
    "summariesPath": ("memory_summaries", "memory/summaries.jsonl"),
}
_FILE_CATEGORIES = {"journal", *[category for category, _suffix in _POLICY_PATHS.values() if category != "memory"]}
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


@dataclass
class SourcePaths:
    """Only report is serializable; paths and identities stay in the trusted caller."""

    report: dict
    paths: dict[str, Path]
    _identities: dict[str, tuple] = field(default_factory=dict, repr=False)
    snapshots: dict[str, tuple[FileSnapshot, ...]] = field(default_factory=dict, repr=False)
    directoryproofs: dict[str, tuple[tuple[Path, tuple], ...]] = field(default_factory=dict, repr=False)


def _token(value) -> bool:
    return isinstance(value, str) and bool(_TOKEN.fullmatch(value))


def _path(raw, *, project_root: Path, workspace: Path, absolute=False) -> Path:
    if not isinstance(raw, (str, Path)) or not str(raw).strip():
        raise MigrationIOError("invalid_source_path")
    text = str(raw).strip()
    if text.startswith(("\\\\?\\", "\\\\.\\")) or "\x00" in text:
        raise MigrationIOError("source_path_alias")
    if any(part in {".", ".."} for part in re.split(r"[/\\]", text)):
        raise MigrationIOError("source_path_alias")
    candidate = Path(text)
    if ".." in candidate.parts or any(part.endswith((".", " ")) for part in candidate.parts if part != candidate.anchor):
        raise MigrationIOError("source_path_alias")
    if os.name == "nt" and any(":" in part for part in candidate.parts if part != candidate.anchor):
        raise MigrationIOError("source_path_alias")
    if absolute and not candidate.is_absolute():
        raise MigrationIOError("absolute_source_required")
    if candidate.parts and candidate.parts[0].lower() == "workspace":
        candidate = workspace.joinpath(*candidate.parts[1:])
    elif not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate


def _identity_chain(path: Path) -> tuple:
    """Check the whole lexical chain before resolving; missing is not an empty source."""
    result = []
    for node in (*reversed(path.parents), path):
        try:
            value = node.lstat()
        except FileNotFoundError:
            return tuple(result)
        except OSError:
            raise MigrationIOError("source_unavailable") from None
        if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
            raise MigrationIOError("linked_source")
        if node != path and not stat.S_ISDIR(value.st_mode):
            raise MigrationIOError("source_type_mismatch")
        try:
            result.append((node, path_identity(node)))
        except OSError:
            raise MigrationIOError("source_unavailable_or_changed") from None
    check_path(path)
    return tuple(result)


def _grants(value, scope: dict, project_root: Path, workspace: Path) -> list[dict]:
    if value is None:
        return []
    if (not isinstance(value, dict) or set(value) != {"schemaVersion", "sourceScope", "grants"}
            or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1
            or value["sourceScope"] != scope or not isinstance(value["sourceScope"], dict)
            or not isinstance(value["grants"], list) or len(value["grants"]) > 64):
        raise MigrationIOError("invalid_path_grants")
    result, seen = [], set()
    for entry in value["grants"]:
        if (not isinstance(entry, dict) or set(entry) != {"category", "root", "revision"}
                or entry["category"] not in SOURCE_CATEGORIES
                or not isinstance(entry["root"], str)
                or type(entry["revision"]) is not int or entry["revision"] < 1):
            raise MigrationIOError("invalid_path_grants")
        root = _path(entry["root"], project_root=project_root, workspace=workspace, absolute=True)
        key = (entry["category"], root)
        if key in seen:
            raise MigrationIOError("duplicate_path_grant")
        seen.add(key)
        result.append({**entry, "root": root})
    return result


def _ownership(path: Path, project_root: Path, workspace: Path, agent_id: str, session_id: str) -> None:
    # A malformed declaration or operator typo must not silently scan another Agent.
    for root in (workspace / "agents", project_root / "agents"):
        if path.is_relative_to(root):
            parts = path.relative_to(root).parts
            if not parts or parts[0] != agent_id:
                raise MigrationIOError("foreign_agent_source")
    if path.is_relative_to(workspace / "sessions"):
        parts = path.relative_to(workspace / "sessions").parts
        if not parts or parts[0] != session_id:
            raise MigrationIOError("foreign_session_source")
    if any(root.is_relative_to(path) for root in (project_root, workspace)):
        raise MigrationIOError("source_scope_too_broad")


def _category_status(sources: list[dict], category: str) -> str:
    statuses = [row["status"] for row in sources if row["category"] == category]
    if statuses.count("available") > 1:
        return "conflict"
    return next((state for state in ("unapproved", "unsupported", "available", "missing") if state in statuses), "unsupported")


def resolve_source_paths(*, project_root: Path, workspace: Path, project_id: str, instance_id: str,
                         agent_row: dict, memory_policy: dict | None = None, grants=None) -> SourcePaths:
    """Resolve only the explicitly selected PA snapshot, without loading any registry.

    memory_policy is the raw memoryPolicies[agent_row.memoryPolicyId] snapshot.
    No normalizing getter is called. Grants may also declare an exact extra source,
    including a PersonalAffairs root supplied through the native injected resolver.
    """
    project_root, workspace = Path(project_root), Path(workspace)
    if not project_root.is_absolute() or not workspace.is_absolute():
        raise MigrationIOError("absolute_source_roots_required")
    project_root = _path(project_root, project_root=project_root, workspace=workspace, absolute=True)
    workspace = _path(workspace, project_root=project_root, workspace=workspace, absolute=True)
    for root in (project_root, workspace):
        check_path(root)
        if not root.is_dir():
            raise MigrationIOError("source_type_mismatch")
    if (not _token(project_id) or not _token(instance_id) or not isinstance(agent_row, dict)
            or not _token(agent_row.get("agentId")) or not _token(agent_row.get("directSessionId"))
            or not isinstance(agent_row.get("metadata", {}), dict)
            or agent_row.get("roleKey") != "personal_assistant"
            or agent_row.get("metadata", {}).get("personalAssistantProfile") != "personal_assistant_v1"):
        raise MigrationIOError("assistant_identity_unavailable")
    aid, sid = agent_row["agentId"], agent_row["directSessionId"]
    scope = {"projectId": project_id, "instanceId": instance_id, "agentId": aid}
    allowed = _grants(grants, scope, project_root, workspace)
    candidates: dict[tuple[str, Path], dict] = {}
    issues = []

    def add(category, raw, origin):
        try:
            path = _path(raw, project_root=project_root, workspace=workspace)
        except MigrationIOError as error:
            issues.append({"category": category, "origin": origin, "code": str(error)})
            return
        candidate = candidates.setdefault((category, path), {"category": category, "path": path, "origins": []})
        if origin not in candidate["origins"]:
            candidate["origins"].append(origin)

    def agent_locations(root, origin):
        for category, suffix in (("agent_assets", "artifacts"), ("memory", "memory"), ("mental_model", "mental_model"),
                                 ("inbox", "inbox"), ("outbox", "outbox"), ("plugins", "plugins"),
                                 ("personal_affairs", "plugins/personal-affairs")):
            add(category, root / suffix, origin)
        for category, suffix in _POLICY_PATHS.values():
            add(category, root / suffix, origin)

    agent_locations(workspace / "agents" / aid, "canonical_workspace")
    for key, value in (("declared_workspace", agent_row.get("workspacePath")),
                       ("legacy_workspace", agent_row.get("metadata", {}).get("legacyWorkspacePath"))):
        if value not in (None, ""):
            try:
                agent_locations(_path(value, project_root=project_root, workspace=workspace), key)
            except MigrationIOError as error:
                issues.append({"category": "workspace", "origin": key, "code": str(error)})
    add("journal", workspace / "sessions" / sid / "turn_journal.jsonl", "canonical_session")
    add("session_assets", workspace / "sessions" / sid / "artifacts", "canonical_session")
    add("private_knowledge", workspace / "agents" / aid / "knowledge", "canonical_knowledge_owner")
    add("personal_affairs", project_root / "agents" / aid / "plugins/personal-affairs", "legacy_plugin_default")
    if memory_policy is None:
        memory_policy = agent_row.get("memoryPolicy")
    if memory_policy is None and agent_row.get("memoryPolicyId"):
        issues.append({"category": "memory", "code": "memory_policy_snapshot_required"})
    elif memory_policy is not None:
        if not isinstance(memory_policy, dict) or (memory_policy.get("policyId") and agent_row.get("memoryPolicyId")
                and memory_policy["policyId"] != agent_row["memoryPolicyId"]):
            raise MigrationIOError("invalid_memory_policy_snapshot")
        for field_name, (category, _suffix) in _POLICY_PATHS.items():
            value = memory_policy.get(field_name)
            if value not in (None, ""):
                add(category, value, "memory_policy." + field_name)
    for grant in allowed:
        add(grant["category"], grant["root"], "operator_grant")

    sources, paths, identities = [], {}, {}
    for (category, path), candidate in candidates.items():
        ref = "mps-" + hashlib.sha256(json.dumps([scope, category, str(path)], sort_keys=True).encode()).hexdigest()[:32]
        row = {"sourceRef": ref, "category": category, "root": str(path), "origins": candidate["origins"], "status": "unsupported", "issues": []}
        matching = [grant for grant in allowed if grant["category"] == category and grant["root"] == path]
        if matching:
            row["grantRevision"] = matching[0]["revision"]
        try:
            _ownership(path, project_root, workspace, aid, sid)
            internal = path.is_relative_to(project_root) or path.is_relative_to(workspace)
            if not internal and not matching:
                row["status"] = "unapproved"
                row["issues"].append({"code": "explicit_path_grant_required"})
            else:
                chain = _identity_chain(path)
                if not chain or chain[-1][0] != path:
                    row["status"] = "missing"
                    row["issues"].append({"code": "source_missing"})
                elif (category in _FILE_CATEGORIES) != path.is_file() or (category not in _FILE_CATEGORIES and not path.is_dir()):
                    raise MigrationIOError("source_type_mismatch")
                else:
                    row["status"] = "available"
                    paths[ref], identities[ref] = path, chain
        except MigrationIOError as error:
            row["issues"].append({"code": str(error)})
        sources.append(row)
    statuses = {category: _category_status(sources, category) for category in SOURCE_CATEGORIES}
    return SourcePaths({"schemaVersion": 1, "stage": "source_paths", "sourceScope": scope,
        "sources": sources, "categoryStatus": statuses, "issues": issues,
        "sourceQuiesced": False, "readyForCutover": False}, paths, identities)


def source_snapshot(resolved: SourcePaths, *, max_file_bytes=16 * 1024 * 1024,
                    max_files=10000, max_total_bytes=128 * 1024 * 1024) -> SourcePaths:
    """Fingerprint approved candidates using one shared budget, retaining all conflicts.

    This is a bounded observation, never proof of source quiescence or permission
    for a later import. The caller must revalidate grants and snapshots at handoff.
    """
    if (any(type(n) is not int or n < 1 for n in (max_file_bytes, max_files, max_total_bytes))
            or max_file_bytes > 16 * 1024 * 1024):
        raise MigrationIOError("invalid_source_budget")
    report = json.loads(json.dumps(resolved.report))
    report["stage"] = "source_snapshot"
    paths, snapshots, directoryproofs, remaining_files, remaining_bytes = {}, [], {}, max_files, max_total_bytes
    for row in report["sources"]:
        if row["status"] != "available":
            continue
        ref, path = row["sourceRef"], resolved.paths[row["sourceRef"]]
        try:
            if _identity_chain(path) != resolved._identities[ref]:
                raise MigrationIOError("source_changed")
            if remaining_files < 1 or remaining_bytes < 1:
                raise MigrationIOError("global_source_budget_exhausted")
            files = fingerprint_tree(path, max_file_bytes=max_file_bytes, max_files=remaining_files,
                                     max_total_bytes=remaining_bytes)
            remaining_files -= files.visited_entries
            remaining_bytes -= sum(len(item.raw) for item in files)
            row["entries"] = [{"path": item.path.relative_to(path if path.is_dir() else path.parent).as_posix(),
                               "size": len(item.raw), "sha256": item.sha256} for item in files]
            paths[ref] = path
            snapshots.extend((ref, item) for item in files)
            directoryproofs[ref] = files.directories
        except MigrationIOError as error:
            row["status"] = "unsupported"
            row["issues"].append({"code": str(error)})
            row.pop("entries", None)
            # A failed tree may have consumed part of its budget. Do not allow
            # another candidate to reuse an unmeasured remainder.
            remaining_files = remaining_bytes = 0
    failed = {}
    # Include empty directories: they can change after their own tree scan too.
    for ref, path in paths.items():
        try:
            if _identity_chain(path) != resolved._identities[ref]:
                raise MigrationIOError("source_changed")
            for directory, before in directoryproofs[ref]:
                check_path(directory)
                if path_identity(directory) != before:
                    raise MigrationIOError("source_changed")
        except MigrationIOError as error:
            failed[ref] = str(error)
        except OSError:
            failed[ref] = "source_changed"
    for ref, snapshot in snapshots:
        try:
            verify_snapshot(snapshot)
            if _identity_chain(resolved.paths[ref]) != resolved._identities[ref]:
                raise MigrationIOError("source_changed")
        except MigrationIOError as error:
            failed[ref] = str(error)
    for row in report["sources"]:
        if row["sourceRef"] in failed:
            row["status"] = "unsupported"
            row["issues"].append({"code": failed[row["sourceRef"]]})
            row.pop("entries", None)
            paths.pop(row["sourceRef"], None)
    report["categoryStatus"] = {category: _category_status(report["sources"], category) for category in SOURCE_CATEGORIES}
    report["snapshotComplete"] = not report["issues"] and all(row["status"] == "available" for row in report["sources"])
    return SourcePaths(report, paths, {ref: resolved._identities[ref] for ref in paths},
                       {ref: tuple(snapshot for source_ref, snapshot in snapshots if source_ref == ref) for ref in paths},
                       {ref: directoryproofs[ref] for ref in paths})
