# -*- coding: utf-8 -*-
"""Bounded experience repository for self-evolution runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from core.gym.models import utcnow_iso
from core.infrastructure.workspace_manager import get_workspace


EXPERIENCE_ROOT = Path("self_evolution/experience")
EXPERIENCE_JSONL = EXPERIENCE_ROOT / "experience.jsonl"
EXPERIENCE_INDEX = EXPERIENCE_ROOT / "index.json"


@dataclass(frozen=True)
class ExperiencePaths:
    root: Path
    jsonl: Path
    index: Path


@dataclass(frozen=True)
class AppendExperienceResult:
    record: dict[str, Any]
    created: bool
    path: Path


def experience_paths(*, project_root: Optional[Path] = None) -> ExperiencePaths:
    root = _workspace_root(project_root)
    experience_root = root / EXPERIENCE_ROOT
    return ExperiencePaths(
        root=experience_root,
        jsonl=root / EXPERIENCE_JSONL,
        index=root / EXPERIENCE_INDEX,
    )


def _workspace_root(project_root: Optional[Path] = None) -> Path:
    if project_root is None:
        return get_workspace().root.resolve()
    root = Path(project_root).resolve()
    return root if root.name.lower() == "workspace" else root / "workspace"


def append_experience_record(
    record: dict[str, Any],
    *,
    project_root: Optional[Path] = None,
) -> AppendExperienceResult:
    normalized = _normalize_record(record)
    paths = experience_paths(project_root=project_root)
    paths.root.mkdir(parents=True, exist_ok=True)

    existing = _find_existing_by_dedupe_key(paths.jsonl, normalized.get("dedupe_key"))
    if existing is not None:
        return AppendExperienceResult(record=existing, created=False, path=paths.jsonl)

    with paths.jsonl.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(normalized, ensure_ascii=False) + "\n")
    _write_index(paths.index, normalized, record_count=len(_read_jsonl_records(paths.jsonl)))
    return AppendExperienceResult(record=normalized, created=True, path=paths.jsonl)


def list_experience_records(
    *,
    project_root: Optional[Path] = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    paths = experience_paths(project_root=project_root)
    rows = _read_jsonl_records(paths.jsonl)
    if limit is not None:
        count = max(0, int(limit))
        if count == 0:
            return []
        return rows[-count:]
    return rows


def build_terminal_self_evolution_experience(
    snapshot: dict[str, Any],
    *,
    rollback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise ValueError("Terminal self-evolution snapshot must be a JSON object")
    run_id = _required_text(snapshot, "runId")
    status = _text(snapshot.get("status")) or "unknown"
    summary = _terminal_summary(snapshot, status=status)
    rollback_payload = rollback if isinstance(rollback, dict) else _object(snapshot.get("rollback"))
    artifacts = _object(snapshot.get("artifacts"))

    return {
        "kind": _terminal_kind(status),
        "source_run_id": run_id,
        "source_turn": _safe_int(snapshot.get("turnCount"), default=0),
        "txn_id": _text(snapshot.get("txnId") or snapshot.get("txn_id")),
        "runtime_scene_refs": _artifact_refs(artifacts, keys=("runDir",)),
        "audit_refs": _artifact_refs(artifacts, keys=("manifestPath",)),
        "summary": summary,
        "evidence": {
            "status": status,
            "phase": _text(snapshot.get("phase")),
            "tool_name": _text(snapshot.get("lastToolName")),
            "tool_call_count": _safe_int(snapshot.get("toolCallCount"), default=0),
            "runtime_status": _text(snapshot.get("runtimeStatus")),
            "rollback_status": _text(rollback_payload.get("status")),
            "rollback_entry_count": _safe_int(rollback_payload.get("entryCount"), default=0),
            "error_present": bool(_text(snapshot.get("error"))),
            "cancel_requested": bool(snapshot.get("cancelRequested")),
        },
        "quality_score": _terminal_quality(status),
        "confidence": 0.6 if status in {"done", "failed", "cancelled"} else 0.3,
        "dedupe_key": f"self_terminal:{run_id}",
        "downstream_use": _terminal_downstream_use(status),
        "supervised_required": True,
    }


def record_terminal_self_evolution_experience(
    snapshot: dict[str, Any],
    *,
    rollback: dict[str, Any] | None = None,
    project_root: Optional[Path] = None,
) -> AppendExperienceResult:
    return append_experience_record(
        build_terminal_self_evolution_experience(snapshot, rollback=rollback),
        project_root=project_root,
    )


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("Experience record must be a JSON object")

    kind = _required_text(record, "kind")
    source_run_id = _required_text(record, "source_run_id")
    summary = _required_text(record, "summary")
    created_at = _text(record.get("created_at")) or utcnow_iso()

    payload: dict[str, Any] = {
        "experience_id": _text(record.get("experience_id")) or _experience_id(source_run_id, kind, summary, created_at),
        "kind": kind,
        "source_run_id": source_run_id,
        "source_turn": _safe_int(record.get("source_turn"), default=0),
        "txn_id": _text(record.get("txn_id")),
        "runtime_scene_refs": _string_list(record.get("runtime_scene_refs")),
        "audit_refs": _string_list(record.get("audit_refs")),
        "summary": summary,
        "evidence": _object(record.get("evidence")),
        "quality_score": _safe_float(record.get("quality_score"), default=0.0),
        "confidence": _safe_float(record.get("confidence"), default=0.0),
        "dedupe_key": _text(record.get("dedupe_key")) or _dedupe_key(source_run_id, kind, summary),
        "downstream_use": _string_list(record.get("downstream_use")),
        "supervised_required": bool(record.get("supervised_required", True)),
        "created_at": created_at,
    }
    return payload


def _find_existing_by_dedupe_key(path: Path, dedupe_key: Any) -> dict[str, Any] | None:
    key = _text(dedupe_key)
    if not key or not path.exists():
        return None
    for record in _read_jsonl_records(path):
        if _text(record.get("dedupe_key")) == key:
            return record
    return None


def _read_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _write_index(path: Path, latest: dict[str, Any], *, record_count: int) -> None:
    payload = {
        "version": 1,
        "record_count": max(0, int(record_count)),
        "latest_experience_id": str(latest.get("experience_id") or ""),
        "updated_at": utcnow_iso(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _required_text(record: dict[str, Any], key: str) -> str:
    value = _text(record.get(key))
    if not value:
        raise ValueError(f"Experience record missing required field: {key}")
    return value


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    raw_items = value if isinstance(value, list) else [] if value is None else [value]
    items: list[str] = []
    for raw in raw_items:
        item = _text(raw)
        if item and item not in items:
            items.append(item)
    return items


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _artifact_refs(artifacts: dict[str, Any], *, keys: tuple[str, ...]) -> list[str]:
    refs: list[str] = []
    for key in keys:
        value = _text(artifacts.get(key))
        if value:
            refs.append(value)
    return refs


def _terminal_summary(snapshot: dict[str, Any], *, status: str) -> str:
    for key in ("summary", "latestMessage", "error", "goal"):
        value = _text(snapshot.get(key))
        if value:
            return value[:500]
    return f"Self-evolution run reached terminal status: {status}"


def _terminal_kind(status: str) -> str:
    if status == "done":
        return "successful_strategy"
    if status == "failed":
        return "failure_pattern"
    if status == "cancelled":
        return "diagnostic_case"
    return "diagnostic_case"


def _terminal_quality(status: str) -> float:
    if status == "done":
        return 0.6
    if status == "failed":
        return 0.4
    if status == "cancelled":
        return 0.2
    return 0.0


def _terminal_downstream_use(status: str) -> list[str]:
    if status == "done":
        return ["self_questioning", "self_navigating", "supervised_candidate"]
    if status == "failed":
        return ["self_questioning", "self_attributing", "diagnostic_case"]
    if status == "cancelled":
        return ["self_attributing", "diagnostic_case"]
    return ["diagnostic_case"]


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _experience_id(source_run_id: str, kind: str, summary: str, created_at: str) -> str:
    digest = hashlib.sha256(f"{source_run_id}\n{kind}\n{summary}\n{created_at}".encode("utf-8")).hexdigest()
    return f"exp_{digest[:16]}"


def _dedupe_key(source_run_id: str, kind: str, summary: str) -> str:
    digest = hashlib.sha256(f"{source_run_id}\n{kind}\n{summary}".encode("utf-8")).hexdigest()
    return f"{source_run_id}:{kind}:{digest[:16]}"


__all__ = [
    "EXPERIENCE_INDEX",
    "EXPERIENCE_JSONL",
    "EXPERIENCE_ROOT",
    "AppendExperienceResult",
    "ExperiencePaths",
    "append_experience_record",
    "build_terminal_self_evolution_experience",
    "experience_paths",
    "list_experience_records",
    "record_terminal_self_evolution_experience",
]
