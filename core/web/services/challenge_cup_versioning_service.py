"""Lightweight Challenge Cup candidate versioning ledger."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.web.services import team_service
from core.web.services.runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
STORE_KIND = "challenge_cup_candidate_versioning_store"
MAX_VERSION_RECORDS = 160
MAX_RELATION_RECORDS = 240
MAX_REJECTION_RECORDS = 120
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
_LOCK = threading.RLock()


class ChallengeCupVersioningError(ValueError):
    """Raised when a candidate versioning request is invalid."""


def get_candidate_versioning_status(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team = team_service.get_team(normalized_team_id)
    with _LOCK:
        store = _load_versioning_store(normalized_team_id)
    return _status_payload(normalized_team_id, team, store)


def record_candidate_version_event(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    operation = _safe_token(request_payload.get("operation"), default="record_version", max_length=64)
    if operation not in {"record_version", "supersede", "derive", "reject"}:
        raise ChallengeCupVersioningError(f"Unsupported versioning operation: {operation}.")
    candidate_id = _trim_text(request_payload.get("candidateId"), max_length=160)
    if not candidate_id:
        raise ChallengeCupVersioningError("Candidate id is required.")
    if operation == "supersede" and not _trim_text(request_payload.get("supersedesVersionId"), max_length=160):
        raise ChallengeCupVersioningError("Superseded version id is required for supersede operation.")
    if operation == "derive" and not _trim_text(request_payload.get("derivedFromVersionId"), max_length=160):
        raise ChallengeCupVersioningError("Derived-from version id is required for derive operation.")
    now = utc_now_iso()
    recorded_by_agent = _trim_text(request_payload.get("recordedByAgent"), max_length=160) or "challenge_cup_versioning"
    version_record = _version_record(
        normalized_team_id,
        request_payload,
        operation=operation,
        candidate_id=candidate_id,
        recorded_by_agent=recorded_by_agent,
        recorded_at=now,
    )
    relation_record = _relation_record(version_record, request_payload, operation=operation)
    rejection_record = _rejection_record(version_record, request_payload) if operation == "reject" else None
    with _LOCK:
        store = _load_versioning_store(normalized_team_id)
        versions = [item for item in store.get("versionHistory") or [] if isinstance(item, dict)]
        versions.append(version_record)
        store["versionHistory"] = versions[-MAX_VERSION_RECORDS:]
        if relation_record:
            relations = [item for item in store.get("relations") or [] if isinstance(item, dict)]
            relations.append(relation_record)
            store["relations"] = relations[-MAX_RELATION_RECORDS:]
        if rejection_record:
            rejections = [item for item in store.get("rejectionArchive") or [] if isinstance(item, dict)]
            rejections.append(rejection_record)
            store["rejectionArchive"] = rejections[-MAX_REJECTION_RECORDS:]
        store["updatedAt"] = now
        _write_json(_versioning_store_path(normalized_team_id), store)
    _record_versioning_event(
        "challenge_cup.versioning_recorded",
        normalized_team_id,
        fields={
            "operation": operation,
            "candidateId": candidate_id,
            "versionId": version_record["versionId"],
            "relationId": str((relation_record or {}).get("relationId") or ""),
            "rejectionId": str((rejection_record or {}).get("rejectionId") or ""),
            "recordedByAgent": recorded_by_agent,
        },
        child_log_payload=_versioning_record_child_log_payload(
            normalized_team_id,
            version_record,
            relation_record=relation_record,
            rejection_record=rejection_record,
        ),
    )
    return {
        "event": version_record,
        "relation": relation_record,
        "rejection": rejection_record,
        "status": _status_payload(normalized_team_id, team, store),
        "boundaries": _versioning_boundaries(),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_payload(team_id: str, team: dict[str, Any], store: dict[str, Any]) -> dict[str, Any]:
    versions = [item for item in store.get("versionHistory") or [] if isinstance(item, dict)]
    relations = [item for item in store.get("relations") or [] if isinstance(item, dict)]
    rejections = [item for item in store.get("rejectionArchive") or [] if isinstance(item, dict)]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "storeKind": STORE_KIND,
        "teamId": team_id,
        "team": {"teamId": team.get("teamId", team_id), "name": team.get("name", "")},
        "versionHistory": versions[-40:],
        "relations": relations[-60:],
        "rejectionArchive": rejections[-40:],
        "summary": {
            "versionCount": len(versions),
            "relationCount": len(relations),
            "rejectionCount": len(rejections),
            "candidateCount": len({str(item.get("candidateId") or "") for item in versions if item.get("candidateId")}),
        },
        "boundaries": _versioning_boundaries(),
        "storagePath": _relative_path(_versioning_store_path(team_id)),
        "updatedAt": str(store.get("updatedAt") or ""),
    }


def _version_record(
    team_id: str,
    payload: dict[str, Any],
    *,
    operation: str,
    candidate_id: str,
    recorded_by_agent: str,
    recorded_at: str,
) -> dict[str, Any]:
    return {
        "versionId": _new_record_id("candidate-version"),
        "teamId": team_id,
        "operation": operation,
        "candidateId": candidate_id,
        "versionLabel": _trim_text(payload.get("versionLabel"), max_length=120)
        or _default_version_label(operation, candidate_id),
        "summary": _trim_text(payload.get("summary"), max_length=4000),
        "reason": _trim_text(payload.get("reason"), max_length=2000),
        "status": "rejected" if operation == "reject" else "recorded",
        "supersedesVersionId": _trim_text(payload.get("supersedesVersionId"), max_length=160),
        "derivedFromVersionId": _trim_text(payload.get("derivedFromVersionId"), max_length=160),
        "relatedCandidateId": _trim_text(payload.get("relatedCandidateId"), max_length=160),
        "evidenceRefs": _normalize_refs(payload.get("evidenceRefs"), max_items=32),
        "changeSet": _trim_list(payload.get("changeSet"), max_items=40, max_length=500),
        "recordedByAgent": recorded_by_agent,
        "recordedAt": recorded_at,
        "metadata": _normalize_metadata(payload.get("metadata")),
        "officialBoundary": _versioning_boundaries(),
    }


def _relation_record(version: dict[str, Any], payload: dict[str, Any], *, operation: str) -> dict[str, Any] | None:
    relation_type = ""
    target_version_id = ""
    if operation == "supersede":
        relation_type = "supersedes"
        target_version_id = _trim_text(payload.get("supersedesVersionId"), max_length=160)
    elif operation == "derive":
        relation_type = "derived_from"
        target_version_id = _trim_text(payload.get("derivedFromVersionId"), max_length=160)
    if not relation_type:
        return None
    return {
        "relationId": _new_record_id("candidate-version-relation"),
        "relationType": relation_type,
        "sourceVersionId": version["versionId"],
        "targetVersionId": target_version_id,
        "candidateId": version["candidateId"],
        "relatedCandidateId": version["relatedCandidateId"],
        "reason": version["reason"],
        "createdAt": version["recordedAt"],
        "createdByAgent": version["recordedByAgent"],
    }


def _rejection_record(version: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "rejectionId": _new_record_id("candidate-rejection"),
        "candidateId": version["candidateId"],
        "versionId": version["versionId"],
        "reason": version["reason"] or version["summary"],
        "summary": version["summary"],
        "evidenceRefs": version["evidenceRefs"],
        "archivedByAgent": version["recordedByAgent"],
        "archivedAt": version["recordedAt"],
        "metadata": _normalize_metadata(payload.get("metadata")),
    }


def _versioning_boundaries() -> dict[str, bool | str]:
    return {
        "autoApply": False,
        "autoExecution": False,
        "writesFormalKnowledge": False,
        "writesRag": False,
        "writesOfficialGraph": False,
        "createsExperimentAttempt": False,
        "requiresUserDecision": True,
        "boundary": "candidate_versioning_ledger_only_not_official_graph",
    }


def _default_version_label(operation: str, candidate_id: str) -> str:
    suffix = candidate_id[-8:] if len(candidate_id) > 8 else candidate_id
    return f"{operation}:{suffix}"


def _load_versioning_store(team_id: str) -> dict[str, Any]:
    path = _versioning_store_path(team_id)
    payload = _read_json(path)
    if payload.get("storeKind") != STORE_KIND:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "storeKind": STORE_KIND,
            "teamId": team_id,
            "versionHistory": [],
            "relations": [],
            "rejectionArchive": [],
            "updatedAt": "",
        }
    payload.setdefault("versionHistory", [])
    payload.setdefault("relations", [])
    payload.setdefault("rejectionArchive", [])
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _versioning_store_path(team_id: str) -> Path:
    return _team_workspace_root(team_id) / "candidate_versions" / "index.json"


def _team_workspace_root(team_id: str) -> Path:
    return developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_token(team_id, default="team", max_length=96),
    )


def _project_root() -> Path:
    root = Path(PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_project_root())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _new_record_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _normalize_required_id(value: Any, message: str) -> str:
    normalized = _safe_token(value, default="", max_length=128)
    if not normalized:
        raise ChallengeCupVersioningError(message)
    return normalized


def _safe_token(value: Any, *, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    text = _SAFE_ID_FRAGMENT.sub("-", text).strip(".-_")
    return (text or default)[:max_length]


def _trim_text(value: Any, *, max_length: int) -> str:
    return str(value or "").strip()[:max_length]


def _trim_list(value: Any, *, max_items: int, max_length: int) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        return []
    result: list[str] = []
    for item in items:
        text = _trim_text(item, max_length=max_length)
        if text:
            result.append(text)
        if len(result) >= max_items:
            break
    return result


def _normalize_refs(value: Any, *, max_items: int) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        return []
    refs: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            ref = {str(key)[:80]: _normalize_metadata_value(val) for key, val in item.items()}
        else:
            text = _trim_text(item, max_length=500)
            ref = {"ref": text} if text else {}
        if ref:
            refs.append(ref)
        if len(refs) >= max_items:
            break
    return refs


def _normalize_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key)[:80]: _normalize_metadata_value(item) for key, item in list(value.items())[:40]}


def _normalize_metadata_value(value: Any) -> Any:
    if isinstance(value, str):
        return _trim_text(value, max_length=1000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_normalize_metadata_value(item) for item in value[:40]]
    if isinstance(value, dict):
        return _normalize_metadata(value)
    return _trim_text(value, max_length=1000)


def _versioning_record_child_log_payload(
    team_id: str,
    version_record: dict[str, Any],
    *,
    relation_record: dict[str, Any] | None = None,
    rejection_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "challenge_cup_versioning_record",
        "teamId": team_id,
        "operation": _trim_text(version_record.get("operation"), max_length=80),
        "candidateId": _trim_text(version_record.get("candidateId"), max_length=160),
        "versionId": _trim_text(version_record.get("versionId"), max_length=160),
        "versionLabel": _trim_text(version_record.get("versionLabel"), max_length=120),
        "relationId": _trim_text((relation_record or {}).get("relationId"), max_length=160),
        "rejectionId": _trim_text((rejection_record or {}).get("rejectionId"), max_length=160),
        "supersedesVersionId": _trim_text(version_record.get("supersedesVersionId"), max_length=160),
        "derivedFromVersionId": _trim_text(version_record.get("derivedFromVersionId"), max_length=160),
        "evidenceRefCount": len([item for item in list(version_record.get("evidenceRefs") or []) if isinstance(item, dict)]),
        "changeSetCount": len([item for item in list(version_record.get("changeSet") or []) if isinstance(item, dict)]),
        "recordedByAgent": _trim_text(version_record.get("recordedByAgent"), max_length=160),
        "boundary": "candidate_versioning_ledger_only_not_official_graph",
    }


def _record_versioning_event(
    event_code: str,
    team_id: str,
    *,
    fields: dict[str, Any],
    child_log_payload: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "challenge_cup_versioning",
            "workflow",
            event_code,
            message=event_code,
            fields={"teamId": team_id, **fields},
            child_log_path=f"artifacts/challenge-cup-versioning-{_safe_token(team_id, default='team', max_length=96)}.jsonl",
            child_log_payload=child_log_payload,
        )
    except Exception:
        return
