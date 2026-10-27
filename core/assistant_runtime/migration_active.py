"""Explicit, offline promotion of selected PA-owned personal data snapshots.

The caller authenticates the selected project/instance and supplies its stable
registry and route proof. The model cannot invoke this internal operator API.
Promotion is a reversible migration step, not source quiescence or cutover.
"""
from __future__ import annotations

from pathlib import Path

from .migration_io import MigrationIOError, check_path, path_identity, strict_json, verify_snapshot
from .migration_paths import SourcePaths, _identity_chain
from .migration_profile import OfflineMigrationProfileLease


def _verify_captured(captured, authority_snapshots, authority_verify):
    authority_verify()
    for snapshot in authority_snapshots:
        verify_snapshot(snapshot)
    for ref, path in captured.paths.items():
        if _identity_chain(path) != captured._identities.get(ref):
            raise MigrationIOError("source_changed")
        for directory, before in captured.directoryproofs.get(ref, ()):
            check_path(directory)
            if path_identity(directory) != before:
                raise MigrationIOError("source_changed")
        for snapshot in captured.snapshots.get(ref, ()):
            verify_snapshot(snapshot)
    authority_verify()


def _selected(captured, category):
    if captured.report.get("categoryStatus", {}).get(category) != "available":
        raise MigrationIOError("active_source_unavailable")
    rows = [row for row in captured.report.get("sources", [])
            if row.get("category") == category and row.get("status") == "available"]
    if len(rows) != 1 or rows[0].get("sourceRef") not in captured.paths:
        raise MigrationIOError("active_source_ambiguous")
    ref = rows[0]["sourceRef"]
    snapshots = captured.snapshots.get(ref, ())
    if category == "episodic_memory":
        if len(snapshots) != 1:
            raise MigrationIOError("active_source_unavailable")
        return snapshots[0]
    root = captured.paths[ref]
    files = {item.path.relative_to(root).as_posix(): item for item in snapshots}
    if set(files) - {"affairs/items.jsonl", "affairs/items.jsonl.lock"}:
        raise MigrationIOError("affairs_extra_state_unhandled")
    if "affairs/items.jsonl" not in files:
        raise MigrationIOError("active_source_unavailable")
    return files["affairs/items.jsonl"]


def activate_personal_snapshot(lease, captured: SourcePaths, *, migration_id: str,
        source_roots, authority_snapshots=(), authority_verify=None) -> dict:
    """Archive and import validated episodes/affairs for one selected old PA.

    The caller is responsible for the source project's physical route proof;
    a checked registry snapshot independently binds its selected PA identity.
    The target is already exclusively locked by ``offline_migration_profile``.
    Separate native ledger commits are reported individually on partial failure.
    """
    if type(lease) is not OfflineMigrationProfileLease or not isinstance(captured, SourcePaths):
        raise MigrationIOError("active_profile_or_source_invalid")
    lease.check()
    roots = tuple(Path(root) for root in source_roots)
    if len(roots) != 2 or not callable(authority_verify):
        raise MigrationIOError("source_authority_required")
    project, workspace = roots
    scope = captured.report.get("sourceScope")
    registry_path = workspace / "agents/agents.json"
    registry = [snapshot for snapshot in authority_snapshots if snapshot.path == registry_path]
    if len(registry) != 1 or not isinstance(scope, dict):
        raise MigrationIOError("source_authority_required")
    from .migration_inventory import declared_assistant_identities
    payload = strict_json(registry[0].raw)
    if (not isinstance(payload, dict) or not any(row["agentId"] == scope.get("agentId")
            for row in declared_assistant_identities(payload.get("agents")))):
        raise MigrationIOError("assistant_identity_unavailable")
    if captured.report.get("stage") != "source_snapshot":
        raise MigrationIOError("source_snapshot_required")
    episode, affairs = _selected(captured, "episodic_memory"), _selected(captured, "personal_affairs")
    from . import migration_affairs, migration_episodic
    # Validate every selected source before publishing even the archive, so an
    # invalid second category cannot leave an avoidable partial active import.
    migration_episodic._parse_rows(episode.raw, scope["agentId"])
    migration_affairs._parse_rows(affairs.raw)
    _verify_captured(captured, authority_snapshots, authority_verify)
    from .migration_source_archive import import_source_snapshots
    archive = import_source_snapshots(captured, lease.root, migration_id,
        source_roots=roots, authority_snapshots=authority_snapshots, authority_verify=authority_verify)
    result = {"status": "complete", "archive": archive, "sourceScope": scope,
              "sourceQuiesced": False, "readyForCutover": False}
    for category, snapshot, adapter in (("episodic", episode, migration_episodic.import_episodic),
                                       ("affairs", affairs, migration_affairs.import_affairs)):
        try:
            lease.check()
            _verify_captured(captured, authority_snapshots, authority_verify)
            result[category] = adapter(lease, snapshot.raw, source_scope=scope,
                source_sha256=snapshot.sha256, migration_id=migration_id)
            _verify_captured(captured, authority_snapshots, authority_verify)
        except MigrationIOError as error:
            result.update(status="partial", failedCategory=category, reason=str(error))
            return result
    return result
