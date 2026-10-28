"""Bounded read-only access to confirmed initial personal source archives.

This is an internal owner API, not a route or model tool. The caller supplies
only opaque operation and item IDs; root, principal and source scope come from
the live Launcher identity and the original authorized migration intent.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
import json
import re

from core.infrastructure.native_runtime import assistant_native_root

from .migration_io import MigrationIOError, pinned_source_files, pinned_target_directory, read_stable_file, strict_json, verify_snapshot

_ID = re.compile(r"initial-[a-f0-9]{40}\Z")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_VERSION = re.compile(r"[a-f0-9]{64}\Z")
_MAX_FILE = 1024 * 1024
_MAX_PAGE = 1600
_OUTPUT_BUDGET = 3300
_ITEMS = {
    "memory": (("memory", "memory.json"),),
    "summaries": (("memory", "summaries.jsonl"), ("memory_summaries", "summaries.jsonl")),
    "mental_rules": (("mental_model", "rules.json"),),
    "mental_self": (("mental_model", "self_model.json"),),
}


@contextmanager
def _verified(operation_id):
    if not isinstance(operation_id, str) or not _ID.fullmatch(operation_id):
        raise MigrationIOError("legacy_memory_operation_invalid")
    from . import native
    from .initial_migration_binding import read_initial_intent
    from .migration_history import _confirmation_exists
    from core.web.services import agent_directory_service as directory
    from core.web.services.session import directory_runtime
    from scripts.assistant_migration_activate import verify_initial_personal_receipts

    root = assistant_native_root()
    if not native._LOCK.acquire(blocking=False):
        raise MigrationIOError("legacy_memory_busy")
    try:
        runtime = directory.current_agent_runtime(bound_only=True)
        if (not isinstance(runtime, dict) or not native._STARTED or native._OFFLINE_MIGRATION
                or native._STOP_REQUESTED.is_set() or runtime.get("agentId") != native._AGENT_ID
                or runtime.get("sessionId") != native._SESSION_ID
                or directory_runtime.directory_store_project_root() != root):
            raise MigrationIOError("legacy_memory_owner_unavailable")
        intent = read_initial_intent(root, operation_id)
        if (not isinstance(intent, dict) or intent.get("category") != "personal"
                or intent.get("targetAgentId") != native._AGENT_ID
                or intent.get("targetSessionId") != native._SESSION_ID):
            raise MigrationIOError("legacy_memory_authority_unavailable")
        archive = root / "history_sources" / "migrations" / operation_id
        with ExitStack() as stack:
            stack.enter_context(pinned_target_directory(archive))
            stack.enter_context(pinned_target_directory(archive / ".confirmed"))
            if not _confirmation_exists(archive):
                raise MigrationIOError("legacy_memory_archive_unconfirmed")
            verify_initial_personal_receipts(root, operation_id)
            manifest = read_stable_file(archive / "manifest.json", 16 * 1024 * 1024)
            stack.enter_context(pinned_source_files((manifest,)))
            value = strict_json(manifest.raw)
            if (type(value) is not dict or value.get("migrationId") != operation_id
                    or value.get("sourceScope") != intent["sourceScope"] or type(value.get("entries")) is not list):
                raise MigrationIOError("legacy_memory_archive_invalid")
            entries = {}
            for kind, candidates in _ITEMS.items():
                matches = []
                for row in value["entries"]:
                    if type(row) is not dict:
                        raise MigrationIOError("legacy_memory_archive_invalid")
                    ref = row.get("sourceRef")
                    if not isinstance(ref, str) or not _REF.fullmatch(ref):
                        raise MigrationIOError("legacy_memory_archive_invalid")
                    if any(row.get("category") == category and row.get("path") == f"sources/{ref}/{name}"
                           for category, name in candidates):
                        matches.append(row)
                if matches:
                    if len({(row.get("sha256"), row.get("size")) for row in matches}) != 1:
                        raise MigrationIOError("legacy_memory_source_ambiguous")
                    entries[kind] = sorted(matches, key=lambda row: row["path"])[0]
            version = hashlib.sha256((operation_id + ":" + manifest.sha256).encode("ascii")).hexdigest()
            yield root, archive, intent, manifest, entries, version, stack
            verify_snapshot(manifest)
            if read_initial_intent(root, operation_id) != intent or not _confirmation_exists(archive):
                raise MigrationIOError("legacy_memory_archive_changed")
            verify_initial_personal_receipts(root, operation_id)
    finally:
        native._LOCK.release()


def list_legacy_memory(operation_id: str) -> dict:
    """List supported archive items without exposing file paths or content."""
    with _verified(operation_id) as (_, _, intent, _, entries, version, _):
        result = {"operationId": operation_id, "sourceScope": dict(intent["sourceScope"]),
                "archiveVersion": version, "items": [{"kind": kind, "sha256": row["sha256"],
                    "size": row["size"], "readable": row["size"] <= _MAX_FILE}
                    for kind, row in entries.items()], "readOnly": True, "untrustedContent": True,
                "activeMemoryChanged": False, "readyForCutover": False}
        if _output_size(result) > _OUTPUT_BUDGET:
            raise MigrationIOError("legacy_memory_output_budget")
        return result


def _output_size(result: dict) -> int:
    # Include the established launcher tool wrapper and count UTF-8 bytes,
    # accounting for both JSON escaping and multibyte user content.
    wrapped = {"source": "launcher-assistant", "untrustedContent": True, **result}
    return len(json.dumps(wrapped, ensure_ascii=False).encode("utf-8"))


def read_legacy_memory(operation_id: str, kind: str, *, offset: int = 0, limit: int = 1200,
                       expected_version: str | None = None) -> dict:
    """Read one UTF-8 text page; continuation must bind the archive version."""
    if (not isinstance(kind, str) or kind not in _ITEMS or type(offset) is not int or offset < 0
            or type(limit) is not int or not 1 <= limit <= _MAX_PAGE
            or (expected_version is not None and (not isinstance(expected_version, str) or not _VERSION.fullmatch(expected_version)))
            or (offset > 0 and expected_version is None)):
        raise MigrationIOError("legacy_memory_request_invalid")
    with _verified(operation_id) as (_, archive, intent, _, entries, version, stack):
        if expected_version is not None and expected_version != version:
            raise MigrationIOError("legacy_memory_version_changed")
        row = entries.get(kind)
        if row is None or type(row.get("size")) is not int or row["size"] > _MAX_FILE:
            raise MigrationIOError("legacy_memory_item_unavailable")
        snapshot = read_stable_file(archive / row["path"], _MAX_FILE)
        if snapshot.sha256 != row.get("sha256") or len(snapshot.raw) != row["size"]:
            raise MigrationIOError("legacy_memory_archive_changed")
        stack.enter_context(pinned_source_files((snapshot,)))
        try:
            content = snapshot.raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise MigrationIOError("legacy_memory_encoding_invalid") from None
        if offset > len(content):
            raise MigrationIOError("legacy_memory_offset_invalid")
        verify_snapshot(snapshot)
        def page(width):
            end = min(len(content), offset + width)
            return {"operationId": operation_id, "sourceScope": dict(intent["sourceScope"]), "kind": kind,
                    "archiveVersion": version, "sourceSha256": snapshot.sha256, "offset": offset,
                    "text": content[offset:end], "nextOffset": end if end < len(content) else None,
                    "readOnly": True, "untrustedContent": True, "activeMemoryChanged": False,
                    "readyForCutover": False}
        low, high = 0, min(limit, len(content) - offset)
        if _output_size(page(0)) > _OUTPUT_BUDGET:
            raise MigrationIOError("legacy_memory_output_budget")
        while low < high:
            middle = (low + high + 1) // 2
            if _output_size(page(middle)) <= _OUTPUT_BUDGET:
                low = middle
            else:
                high = middle - 1
        if low == 0 and offset < len(content):
            raise MigrationIOError("legacy_memory_output_budget")
        return page(low)
