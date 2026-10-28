"""Read-only, short-lived identities for a registered legacy reminder source.

Only trusted in-process callers may use this module. It accepts a registered
project ID, never a caller-supplied path or Agent ID. An observation describes
the currently resolved files, not the executable or data home of a live sender;
it is neither notification admission nor authority to transfer execution.
"""
from __future__ import annotations

import os
from pathlib import Path

from .initial_migration_binding import _digest, _directory
from .migration_io import MigrationIOError, read_stable_file, strict_json, verify_snapshot
from .migration_paths import _identity_chain

# Native writes retain at most 2048 rows. Their three bounded user strings
# (title 160, note 600, sourceTurnId 200 characters) need at most six UTF-8
# bytes per character after JSON escaping; fixed fields and UTC timestamps fit
# within a further 512 bytes per row. 2048 * (6 * 960 + 512) < 16 MiB.
# This is the existing stable-reader ceiling, not an unlimited ledger claim;
# externally expanded/legacy rows beyond it remain unavailable.
_LEDGER_LIMIT = 16 * 1024 * 1024


def _path_key(path: Path) -> str:
    text = str(path)
    return text.casefold() if os.name == "nt" else text


class ReminderSourceObservation:
    """Private preview-backed handle; revalidate immediately before comparison."""

    __slots__ = ("agent_id", "ready_for_cutover", "_ledger", "_authority", "_verify", "_preview", "_token", "_closed")

    def __init__(self, agent_id, ledger, authority, verify, preview, token):
        self.agent_id = agent_id
        self.ready_for_cutover = False
        self._ledger, self._authority, self._verify = ledger, authority, verify
        self._preview, self._token, self._closed = preview, token, False

    def close(self):
        if not self._closed:
            self._closed = True
            self._preview.discard(self._token)

    def __enter__(self):
        if self._closed:
            raise MigrationIOError("reminder_source_observation_closed")
        return self

    def __exit__(self, *args):
        self.close()

    def _check(self):
        if self._closed:
            raise MigrationIOError("reminder_source_observation_closed")
        try:
            self._verify()
        except Exception:
            raise MigrationIOError("reminder_source_observation_changed") from None


def observe_reminder_source(dispatch, preview, project_id: str, revision: int) -> ReminderSourceObservation:
    """Observe an admitted registration and its canonical native affairs ledger.

    The verified HistoryPreview supplies registration, config, workspace,
    registry, and routing; this function never accepts source paths from a
    renderer or model. Missing/ambiguous metadata and missing files fail closed.
    The observation expires with its preview and must be closed by its caller.
    """
    if (getattr(preview, "_dispatch", None) is not dispatch or type(revision) is not int
            or revision < 0 or getattr(dispatch, "_registry_revision", None) != revision):
        raise MigrationIOError("reminder_source_unavailable")
    token = None
    try:
        public = preview.preview(project_id)
        token = public["previewId"]
        with preview._lock:
            public = preview.verify_preview(token)
            row = preview._previews[token]
            root, workspace, snapshots = Path(row[3]), Path(row[4]), row[7]
            agent_id = public["assistantAgentId"]
            registry_path = workspace / "agents/agents.json"
            registry = next(s for s in snapshots if s.path == registry_path)
            value = strict_json(registry.raw)
            candidates = [item for item in value["agents"] if item.get("agentId") == agent_id]
            # Match the ordinary Workbench profile and its active ledger loader;
            # do not rely on normalization or repair to fill missing fields.
            if (len(candidates) != 1 or candidates[0].get("primaryMode") != "general"
                    or candidates[0].get("status") != "active"):
                raise MigrationIOError("reminder_source_unavailable")
            ledger = root / "agents" / agent_id / "plugins/personal-affairs/affairs/items.jsonl"
            snapshot = read_stable_file(ledger, _LEDGER_LIMIT)
            parent = ledger.parent
            root_id, workspace_id, ledger_dir_id = _directory(root), _directory(workspace), _directory(parent)
            ledger_chain = _identity_chain(parent)
            ledger_key = _digest({"path": _path_key(ledger), "parent": ledger_dir_id, "agentId": agent_id})
            authority_key = _digest({"root": root_id, "rootPath": _path_key(root),
                                     "workspace": workspace_id, "workspacePath": _path_key(workspace),
                                     "agentId": agent_id})

            def verify():
                if getattr(dispatch, "_registry_revision", None) != revision:
                    raise MigrationIOError("reminder_source_observation_changed")
                preview.verify_preview(token)
                verify_snapshot(snapshot)
                if (_directory(root) != root_id or _directory(workspace) != workspace_id
                        or _directory(parent) != ledger_dir_id or _identity_chain(parent) != ledger_chain):
                    raise MigrationIOError("reminder_source_observation_changed")
                preview.verify_preview(token)

            verify()
            return ReminderSourceObservation(agent_id, ledger_key, authority_key, verify, preview, token)
    except Exception as error:
        if token is not None:
            preview.discard(token)
        if isinstance(error, MigrationIOError):
            raise
        raise MigrationIOError("reminder_source_unavailable") from None


def compare_reminder_sources(left: ReminderSourceObservation, right: ReminderSourceObservation) -> str:
    """Compare two live observations, without asserting sender/process identity.

    Distinct ledgers are different. The same physical ledger reached through
    distinct workspace authorities is ambiguous, even when Agent IDs match.
    No comparison remains proof after this function returns.
    """
    if type(left) is not ReminderSourceObservation or type(right) is not ReminderSourceObservation:
        raise MigrationIOError("reminder_source_observation_required")
    left._check()
    right._check()
    result = ("different" if left._ledger != right._ledger else
              "same" if left._authority == right._authority else "unknown")
    left._check()
    right._check()
    return result


__all__ = ["ReminderSourceObservation", "observe_reminder_source", "compare_reminder_sources"]
