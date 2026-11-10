"""Watermark for the startup recovery sweep.

The sweep prefilter needs one durable fact: when did a clean sweep last cover
every session? A session whose ledger has not changed after that moment cannot
own a turn the next restart may resume, so its journal never needs reading.
A missing or damaged watermark only costs one full sweep, never correctness.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

WATERMARK_FILENAME = "session-recovery-sweep.json"
WATERMARK_SCHEMA_VERSION = 1

_logger = logging.getLogger(__name__)


def watermark_path_for_store(store: Any) -> Path | None:
    """Watermark file living beside ``work_runs`` so both share one authority."""

    root = getattr(store, "root", None)
    if root is None:
        return None
    return Path(root).parent / WATERMARK_FILENAME


def load_sweep_watermark_ns(store: Any) -> int:
    """Epoch ns of the last clean sweep start, or 0 when unknown."""

    path = watermark_path_for_store(store)
    if path is None or not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(payload, dict) or payload.get("schemaVersion") != WATERMARK_SCHEMA_VERSION:
        return 0
    try:
        return int(payload.get("completedAtNs") or 0)
    except (TypeError, ValueError):
        return 0


def record_sweep_watermark(
    store: Any,
    *,
    started_at_ns: int,
    scanned_session_count: int,
    resumed_count: int,
) -> None:
    """Record the start of a clean sweep.

    The sweep *start* is deliberate: anything a session writes while the sweep
    is still running keeps its ledger newer than the watermark, so the next
    restart inspects it again instead of trusting a half-finished pass.
    """

    path = watermark_path_for_store(store)
    if path is None:
        return
    payload = {
        "schemaVersion": WATERMARK_SCHEMA_VERSION,
        "completedAtNs": int(started_at_ns),
        "scannedSessionCount": int(scanned_session_count),
        "resumedCount": int(resumed_count),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp-{os.getpid()}")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, path)
    except OSError as exc:  # noqa: BLE001 - losing the watermark only costs a rescan
        _logger.warning(
            "Failed to record recovery sweep watermark (%s).", type(exc).__name__
        )
