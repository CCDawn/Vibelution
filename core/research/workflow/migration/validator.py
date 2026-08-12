"""Classification contract for one legacy JSON Run (spec §14.4)."""

from __future__ import annotations

from typing import Any

CLASSIFICATIONS = (
    "migratable",
    "archivable_terminal",
    "reconciliation_required",
    "corrupt",
    "duplicate_identity",
    "scope_mismatch",
)


def unknown_entries(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unknown: list[dict[str, Any]] = []
    for entry in runs:
        classification = str(entry.get("classification") or "")
        if classification not in CLASSIFICATIONS:
            unknown.append(entry)
    return unknown
