"""Build one bounded Launcher state refresh payload for Electron main.

The renderer never calls this module directly. Electron supplies its window
truth, and this bridge combines the remaining Python-owned observations in one
process so status refreshes do not fan out into several Python/Git children.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


ORPHAN_CRITERIA = (
    "worktree_missing_or_not_registered",
    "all_registered_pids_dead_or_identity_mismatch",
    "no_electron_window",
    "no_owned_listener",
    "in_flight_deadline_expired",
    "two_identical_observations_at_least_10_seconds_apart",
)


def _window_instance_ids(values: Iterable[object], *, current_id: str) -> list[str]:
    normalized: set[str] = set()
    for value in values:
        instance_id = str(value or "").strip()
        if not instance_id:
            continue
        if instance_id == "main" and current_id:
            normalized.add(current_id)
        else:
            normalized.add(instance_id)
    return sorted(normalized)


def _git_worktree_roots(branch_instances: dict[str, Any]) -> list[str]:
    roots: set[str] = set()
    for item in branch_instances.get("items") or []:
        if not isinstance(item, dict) or not bool(item.get("checkedOut")):
            continue
        path = str(item.get("path") or "").strip()
        if path:
            roots.add(path)
    return sorted(roots)


def _branch_cleanup_dry_run(branch_instances: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in branch_instances.get("items") or []:
        if (
            not isinstance(item, dict)
            or str(item.get("kind") or "") not in {"worktree", "retired"}
            or not bool(item.get("cleanupEligible"))
        ):
            continue
        instance_id = str(item.get("id") or "").strip()
        if not instance_id or bool(item.get("current")):
            continue
        items.append(
            {
                "instanceId": instance_id,
                "projectRoot": str(item.get("path") or ""),
                "branch": str(item.get("branch") or ""),
                "reason": "branch_cleanup_preview",
                "action": "dry_run_only",
                "dirty": bool(item.get("dirty")),
                "mergedToMain": bool(item.get("mergedToMain")),
                "risks": [str(value) for value in item.get("cleanupRisks") or []],
            }
        )
    return items


def _merge_worktree_dry_run(
    registry_items: object,
    branch_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    candidates = list(registry_items) if isinstance(registry_items, list) else []
    candidates.extend(branch_items)
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item["action"] = "dry_run_only"
        key = (str(item.get("instanceId") or ""), str(item.get("reason") or ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def build_launcher_state_refresh(*, electron_window_instance_ids: Iterable[object] = ()) -> dict[str, Any]:
    """Return status, inventory, freshness, and safe registry reconciliation."""

    from core.launcher import service as launcher_service
    from core.runtime_manager.instances_registry import load_registry, reconcile_registry

    branch_instances = launcher_service.list_launcher_branch_instances(include_cleanup_metadata=True)
    current_id = str(branch_instances.get("currentId") or "main").strip()
    registry = reconcile_registry(
        git_worktree_roots=_git_worktree_roots(branch_instances),
        electron_window_instance_ids=_window_instance_ids(
            electron_window_instance_ids,
            current_id=current_id,
        ),
    )
    registry_entries = load_registry().get("instances") or {}
    for item in registry.get("instances") or []:
        if not isinstance(item, dict):
            continue
        entry = registry_entries.get(str(item.get("instanceId") or "")) if isinstance(registry_entries, dict) else None
        ports: set[int] = set()
        if isinstance(entry, dict):
            for key in ("port", "controlPort"):
                try:
                    port = int(entry.get(key) or 0)
                except (TypeError, ValueError):
                    port = 0
                if 0 < port < 65536:
                    ports.add(port)
        item["ports"] = sorted(ports)
    registry["worktreeDryRun"] = _merge_worktree_dry_run(
        registry.get("worktreeDryRun"),
        _branch_cleanup_dry_run(branch_instances),
    )
    registry["orphanCriteria"] = list(ORPHAN_CRITERIA)
    return {
        "schemaVersion": 1,
        "status": launcher_service.get_launcher_status(),
        "branchInstances": branch_instances,
        "freshness": launcher_service.get_launcher_freshness(),
        "cleanup": registry,
    }
