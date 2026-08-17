"""Append-only research template baseline/addendum service.

A ``TemplateBaseline`` is frozen once approved and can never be modified in
place.  Legitimate amendments are appended as ``TemplateAddendum`` records; a
semantic content change must be a new baseline version that points at its
frozen parent and carries a fresh approval.  All artifacts are pure offline
JSONL under the team workspace.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.research.workflow.contracts import (
    ContractValidationError,
    TemplateAddendum,
    TemplateBaseline,
    scope_hash_for,
)

SCHEMA_VERSION = 1
DEFAULT_MODE = "formal"
_LOCK = threading.RLock()
_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class ResearchTemplateError(RuntimeError):
    """Base error for research template persistence."""


class ResearchTemplateBaselineNotFoundError(ResearchTemplateError):
    """Raised when a template baseline does not exist."""


class ResearchTemplateBaselineNotFrozenError(ResearchTemplateError):
    """Raised when an operation requires a frozen baseline."""


def _project_root() -> Path:
    return Path(PROJECT_ROOT)


def _safe_team_id(team_id: str) -> str:
    return (
        "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in str(team_id or "")
        )[:96]
        or "team"
    )


def _team_workspace_root(team_id: str) -> Path:
    return developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_team_id(team_id),
    )


def _kind_path(team_id: str, kind: str) -> Path:
    return _team_workspace_root(team_id) / "research_workflow" / f"{kind}.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ResearchTemplateError(
                f"Invalid research template JSONL at line {line_number}."
            ) from exc
        if not isinstance(payload, dict):
            raise ResearchTemplateError(
                f"Invalid research template record at line {line_number}."
            )
        records.append(payload)
    return records


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(existing)
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _resolve_scope(payload: Mapping[str, Any]) -> dict[str, str]:
    identity: dict[str, str] = {}
    for field in _SCOPE_FIELDS:
        value = str(payload.get(field) or "").strip()
        if not value:
            raise ContractValidationError(
                f"scope requires a non-empty '{field}' field"
            )
        identity[field] = value
    agent_id = str(payload.get("agentId") or "").strip()
    if not agent_id:
        raise ContractValidationError("scope requires a non-empty agentId")
    mode = str(payload.get("mode") or "").strip().lower() or DEFAULT_MODE
    if mode not in {"formal", "dev", "platform"}:
        raise ContractValidationError(f"unsupported scope mode: {mode}")
    scope_hash = scope_hash_for(**identity, agent_id=agent_id, mode=mode)
    return {**identity, "agentId": agent_id, "mode": mode, "scopeHash": scope_hash}


def _latest_by_id(records: list[dict[str, Any]], field: str, record_id: str) -> dict[str, Any] | None:
    matched = [record for record in records if str(record.get(field) or "") == record_id]
    return matched[-1] if matched else None


def _baselines_path(team_id: str) -> Path:
    return _kind_path(team_id, "research_templates")


def _addenda_path(team_id: str) -> Path:
    return _kind_path(team_id, "template_addenda")


def _load_baselines(team_id: str) -> list[dict[str, Any]]:
    return _read_jsonl(_baselines_path(team_id))


def _load_addenda(team_id: str) -> list[dict[str, Any]]:
    return _read_jsonl(_addenda_path(team_id))


def _baseline_definition(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "baselineId",
            "templateId",
            "version",
            "parentBaselineId",
            "parentVersion",
            "status",
            "content",
            "program",
            "theme",
            "campaign",
            "question",
            "branch",
            "workflow",
            "agentId",
            "mode",
            "scopeHash",
            "approvedBy",
            "approvalRef",
            "semanticChangeReason",
        )
    }


def _addendum_definition(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "addendumId",
            "baselineId",
            "templateId",
            "version",
            "reason",
            "deltas",
            "semanticChange",
            "appendedBy",
            "status",
        )
    }


def create_template_baseline(
    team_id: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create and freeze one template baseline, optionally as a child version.

    A child baseline requires a frozen parent and carries its own approval.
    Re-creating the same ``baselineId`` with different content is rejected:
    a frozen baseline can never be modified in place.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    request = dict(payload) if isinstance(payload, Mapping) else {}
    scope = _resolve_scope(request)
    now = _utc_now()
    template_id = str(request.get("templateId") or "").strip()
    if not template_id:
        raise ContractValidationError("templateId is required")
    parent_baseline_id = str(request.get("parentBaselineId") or "").strip()
    parent_version = 0
    if parent_baseline_id:
        with _LOCK:
            parents = _load_baselines(normalized_team_id)
            parent = _latest_by_id(parents, "baselineId", parent_baseline_id)
        if parent is None:
            raise ResearchTemplateBaselineNotFoundError(
                "Parent template baseline not found."
            )
        if str(parent.get("status") or "") != "frozen":
            raise ResearchTemplateBaselineNotFrozenError(
                "A child baseline requires a frozen parent."
            )
        parent_version = max(0, int(parent.get("version") or 0))
        if str(parent.get("templateId") or "") != template_id:
            raise ContractValidationError(
                "a child baseline must keep the parent templateId"
            )
        if str(parent.get("scopeHash") or "") != scope["scopeHash"]:
            raise ContractValidationError(
                "a child baseline must stay within the parent research scope"
            )
    version = max(1, int(request.get("version") or parent_version + 1))
    if parent_baseline_id and version != parent_version + 1:
        raise ContractValidationError(
            "a child baseline version must equal parentVersion + 1"
        )
    if not parent_baseline_id and version != 1:
        raise ContractValidationError("a root template baseline must start at version 1")
    baseline_id = (
        str(request.get("baselineId") or "").strip()
        or f"baseline-{template_id}-v{version}"
    )
    baseline_payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "baselineId": baseline_id,
        "templateId": template_id,
        "version": version,
        "parentBaselineId": parent_baseline_id,
        "parentVersion": parent_version,
        "status": str(request.get("status") or "frozen").strip().lower(),
        "content": dict(request.get("content")) if isinstance(request.get("content"), Mapping) else {},
        **scope,
        "approvedBy": str(request.get("approvedBy") or "").strip(),
        "approvedAt": str(request.get("approvedAt") or "").strip() or now,
        "approvalRef": str(request.get("approvalRef") or "").strip(),
        "semanticChangeReason": str(request.get("semanticChangeReason") or "").strip(),
        "frozenAt": str(request.get("frozenAt") or "").strip() or now,
        "createdAt": now,
    }
    if baseline_payload["status"] == "frozen" and not baseline_payload["approvedBy"]:
        raise ContractValidationError(
            "freezing a baseline requires approvedBy"
        )
    if parent_baseline_id:
        if not baseline_payload["semanticChangeReason"]:
            raise ContractValidationError(
                "a child baseline requires semanticChangeReason and re-approval"
            )
        if baseline_payload["content"] == dict(parent.get("content") or {}):
            raise ContractValidationError(
                "a child baseline must contain a semantic change"
            )
    parsed = TemplateBaseline.from_dict(baseline_payload)
    if not parsed.is_frozen():
        raise ContractValidationError(
            "only frozen baselines are persisted; re-approval is required for changes"
        )
    with _LOCK:
        existing = _latest_by_id(_load_baselines(normalized_team_id), "baselineId", baseline_id)
        if existing is not None:
            if _baseline_definition(existing) != _baseline_definition(baseline_payload):
                raise ResearchTemplateError(
                    "a frozen baseline id cannot be reused with different content or approval"
                )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "baseline": existing,
                "storagePath": str(_baselines_path(normalized_team_id)),
            }
        _append_jsonl(_baselines_path(normalized_team_id), baseline_payload)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "baseline": baseline_payload,
        "parentVersion": parent_version,
        "storagePath": str(_baselines_path(normalized_team_id)),
    }


def append_template_addendum(
    team_id: str,
    baseline_id: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one non-semantic addendum on top of a frozen baseline.

    The baseline record itself is never touched; the addendum is a separate
    append-only record.  Semantic changes are rejected here and must become a
    new baseline version.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_baseline_id = str(baseline_id or "").strip()
    if not normalized_baseline_id:
        raise ResearchTemplateError("Baseline id is required.")
    request = dict(payload) if isinstance(payload, Mapping) else {}
    with _LOCK:
        baselines = _load_baselines(normalized_team_id)
        baseline = _latest_by_id(baselines, "baselineId", normalized_baseline_id)
        if baseline is None:
            raise ResearchTemplateBaselineNotFoundError("Template baseline not found.")
        if str(baseline.get("status") or "") != "frozen":
            raise ResearchTemplateBaselineNotFrozenError(
                "addenda may only be appended to a frozen baseline"
            )
        if bool(request.get("semanticChange")):
            raise ContractValidationError(
                "a semantic change must be a new baseline version with parent and re-approval"
            )
        now = _utc_now()
        addendum_id = (
            str(request.get("addendumId") or "").strip()
            or f"addendum-{_stable_hash({'baselineId': normalized_baseline_id, 'reason': str(request.get('reason') or ''), 'deltas': request.get('deltas') or {}})[:16]}"
        )
        addendum: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "addendumId": addendum_id,
            "baselineId": normalized_baseline_id,
            "templateId": str(baseline.get("templateId") or "").strip(),
            "version": max(1, int(baseline.get("version") or 1)),
            "reason": str(request.get("reason") or "").strip(),
            "deltas": dict(request.get("deltas")) if isinstance(request.get("deltas"), Mapping) else {},
            "semanticChange": False,
            "appendedBy": str(request.get("appendedBy") or "").strip(),
            "appendedAt": now,
            "status": "active",
        }
        if not addendum["reason"] or not addendum["appendedBy"]:
            raise ContractValidationError(
                "an addendum requires reason and appendedBy"
            )
        existing = _latest_by_id(
            _load_addenda(normalized_team_id), "addendumId", addendum_id
        )
        if existing is not None:
            if _addendum_definition(existing) != _addendum_definition(addendum):
                raise ResearchTemplateError(
                    "template addendum id is already bound to different content"
                )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "addendum": existing,
                "storagePath": str(_addenda_path(normalized_team_id)),
            }
        active_addenda = [
            item
            for item in _load_addenda(normalized_team_id)
            if str(item.get("baselineId") or "") == normalized_baseline_id
            and str(item.get("status") or "") == "active"
        ]
        occupied_keys = set(dict(baseline.get("content") or {}))
        for existing_addendum in active_addenda:
            occupied_keys.update(dict(existing_addendum.get("deltas") or {}))
        overlapping_keys = occupied_keys & set(addendum["deltas"])
        if overlapping_keys:
            raise ContractValidationError(
                "an addendum may only supplement the frozen template; it cannot overwrite keys: "
                + ", ".join(sorted(overlapping_keys))
            )
        TemplateAddendum.from_dict(addendum)
        _append_jsonl(_addenda_path(normalized_team_id), addendum)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "addendum": addendum,
        "storagePath": str(_addenda_path(normalized_team_id)),
    }


def get_template_baseline(team_id: str, baseline_id: str) -> dict[str, Any]:
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_baseline_id = str(baseline_id or "").strip()
    with _LOCK:
        baseline = _latest_by_id(_load_baselines(normalized_team_id), "baselineId", normalized_baseline_id)
    if baseline is None:
        raise ResearchTemplateBaselineNotFoundError("Template baseline not found.")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "baseline": baseline,
        "storagePath": str(_baselines_path(normalized_team_id)),
    }


def list_template_baselines(team_id: str) -> dict[str, Any]:
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    with _LOCK:
        baselines = _load_baselines(normalized_team_id)
    latest: dict[str, dict[str, Any]] = {}
    for record in baselines:
        latest[str(record.get("baselineId") or "")] = record
    rows = sorted(latest.values(), key=lambda item: (str(item.get("templateId") or ""), int(item.get("version") or 0)))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "baselineCount": len(rows),
        "baselines": rows,
        "storagePath": str(_baselines_path(normalized_team_id)),
    }


def list_template_addenda(team_id: str, baseline_id: str = "") -> dict[str, Any]:
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    with _LOCK:
        addenda = _load_addenda(normalized_team_id)
    if baseline_id:
        addenda = [
            item for item in addenda if str(item.get("baselineId") or "") == str(baseline_id or "").strip()
        ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "addendumCount": len(addenda),
        "addenda": addenda,
        "storagePath": str(_addenda_path(normalized_team_id)),
    }


def frozen_template_view(team_id: str, baseline_id: str) -> dict[str, Any]:
    """Project the frozen baseline content plus its active addenda.

    Read-only: this never rewrites the baseline record.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_baseline_id = str(baseline_id or "").strip()
    with _LOCK:
        baseline = _latest_by_id(_load_baselines(normalized_team_id), "baselineId", normalized_baseline_id)
        if baseline is None:
            raise ResearchTemplateBaselineNotFoundError("Template baseline not found.")
        addenda = [
            item
            for item in _load_addenda(normalized_team_id)
            if str(item.get("baselineId") or "") == normalized_baseline_id
            and str(item.get("status") or "") == "active"
        ]
    content = dict(baseline.get("content") or {})
    for addendum in addenda:
        deltas = addendum.get("deltas")
        if isinstance(deltas, dict):
            content.update(deltas)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "baselineId": normalized_baseline_id,
        "templateId": str(baseline.get("templateId") or ""),
        "version": int(baseline.get("version") or 0),
        "status": str(baseline.get("status") or ""),
        "scopeHash": str(baseline.get("scopeHash") or ""),
        "content": content,
        "activeAddendumCount": len(addenda),
        "addenda": addenda,
    }
