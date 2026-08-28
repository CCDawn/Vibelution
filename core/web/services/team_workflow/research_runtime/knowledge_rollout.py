"""Knowledge sideflow rollout authority: off → shadow → on (Task 7).

Single read point for the trusted operator config section
``[research.knowledge_sideflow]`` (``mode = "off" | "shadow" | "on"``,
default ``off``).  Every consumer re-reads the current config on each call,
so an operator can flip the mode without process restarts.

Mode semantics:

- ``off``:  status quo.  New formal runs keep the pinned 2.1.0 default
  definition; knowledge command offers are hidden at the snapshot layer.
- ``shadow``: new runs still use 2.1.0, but every legacy-chain collection
  request also records a shadow knowledge invocation (fingerprint-aligned
  with the real invocation ledger) for the comparison projection.  The
  legacy chain's own behavior is byte-for-byte unchanged; shadow records
  never drive a parent, never create child runs and never write knowledge
  packages.
- ``on``: new formal runs are created against the registered main-flow 3.0.0
  definition (register-or-resolve).  Historical 2.1.0 runs are always
  interpreted through the registry's pinned old definition (T2) — this module
  only decides the definition for NEW run creation, never for reads.

Shadow records live in their own append-only JSONL store under the research
workflow data root; they are deliberately NOT rows in the ledger's
``knowledge_invocations`` table because that table's lineage model requires a
real parent ``WorkflowRun``, which the legacy hypothesis-first chain does not
have.  Fabricating lineage would pollute the T6 badge projections.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import (
    DefinitionIdentity,
    definition_identity,
    register_or_resolve,
)
from core.research.workflow.knowledge_sideflow_definition import (
    build_challenge_cup_workflow_definition_v3,
)

KNOWLEDGE_SIDEFLOW_MODE_OFF = "off"
KNOWLEDGE_SIDEFLOW_MODE_SHADOW = "shadow"
KNOWLEDGE_SIDEFLOW_MODE_ON = "on"
KNOWLEDGE_SIDEFLOW_MODES = (
    KNOWLEDGE_SIDEFLOW_MODE_OFF,
    KNOWLEDGE_SIDEFLOW_MODE_SHADOW,
    KNOWLEDGE_SIDEFLOW_MODE_ON,
)

SHADOW_RECORD_KIND = "knowledge_shadow_invocation"
SHADOW_SCHEMA_VERSION = 1
# Fingerprint parity constant: shadow rows reuse the T3 fingerprint chain with
# the source policy version the legacy chain never carried, so the tuple is
# deterministic and comparable within the shadow store.
_SHADOW_SOURCE_POLICY_VERSION = "legacy-shadow"

_APPEND_LOCK = threading.Lock()


class KnowledgeSideflowDisabledError(RuntimeError):
    """Raised when a knowledge-flow entry point is used while mode=off."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "knowledge_sideflow_disabled"


def knowledge_sideflow_mode() -> str:
    """Current rollout mode; unknown/unreadable config fails closed to off."""
    try:
        from config.settings import get_config

        raw = str(get_config().research.knowledge_sideflow.mode)
    except Exception:  # noqa: BLE001 - rollout gating must never break runs
        return KNOWLEDGE_SIDEFLOW_MODE_OFF
    normalized = raw.strip().lower()
    return normalized if normalized in KNOWLEDGE_SIDEFLOW_MODES else (
        KNOWLEDGE_SIDEFLOW_MODE_OFF
    )


def knowledge_ensure_enabled() -> bool:
    """True only in mode ``on``: only then may an ensure command create a
    REAL child run.  Shadow deliberately stays projection-only (plan §10.1):
    it must never drive a parent flow, spawn a sideflow run or write a
    knowledge package."""
    return knowledge_sideflow_mode() == KNOWLEDGE_SIDEFLOW_MODE_ON


def knowledge_inspect_enabled() -> bool:
    """True in ``shadow``/``on``: inspection is read-only and always honest."""
    return knowledge_sideflow_mode() != KNOWLEDGE_SIDEFLOW_MODE_OFF


def creation_workflow_definition() -> tuple[Any, DefinitionIdentity]:
    """Definition + registered identity for NEW formal run creation.

    off/shadow → the frozen 2.1.0 default; on → the registered main-flow 3.0.0
    definition.  Both go through ``register_or_resolve`` so the run's version
    identity is pinned before any checkpoint or ledger write.
    """
    definition = (
        build_challenge_cup_workflow_definition_v3()
        if knowledge_sideflow_mode() == KNOWLEDGE_SIDEFLOW_MODE_ON
        else build_challenge_cup_workflow_definition()
    )
    return definition, register_or_resolve(definition)


# --------------------------------------------------------------------------
# Shadow invocation records (对照投影; never drive any run)
# --------------------------------------------------------------------------


def _shadow_dir() -> Path:
    from .paths import research_workflow_data_root

    return research_workflow_data_root() / "knowledge_shadow_invocations"


def _shadow_store_path(team_id: str) -> Path:
    from core.web.services.team_workflow.storage_ids import safe_storage_component

    safe_team = safe_storage_component(team_id, fallback="team")
    return _shadow_dir() / f"{safe_team}.jsonl"


def compute_shadow_invocation_fingerprints(
    *,
    question_id: str,
    scope: Mapping[str, Any],
    search_envelope: Mapping[str, Any] | None,
    requirements: Mapping[str, Any] | None,
) -> dict[str, str]:
    """T3 fingerprint semantics applied to a legacy-chain request."""
    from .knowledge_sideflow_service import compute_invocation_fingerprints

    return compute_invocation_fingerprints(
        question_id=str(question_id or "").strip().upper(),
        scope=dict(scope or {}),
        search_envelope=dict(search_envelope or {}),
        requirements=dict(requirements or {}),
        source_policy_version=_SHADOW_SOURCE_POLICY_VERSION,
    )


def record_shadow_knowledge_invocation(
    *,
    team_id: str,
    question_id: str,
    scope: Mapping[str, Any],
    search_envelope: Mapping[str, Any] | None,
    requirements: Mapping[str, Any] | None,
    collection_run_id: str = "",
    collection_request_id: str = "",
    meeting_round_id: str = "",
    decision_id: str = "",
    legacy_scope_hash: str = "",
    now_provider: Any = None,
) -> dict[str, Any] | None:
    """Append one shadow invocation row; no-op unless mode == shadow.

    Returns the stored record (or ``None`` when the mode is not shadow or the
    record could not be persisted).  Any failure is swallowed: shadow
    bookkeeping must never alter the legacy chain's own outcome.

    Idempotent on the T3 fingerprint tuple — the same request (same
    questionId + scopeHash + searchEnvelopeHash + requirementsHash for the
    same collection request) is written ONCE; replays are dropped and the
    first record wins.  Corrupt lines are quarantined (renamed aside, never
    rewritten) following the managed-roots registry precedent.
    """
    if knowledge_sideflow_mode() != KNOWLEDGE_SIDEFLOW_MODE_SHADOW:
        return None
    normalized_team = str(team_id or "").strip()
    normalized_question = str(question_id or "").strip().upper()
    if not normalized_team or not normalized_question:
        return None
    try:
        fingerprints = compute_shadow_invocation_fingerprints(
            question_id=normalized_question,
            scope=scope,
            search_envelope=search_envelope,
            requirements=requirements,
        )
        now_ms = int(time.time() * 1000) if now_provider is None else int(now_provider())
        path = _shadow_store_path(normalized_team)
        with _APPEND_LOCK:
            existing_rows, _corrupt = _read_shadow_rows(path)
            identity_key = _shadow_identity_key(
                normalized_question,
                fingerprints,
                str(collection_request_id or ""),
            )
            for row in existing_rows:
                if (
                    _shadow_identity_key(
                        str(row.get("questionId") or ""),
                        {
                            "scopeHash": str(row.get("scopeHash") or ""),
                            "searchEnvelopeHash": str(
                                row.get("searchEnvelopeHash") or ""
                            ),
                            "requirementsHash": str(
                                row.get("requirementsHash") or ""
                            ),
                            "requestHash": str(row.get("requestHash") or ""),
                        },
                        str(row.get("collectionRequestId") or ""),
                    )
                    == identity_key
                ):
                    # Idempotent replay: the first record stays authoritative.
                    return row
            record: dict[str, Any] = {
                "schemaVersion": SHADOW_SCHEMA_VERSION,
                "recordKind": SHADOW_RECORD_KIND,
                "shadow": True,
                "invocationId": f"kshadow-{fingerprints['requestHash'][:16]}",
                "teamId": normalized_team,
                "questionId": normalized_question,
                "scopeHash": fingerprints["scopeHash"],
                "searchEnvelopeHash": fingerprints["searchEnvelopeHash"],
                "requirementsHash": fingerprints["requirementsHash"],
                "requestHash": fingerprints["requestHash"],
                "sourcePolicyVersion": _SHADOW_SOURCE_POLICY_VERSION,
                "collectionRunId": str(collection_run_id or ""),
                "collectionRequestId": str(collection_request_id or ""),
                "meetingRoundId": str(meeting_round_id or ""),
                "decisionId": str(decision_id or ""),
                "legacyScopeHash": str(legacy_scope_hash or ""),
                "createdAtMs": now_ms,
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                )
        return record
    except Exception:  # noqa: BLE001 - shadow must never break the legacy chain
        return None


def _shadow_identity_key(
    question_id: str,
    fingerprints: Mapping[str, Any],
    collection_request_id: str,
) -> tuple[str, ...]:
    """T3 reuse-tuple semantics (+ request lineage) for shadow dedup."""
    return (
        str(question_id or "").strip().upper(),
        str(fingerprints.get("scopeHash") or ""),
        str(fingerprints.get("searchEnvelopeHash") or ""),
        str(fingerprints.get("requirementsHash") or ""),
        str(fingerprints.get("requestHash") or ""),
        str(collection_request_id or ""),
    )


def _read_shadow_rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Parse the shadow store; quarantine corrupt lines, never rewrite them.

    Follows the managed-roots registry precedent: a corrupt segment is moved
    aside under a ``.corrupt-<stamp>`` name (isolation failure is tolerated —
    the store then just starts fresh) and parsing continues with the good
    tail instead of poisoning every future read.
    """
    rows: list[dict[str, Any]] = []
    corrupt_lines: list[str] = []
    if not path.is_file():
        return rows, 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except ValueError:
                corrupt_lines.append(stripped)
                continue
            if isinstance(row, dict):
                rows.append(row)
    if corrupt_lines:
        _quarantine_corrupt_shadow_lines(path, corrupt_lines)
    return rows, len(corrupt_lines)


def _quarantine_corrupt_shadow_lines(path: Path, corrupt_lines: list[str]) -> None:
    try:
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        quarantine = path.parent / f"{path.name}.corrupt-{stamp}.jsonl"
        with quarantine.open("a", encoding="utf-8") as handle:
            for line in corrupt_lines:
                handle.write(line + "\n")
    except Exception:  # noqa: BLE001 - isolation is best-effort, never fatal
        pass


def list_shadow_knowledge_invocations(
    team_id: str,
    *,
    question_id: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """Read shadow rows for the comparison projection (newest last, bounded)."""
    normalized_team = str(team_id or "").strip()
    normalized_question = str(question_id or "").strip().upper()
    rows: list[dict[str, Any]] = []
    path = _shadow_store_path(normalized_team) if normalized_team else None
    if path is not None:
        rows, _corrupt = _read_shadow_rows(path)
    filtered = [
        row
        for row in rows
        if not normalized_question
        or str(row.get("questionId") or "").strip().upper() == normalized_question
    ]
    return {
        "teamId": normalized_team,
        "questionId": normalized_question,
        "mode": knowledge_sideflow_mode(),
        "total": len(filtered),
        "records": filtered[-max(1, int(limit or 200)):],
    }


def shadow_records_for_requests(
    team_id: str,
    request_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Latest shadow row per collection request id (comparison helper)."""
    latest: dict[str, dict[str, Any]] = {}
    normalized = [str(item or "").strip() for item in request_ids if str(item or "").strip()]
    if not normalized:
        return latest
    payload = list_shadow_knowledge_invocations(team_id, limit=10_000)
    wanted = set(normalized)
    for row in payload["records"]:
        request_id = str(row.get("collectionRequestId") or "")
        if request_id in wanted:
            latest[request_id] = row
    return latest
