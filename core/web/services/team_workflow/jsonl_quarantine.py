"""Quarantine-on-read JSONL helper for append-only team workflow stores.

Unlike ``storage_durability.read_jsonl_tolerant`` (which rewrites the store
without corrupt lines), this reader never modifies the original file: stores
using read-modify-append semantics must keep their bytes stable while other
writers may concurrently append.  A corrupt line therefore remains in the
store and is encountered on every read; quarantine evidence goes to an
append-only ``<store>.corrupt.jsonl`` sidecar keyed by line hash, so repeated
reads deduplicate against the sidecar instead of growing it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SIDECAR_SUFFIX = ".corrupt.jsonl"


def _sidecar_path(path: Path) -> Path:
    return path.with_name(path.name + SIDECAR_SUFFIX)


def _line_hash(raw_line: str) -> str:
    return hashlib.sha256(raw_line.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _known_sidecar_hashes(sidecar_path: Path) -> set[str]:
    """Load already-quarantined line hashes.

    The sidecar is itself the quarantine area, so its unreadable or malformed
    lines are ignored rather than raised on; degraded dedup only risks benign
    duplicate evidence rows, never a lost record.
    """
    known: set[str] = set()
    try:
        text = sidecar_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # A missing sidecar is the pristine state, not an incident.
        return known
    except OSError:
        logger.warning(
            "jsonl quarantine sidecar unreadable at %s", sidecar_path
        )
        return known
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            line_hash = str(payload.get("lineHash") or "").strip()
            if line_hash:
                known.add(line_hash)
    return known


def _append_sidecar_entries(sidecar_path: Path, entries: list[dict[str, Any]]) -> None:
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for entry in entries
    )
    with sidecar_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)


def read_jsonl_with_quarantine(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Read a JSONL store, isolating corrupt lines instead of raising.

    Returns ``(records, corruptLineCount)`` where blank lines are skipped and
    every non-blank line that fails JSON parsing or is not a JSON object is
    skipped, counted, and recorded in the append-only sidecar under
    ``<path>.corrupt.jsonl``.  The original file is never rewritten, so a
    quarantined line stays visible on every subsequent read; the count always
    reflects the corruption still present in the store, not just newly seen
    lines.  Store IO errors (missing file returns empty) still raise exactly
    like the strict readers they replace.
    """
    if not path.exists():
        return [], 0
    records: list[dict[str, Any]] = []
    corrupt_lines: list[tuple[int, str]] = []
    text = path.read_text(encoding="utf-8")
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            corrupt_lines.append((line_number, raw_line))
            continue
        if not isinstance(payload, dict):
            corrupt_lines.append((line_number, raw_line))
            continue
        records.append(payload)
    if corrupt_lines:
        sidecar_path = _sidecar_path(path)
        try:
            known_hashes = _known_sidecar_hashes(sidecar_path)
            fresh_entries = [
                {
                    "lineHash": _line_hash(raw_line),
                    "lineNumber": line_number,
                    "quarantinedAt": _utc_now_iso(),
                }
                for line_number, raw_line in corrupt_lines
                if _line_hash(raw_line) not in known_hashes
            ]
            if fresh_entries:
                _append_sidecar_entries(sidecar_path, fresh_entries)
        except OSError as exc:
            # Losing quarantine evidence must not brick the read itself;
            # the returned count keeps the corruption observable.
            logger.warning(
                "jsonl quarantine append failed at %s (%s)",
                sidecar_path,
                type(exc).__name__,
            )
        logger.warning(
            "%s: %d corrupt JSONL line(s) quarantined",
            path,
            len(corrupt_lines),
        )
    return records, len(corrupt_lines)
