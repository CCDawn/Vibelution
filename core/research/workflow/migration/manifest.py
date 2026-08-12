"""Durable migration manifest under research_workflows/migration/."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

MANIFEST_NAME = "workflow-ledger-v1-manifest.json"
AUDIT_NAME = "workflow-ledger-v1-audit.json"
APPLY_NAME = "workflow-ledger-v1-apply.json"
VERIFY_NAME = "workflow-ledger-v1-verify.json"

_ALLOWED = {
    "not_started",
    "audited",
    "backup_verified",
    "imported",
    "verified",
    "activated",
    "failed",
}


class ManifestStatus(str, Enum):
    NOT_STARTED = "not_started"
    AUDITED = "audited"
    BACKUP_VERIFIED = "backup_verified"
    IMPORTED = "imported"
    VERIFIED = "verified"
    ACTIVATED = "activated"
    FAILED = "failed"


def migration_dir(data_root: Path) -> Path:
    path = Path(data_root) / "migration"
    path.mkdir(parents=True, exist_ok=True)
    return path


def manifest_path(data_root: Path) -> Path:
    return migration_dir(data_root) / MANIFEST_NAME


def load_manifest(data_root: Path) -> dict[str, Any]:
    path = manifest_path(data_root)
    if not path.exists():
        return {
            "schemaVersion": 1,
            "status": ManifestStatus.NOT_STARTED.value,
            "ledgerRelativePath": "workflow-ledger.sqlite",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable migration manifest: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("migration manifest must be an object")
    return payload


def write_manifest(data_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    status = str(payload.get("status") or "")
    if status not in _ALLOWED:
        raise ValueError(f"unknown manifest status: {status!r}")
    document = dict(payload)
    document["schemaVersion"] = 1
    document["updatedAt"] = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    path = manifest_path(data_root)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_activated(data_root: Path) -> bool:
    try:
        status = str(load_manifest(data_root).get("status") or "")
    except ValueError:
        return False
    return status == ManifestStatus.ACTIVATED.value
