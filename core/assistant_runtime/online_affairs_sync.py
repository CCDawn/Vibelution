"""Host-only coordinator for an approved, already-imported affairs source.

No endpoint or model-facing path exists here. The caller owns the main-only
preview consumption and passes its exact returned binding under the host's
generation/Turn/registry guard. This coordinator never performs first import.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

from .migration_io import MigrationIOError, check_path, pinned_source_files
from .online_affairs_sync_lease import OnlineAffairsSyncOwner, check_affairs_sync_lease

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")
_CATEGORIES = frozenset({"personal_affairs"})


def synchronize_affairs(*, preview_binding, owner: OnlineAffairsSyncOwner, generation: str,
                        turn_id: str, migration_id: str, baseline_migration_id: str) -> dict:
    """Synchronize one consumed HistoryPreview binding with a stable ID.

    ``preview_binding`` is the six-tuple returned by
    ``HistoryPreview.consume_for_import``. It is never accepted from a model
    or renderer. The injected owner guard must authenticate the original Turn,
    current generation, registration and governed approval through completion.
    """
    base = {"schemaVersion": 1, "migrationId": migration_id,
            "sourceQuiesced": False, "readyForCutover": False}
    phase = "validation"
    result = None
    try:
        if (type(owner) is not OnlineAffairsSyncOwner or not isinstance(preview_binding, tuple)
                or len(preview_binding) != 6 or not isinstance(migration_id, str)
                or not _ID.fullmatch(migration_id) or not isinstance(baseline_migration_id, str)
                or not _ID.fullmatch(baseline_migration_id) or migration_id == baseline_migration_id):
            raise MigrationIOError("affairs_sync_request_invalid")
        project, workspace, paths, agent_id, verify, snapshots = preview_binding
        if (not isinstance(project, Path) or not isinstance(workspace, Path)
                or not project.is_absolute() or not workspace.is_absolute()
                or not callable(verify) or not isinstance(snapshots, tuple)
                or Path(paths.project_root) != project):
            raise MigrationIOError("affairs_sync_request_invalid")
        from .migration_affairs_conflicts import _scope, prepare_affairs_conflicts
        from .migration_affairs_sync import reconcile_affairs
        from .migration_active import _selected, _verify_captured
        from .migration_source_archive import import_source_snapshots
        from scripts.assistant_migration_activate import _capture

        scope = _scope({"projectId": paths.project_id, "instanceId": paths.instance_id, "agentId": agent_id})
        with owner.admit(generation=generation, turn_id=turn_id,
                         baseline_migration_id=baseline_migration_id, source_scope=scope) as lease:
            def check():
                check_affairs_sync_lease(lease, source_scope=scope, baseline_migration_id=baseline_migration_id)

            check()
            verify()
            captured, selected_authorities = _capture(project, workspace, scope, None, categories=_CATEGORIES)
            source = _selected(captured, "personal_affairs")
            authority = (*snapshots, *selected_authorities)
            target = check_path(lease.root).resolve()
            for path in (project, workspace, *captured.paths.values(), *(item.path for item in authority)):
                resolved = check_path(path).resolve()
                if target.is_relative_to(resolved) or resolved.is_relative_to(target):
                    raise MigrationIOError("history_source_target_overlap")

            def verify_all():
                check()
                _verify_captured(captured, authority, verify)
                check()

            @contextmanager
            def write_guard():
                verify_all()
                yield
                verify_all()

            verify_all()
            # Pin the exact selected source plus identity/routing authority
            # through archive, difference capture, ledger and receipt commits.
            with pinned_source_files((*authority, source)):
                verify_all()
                phase = "archive"
                archive = import_source_snapshots(captured, lease.root, migration_id,
                    source_roots=(project, workspace), authority_snapshots=authority,
                    authority_verify=verify_all, categories=_CATEGORIES, write_guard=write_guard)
                phase = "prepare"
                differences = prepare_affairs_conflicts(lease, baseline_migration_id=baseline_migration_id,
                    snapshot_migration_id=migration_id, sync_id=migration_id, source_scope=scope)
                verify_all()
                phase = "sync"
                sync = reconcile_affairs(lease, sync_id=migration_id, source_scope=scope)
                result = {**base, "state": "partial" if sync["conflictCount"] else "complete",
                          "code": "unresolved" if sync["conflictCount"] else "synchronized",
                          "archivePublished": bool(archive["published"]),
                          "differenceCount": differences["conflictCount"],
                          "appliedCount": sync["appliedCount"], "conflictCount": sync["conflictCount"],
                          "reused": sync["reused"]}
                phase = "postcheck"
                verify_all()
        return result
    except Exception:
        # Do not leak paths, source content, raw exceptions or approvals. Once
        # a stage starts, a missing acknowledgement never authorizes replay.
        if phase == "validation":
            return {**base, "state": "rejected", "code": "source_or_authority_unavailable"}
        if phase == "archive":
            return {**base, "state": "unknown", "code": "archive_outcome_unknown"}
        if phase == "prepare":
            return {**base, "state": "partial", "code": "difference_outcome_unknown", "archivePublished": True}
        if phase == "sync":
            return {**base, "state": "unknown", "code": "sync_outcome_unknown", "archivePublished": True}
        return {**result, "state": "partial", "code": "postcheck_unconfirmed"}
