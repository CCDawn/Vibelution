# -*- coding: utf-8 -*-
"""Bounded reflection records derived from self-evolution experiences."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from core.gym.models import utcnow_iso
from core.infrastructure.workspace_manager import get_workspace


REFLECTION_ROOT = Path("self_evolution/reflection")
REFLECTION_JSONL = REFLECTION_ROOT / "reflection.jsonl"
REFLECTION_INDEX = REFLECTION_ROOT / "index.json"


@dataclass(frozen=True)
class ReflectionPaths:
    root: Path
    jsonl: Path
    index: Path


@dataclass(frozen=True)
class RecordReflectionResult:
    record: dict[str, Any]
    created: bool
    path: Path


def reflection_paths(*, project_root: Optional[Path] = None) -> ReflectionPaths:
    root = _workspace_root(project_root)
    reflection_root = root / REFLECTION_ROOT
    return ReflectionPaths(
        root=reflection_root,
        jsonl=root / REFLECTION_JSONL,
        index=root / REFLECTION_INDEX,
    )


def _workspace_root(project_root: Optional[Path] = None) -> Path:
    if project_root is None:
        return get_workspace().root.resolve()
    root = Path(project_root).resolve()
    return root if root.name.lower() == "workspace" else root / "workspace"


def build_bounded_self_evolution_reflection(experience: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(experience, dict):
        raise ValueError("Self-evolution reflection requires an experience record")
    experience_id = _required_text(experience, "experience_id")
    source_run_id = _required_text(experience, "source_run_id")
    evidence = _object(experience.get("evidence"))
    evidence_refs = _evidence_refs(experience)
    status = _text(evidence.get("status")) or _text(experience.get("kind")) or "unknown"
    tool_name = _text(evidence.get("tool_name")) or "unknown_tool"
    summary = _text(experience.get("summary"))[:500]
    created_at = utcnow_iso()
    dedupe_key = f"self_reflection:{experience_id}"

    record = {
        "reflection_id": _reflection_id(experience_id, source_run_id, dedupe_key),
        "source_experience_id": experience_id,
        "source_run_id": source_run_id,
        "source_turn": _safe_int(experience.get("source_turn"), default=0),
        "txn_id": _text(experience.get("txn_id")),
        "dedupe_key": dedupe_key,
        "summary": summary,
        "bounded": True,
        "candidate_only": True,
        "auto_apply": False,
        "supervised_required": True,
        "downstream_use": ["self_questioning", "self_navigating", "self_attributing", "candidate_pool"],
        "self_questioning": _build_questions(
            status=status,
            tool_name=tool_name,
            summary=summary,
            evidence_refs=evidence_refs,
        ),
        "self_navigating": _build_navigation_hints(
            status=status,
            tool_name=tool_name,
            evidence_refs=evidence_refs,
        ),
        "self_attributing": _build_attributions(
            status=status,
            tool_name=tool_name,
            evidence=evidence,
            evidence_refs=evidence_refs,
            confidence=_safe_float(experience.get("confidence"), default=0.0),
        ),
        "created_at": created_at,
    }
    return record


def record_bounded_self_evolution_reflection(
    experience: dict[str, Any],
    *,
    project_root: Optional[Path] = None,
) -> RecordReflectionResult:
    record = build_bounded_self_evolution_reflection(experience)
    paths = reflection_paths(project_root=project_root)
    paths.root.mkdir(parents=True, exist_ok=True)
    existing = _find_existing_by_dedupe_key(paths.jsonl, record["dedupe_key"])
    if existing is not None:
        return RecordReflectionResult(record=existing, created=False, path=paths.jsonl)

    with paths.jsonl.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    _write_index(paths.index, record, record_count=len(_read_jsonl_records(paths.jsonl)))
    return RecordReflectionResult(record=record, created=True, path=paths.jsonl)


def list_reflection_records(
    *,
    project_root: Optional[Path] = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    paths = reflection_paths(project_root=project_root)
    rows = _read_jsonl_records(paths.jsonl)
    if limit is not None:
        count = max(0, int(limit))
        if count == 0:
            return []
        return rows[-count:]
    return rows


def _build_questions(
    *,
    status: str,
    tool_name: str,
    summary: str,
    evidence_refs: list[str],
) -> list[dict[str, Any]]:
    question = (
        f"What bounded check would prevent a {status} run after {tool_name} "
        "without changing evaluation standards?"
    )
    if summary:
        question = f"{question} Evidence summary: {summary[:180]}"
    return [
        {
            "candidate_type": "question_candidate",
            "question": question,
            "bounded": True,
            "evidence_refs": evidence_refs,
            "blocked_downstream_uses": ["accepted_baseline", "selection_policy", "runtime_prompt"],
        }
    ]


def _build_navigation_hints(
    *,
    status: str,
    tool_name: str,
    evidence_refs: list[str],
) -> list[dict[str, Any]]:
    if status == "done":
        hint = f"Reuse the verified path around {tool_name} only after checking current worktree, leases, and transaction state."
    else:
        hint = f"Before retrying after {tool_name}, inspect current evidence and run the smallest verification that reproduces the issue."
    return [
        {
            "candidate_type": "navigation_hint",
            "hint": hint,
            "bounded": True,
            "must_recheck_current_state": True,
            "auto_apply": False,
            "evidence_refs": evidence_refs,
        }
    ]


def _build_attributions(
    *,
    status: str,
    tool_name: str,
    evidence: dict[str, Any],
    evidence_refs: list[str],
    confidence: float,
) -> list[dict[str, Any]]:
    rollback_count = _safe_int(evidence.get("rollback_entry_count"), default=0)
    claim = f"Run status {status} is associated with tool {tool_name}"
    if rollback_count:
        claim = f"{claim} and {rollback_count} rollback-tracked file change(s)"
    return [
        {
            "candidate_type": "attribution_record",
            "claim": claim,
            "bounded": True,
            "confidence": max(0.0, min(1.0, confidence or 0.4)),
            "evidence_refs": evidence_refs,
            "supports_candidate_ranking_only": True,
        }
    ]


def _evidence_refs(experience: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("runtime_scene_refs", "audit_refs"):
        for value in _string_list(experience.get(key)):
            if value not in refs:
                refs.append(value)
    source = _text(experience.get("source_run_id"))
    if not refs and source:
        refs.append(f"experience:{source}")
    return refs


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
        "latest_reflection_id": str(latest.get("reflection_id") or ""),
        "updated_at": utcnow_iso(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _required_text(record: dict[str, Any], key: str) -> str:
    value = _text(record.get(key))
    if not value:
        raise ValueError(f"Self-evolution reflection missing required field: {key}")
    return value


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    raw_items = value if isinstance(value, list) else [] if value is None else [value]
    items: list[str] = []
    for raw in raw_items:
        item = _text(raw)
        if item and item not in items:
            items.append(item)
    return items


def _text(value: Any) -> str:
    return str(value or "").strip()


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


def _reflection_id(experience_id: str, source_run_id: str, dedupe_key: str) -> str:
    digest = hashlib.sha256(f"{experience_id}\n{source_run_id}\n{dedupe_key}".encode("utf-8")).hexdigest()
    return f"refl_{digest[:16]}"


__all__ = [
    "REFLECTION_INDEX",
    "REFLECTION_JSONL",
    "REFLECTION_ROOT",
    "RecordReflectionResult",
    "ReflectionPaths",
    "build_bounded_self_evolution_reflection",
    "list_reflection_records",
    "record_bounded_self_evolution_reflection",
    "reflection_paths",
]
