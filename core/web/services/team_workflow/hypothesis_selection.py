"""Append-only hypothesis selection service for the hypothesis-first flow.

Recording a selection fails closed: the scope identity must be complete, every
selected candidate must exist in the approved formal v2 question artifact's
hypothesis list (the same approval source as ``question_launch``), and a
re-selection for the same scoped question must carry a ``previousSelectionId``
that resolves to an existing record of that same scope and question.

Identical requests are idempotent: a content hash (``selectionHash``, no
timestamps) lets a repeated submission reuse the already appended record
instead of duplicating it.  The latest record of a scoped question is its
current base hypothesis set.  No chat room or research runtime is involved.
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
    MAX_SELECTED_CANDIDATES,
    ContractValidationError,
    HypothesisSelectionRecord,
    scope_hash_for,
)

SCHEMA_VERSION = 1
DEFAULT_MODE = "formal"
_LOCK = threading.RLock()
_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class ResearchHypothesisSelectionError(RuntimeError):
    """Base error for hypothesis selection persistence."""


class ResearchHypothesisSelectionNotFoundError(ResearchHypothesisSelectionError):
    """Raised when a hypothesis selection record does not exist."""


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
            raise ResearchHypothesisSelectionError(
                f"Invalid hypothesis selection JSONL at line {line_number}."
            ) from exc
        if not isinstance(payload, dict):
            raise ResearchHypothesisSelectionError(
                f"Invalid hypothesis selection record at line {line_number}."
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


def _resolve_read_scope(payload: Mapping[str, Any] | None) -> dict[str, str]:
    """Validate the complete scope supplied to a scoped latest read.

    ``_resolve_scope`` intentionally derives ``scopeHash`` for write requests.
    A read must carry the hash as an explicit, independently verifiable
    selector; deriving it from a partial request would let a caller silently
    broaden a question read across branches, agents, or modes.
    """
    if not isinstance(payload, Mapping):
        raise ContractValidationError(
            "get_latest_hypothesis_selection requires a complete scope including scopeHash"
        )
    required_fields = (*_SCOPE_FIELDS, "agentId", "mode", "scopeHash")
    missing = [field for field in required_fields if not str(payload.get(field) or "").strip()]
    if missing:
        raise ContractValidationError(
            "get_latest_hypothesis_selection requires a complete scope including "
            + ", ".join(missing)
        )
    identity = {
        field: str(payload.get(field) or "").strip() for field in _SCOPE_FIELDS
    }
    agent_id = str(payload.get("agentId") or "").strip()
    mode = str(payload.get("mode") or "").strip().lower()
    if mode not in {"formal", "dev", "platform"}:
        raise ContractValidationError(f"unsupported scope mode: {mode}")
    supplied_hash = str(payload.get("scopeHash") or "").strip().lower()
    expected_hash = scope_hash_for(
        **identity,
        agent_id=agent_id,
        mode=mode,
    )
    if supplied_hash != expected_hash:
        raise ContractValidationError(
            "scopeHash does not match the selection scope identity"
        )
    return {**identity, "agentId": agent_id, "mode": mode, "scopeHash": supplied_hash}


def _latest_by_id(records: list[dict[str, Any]], field: str, record_id: str) -> dict[str, Any] | None:
    matched = [record for record in records if str(record.get(field) or "") == record_id]
    return matched[-1] if matched else None


def _storage_path(team_id: str) -> Path:
    return _kind_path(team_id, "hypothesis_selections")


def _approved_candidate_ids(team_id: str, question_id: str) -> set[str]:
    """Return the selectable candidate ids for one question.

    Primary source is the approved formal v2 question artifact, reusing the
    question launch approval read path so "approved" never drifts between
    launching a run and selecting hypotheses for it.  Catalog-seeded questions
    have no approved artifact; their candidates come from the round-0
    candidate-generation discussion recorded in the hypothesis-first chain
    ledger.
    """
    from core.web.services.team_workflow.research_runtime import question_launch

    detail = question_launch._approved_details(team_id).get(question_id.upper())
    if detail is None:
        if question_launch._catalog_question(question_id.upper()) is None:
            raise ResearchHypothesisSelectionError(
                f"Question {question_id} is not an approved formal v2 question artifact."
            )
        from core.web.services.team_workflow.research_runtime import (
            hypothesis_first_chain,
        )

        return {
            str(record.get("candidateId") or "").strip()
            for record in hypothesis_first_chain.list_hypothesis_candidates(
                team_id, question_id=question_id
            )["candidates"]
            if str(record.get("candidateId") or "").strip()
        }
    output = detail.get("output") if isinstance(detail.get("output"), Mapping) else {}
    hypotheses = output.get("hypotheses") if isinstance(output.get("hypotheses"), list) else []
    return {
        str(item.get("hypothesis_id") or "").strip()
        for item in hypotheses
        if isinstance(item, dict) and str(item.get("hypothesis_id") or "").strip()
    }


def _normalize_candidate_ids(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise ContractValidationError("selectedCandidateIds must be a non-empty list")
    candidates = [str(item or "").strip() for item in raw]
    if any(not candidate for candidate in candidates):
        raise ContractValidationError("selectedCandidateIds must not contain empty entries")
    if not candidates:
        raise ContractValidationError("selectedCandidateIds must be a non-empty list")
    if len(candidates) > MAX_SELECTED_CANDIDATES:
        raise ContractValidationError(
            f"selectedCandidateIds must contain at most {MAX_SELECTED_CANDIDATES} candidates"
        )
    if len(set(candidates)) != len(candidates):
        raise ContractValidationError("selectedCandidateIds must be unique")
    return candidates


def _selection_hash(payload: Mapping[str, Any]) -> str:
    """Content hash over the semantic request fields, excluding timestamps."""
    return _stable_hash(
        {
            "scopeHash": str(payload.get("scopeHash") or ""),
            "questionId": str(payload.get("questionId") or ""),
            "selectedCandidateIds": list(payload.get("selectedCandidateIds") or []),
            "previousSelectionId": str(payload.get("previousSelectionId") or ""),
            "decidedBy": str(payload.get("decidedBy") or ""),
        }
    )


def _selection_definition(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return immutable selection fields used to detect conflicting id reuse."""
    return {
        key: record.get(key)
        for key in (
            "selectionId",
            "program",
            "theme",
            "campaign",
            "question",
            "branch",
            "workflow",
            "agentId",
            "mode",
            "scopeHash",
            "questionId",
            "selectedCandidateIds",
            "previousSelectionId",
            "decidedBy",
        )
    }


def _scoped_question_records(
    records: list[dict[str, Any]],
    *,
    scope_hash: str,
    question_id: str,
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if str(record.get("scopeHash") or "") == scope_hash
        and str(record.get("questionId") or "").upper() == question_id.upper()
    ]


def _auto_open_review_meeting(
    team_id: str,
    record: Mapping[str, Any],
    *,
    agent_runner: Any = None,
    background: bool = True,
) -> dict[str, Any]:
    """Best-effort auto-open of the first hypothesis-review meeting (HF-4).

    The selection is already persisted (append-only fact), so a meeting
    failure is reported structurally instead of rolling the selection back.
    Replays reuse the already-opened meeting through the chain's deterministic
    meeting id, which also self-heals a previously failed auto-open.
    """
    try:
        from core.web.services.team_workflow.research_runtime import (
            hypothesis_first_chain,
        )

        opened = hypothesis_first_chain.open_review_meeting_for_selection(
            team_id,
            record,
            agent_runner=agent_runner,
            background=background,
            round_index=1,
        )
        return {
            "status": str(opened.get("status") or ""),
            "meetingRound": opened.get("meetingRound") or {},
            "roomId": str(opened.get("roomId") or ""),
            "roundId": str(opened.get("roundId") or ""),
            "chatRoomRoundIds": list(opened.get("chatRoomRoundIds") or []),
            "discussion": dict(opened.get("discussion") or {}),
            "roundIndex": int(opened.get("roundIndex") or 1),
        }
    except Exception as exc:  # selection fact stays; report the side effect
        return {
            "status": "failed",
            "error": str(exc),
            "errorType": type(exc).__name__,
        }


def record_hypothesis_selection(
    team_id: str,
    payload: Mapping[str, Any] | None = None,
    *,
    agent_runner: Any = None,
    background: bool = True,
) -> dict[str, Any]:
    """Record one append-only hypothesis selection, failing closed on defects.

    Repeating an identical request reuses the existing record; a changed
    selection for the same scoped question appends a new record that must link
    to an existing one through ``previousSelectionId``.

    After the record is on disk, the first hypothesis-review meeting is
    auto-opened in the background (HF-4 orchestration); the outcome is
    reported under ``reviewMeeting`` and never rolls the selection back.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    request = dict(payload) if isinstance(payload, Mapping) else {}
    scope = _resolve_scope(request)
    question_id = str(request.get("questionId") or "").strip()
    if not question_id:
        raise ContractValidationError("questionId must be a non-empty string")
    decided_by = str(request.get("decidedBy") or "").strip()
    if not decided_by:
        raise ContractValidationError("decidedBy must be a non-empty string")
    candidates = _normalize_candidate_ids(request.get("selectedCandidateIds"))
    approved_candidates = _approved_candidate_ids(normalized_team_id, question_id)
    unknown = [candidate for candidate in candidates if candidate not in approved_candidates]
    if unknown:
        raise ContractValidationError(
            "selectedCandidateIds must exist in the approved question artifact candidates: "
            + ", ".join(unknown)
        )
    if len(candidates) < 2:
        raise ContractValidationError(
            "selectedCandidateIds must keep at least two candidates: the review round "
            "needs a comparable pair and a single-candidate selection can never "
            "generate a hypothesis round; reselect with two or more candidates, or "
            "rerun candidate generation when fewer exist"
        )
    previous_selection_id = str(request.get("previousSelectionId") or "").strip()
    now = _utc_now()
    record: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "selectionId": "",
        **scope,
        "questionId": question_id,
        "selectedCandidateIds": candidates,
        "previousSelectionId": previous_selection_id,
        "decidedBy": decided_by,
        "createdAt": str(request.get("createdAt") or "").strip() or now,
    }
    record["selectionHash"] = _selection_hash(record)
    record["selectionId"] = (
        str(request.get("selectionId") or "").strip()
        or f"hsel-{record['selectionHash'][:16]}"
    )
    HypothesisSelectionRecord.from_dict(record)
    with _LOCK:
        records = _read_jsonl(_storage_path(normalized_team_id))
        for existing in records:
            if str(existing.get("selectionHash") or "") == record["selectionHash"]:
                return {
                    "schemaVersion": SCHEMA_VERSION,
                    "teamId": normalized_team_id,
                    "status": "reused",
                    "selection": existing,
                    "reviewMeeting": _auto_open_review_meeting(
                        normalized_team_id,
                        existing,
                        agent_runner=agent_runner,
                        background=background,
                    ),
                    "storagePath": str(_storage_path(normalized_team_id)),
                }
        existing_by_id = _latest_by_id(records, "selectionId", record["selectionId"])
        if existing_by_id is not None:
            if _selection_definition(existing_by_id) != _selection_definition(record):
                raise ResearchHypothesisSelectionError(
                    "hypothesis selection id is already bound to different content"
                )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "selection": existing_by_id,
                "reviewMeeting": _auto_open_review_meeting(
                    normalized_team_id,
                    existing_by_id,
                    agent_runner=agent_runner,
                    background=background,
                ),
                "storagePath": str(_storage_path(normalized_team_id)),
            }
        question_records = _scoped_question_records(
            records,
            scope_hash=scope["scopeHash"],
            question_id=question_id,
        )
        if question_records and not previous_selection_id:
            raise ResearchHypothesisSelectionError(
                "re-selection for a scoped question requires previousSelectionId"
            )
        if previous_selection_id and not any(
            str(item.get("selectionId") or "") == previous_selection_id
            for item in question_records
        ):
            raise ResearchHypothesisSelectionError(
                "previousSelectionId does not resolve to an existing selection of this scoped question"
            )
        _append_jsonl(_storage_path(normalized_team_id), record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "selection": record,
        "reviewMeeting": _auto_open_review_meeting(
            normalized_team_id,
            record,
            agent_runner=agent_runner,
            background=background,
        ),
        "storagePath": str(_storage_path(normalized_team_id)),
    }


def list_hypothesis_selections(team_id: str, *, question_id: str = "") -> dict[str, Any]:
    """List selection records for a team, optionally filtered by question."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    with _LOCK:
        records = _read_jsonl(_storage_path(normalized_team_id))
    selections = [
        record
        for record in records
        if not normalized_question_id
        or str(record.get("questionId") or "").upper() == normalized_question_id
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "selectionCount": len(selections),
        "selections": selections,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


def get_hypothesis_selection(team_id: str, selection_id: str) -> dict[str, Any]:
    """Return the latest record of one hypothesis selection."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_selection_id = str(selection_id or "").strip()
    with _LOCK:
        records = _read_jsonl(_storage_path(normalized_team_id))
        record = _latest_by_id(records, "selectionId", normalized_selection_id)
    if record is None:
        raise ResearchHypothesisSelectionNotFoundError("Hypothesis selection not found.")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "selection": record,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


def get_latest_hypothesis_selection(
    team_id: str,
    question_id: str,
    *,
    scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the current base hypothesis set of one question.

    The current set is the latest appended selection record for the exact
    question and complete scope in the team's selection ledger.  Scope is
    mandatory on reads so a same-question record from another branch, agent,
    or mode can never be selected by fallback.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip()
    if not normalized_question_id:
        raise ResearchHypothesisSelectionError("Question id is required.")
    resolved_scope = _resolve_read_scope(scope)
    with _LOCK:
        records = _read_jsonl(_storage_path(normalized_team_id))
    matched = [
        record
        for record in records
        if str(record.get("questionId") or "").upper() == normalized_question_id.upper()
        and str(record.get("scopeHash") or "").strip().lower()
        == resolved_scope["scopeHash"]
        and all(
            str(record.get(field) or "").strip() == resolved_scope[field]
            for field in (*_SCOPE_FIELDS, "agentId", "mode")
        )
    ]
    if not matched:
        raise ResearchHypothesisSelectionNotFoundError(
            "No hypothesis selection recorded for this question."
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "selection": matched[-1],
        "storagePath": str(_storage_path(normalized_team_id)),
    }
