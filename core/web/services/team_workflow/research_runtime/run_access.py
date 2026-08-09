"""Canonical team scope and optimistic Run access guards."""

from __future__ import annotations

from typing import Any


class RunAccessError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def require_run_access(
    record: dict[str, Any],
    *,
    team_id: str,
    expected_run_version: int | None = None,
) -> dict[str, Any]:
    canonical_team_id = str(team_id or "").strip()
    if not canonical_team_id:
        raise RunAccessError("teamId is required", code="team_id_required")
    if str(record.get("teamId") or "").strip() != canonical_team_id:
        raise RunAccessError(
            "Run does not exist in the requested team scope",
            code="team_scope_mismatch",
        )
    if expected_run_version is None:
        return record
    stored_version = record.get("runVersion")
    if not isinstance(stored_version, int) or stored_version < 1:
        raise RunAccessError(
            "Run has no valid runVersion and cannot accept commands",
            code="run_version_missing",
        )
    if stored_version != expected_run_version:
        raise RunAccessError(
            f"expectedRunVersion {expected_run_version} does not match current runVersion {stored_version}",
            code="run_version_conflict",
        )
    return record
