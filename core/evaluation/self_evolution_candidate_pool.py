# -*- coding: utf-8 -*-
"""Candidate pool for bounded self-evolution outputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from core.gym.models import utcnow_iso
from core.infrastructure.workspace_manager import get_workspace
from .supervised_intake import (
    self_evolution_allowed_downstream_uses,
    self_evolution_blocked_downstream_uses,
    self_evolution_candidate_boundary,
    self_evolution_candidate_risk_level,
)


CANDIDATE_ROOT = Path("workspace/self_evolution/candidates")
CANDIDATE_INDEX = CANDIDATE_ROOT / "index.json"
CANDIDATE_JSONL_BY_TYPE = {
    "skill_candidate": CANDIDATE_ROOT / "skill_candidates.jsonl",
    "prompt_candidate": CANDIDATE_ROOT / "prompt_candidates.jsonl",
    "proposal_candidate": CANDIDATE_ROOT / "proposal_candidates.jsonl",
}
ALLOWED_CANDIDATE_TYPES = set(CANDIDATE_JSONL_BY_TYPE)


@dataclass(frozen=True)
class CandidatePoolPaths:
    root: Path
    index: Path
    by_type: dict[str, Path]


@dataclass(frozen=True)
class AppendCandidateResult:
    record: dict[str, Any]
    created: bool
    path: Path


def candidate_pool_paths(*, project_root: Optional[Path] = None) -> CandidatePoolPaths:
    root = (project_root or get_workspace().project_root).resolve()
    return CandidatePoolPaths(
        root=root / CANDIDATE_ROOT,
        index=root / CANDIDATE_INDEX,
        by_type={candidate_type: root / path for candidate_type, path in CANDIDATE_JSONL_BY_TYPE.items()},
    )


def build_candidate_from_reflection(reflection: dict[str, Any], *, candidate_type: str) -> dict[str, Any]:
    normalized_type = _validate_candidate_type(candidate_type)
    if not isinstance(reflection, dict):
        raise ValueError("Self-evolution candidate requires a reflection record")
    reflection_id = _required_text(reflection, "reflection_id")
    source_experience_id = _required_text(reflection, "source_experience_id")
    source_run_id = _required_text(reflection, "source_run_id")
    txn_id = _text(reflection.get("txn_id"))
    evidence_refs = _reflection_evidence_refs(reflection)
    payload = _candidate_payload(reflection, normalized_type)
    dedupe_key = f"self_candidate:{normalized_type}:{reflection_id}"
    candidate_id = f"{normalized_type}:{_stable_digest(dedupe_key)[:16]}"
    allowed_downstream_uses = self_evolution_allowed_downstream_uses(normalized_type)
    blocked_downstream_uses = self_evolution_blocked_downstream_uses(normalized_type)
    supervised_intake_boundary = self_evolution_candidate_boundary(
        {
            "candidate_type": normalized_type,
            "allowed_downstream_uses": allowed_downstream_uses,
        }
    )

    return {
        "candidate_id": candidate_id,
        "candidate_type": normalized_type,
        "source_experience_id": source_experience_id,
        "source_reflection_id": reflection_id,
        "source_run_id": source_run_id,
        "txn_id": txn_id,
        "provenance": {
            "source_experience_id": source_experience_id,
            "source_reflection_id": reflection_id,
            "source_run_id": source_run_id,
            "source_turn": _safe_int(reflection.get("source_turn"), default=0),
            "txn_id": txn_id,
            "evidence_refs": evidence_refs,
            "created_from": "self_evolution_reflection",
        },
        "payload": payload,
        "review_state": "pending",
        "risk_level": supervised_intake_boundary["risk_level"],
        "allowed_downstream_uses": supervised_intake_boundary["allowed_downstream_uses"],
        "blocked_downstream_uses": supervised_intake_boundary["blocked_downstream_uses"],
        "supervised_required": True,
        "candidate_only": True,
        "auto_apply": False,
        "supervised_intake_boundary": supervised_intake_boundary,
        "dedupe_key": dedupe_key,
        "quality_score": 0.0,
        "confidence": _safe_float(_first_attribution(reflection).get("confidence"), default=0.0),
        "target_path": str(CANDIDATE_JSONL_BY_TYPE[normalized_type]).replace("\\", "/"),
        "created_at": utcnow_iso(),
    }


def append_candidate_record(
    candidate: dict[str, Any],
    *,
    project_root: Optional[Path] = None,
) -> AppendCandidateResult:
    record = _normalize_candidate_record(candidate)
    paths = candidate_pool_paths(project_root=project_root)
    path = paths.by_type[record["candidate_type"]]
    paths.root.mkdir(parents=True, exist_ok=True)

    existing = _find_existing_by_dedupe_key(path, record.get("dedupe_key"))
    if existing is not None:
        return AppendCandidateResult(record=existing, created=False, path=path)

    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    _write_index(paths.index, paths.by_type)
    return AppendCandidateResult(record=record, created=True, path=path)


def list_candidate_records(
    candidate_type: str,
    *,
    project_root: Optional[Path] = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    normalized_type = _validate_candidate_type(candidate_type)
    path = candidate_pool_paths(project_root=project_root).by_type[normalized_type]
    rows = _read_jsonl_records(path)
    if limit is not None:
        count = max(0, int(limit))
        if count == 0:
            return []
        return rows[-count:]
    return rows


def _normalize_candidate_record(candidate: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ValueError("Self-evolution candidate must be a JSON object")
    candidate_type = _validate_candidate_type(candidate.get("candidate_type"))
    source_experience_id = _required_text(candidate, "source_experience_id")
    source_run_id = _required_text(candidate, "source_run_id")
    provenance = _object(candidate.get("provenance"))
    if not provenance:
        raise ValueError("Self-evolution candidate requires provenance")
    candidate_id = _text(candidate.get("candidate_id")) or f"{candidate_type}:{_stable_digest(json.dumps(provenance, sort_keys=True))[:16]}"
    dedupe_key = _text(candidate.get("dedupe_key")) or f"self_candidate:{candidate_type}:{candidate_id}"
    blocked_downstream_uses = _merge_unique(
        _string_list(candidate.get("blocked_downstream_uses")),
        self_evolution_blocked_downstream_uses(candidate_type),
    )
    allowed_downstream_uses = _filter_allowed_downstream_uses(
        _string_list(candidate.get("allowed_downstream_uses"))
        or self_evolution_allowed_downstream_uses(candidate_type),
        blocked_downstream_uses,
        candidate_type,
    )
    boundary = self_evolution_candidate_boundary(
        {
            **candidate,
            "candidate_type": candidate_type,
            "allowed_downstream_uses": allowed_downstream_uses,
            "risk_level": _candidate_risk_level(candidate.get("risk_level")),
        }
    )
    return {
        "candidate_id": candidate_id,
        "candidate_type": candidate_type,
        "source_experience_id": source_experience_id,
        "source_reflection_id": _text(candidate.get("source_reflection_id") or provenance.get("source_reflection_id")),
        "source_run_id": source_run_id,
        "txn_id": _text(candidate.get("txn_id") or provenance.get("txn_id")),
        "provenance": provenance,
        "payload": _object(candidate.get("payload")),
        "review_state": "pending",
        "risk_level": boundary["risk_level"],
        "allowed_downstream_uses": boundary["allowed_downstream_uses"],
        "blocked_downstream_uses": boundary["blocked_downstream_uses"],
        "supervised_required": True,
        "candidate_only": True,
        "auto_apply": False,
        "supervised_intake_boundary": boundary,
        "dedupe_key": dedupe_key,
        "quality_score": _safe_float(candidate.get("quality_score"), default=0.0),
        "confidence": _safe_float(candidate.get("confidence"), default=0.0),
        "target_path": str(CANDIDATE_JSONL_BY_TYPE[candidate_type]).replace("\\", "/"),
        "created_at": _text(candidate.get("created_at")) or utcnow_iso(),
    }


def _candidate_payload(reflection: dict[str, Any], candidate_type: str) -> dict[str, Any]:
    if candidate_type == "skill_candidate":
        source = _first_item(reflection.get("self_navigating"))
        return {
            "suggested_skill_scope": "bounded_self_evolution_heuristic",
            "description": _text(source.get("hint") or reflection.get("summary"))[:500],
            "evidence_refs": _reflection_evidence_refs(reflection),
        }
    if candidate_type == "prompt_candidate":
        source = _first_item(reflection.get("self_questioning"))
        return {
            "suggested_prompt_change": _text(source.get("question") or reflection.get("summary"))[:500],
            "constraints": ["candidate_only", "requires_supervised_review"],
            "evidence_refs": _reflection_evidence_refs(reflection),
        }
    if candidate_type == "proposal_candidate":
        source = _first_attribution(reflection)
        return {
            "proposal_summary": _text(source.get("claim") or reflection.get("summary"))[:500],
            "supports_candidate_ranking_only": True,
            "evidence_refs": _reflection_evidence_refs(reflection),
        }
    raise ValueError(f"Unknown self-evolution candidate type: {candidate_type}")


def _allowed_downstream_uses(candidate_type: str) -> list[str]:
    return self_evolution_allowed_downstream_uses(candidate_type)


def _blocked_downstream_uses(candidate_type: str) -> list[str]:
    return self_evolution_blocked_downstream_uses(candidate_type)


def _filter_allowed_downstream_uses(allowed: list[str], blocked: list[str], candidate_type: str) -> list[str]:
    filtered = [item for item in allowed if item not in set(blocked)]
    return filtered or _allowed_downstream_uses(candidate_type)


def _candidate_risk_level(value: Any) -> str:
    return self_evolution_candidate_risk_level(value)


def _reflection_evidence_refs(reflection: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for bucket_name in ("self_questioning", "self_navigating", "self_attributing"):
        for item in list(reflection.get(bucket_name) or []):
            if isinstance(item, dict):
                refs = _merge_unique(refs, _string_list(item.get("evidence_refs")))
    if not refs:
        source_run_id = _text(reflection.get("source_run_id"))
        if source_run_id:
            refs.append(f"reflection:{source_run_id}")
    return refs


def _first_attribution(reflection: dict[str, Any]) -> dict[str, Any]:
    return _first_item(reflection.get("self_attributing"))


def _first_item(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


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


def _write_index(path: Path, by_type: dict[str, Path]) -> None:
    payload = {
        "version": 1,
        "updated_at": utcnow_iso(),
        "counts": {
            candidate_type: len(_read_jsonl_records(candidate_path))
            for candidate_type, candidate_path in sorted(by_type.items())
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_candidate_type(value: Any) -> str:
    candidate_type = _text(value)
    if candidate_type not in ALLOWED_CANDIDATE_TYPES:
        raise ValueError(f"Unknown self-evolution candidate type: {candidate_type or value}")
    return candidate_type


def _required_text(record: dict[str, Any], key: str) -> str:
    value = _text(record.get(key))
    if not value:
        raise ValueError(f"Self-evolution candidate missing required field: {key}")
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


def _merge_unique(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item and item not in merged:
                merged.append(item)
    return merged


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


def _stable_digest(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


__all__ = [
    "ALLOWED_CANDIDATE_TYPES",
    "CANDIDATE_INDEX",
    "CANDIDATE_JSONL_BY_TYPE",
    "CANDIDATE_ROOT",
    "AppendCandidateResult",
    "CandidatePoolPaths",
    "append_candidate_record",
    "build_candidate_from_reflection",
    "candidate_pool_paths",
    "list_candidate_records",
]
