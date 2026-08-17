"""Append-only personal memory candidate service with scope gating.

Classifies each participating agent's memory candidate by theme, campaign,
memory class, reuse policy, and evidence status.  Cross-theme candidates are
only ever advisory and always require revalidation; an unaccepted candidate is
never injected.  Pure offline JSONL under the team workspace.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.research.workflow.contracts import (
    ContractValidationError,
    PersonalMemoryCandidate,
    scope_hash_for,
)

SCHEMA_VERSION = 1
DEFAULT_MODE = "formal"
_LOCK = threading.RLock()
_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class PersonalMemoryCandidateError(RuntimeError):
    """Base error for personal memory candidate persistence."""


class PersonalMemoryCandidateNotFoundError(PersonalMemoryCandidateError):
    """Raised when a memory candidate does not exist."""


class PersonalMemoryCandidateNotAcceptedError(PersonalMemoryCandidateError):
    """Raised when an unaccepted candidate would be injected."""


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


def _safe_agent_id(agent_id: str) -> str:
    raw = str(agent_id or "").strip()
    prefix = (
        "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in raw
        )[:72]
        or "agent"
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


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
            raise PersonalMemoryCandidateError(
                f"Invalid personal memory JSONL at line {line_number}."
            ) from exc
        if not isinstance(payload, dict):
            raise PersonalMemoryCandidateError(
                f"Invalid personal memory record at line {line_number}."
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


def _store_path(team_id: str, agent_id: str) -> Path:
    """Return one physically isolated JSONL store for one agent."""
    return (
        _team_workspace_root(team_id)
        / "research_workflow"
        / "personal_memory"
        / f"{_safe_agent_id(agent_id)}.jsonl"
    )


def _candidate_definition(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "memoryCandidateId",
            "agentId",
            "theme",
            "campaign",
            "scopeHash",
            "targetTheme",
            "targetCampaign",
            "targetScopeHash",
            "sourceRefs",
            "memoryClass",
            "reusePolicy",
            "evidenceStatus",
            "summary",
            "needsRevalidation",
            "advisoryOnly",
            "accepted",
            "injected",
        )
    }


def record_personal_memory_candidates(
    team_id: str,
    *,
    scope_payload: Mapping[str, Any],
    target_scope_payload: Mapping[str, Any] | None = None,
    agents: Sequence[str],
    source_refs: Sequence[str],
    memory_class: str = "personal_reflection",
    summaries: Mapping[str, str] | None = None,
    reuse_policy: str = "advisory_only",
    evidence_status: str = "unverified",
    needs_revalidation: bool | None = None,
    advisory_only: bool | None = None,
    accepted: bool = False,
) -> dict[str, Any]:
    """Record one personal memory candidate per participating agent.

    Idempotent by candidate id: a repeated call with identical inputs reuses
    the existing candidate instead of appending a duplicate.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    source_scope = _resolve_scope(dict(scope_payload))
    target_scope = _resolve_scope(
        dict(target_scope_payload) if isinstance(target_scope_payload, Mapping) else dict(scope_payload)
    )
    agent_ids = [str(agent or "").strip() for agent in agents]
    agent_ids = [agent for agent in agent_ids if agent]
    if not agent_ids:
        raise ContractValidationError("at least one participating agent is required")
    if len(set(agent_ids)) != len(agent_ids):
        raise ContractValidationError("participating agent ids must be unique")
    source_refs_list = [str(ref or "").strip() for ref in source_refs]
    summary_map = {
        str(key or "").strip(): str(value or "").strip()
        for key, value in (summaries or {}).items()
    }
    cross_theme = (
        source_scope["theme"] != target_scope["theme"]
        or source_scope["campaign"] != target_scope["campaign"]
        or source_scope["scopeHash"] != target_scope["scopeHash"]
    )
    resolved_needs_revalidation = (
        bool(needs_revalidation) if needs_revalidation is not None else cross_theme
    )
    resolved_advisory_only = (
        bool(advisory_only) if advisory_only is not None else cross_theme
    )
    if cross_theme and not (resolved_advisory_only and resolved_needs_revalidation):
        raise ContractValidationError(
            "cross-theme memory candidates must be advisoryOnly and needsRevalidation"
        )
    normalized_class = str(memory_class or "").strip().lower() or "personal_reflection"
    normalized_policy = str(reuse_policy or "").strip().lower() or "advisory_only"
    normalized_evidence = str(evidence_status or "").strip().lower() or "unverified"
    now = _utc_now()
    created: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    storage_paths: dict[str, str] = {}
    for agent_id in agent_ids:
        summary = summary_map.get(agent_id) or f"{normalized_class} note for {agent_id}"
        seed = {
            "agentId": agent_id,
            "scopeHash": source_scope["scopeHash"],
            "memoryClass": normalized_class,
            "summary": summary,
            "sourceRefs": source_refs_list,
            "targetScopeHash": target_scope["scopeHash"],
        }
        candidate_id = f"memory-{_stable_hash(seed)[:20]}"
        record: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "memoryCandidateId": candidate_id,
            "agentId": agent_id,
            "theme": source_scope["theme"],
            "campaign": source_scope["campaign"],
            "scopeHash": source_scope["scopeHash"],
            "targetTheme": target_scope["theme"],
            "targetCampaign": target_scope["campaign"],
            "targetScopeHash": target_scope["scopeHash"],
            "sourceRefs": source_refs_list,
            "memoryClass": normalized_class,
            "reusePolicy": normalized_policy,
            "evidenceStatus": normalized_evidence,
            "summary": summary,
            "needsRevalidation": resolved_needs_revalidation,
            "advisoryOnly": resolved_advisory_only,
            "accepted": accepted,
            "injected": False,
            "createdAt": now,
            "acceptedAt": now if accepted else "",
            "injectedAt": "",
        }
        # Fail closed before persistence.
        PersonalMemoryCandidate.from_dict(record)
        store_path = _store_path(normalized_team_id, agent_id)
        storage_paths[agent_id] = str(store_path)
        with _LOCK:
            existing = _latest_by_id(
                _read_jsonl(store_path),
                "memoryCandidateId",
                candidate_id,
            )
            if existing is not None:
                if _candidate_definition(existing) != _candidate_definition(record):
                    raise PersonalMemoryCandidateError(
                        "memory candidate id is already bound to different content"
                    )
                reused.append(existing)
                continue
            _append_jsonl(store_path, record)
        created.append(record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "createdCount": len(created),
        "reusedCount": len(reused),
        "candidates": created + reused,
        "policy": {
            "crossThemeAdvisoryOnly": True,
            "unacceptedNeverInjected": True,
            "revalidationRequiredForCrossTheme": True,
        },
        "storagePathsByAgent": storage_paths,
    }


def get_personal_memory_candidate(
    team_id: str,
    memory_candidate_id: str,
    *,
    agent_id: str,
) -> dict[str, Any]:
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_id = str(memory_candidate_id or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise PersonalMemoryCandidateError("Agent id is required for private memory access.")
    store_path = _store_path(normalized_team_id, normalized_agent_id)
    with _LOCK:
        record = _latest_by_id(
            _read_jsonl(store_path),
            "memoryCandidateId",
            normalized_id,
        )
    if record is None:
        raise PersonalMemoryCandidateNotFoundError("Personal memory candidate not found.")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "candidate": record,
        "storagePath": str(store_path),
    }


def list_personal_memory_candidates(
    team_id: str,
    *,
    agent_id: str,
    theme: str = "",
    memory_class: str = "",
) -> dict[str, Any]:
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise PersonalMemoryCandidateError("Agent id is required for private memory access.")
    store_path = _store_path(normalized_team_id, normalized_agent_id)
    with _LOCK:
        records = _read_jsonl(store_path)
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        latest[str(record.get("memoryCandidateId") or "")] = record
    rows = list(latest.values())
    rows = [
        item
        for item in rows
        if str(item.get("agentId") or "") == normalized_agent_id
    ]
    if theme:
        normalized_theme = str(theme or "").strip()
        rows = [
            item
            for item in rows
            if normalized_theme
            in {
                str(item.get("theme") or ""),
                str(item.get("targetTheme") or ""),
            }
        ]
    if memory_class:
        rows = [
            item
            for item in rows
            if str(item.get("memoryClass") or "").strip().lower()
            == str(memory_class or "").strip().lower()
        ]
    rows.sort(key=lambda item: str(item.get("createdAt") or ""))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "candidateCount": len(rows),
        "candidates": rows,
        "storagePath": str(store_path),
    }


def accept_personal_memory_candidate(
    team_id: str,
    memory_candidate_id: str,
    *,
    agent_id: str,
    accepted_by: str,
) -> dict[str, Any]:
    """Accept one candidate, appending an updated record (append-only).

    Cross-theme candidates stay advisory and needsRevalidation after
    acceptance; only the accepted flag and timestamp change.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_id = str(memory_candidate_id or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise PersonalMemoryCandidateError("Agent id is required for private memory access.")
    if not normalized_id:
        raise PersonalMemoryCandidateError("Memory candidate id is required.")
    reviewer = str(accepted_by or "").strip()
    if not reviewer:
        raise ContractValidationError("acceptedBy is required to accept a candidate")
    store_path = _store_path(normalized_team_id, normalized_agent_id)
    with _LOCK:
        records = _read_jsonl(store_path)
        current = _latest_by_id(records, "memoryCandidateId", normalized_id)
        if current is None:
            raise PersonalMemoryCandidateNotFoundError("Personal memory candidate not found.")
        now = _utc_now()
        updated = dict(current)
        updated["accepted"] = True
        updated["acceptedAt"] = now
        updated["acceptedBy"] = reviewer
        if PersonalMemoryCandidate.from_dict(updated).is_cross_theme():
            updated["advisoryOnly"] = True
            updated["needsRevalidation"] = True
        PersonalMemoryCandidate.from_dict(updated)
        _append_jsonl(store_path, updated)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "accepted",
        "candidate": updated,
        "storagePath": str(store_path),
    }


def inject_personal_memory_candidate(
    team_id: str,
    memory_candidate_id: str,
    *,
    agent_id: str,
    injected_by: str = "",
) -> dict[str, Any]:
    """Mark one accepted candidate as injected.

    Fails closed when the candidate has not been accepted: unaccepted
    candidates are never injected.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_id = str(memory_candidate_id or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise PersonalMemoryCandidateError("Agent id is required for private memory access.")
    if not normalized_id:
        raise PersonalMemoryCandidateError("Memory candidate id is required.")
    store_path = _store_path(normalized_team_id, normalized_agent_id)
    with _LOCK:
        records = _read_jsonl(store_path)
        current = _latest_by_id(records, "memoryCandidateId", normalized_id)
        if current is None:
            raise PersonalMemoryCandidateNotFoundError("Personal memory candidate not found.")
        if not bool(current.get("accepted")):
            raise PersonalMemoryCandidateNotAcceptedError(
                "an unaccepted memory candidate is never injected"
            )
        now = _utc_now()
        updated = dict(current)
        updated["injected"] = True
        updated["injectedAt"] = now
        updated["injectedBy"] = str(injected_by or "").strip()
        PersonalMemoryCandidate.from_dict(updated)
        _append_jsonl(store_path, updated)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "injected",
        "candidate": updated,
        "storagePath": str(store_path),
    }
