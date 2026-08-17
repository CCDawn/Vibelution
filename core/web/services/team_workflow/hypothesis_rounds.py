"""Append-only hypothesis round service for the Challenge Cup D04 loop.

Creates and closes hypothesis review rounds as pure offline artifacts under the
team workspace.  Closing a round fails closed when the round is incomplete
(less than two substantially different candidates, missing review dimension,
missing pair comparison, incomplete Pareto, missing MetaReview, or missing
meeting refs).  No chat room or research runtime is touched.
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
    HypothesisRound,
    scope_hash_for,
)

SCHEMA_VERSION = 1
DEFAULT_MODE = "formal"
_LOCK = threading.RLock()
_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class ResearchHypothesisRoundError(RuntimeError):
    """Base error for hypothesis round persistence."""


class ResearchHypothesisRoundNotFoundError(ResearchHypothesisRoundError):
    """Raised when a hypothesis round does not exist."""


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
            raise ResearchHypothesisRoundError(
                f"Invalid hypothesis round JSONL at line {line_number}."
            ) from exc
        if not isinstance(payload, dict):
            raise ResearchHypothesisRoundError(
                f"Invalid hypothesis round record at line {line_number}."
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


def _storage_path(team_id: str) -> Path:
    return _kind_path(team_id, "hypothesis_rounds")


def _round_definition(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return immutable round fields used to detect conflicting id reuse."""
    return {
        key: record.get(key)
        for key in (
            "roundId",
            "program",
            "theme",
            "campaign",
            "question",
            "branch",
            "workflow",
            "agentId",
            "mode",
            "scopeHash",
            "status",
            "candidates",
            "pairwiseComparisons",
            "pareto",
            "metaReview",
            "lineage",
            "meetingRefs",
        )
    }


def _closure_hash(payload: Mapping[str, Any]) -> str:
    return _stable_hash(
        {
            "pairwiseComparisons": list(payload.get("pairwiseComparisons") or []),
            "pareto": dict(payload.get("pareto")) if isinstance(payload.get("pareto"), Mapping) else {},
            "metaReview": dict(payload.get("metaReview")) if isinstance(payload.get("metaReview"), Mapping) else {},
            "meetingRefs": list(payload.get("meetingRefs") or []),
            "closedBy": str(payload.get("closedBy") or "").strip(),
        }
    )


def create_hypothesis_round(team_id: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Create one append-only hypothesis review round and fail closed on defects."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    request = dict(payload) if isinstance(payload, Mapping) else {}
    scope = _resolve_scope(request)
    now = _utc_now()
    candidates = list(request.get("candidates") or [])
    if not candidates:
        raise ContractValidationError(
            "a hypothesis round requires at least two candidates"
        )
    seed_payload = {
        "scopeHash": scope["scopeHash"],
        "candidateIds": sorted(
            str(item.get("candidateId") or "") for item in candidates if isinstance(item, dict)
        ),
        "createdAt": now,
    }
    round_id = str(request.get("roundId") or "").strip() or f"hround-{_stable_hash(seed_payload)[:16]}"
    record: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "roundId": round_id,
        **scope,
        "status": str(request.get("status") or "open").strip().lower(),
        "candidates": candidates,
        "pairwiseComparisons": list(request.get("pairwiseComparisons") or []),
        "pareto": dict(request.get("pareto")) if isinstance(request.get("pareto"), Mapping) else {
            "paretoFrontCandidateIds": [],
            "dominatedCandidateIds": [],
            "analystAgentId": str(request.get("analystAgentId") or "").strip(),
            "notes": "",
        },
        "metaReview": dict(request.get("metaReview")) if isinstance(request.get("metaReview"), Mapping) else {
            "metaReviewId": f"meta-{_stable_hash({'roundId': round_id, 'createdAt': now})[:12]}",
            "reviewerAgentId": str(request.get("metaReviewerAgentId") or "").strip(),
            "recommendationCandidateId": "",
            "rationale": "",
            "riskNotes": "",
            "accepted": False,
        },
        "lineage": list(request.get("lineage") or []),
        "meetingRefs": list(request.get("meetingRefs") or []),
        "createdAt": now,
        "closedAt": str(request.get("closedAt") or "").strip(),
        "closedBy": str(request.get("closedBy") or "").strip(),
    }
    # Fail closed before persistence: parse validates shape, completeness of
    # candidates and scope; a complete round must pass validate_complete().
    parsed = HypothesisRound.from_dict(record)
    if parsed.status in {"reviewed", "closed"}:
        parsed.validate_complete()
    with _LOCK:
        records = _read_jsonl(_storage_path(normalized_team_id))
        existing = _latest_by_id(records, "roundId", round_id)
        if existing is not None and existing.get("schemaVersion") is not None:
            if _round_definition(existing) != _round_definition(record):
                raise ResearchHypothesisRoundError(
                    "hypothesis round id is already bound to different content"
                )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "round": existing,
                "storagePath": str(_storage_path(normalized_team_id)),
            }
        _append_jsonl(_storage_path(normalized_team_id), record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "round": record,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


def close_hypothesis_round(
    team_id: str,
    round_id: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Close one round with complete pair/Pareto/MetaReview/meeting evidence.

    Idempotent: closing an already-closed round with the same closure content
    returns the existing record instead of appending a duplicate.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        raise ResearchHypothesisRoundError("Hypothesis round id is required.")
    request = dict(payload) if isinstance(payload, Mapping) else {}
    with _LOCK:
        records = _read_jsonl(_storage_path(normalized_team_id))
        open_round = _latest_by_id(records, "roundId", normalized_round_id)
        if open_round is None:
            raise ResearchHypothesisRoundNotFoundError("Hypothesis round not found.")
        if str(open_round.get("status") or "") in {"reviewed", "closed"}:
            requested_closure_hash = _closure_hash(request)
            if str(open_round.get("closureHash") or "") != requested_closure_hash:
                raise ResearchHypothesisRoundError(
                    "closed hypothesis round cannot be reused with different closure content"
                )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "closed": True,
                "round": open_round,
                "storagePath": str(_storage_path(normalized_team_id)),
            }
        now = _utc_now()
        closed_record = dict(open_round)
        closed_record["status"] = "closed"
        closed_record["pairwiseComparisons"] = list(request.get("pairwiseComparisons") or [])
        closed_record["pareto"] = dict(request.get("pareto")) if isinstance(request.get("pareto"), Mapping) else {}
        if "metaReview" in request:
            closed_record["metaReview"] = dict(request["metaReview"])
        elif "metaReviewerAgentId" in request:
            meta_review = dict(closed_record["metaReview"])
            meta_review["reviewerAgentId"] = str(request.get("metaReviewerAgentId") or "").strip()
            meta_review["recommendationCandidateId"] = str(
                request.get("recommendationCandidateId") or ""
            ).strip()
            meta_review["rationale"] = str(request.get("metaRationale") or "").strip()
            meta_review["riskNotes"] = str(request.get("metaRiskNotes") or "").strip()
            meta_review["accepted"] = bool(request.get("metaAccepted"))
            closed_record["metaReview"] = meta_review
        closed_record["meetingRefs"] = list(request.get("meetingRefs") or closed_record.get("meetingRefs") or [])
        closed_record["closedAt"] = now
        closed_record["closedBy"] = str(request.get("closedBy") or "").strip()
        closed_record["closureHash"] = _closure_hash(request)
        parsed = HypothesisRound.from_dict(closed_record)
        parsed.validate_complete()
        _append_jsonl(_storage_path(normalized_team_id), closed_record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "closed": True,
        "round": closed_record,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


def list_hypothesis_rounds(team_id: str) -> dict[str, Any]:
    """List the latest record of every hypothesis round for a team."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    with _LOCK:
        records = _read_jsonl(_storage_path(normalized_team_id))
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        latest[str(record.get("roundId") or "")] = record
    rounds = sorted(latest.values(), key=lambda item: str(item.get("createdAt") or ""))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "roundCount": len(rounds),
        "rounds": rounds,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


def get_hypothesis_round(team_id: str, round_id: str) -> dict[str, Any]:
    """Return the latest record of one hypothesis round."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(round_id or "").strip()
    with _LOCK:
        records = _read_jsonl(_storage_path(normalized_team_id))
        record = _latest_by_id(records, "roundId", normalized_round_id)
    if record is None:
        raise ResearchHypothesisRoundNotFoundError("Hypothesis round not found.")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "round": record,
        "storagePath": str(_storage_path(normalized_team_id)),
    }
