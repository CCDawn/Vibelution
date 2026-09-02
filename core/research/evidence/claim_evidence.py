"""Append-safe claim evidence storage with explicit fact/inference boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vibelution_storage import resolve_project_workspace_home


SCHEMA_VERSION = 1
_LOCK = threading.RLock()
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_REASONING_ROLES = {"fact", "inference", "analogy", "hypothesis"}
_EVIDENCE_KINDS = {"primary_result", "review_summary", "metadata", "counter_evidence"}
_SUPPORT_LEVELS = {"supports", "contradicts", "insufficient", "unverified"}
_EXTRACTION_METHODS = {"paperqa2", "manual", "model"}


class ClaimEvidenceError(ValueError):
    """Raised when claim evidence would weaken provenance or governance."""


class ClaimEvidenceStore:
    """Persist canonical claim evidence below one project root.

    Legacy evidence is exposed only through :meth:`project_legacy`; that method is
    deliberately read-only so incomplete historical material cannot silently gain
    canonical evidence status.
    """

    def __init__(self, project_root: str | os.PathLike[str]) -> None:
        self.project_root = Path(project_root).expanduser().resolve()

    def register(self, team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = _normalize_payload(payload)
        team = _safe_id(team_id, field="teamId")
        evidence_id = _evidence_id(normalized)
        path = self._path(team)
        with _LOCK:
            records = _read_jsonl(path)
            existing = next((item for item in records if item.get("claimEvidenceId") == evidence_id), None)
            if existing is not None:
                return existing
            now = _now_utc()
            record = {
                "schemaVersion": SCHEMA_VERSION,
                "claimEvidenceId": evidence_id,
                **normalized,
                "quoteHash": _sha256_text(normalized["quote"]),
                "reviewStatus": "pending",
                "reviewedBy": "",
                "shadowOnly": False,
                "formalKnowledgeWriteAllowed": False,
                "createdAt": now,
                "updatedAt": now,
            }
            records.append(record)
            _write_jsonl_atomic(path, records)
        _record_event(
            "research_evidence.claim_registered",
            team_id=team,
            fields={
                "claimEvidenceId": evidence_id,
                "candidateId": normalized["candidateId"],
                "evidenceKind": normalized["evidenceKind"],
                "reasoningRole": normalized["reasoningRole"],
                "supportLevel": normalized["supportLevel"],
            },
        )
        return record

    def list(self, team_id: str, *, candidate_id: str = "", claim_id: str = "") -> list[dict[str, Any]]:
        team = _safe_id(team_id, field="teamId")
        with _LOCK:
            records = _read_jsonl(self._path(team))
        if candidate_id:
            records = [item for item in records if item.get("candidateId") == candidate_id]
        if claim_id:
            records = [item for item in records if item.get("claimId") == claim_id]
        return records

    def reconcile_source_revision(self, team_id: str, *, source_id: str, current_revision: str) -> dict[str, Any]:
        team = _safe_id(team_id, field="teamId")
        normalized_source_id = _required_text(source_id, "sourceId", 300)
        normalized_revision = _source_revision(current_revision)
        path = self._path(team)
        stale_count = 0
        with _LOCK:
            records = _read_jsonl(path)
            for record in records:
                if record.get("sourceId") != normalized_source_id:
                    continue
                if record.get("sourceRevision") == normalized_revision:
                    continue
                if record.get("reviewStatus") != "stale":
                    stale_count += 1
                record["reviewStatus"] = "stale"
                record["staleReason"] = "source_revision_changed"
                record["currentSourceRevision"] = normalized_revision
                record["formalKnowledgeWriteAllowed"] = False
                record["updatedAt"] = _now_utc()
            if stale_count:
                _write_jsonl_atomic(path, records)
        if stale_count:
            _record_event(
                "research_evidence.source_stale",
                team_id=team,
                fields={"sourceId": normalized_source_id, "staleCount": stale_count},
            )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": team,
            "sourceId": normalized_source_id,
            "currentSourceRevision": normalized_revision,
            "staleCount": stale_count,
        }

    def review(
        self,
        team_id: str,
        claim_evidence_id: str,
        *,
        decision: str,
        reviewed_by: str,
        note: str = "",
    ) -> dict[str, Any]:
        team = _safe_id(team_id, field="teamId")
        evidence_id = _required_text(claim_evidence_id, "claimEvidenceId", 200)
        normalized_decision = _required_choice(decision, "decision", {"accepted", "rejected"})
        reviewer = _required_text(reviewed_by, "reviewedBy", 200)
        review_note = _optional_text(note, 2000)
        path = self._path(team)
        with _LOCK:
            records = _read_jsonl(path)
            record = next((item for item in records if item.get("claimEvidenceId") == evidence_id), None)
            if record is None:
                raise ClaimEvidenceError("Claim evidence record not found.")
            if record.get("reviewStatus") == "stale":
                raise ClaimEvidenceError("Stale claim evidence cannot be reviewed until it is re-extracted.")
            record["reviewStatus"] = normalized_decision
            record["reviewedBy"] = reviewer
            record["reviewNote"] = review_note
            record["reviewedAt"] = _now_utc()
            record["updatedAt"] = record["reviewedAt"]
            record["formalKnowledgeWriteAllowed"] = False
            _write_jsonl_atomic(path, records)
        _record_event(
            "research_evidence.claim_reviewed",
            team_id=team,
            fields={
                "claimEvidenceId": evidence_id,
                "reviewStatus": normalized_decision,
                "reviewedBy": reviewer,
            },
        )
        return record

    def append_accepted_review_twins(
        self,
        team_id: str,
        sources: Iterable[Mapping[str, Any]],
        *,
        accepted_by: str,
        accepted_at_ms: int,
        acceptance_round_id: str,
        acceptance_source: str,
    ) -> list[dict[str, Any]]:
        """Append accepted twins of pending evidence (append-only acceptance).

        The store is append-only and ``claimEvidenceId`` is a content hash, so
        an acceptance cannot edit the pending record in place.  Each twin keeps
        the exact content identity (hence the same evidence id) and carries
        ``reviewStatus="accepted"`` plus the acceptance audit fields.  Belief
        readers resolve evidence state by id with latest-record-wins, so the
        twin becomes the effective review state while the pending original
        preserves its history.

        Idempotent on (claimId, candidateId, reasoningRole, acceptedBy,
        acceptanceRoundId, acceptanceSource): when an equivalent accepted twin
        already exists in the store — or was appended earlier in this batch —
        the source is skipped.  Malformed sources are skipped instead of
        raised: an acceptance write must never corrupt the payload contract.
        """
        team = _safe_id(team_id, field="teamId")
        reviewer = _required_text(accepted_by, "acceptedBy", 200)
        round_id = _required_text(acceptance_round_id, "acceptanceRoundId", 200)
        source_tag = _optional_text(acceptance_source, 80) or "human_adjudication"
        try:
            accepted_ms = int(accepted_at_ms)
        except (TypeError, ValueError) as exc:
            raise ClaimEvidenceError("acceptedAtMs must be an integer") from exc
        payload_keys = (
            "claimId",
            "candidateId",
            "sourceId",
            "sourceRevision",
            "locator",
            "quote",
            "evidenceKind",
            "reasoningRole",
            "supportLevel",
            "extractionMethod",
            "extractorAgentId",
            "modelRef",
        )
        path = self._path(team)
        appended: list[dict[str, Any]] = []
        with _LOCK:
            records = _read_jsonl(path)
            existing_twins = {
                (
                    str(item.get("claimId") or ""),
                    str(item.get("candidateId") or ""),
                    str(item.get("reasoningRole") or "").strip().lower(),
                    str(item.get("acceptedBy") or ""),
                    str(item.get("acceptanceRoundId") or ""),
                    str(item.get("acceptanceSource") or ""),
                )
                for item in records
                if str(item.get("reviewStatus") or "").strip().lower() == "accepted"
            }
            now = _now_utc()
            for source in sources:
                if not isinstance(source, Mapping):
                    continue
                payload: dict[str, Any] = {key: source.get(key) for key in payload_keys}
                for optional_key in ("sourceCollectionRunId", "workflowRunId"):
                    if source.get(optional_key):
                        payload[optional_key] = source.get(optional_key)
                try:
                    normalized = _normalize_payload(payload)
                except ClaimEvidenceError:
                    continue
                # Belief readers resolve a cited record's scope against the
                # claim's scopeHash; a twin without it would be neutralized,
                # so the caller-supplied scope travels onto the twin.
                scope_hash = str(source.get("scopeHash") or "").strip().lower()
                identity = (
                    normalized["claimId"],
                    normalized["candidateId"],
                    normalized["reasoningRole"],
                    reviewer,
                    round_id,
                    source_tag,
                )
                if identity in existing_twins:
                    continue
                record = {
                    "schemaVersion": SCHEMA_VERSION,
                    "claimEvidenceId": _evidence_id(normalized),
                    **normalized,
                    **({"scopeHash": scope_hash} if scope_hash else {}),
                    "quoteHash": _sha256_text(normalized["quote"]),
                    "reviewStatus": "accepted",
                    "reviewedBy": reviewer,
                    "shadowOnly": False,
                    "formalKnowledgeWriteAllowed": False,
                    "createdAt": now,
                    "updatedAt": now,
                    "acceptedBy": reviewer,
                    "acceptedAtMs": accepted_ms,
                    "acceptanceRoundId": round_id,
                    "acceptanceSource": source_tag,
                }
                records.append(record)
                existing_twins.add(identity)
                appended.append(record)
            if appended:
                _write_jsonl_atomic(path, records)
        if appended:
            _record_event(
                "research_evidence.acceptance_twins_appended",
                team_id=team,
                fields={
                    "acceptedTwinCount": len(appended),
                    "acceptedBy": reviewer,
                    "acceptanceRoundId": round_id,
                    "acceptanceSource": source_tag,
                },
            )
        return appended

    def coverage(self, team_id: str, *, candidate_id: str = "") -> dict[str, Any]:
        team = _safe_id(team_id, field="teamId")
        records = self.list(team, candidate_id=candidate_id)
        summary = {
            "total": len(records),
            "accepted": sum(item.get("reviewStatus") == "accepted" for item in records),
            "pending": sum(item.get("reviewStatus") == "pending" for item in records),
            "rejected": sum(item.get("reviewStatus") == "rejected" for item in records),
            "stale": sum(item.get("reviewStatus") == "stale" for item in records),
            "supports": sum(item.get("supportLevel") == "supports" for item in records),
            "contradicts": sum(item.get("supportLevel") == "contradicts" for item in records),
            "unverified": sum(item.get("supportLevel") == "unverified" for item in records),
        }
        gate_passed = bool(records) and summary["accepted"] == summary["total"] and summary["supports"] > 0
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": team,
            "candidateId": candidate_id,
            "summary": summary,
            "evidenceGatePassed": gate_passed,
            "counterEvidencePresent": summary["contradicts"] > 0,
            "formalKnowledgeWriteAllowed": False,
        }

    def project_legacy(
        self,
        team_id: str,
        *,
        candidate_id: str,
        legacy_entries: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build a non-persistent compatibility projection for old evidence rows."""

        team = _safe_id(team_id, field="teamId")
        candidate = _required_text(candidate_id, "candidateId", 200)
        projected: list[dict[str, Any]] = []
        for index, raw in enumerate(legacy_entries):
            entry = raw if isinstance(raw, dict) else {}
            claim = _optional_text(entry.get("claim") or entry.get("summary"), 1000)
            citation = _optional_text(entry.get("citation") or entry.get("sourceRef"), 500)
            excerpt = _optional_text(entry.get("excerpt") or entry.get("quote"), 4000)
            fingerprint = _stable_hash({"teamId": team, "candidateId": candidate, "index": index, "entry": entry})
            projected.append(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "claimEvidenceId": f"ce-legacy-{fingerprint[:16]}",
                    "claimId": "",
                    "candidateId": candidate,
                    "sourceId": citation,
                    "sourceRevision": "legacy:unverified",
                    "locator": {"kind": "legacy_unverified"},
                    "quote": excerpt,
                    "quoteHash": _sha256_text(excerpt),
                    "claim": claim,
                    "evidenceKind": "legacy_unverified",
                    "reasoningRole": "inference",
                    "supportLevel": "unverified",
                    "extractionMethod": "legacy_projection",
                    "extractorAgentId": "",
                    "modelRef": "",
                    "reviewStatus": "pending",
                    "reviewedBy": "",
                    "shadowOnly": True,
                    "formalKnowledgeWriteAllowed": False,
                    "limitations": ["legacy_evidence_missing_canonical_locator_or_source_revision"],
                }
            )
        return projected

    def _path(self, team_id: str) -> Path:
        return (
            resolve_project_workspace_home(self.project_root)
            / "teams"
            / team_id
            / "claim_evidence"
            / "index.jsonl"
        )


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ClaimEvidenceError("Claim evidence payload must be an object.")
    locator = _locator(payload.get("locator"))
    reasoning_role = _required_choice(payload.get("reasoningRole"), "reasoningRole", _REASONING_ROLES)
    evidence_kind = _required_choice(payload.get("evidenceKind"), "evidenceKind", _EVIDENCE_KINDS)
    support_level = _required_choice(payload.get("supportLevel"), "supportLevel", _SUPPORT_LEVELS)
    extraction_method = _required_choice(payload.get("extractionMethod"), "extractionMethod", _EXTRACTION_METHODS)
    model_ref = _optional_text(payload.get("modelRef"), 300)
    if extraction_method == "model" and not model_ref:
        raise ClaimEvidenceError("modelRef is required for model-extracted evidence.")
    normalized: dict[str, Any] = {
        "claimId": _required_text(payload.get("claimId"), "claimId", 200),
        "candidateId": _required_text(payload.get("candidateId"), "candidateId", 200),
        "sourceId": _required_text(payload.get("sourceId"), "sourceId", 500),
        "sourceRevision": _source_revision(payload.get("sourceRevision")),
        "locator": locator,
        "quote": _required_text(payload.get("quote"), "quote", 4000),
        "evidenceKind": evidence_kind,
        "reasoningRole": reasoning_role,
        "supportLevel": support_level,
        "extractionMethod": extraction_method,
        "extractorAgentId": _required_text(payload.get("extractorAgentId"), "extractorAgentId", 200),
        "modelRef": model_ref,
    }
    # Optional run-scope tags so workflow collectors can exclude unscoped history.
    source_collection_run_id = _optional_text(payload.get("sourceCollectionRunId"), 160)
    workflow_run_id = _optional_text(payload.get("workflowRunId"), 160)
    if source_collection_run_id:
        normalized["sourceCollectionRunId"] = source_collection_run_id
    if workflow_run_id:
        normalized["workflowRunId"] = workflow_run_id
    return normalized


def _locator(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ClaimEvidenceError("locator must be an object with a kind and an address.")
    kind = _optional_text(value.get("kind"), 80)
    if not kind:
        raise ClaimEvidenceError("locator.kind is required.")
    locator: dict[str, Any] = {"kind": kind}
    page = value.get("page")
    if page not in (None, ""):
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise ClaimEvidenceError("locator.page must be a positive integer.")
        locator["page"] = page
    for field in ("section", "anchor", "url"):
        text = _optional_text(value.get(field), 500)
        if text:
            locator[field] = text
    if len(locator) == 1:
        raise ClaimEvidenceError("locator must include page, section, anchor, or url.")
    return locator


def _source_revision(value: Any) -> str:
    text = _optional_text(value, 100).lower()
    if not _SHA256_PATTERN.fullmatch(text):
        raise ClaimEvidenceError("sourceRevision must use sha256:<64 lowercase hex>.")
    return text


def _required_choice(value: Any, field: str, allowed: set[str]) -> str:
    text = _optional_text(value, 80).lower()
    if text not in allowed:
        raise ClaimEvidenceError(f"{field} must be one of: {', '.join(sorted(allowed))}.")
    return text


def _required_text(value: Any, field: str, max_length: int) -> str:
    text = _optional_text(value, max_length)
    if not text:
        raise ClaimEvidenceError(f"{field} is required.")
    return text


def _optional_text(value: Any, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) > max_length:
        raise ClaimEvidenceError(f"Text exceeds maximum length {max_length}.")
    return text


def _safe_id(value: Any, *, field: str) -> str:
    text = _required_text(value, field, 160)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", text):
        raise ClaimEvidenceError(f"{field} contains unsupported characters.")
    return text


def _evidence_id(payload: dict[str, Any]) -> str:
    identity = {
        key: payload[key]
        for key in ("claimId", "candidateId", "sourceId", "sourceRevision", "locator", "quote", "reasoningRole")
    }
    return f"ce-{_stable_hash(identity)[:20]}"


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


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
            raise ClaimEvidenceError(f"Invalid claim evidence JSONL at line {line_number}.") from exc
        if not isinstance(payload, dict):
            raise ClaimEvidenceError(f"Invalid claim evidence record at line {line_number}.")
        records.append(payload)
    return records


def _write_jsonl_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _record_event(event_code: str, *, team_id: str, fields: dict[str, Any]) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "research_evidence",
            "claim_ledger",
            event_code,
            message=event_code,
            fields={"teamId": team_id, **fields},
            lifecycle=True,
        )
    except Exception:
        return
