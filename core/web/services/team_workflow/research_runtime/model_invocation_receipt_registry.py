"""Immutable question-level registry for every real model invocation receipt."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import uuid4

from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)
from core.web.services.team_workflow.research_projects import resolve_team_program_root
from core.web.services.team_workflow.storage_durability import inter_process_lock

STORE_SCHEMA_VERSION = 1
STORE_KIND = "challenge_question_model_invocation_receipts"
REQUIRED_OUTCOME_KINDS = frozenset(
    {"candidate", "review", "revision", "plan", "final_output"}
)
ALLOWED_OUTCOME_KINDS = REQUIRED_OUTCOME_KINDS | frozenset({"source_evidence"})
_LOCK = RLock()

# Governed Challenge Cup reset ports keep their opaque staged snapshots in
# process memory.  The parent reset orchestrator receives only the token and a
# bounded summary, so receipt JSON (which includes model evidence locators) is
# never accidentally copied into a destructive-step response.  The cache is
# intentionally separate from the normal immutable receipt registry lock.
RECEIPT_RESET_PORT_SCHEMA_VERSION = 1
RECEIPT_RESET_PORT_KIND = "challenge_cup_model_invocation_receipt_reset"
_RESET_LOCK = RLock()
_RESET_STAGES: dict[str, dict[str, Any]] = {}


class ReceiptResetPortError(ValueError):
    """Fail-closed error raised by the managed receipt reset port."""

    code = "receipt_reset_port_error"

    def __init__(self, detail: str, *, code: str | None = None) -> None:
        self.detail = str(detail or self.code).strip()
        if code:
            self.code = str(code).strip() or self.code
        super().__init__(self.detail)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _path_component(value: Any, *, field_name: str) -> str:
    """Map an audit identifier to an irreversible, single path component."""

    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    # Never place caller-controlled identifiers in a filesystem path.  The
    # digest is also safe for values such as '.', '..', '/' and '\\'.
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _io_path(path: Path) -> Path:
    """Normalize a store path to the ``\\\\?\\`` extended-length IO form.

    The receipt store nests two SHA-256 path components under the team
    program root; on real deployments the final file path exceeds the legacy
    Windows ``MAX_PATH`` boundary and ``os.replace`` fails with ``WinError 3``
    even though the directory itself is writable.  The logical path returned
    by ``_path`` stays prefix-free so containment checks keep comparing.
    """

    resolved = path.resolve()
    if os.name != "nt":
        return resolved
    value = str(resolved)
    if value.startswith("\\\\?\\"):
        return resolved
    if value.startswith("\\\\"):
        return Path(f"\\\\?\\UNC\\{value[2:]}")
    return Path(f"\\\\?\\{value}")


def _path(team_id: str, question_id: str, workflow_run_id: str) -> Path:
    normalized_question = str(question_id or "").strip().upper()
    normalized_run = str(workflow_run_id or "").strip()
    safe_question = _path_component(normalized_question, field_name="questionId")
    safe_run = _path_component(normalized_run, field_name="workflowRunId")
    return (
        resolve_team_program_root(team_id)
        / "challenge_program"
        / "model_invocation_receipts"
        / safe_question
        / f"{safe_run}.json"
    )


def _load(path: Path) -> dict[str, Any] | None:
    io_path = _io_path(path)
    if not io_path.exists():
        return None
    if not io_path.is_file():
        raise ValueError("model invocation receipt store path is not a file")
    try:
        payload = json.loads(io_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("model invocation receipt store is unreadable or corrupt") from exc
    if not isinstance(payload, dict):
        raise ValueError("model invocation receipt store must be a JSON object")
    return payload


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    io_path = _io_path(path)
    io_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the atomic sibling name short.  The receipt path already contains
    # two SHA-256 segments, so repeating the target basename plus a full UUID
    # can exceed the legacy Windows MAX_PATH boundary even when the final file
    # itself is valid.
    temporary = io_path.with_name(f".tmp-{uuid4().hex[:12]}")
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, io_path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    if os.name != "nt":
        directory_fd = os.open(str(io_path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def _outcome_kinds(receipt: ModelInvocationReceipt) -> tuple[str, ...]:
    raw = receipt.metadata.get("outcomeKinds")
    values = tuple(
        dict.fromkeys(
            str(item or "").strip().lower()
            for item in list(raw or [])
            if str(item or "").strip()
        )
    )
    if not values or any(item not in ALLOWED_OUTCOME_KINDS for item in values):
        raise ValueError("model invocation receipt outcomeKinds are invalid")
    return values


def _require_lower_sha256(value: Any, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{field_name} must be a lowercase sha256 hex digest")
    return normalized


def _validate_receipt(
    value: Mapping[str, Any],
    *,
    question_id: str,
    workflow_run_id: str,
) -> ModelInvocationReceipt:
    if not isinstance(value, Mapping):
        raise ValueError("model invocation receipt must be an object")
    receipt = ModelInvocationReceipt.from_dict(value)
    if receipt.status not in {
        ModelInvocationStatus.SUCCEEDED,
        ModelInvocationStatus.RETRIED,
    }:
        raise ValueError("only successful model invocation receipts may be registered")
    scope = dict(receipt.scope or {})
    locator = dict(receipt.evidence_locator or {})
    normalized_question = str(question_id or "").strip().upper()
    normalized_run = str(workflow_run_id or "").strip()
    if str(scope.get("questionId") or "").strip().upper() != normalized_question:
        raise ValueError("model invocation receipt question scope mismatch")
    if receipt.run_id != normalized_run:
        raise ValueError("model invocation receipt run mismatch")
    if str(scope.get("workflowRunId") or "").strip() != normalized_run:
        raise ValueError("model invocation receipt workflow run scope mismatch")
    for scope_key, locator_key in (
        ("sessionId", "sessionId"),
        ("taskId", "taskId"),
        ("turnId", "turnId"),
        ("formalNodeId", "formalNodeId"),
        ("formalNodeRunId", "formalNodeRunId"),
        ("modelPolicySha256", "modelPolicySha256"),
    ):
        if not str(scope.get(scope_key) or "").strip() or (
            str(scope.get(scope_key) or "").strip()
            != str(locator.get(locator_key) or "").strip()
        ):
            raise ValueError(f"model invocation receipt {scope_key} locator mismatch")
    node_run_id = str(receipt.node_run_id or "").strip()
    if (
        not node_run_id
        or node_run_id != str(scope.get("formalNodeRunId") or "").strip()
        or node_run_id != str(locator.get("formalNodeRunId") or "").strip()
    ):
        raise ValueError("model invocation receipt nodeRunId scope mismatch")
    _require_lower_sha256(scope.get("modelPolicySha256"), field_name="modelPolicySha256")
    for locator_key in (
        "kind",
        "outputRef",
        "invocationId",
    ):
        if not str(locator.get(locator_key) or "").strip():
            raise ValueError(f"model invocation receipt evidenceLocator.{locator_key} is required")
    _require_lower_sha256(locator.get("outputSha256"), field_name="evidenceLocator.outputSha256")
    try:
        locator_attempt = int(locator.get("attempt"))
    except (TypeError, ValueError) as exc:
        raise ValueError("evidenceLocator.attempt must be an integer") from exc
    if isinstance(locator.get("attempt"), bool) or locator_attempt != int(receipt.attempt):
        raise ValueError("model invocation receipt attempt locator mismatch")
    _outcome_kinds(receipt)
    return receipt


def _validate_store_payload(
    payload: Mapping[str, Any] | None,
    *,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
) -> list[dict[str, Any]]:
    """Validate an existing store before it can participate in a write."""

    if payload is None:
        return []
    if (
        payload.get("schemaVersion") != STORE_SCHEMA_VERSION
        or payload.get("storeKind") != STORE_KIND
        or str(payload.get("teamId") or "") != team_id
        or str(payload.get("questionId") or "").strip().upper() != question_id
        or str(payload.get("workflowRunId") or "") != workflow_run_id
    ):
        raise ValueError("model invocation receipt store header is invalid")
    raw_receipts = payload.get("receipts")
    if not isinstance(raw_receipts, list):
        raise ValueError("model invocation receipt store receipts must be a list")
    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_receipts:
        if not isinstance(raw, Mapping):
            raise ValueError("model invocation receipt store contains a non-object receipt")
        receipt = _validate_receipt(
            raw,
            question_id=question_id,
            workflow_run_id=workflow_run_id,
        )
        if receipt.receipt_id in seen:
            raise ValueError("model invocation receipt store contains duplicate receiptId")
        seen.add(receipt.receipt_id)
        values.append(dict(raw))
    return values


def register_question_model_invocation_receipts(
    team_id: str,
    *,
    question_id: str,
    workflow_run_id: str,
    receipts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Append receipts idempotently; a conflicting receipt id fails closed."""

    normalized_team = str(team_id or "").strip()
    normalized_question = str(question_id or "").strip().upper()
    normalized_run = str(workflow_run_id or "").strip()
    if not normalized_team:
        raise ValueError("teamId is required")
    validated = []
    for value in receipts:
        if not isinstance(value, Mapping):
            raise ValueError("model invocation receipt must be an object")
        validated.append(
            _validate_receipt(
                value,
                question_id=normalized_question,
                workflow_run_id=normalized_run,
            )
        )
    path = _path(normalized_team, normalized_question, normalized_run)
    # Atomic replace protects readers from torn files, while the dedicated
    # cross-process lock protects the complete read-modify-write sequence from
    # lost updates.  Do not borrow the Workflow Ledger SQLite writer for this
    # file-store serialization.
    with _LOCK, inter_process_lock(_io_path(path)):
        stored = _load(path)
        existing_values = _validate_store_payload(
            stored,
            team_id=normalized_team,
            question_id=normalized_question,
            workflow_run_id=normalized_run,
        )
        existing = {
            str(item.get("receiptId") or "").strip(): item for item in existing_values
        }
        changed = False
        for receipt in validated:
            payload = receipt.to_dict()
            previous = existing.get(receipt.receipt_id)
            if previous is not None:
                if previous != payload:
                    raise ValueError("model invocation receipt replay conflict")
                continue
            existing[receipt.receipt_id] = payload
            existing_values.append(payload)
            changed = True
        if changed or stored is None:
            _write(
                path,
                {
                    "schemaVersion": STORE_SCHEMA_VERSION,
                    "storeKind": STORE_KIND,
                    "teamId": normalized_team,
                    "questionId": normalized_question,
                    "workflowRunId": normalized_run,
                    "receipts": existing_values,
                },
            )
    return question_model_invocation_receipt_refs(
        normalized_team,
        question_id=normalized_question,
        workflow_run_id=normalized_run,
    )


def validate_question_model_invocation_receipt(
    value: Mapping[str, Any],
    *,
    question_id: str,
    workflow_run_id: str,
) -> dict[str, Any]:
    """Return the canonical validated payload without mutating the registry."""

    return _validate_receipt(
        value,
        question_id=str(question_id or "").strip().upper(),
        workflow_run_id=str(workflow_run_id or "").strip(),
    ).to_dict()


def question_model_invocation_receipts(
    team_id: str,
    *,
    question_id: str,
    workflow_run_id: str,
    session_id: str = "",
    turn_id: str = "",
) -> list[dict[str, Any]]:
    """Read validated receipt payloads from the Challenge Cup audit store.

    Optional Session/Turn filters let the session completion adapter recover
    only the receipts for the canonical turn without reading conversation
    journal content. Corrupt or mismatched stores fail closed as an empty set.
    """

    normalized_team = str(team_id or "").strip()
    normalized_question = str(question_id or "").strip().upper()
    normalized_run = str(workflow_run_id or "").strip()
    normalized_session = str(session_id or "").strip()
    normalized_turn = str(turn_id or "").strip()
    try:
        payload = _load(_path(normalized_team, normalized_question, normalized_run))
        existing_values = _validate_store_payload(
            payload,
            team_id=normalized_team,
            question_id=normalized_question,
            workflow_run_id=normalized_run,
        )
    except (OSError, TypeError, ValueError):
        return []
    receipts: list[dict[str, Any]] = []
    for raw in existing_values:
        scope = raw.get("scope") if isinstance(raw.get("scope"), Mapping) else {}
        if normalized_session and str(scope.get("sessionId") or "").strip() != normalized_session:
            continue
        if normalized_turn and str(scope.get("turnId") or "").strip() != normalized_turn:
            continue
        receipts.append(deepcopy(raw))
    return receipts


def question_model_invocation_receipt_refs(
    team_id: str,
    *,
    question_id: str,
    workflow_run_id: str,
) -> list[dict[str, Any]]:
    """Return hash-verifiable locators, refusing an unreadable/tampered store."""

    normalized_question = str(question_id or "").strip().upper()
    normalized_run = str(workflow_run_id or "").strip()
    try:
        payload = _load(_path(team_id, normalized_question, normalized_run))
        existing_values = _validate_store_payload(
            payload,
            team_id=str(team_id or "").strip(),
            question_id=normalized_question,
            workflow_run_id=normalized_run,
        )
    except (OSError, TypeError, ValueError):
        return []
    if not existing_values:
        return []
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for raw in existing_values:
            receipt = _validate_receipt(
                raw,
                question_id=normalized_question,
                workflow_run_id=normalized_run,
            )
            if receipt.receipt_id in seen:
                return []
            seen.add(receipt.receipt_id)
            locator = deepcopy(dict(receipt.evidence_locator))
            refs.append(
                {
                    "receiptId": receipt.receipt_id,
                    "receiptSha256": _canonical_sha256(receipt.to_dict()),
                    "nodeRunId": receipt.node_run_id,
                    "sessionId": str(receipt.scope.get("sessionId") or ""),
                    "turnId": str(receipt.scope.get("turnId") or ""),
                    "outcomeKinds": list(_outcome_kinds(receipt)),
                    "evidenceLocator": locator,
                    "evidenceLocatorSha256": _canonical_sha256(locator),
                }
            )
    except (TypeError, ValueError, KeyError):
        return []
    return refs


def model_invocation_receipt_coverage(
    refs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    covered = {
        str(kind or "").strip().lower()
        for ref in refs
        if isinstance(ref, Mapping)
        for kind in list(ref.get("outcomeKinds") or [])
        if str(kind or "").strip()
    }
    observed = sorted(covered & REQUIRED_OUTCOME_KINDS)
    missing = sorted(REQUIRED_OUTCOME_KINDS - covered)
    return {
        "status": "passed" if not missing else "failed",
        "coveredKinds": observed,
        "missingKinds": missing,
        "receiptCount": len(list(refs)),
    }


def model_invocation_receipt_evidence_entries(
    team_id: str,
    *,
    question_id: str,
    workflow_run_id: str,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for ref in question_model_invocation_receipt_refs(
        team_id,
        question_id=question_id,
        workflow_run_id=workflow_run_id,
    ):
        entries.append(
            {
                "path": f"model-invocations/{ref['receiptId']}.json",
                "kind": "model_invocation_receipt",
                "sha256": ref["receiptSha256"],
                "scope": {
                    "questionId": str(question_id or "").strip().upper(),
                    "runId": str(workflow_run_id or "").strip(),
                    "nodeRunId": ref["nodeRunId"],
                    "outcomeKinds": list(ref["outcomeKinds"]),
                    "evidenceLocator": deepcopy(ref["evidenceLocator"]),
                    "evidenceLocatorSha256": ref["evidenceLocatorSha256"],
                },
            }
        )
    return entries


# ---------------------------------------------------------------------------
# Governed Challenge Cup reset port
# ---------------------------------------------------------------------------


def _reset_receipt_text(value: Any, *, field: str, required: bool = True) -> str:
    normalized = str(value or "").strip()
    if required and not normalized:
        raise ReceiptResetPortError(
            f"{field} is required", code="receipt_scope_missing"
        )
    return normalized


def _reset_receipt_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _receipt_scope_authority_entries(authority: Any) -> dict[tuple[str, str], dict[str, Any]]:
    """Normalize explicit question/run/team mappings required for reset."""

    if authority is None:
        raise ReceiptResetPortError(
            "receipt scope authority is required", code="receipt_scope_missing"
        )
    source: Any = authority
    if isinstance(source, Mapping):
        for key in ("receipts", "runs", "records", "scopes", "entries"):
            if key in source:
                source = source[key]
                break
        else:
            if any(key in source for key in ("teamId", "team_id", "questionId", "question_id")):
                source = [source]
    if isinstance(source, Mapping):
        iterable = list(source.items())
    elif isinstance(source, (list, tuple)):
        iterable = [(None, item) for item in source]
    else:
        raise ReceiptResetPortError(
            "receipt scope authority must be a mapping or list",
            code="receipt_scope_invalid",
        )
    normalized: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_key, raw_value in iterable:
        if not isinstance(raw_value, Mapping):
            raise ReceiptResetPortError(
                "receipt scope authority contains a non-object entry",
                code="receipt_scope_invalid",
            )
        question_id = _reset_receipt_text(
            raw_value.get("questionId")
            or raw_value.get("question_id")
            or (raw_key.split("/", 1)[0] if isinstance(raw_key, str) and "/" in raw_key else ""),
            field="questionId",
        ).upper()
        workflow_run_id = _reset_receipt_text(
            raw_value.get("workflowRunId")
            or raw_value.get("workflow_run_id")
            or raw_value.get("runId")
            or raw_value.get("run_id")
            or (raw_key.split("/", 1)[1] if isinstance(raw_key, str) and "/" in raw_key else ""),
            field="workflowRunId",
        )
        team_id = _reset_receipt_text(
            raw_value.get("teamId") or raw_value.get("team_id"),
            field="teamId",
        )
        item = {
            "teamId": team_id,
            "questionId": question_id,
            "workflowRunId": workflow_run_id,
        }
        previous = normalized.get((question_id, workflow_run_id))
        if previous is not None and previous != item:
            raise ReceiptResetPortError(
                "receipt scope authority contains conflicting entries",
                code="receipt_scope_mismatch",
            )
        normalized[(question_id, workflow_run_id)] = item
    if not normalized:
        raise ReceiptResetPortError(
            "receipt scope authority is empty", code="receipt_scope_missing"
        )
    return dict(sorted(normalized.items()))


def _receipt_store_root(team_id: str) -> Path:
    normalized_team = _reset_receipt_text(team_id, field="teamId")
    try:
        root = (
            resolve_team_program_root(normalized_team)
            / "challenge_program"
            / "model_invocation_receipts"
        ).expanduser().resolve(strict=False)
    except Exception as exc:  # noqa: BLE001 - missing team is not reset authority
        raise ReceiptResetPortError(
            "receipt team program root is unavailable", code="receipt_scope_unavailable"
        ) from exc
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise ReceiptResetPortError(
            "receipt store root is not a regular directory", code="receipt_store_unsafe"
        )
    return root


def _receipt_raw_bytes(path: Path) -> bytes:
    try:
        value = path.read_bytes()
        json.loads(value.decode("utf-8"))
        return value
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReceiptResetPortError(
            "receipt store is unreadable or corrupt", code="receipt_store_corrupt"
        ) from exc


def _receipt_path_matches(
    path: Path, team_id: str, question_id: str, workflow_run_id: str
) -> None:
    expected = _path(team_id, question_id, workflow_run_id).resolve(strict=False)
    if path.resolve(strict=False) != expected:
        raise ReceiptResetPortError(
            "receipt store path does not match its declared scope",
            code="receipt_scope_mismatch",
        )


def _receipt_store_rows(
    team_id: str,
    authority: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    root = _receipt_store_root(team_id)
    if not root.exists():
        return []
    files: list[Path] = []
    for item in root.rglob("*"):
        if item.is_symlink():
            raise ReceiptResetPortError(
                "receipt store contains a symlink", code="receipt_store_unsafe"
            )
        if item.is_file():
            files.append(item)
    stores: list[dict[str, Any]] = []
    for path in sorted(files, key=lambda value: value.as_posix().lower()):
        if path.suffix.lower() != ".json":
            raise ReceiptResetPortError(
                "receipt store contains an unsupported file", code="receipt_store_corrupt"
            )
        raw_bytes = _receipt_raw_bytes(path)
        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ReceiptResetPortError(
                "receipt store JSON is corrupt", code="receipt_store_corrupt"
            ) from exc
        if not isinstance(payload, Mapping):
            raise ReceiptResetPortError(
                "receipt store must be an object", code="receipt_store_corrupt"
            )
        question_id = _reset_receipt_text(payload.get("questionId"), field="questionId").upper()
        workflow_run_id = _reset_receipt_text(
            payload.get("workflowRunId"), field="workflowRunId"
        )
        payload_team = _reset_receipt_text(payload.get("teamId"), field="teamId")
        if payload_team != team_id:
            raise ReceiptResetPortError(
                "receipt store belongs to another team", code="receipt_scope_mismatch"
            )
        _receipt_path_matches(path, team_id, question_id, workflow_run_id)
        expected = authority.get((question_id, workflow_run_id))
        if expected is None:
            raise ReceiptResetPortError(
                "receipt store has no question/run scope authority",
                code="receipt_scope_missing",
            )
        if str(expected.get("teamId") or "") != team_id:
            raise ReceiptResetPortError(
                "receipt scope authority crosses team boundary",
                code="receipt_scope_mismatch",
            )
        try:
            stored_receipts = _validate_store_payload(
                payload,
                team_id=team_id,
                question_id=question_id,
                workflow_run_id=workflow_run_id,
            )
        except (TypeError, ValueError) as exc:
            raise ReceiptResetPortError(
                "receipt store failed integrity validation", code="receipt_store_corrupt"
            ) from exc
        stores.append(
            {
                "path": path,
                "relativePath": path.relative_to(root).as_posix(),
                "teamId": team_id,
                "questionId": question_id,
                "workflowRunId": workflow_run_id,
                "rawBytes": raw_bytes,
                "storeHash": hashlib.sha256(raw_bytes).hexdigest(),
                "receipts": stored_receipts,
            }
        )
    return stores


def _receipt_store_record(store: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, Any]:
    receipt_id = str(raw.get("receiptId") or "").strip()
    if not receipt_id:
        raise ReceiptResetPortError(
            "receiptId is missing from validated store", code="receipt_store_corrupt"
        )
    try:
        receipt = ModelInvocationReceipt.from_dict(raw)
    except Exception as exc:  # noqa: BLE001 - validation should already catch this
        raise ReceiptResetPortError(
            "receipt record is malformed", code="receipt_store_corrupt"
        ) from exc
    return {
        "id": receipt_id,
        "receiptId": receipt_id,
        "teamId": store["teamId"],
        "questionId": store["questionId"],
        "workflowRunId": store["workflowRunId"],
        "nodeRunId": receipt.node_run_id,
        "outcomeKinds": list(_outcome_kinds(receipt)),
        "receiptSha256": _canonical_sha256(receipt.to_dict()),
        "storeHash": store["storeHash"],
        "storeKey": f"{store['questionId']}:{store['workflowRunId']}",
    }


def _receipt_authority_hash(
    authority: Mapping[tuple[str, str], Mapping[str, Any]]
) -> str:
    return _reset_receipt_hash(
        [
            {
                "questionId": question_id,
                "workflowRunId": workflow_run_id,
                **dict(value),
            }
            for (question_id, workflow_run_id), value in sorted(authority.items())
        ]
    )


def list_team_scoped_model_invocation_receipts(
    team_id: str,
    *,
    scope_authority: Any = None,
) -> list[dict[str, Any]]:
    """List receipt identities only after proving every store's team scope."""

    normalized_team = _reset_receipt_text(team_id, field="teamId")
    authority = _receipt_scope_authority_entries(scope_authority)
    stores = _receipt_store_rows(normalized_team, authority)
    rows: list[dict[str, Any]] = []
    for store in stores:
        rows.extend(_receipt_store_record(store, raw) for raw in store["receipts"])
    return rows


def list_team_model_invocation_latency_samples(
    team_id: str,
    *,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Return bounded, excerpt-free latency facts for deadline calibration.

    The immutable receipt files remain the fact source.  This projection does
    not expose prompts, responses, evidence locators or token data and never
    writes the registry.  Corrupt stores fail closed instead of silently
    biasing the wall-clock policy.
    """

    normalized_team = _reset_receipt_text(team_id, field="teamId")
    root = _receipt_store_root(normalized_team)
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        payload = _load(path)
        if not isinstance(payload, Mapping):
            continue
        question_id = str(payload.get("questionId") or "").strip().upper()
        workflow_run_id = str(payload.get("workflowRunId") or "").strip()
        receipts = _validate_store_payload(
            payload,
            team_id=normalized_team,
            question_id=question_id,
            workflow_run_id=workflow_run_id,
        )
        for raw in receipts:
            receipt = ModelInvocationReceipt.from_dict(raw)
            if receipt.status not in {
                ModelInvocationStatus.SUCCEEDED,
                ModelInvocationStatus.RETRIED,
            }:
                continue
            rows.append(
                {
                    "provider": receipt.provider,
                    "model": receipt.model,
                    "latencyMs": receipt.latency_ms,
                    "finishedAtMs": receipt.finished_at_ms,
                    "purpose": str(receipt.metadata.get("purpose") or "").strip(),
                }
            )
    rows.sort(key=lambda item: int(item.get("finishedAtMs") or 0), reverse=True)
    bounded_limit = max(1, min(10_000, int(limit)))
    return rows[:bounded_limit]


def _receipt_stage_summary(stage: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: stage[key]
        for key in (
            "schemaVersion",
            "kind",
            "stageId",
            "resetId",
            "teamId",
            "storeRoot",
            "authorityHash",
            "storeCount",
            "recordCount",
            "storeFingerprint",
            "storeKeys",
        )
        if key in stage
    }


def prepare_model_invocation_receipt_reset_stage(
    team_id: str,
    reset_id: str,
    *,
    scope_authority: Any = None,
) -> dict[str, Any]:
    """Capture exact receipt files behind an opaque, reset-bound stage token."""

    normalized_team = _reset_receipt_text(team_id, field="teamId")
    normalized_reset = _reset_receipt_text(reset_id, field="resetId")
    authority = _receipt_scope_authority_entries(scope_authority)
    stores = _receipt_store_rows(normalized_team, authority)
    stores = sorted(stores, key=lambda item: str(item["relativePath"]))
    stage_id = f"receipt-stage-{uuid4().hex}"
    cached_stores = [
        {
            "path": str(store["path"]),
            "relativePath": store["relativePath"],
            "teamId": store["teamId"],
            "questionId": store["questionId"],
            "workflowRunId": store["workflowRunId"],
            "rawBytes": base64.b64encode(store["rawBytes"]).decode("ascii"),
            "storeHash": store["storeHash"],
            "recordCount": len(store["receipts"]),
        }
        for store in stores
    ]
    authority_hash = _receipt_authority_hash(authority)
    store_fingerprint = _reset_receipt_hash(
        [store["storeHash"] for store in cached_stores]
    )
    with _RESET_LOCK:
        _RESET_STAGES[stage_id] = {
            "stageId": stage_id,
            "resetId": normalized_reset,
            "teamId": normalized_team,
            "storeRoot": str(_receipt_store_root(normalized_team)),
            "authority": authority,
            "authorityHash": authority_hash,
            "stores": cached_stores,
            "storeFingerprint": store_fingerprint,
            "status": "staged",
        }
    return {
        "schemaVersion": RECEIPT_RESET_PORT_SCHEMA_VERSION,
        "kind": RECEIPT_RESET_PORT_KIND,
        "stageId": stage_id,
        "resetId": normalized_reset,
        "teamId": normalized_team,
        "storeRoot": str(_receipt_store_root(normalized_team)),
        "authorityHash": authority_hash,
        "storeCount": len(cached_stores),
        "recordCount": sum(int(store["recordCount"]) for store in cached_stores),
        "storeFingerprint": store_fingerprint,
        "storeKeys": [
            f"{store['questionId']}:{store['workflowRunId']}"
            for store in cached_stores
        ],
    }


def _receipt_stage_for_operation(stage: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(stage, Mapping):
        raise ReceiptResetPortError(
            "receipt stage must be an object", code="receipt_stage_corrupt"
        )
    if stage.get("schemaVersion") != RECEIPT_RESET_PORT_SCHEMA_VERSION or stage.get("kind") != RECEIPT_RESET_PORT_KIND:
        raise ReceiptResetPortError(
            "receipt stage schema is invalid", code="receipt_stage_corrupt"
        )
    stage_id = _reset_receipt_text(stage.get("stageId"), field="stageId")
    with _RESET_LOCK:
        cached = _RESET_STAGES.get(stage_id)
    if cached is None:
        raise ReceiptResetPortError(
            "receipt stage is not available", code="receipt_stage_missing"
        )
    for key in ("resetId", "teamId", "storeRoot", "authorityHash"):
        if str(stage.get(key) or "") != str(cached.get(key) or ""):
            raise ReceiptResetPortError(
                f"receipt stage {key} does not match cached stage",
                code="receipt_stage_mismatch",
            )
    if int(stage.get("storeCount") or -1) != len(cached["stores"]):
        raise ReceiptResetPortError(
            "receipt stage store count does not match cached stage",
            code="receipt_stage_mismatch",
        )
    return cached


def _receipt_assert_authority_matches(
    cached: Mapping[str, Any], scope_authority: Any = None
) -> dict[tuple[str, str], dict[str, Any]]:
    if scope_authority is None:
        return dict(cached["authority"])
    authority = _receipt_scope_authority_entries(scope_authority)
    if _receipt_authority_hash(authority) != str(cached["authorityHash"]):
        raise ReceiptResetPortError(
            "receipt scope authority changed after stage",
            code="receipt_scope_mismatch",
        )
    return authority


def _receipt_stage_bytes(store: Mapping[str, Any]) -> bytes:
    try:
        return base64.b64decode(str(store.get("rawBytes") or ""), validate=True)
    except (TypeError, ValueError) as exc:
        raise ReceiptResetPortError(
            "receipt staged bytes are invalid", code="receipt_stage_corrupt"
        ) from exc


def _receipt_atomic_write(path: Path, value: bytes) -> None:
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ReceiptResetPortError(
            "receipt restore target is unsafe", code="receipt_store_unsafe"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".reset-tmp-{uuid4().hex[:12]}")
    try:
        temporary.write_bytes(value)
        os.replace(temporary, path)
    except Exception as exc:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass
        raise ReceiptResetPortError(
            "receipt restore write failed", code="receipt_restore_failed"
        ) from exc


def _receipt_compare_stage_stores(
    current: Sequence[Mapping[str, Any]], staged: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    current_map = {str(item["relativePath"]): item for item in current}
    staged_map = {str(item["relativePath"]): item for item in staged}
    for relative, item in current_map.items():
        expected = staged_map.get(relative)
        if expected is None:
            raise ReceiptResetPortError(
                "receipt store changed after stage", code="receipt_stage_stale"
            )
        if str(item["storeHash"]) != str(expected["storeHash"]):
            raise ReceiptResetPortError(
                "receipt staged store changed", code="receipt_stage_stale"
            )
    return current_map, staged_map


def _receipt_mutate_stage(
    stage: Mapping[str, Any],
    *,
    operation: str,
    scope_authority: Any = None,
    reset_id: str | None = None,
) -> dict[str, Any]:
    cached = _receipt_stage_for_operation(stage)
    if reset_id is not None and str(reset_id).strip() != str(cached["resetId"]):
        raise ReceiptResetPortError(
            "receipt resetId does not match staged reset", code="receipt_stage_mismatch"
        )
    authority = _receipt_assert_authority_matches(cached, scope_authority)
    team_id = str(cached["teamId"])
    current = _receipt_store_rows(team_id, authority)
    current_map, staged_map = _receipt_compare_stage_stores(current, cached["stores"])
    changed = 0
    written: list[Path] = []
    try:
        if operation == "purge":
            for relative, store in current_map.items():
                path = Path(str(store["path"]))
                _receipt_path_matches(path, team_id, str(staged_map[relative]["questionId"]), str(staged_map[relative]["workflowRunId"]))
                path.unlink()
                if path.exists():
                    raise ReceiptResetPortError(
                        "receipt purge target still exists", code="receipt_reset_failed"
                    )
                changed += 1
        elif operation == "restore":
            root = Path(str(cached["storeRoot"])).resolve(strict=False)
            for relative, store in staged_map.items():
                path = (root / relative).resolve(strict=False)
                _receipt_path_matches(
                    path,
                    team_id,
                    str(store["questionId"]),
                    str(store["workflowRunId"]),
                )
                if path.exists():
                    continue
                raw_bytes = _receipt_stage_bytes(store)
                # Validate the staged payload before it is made visible again.
                try:
                    payload = json.loads(raw_bytes.decode("utf-8"))
                    _validate_store_payload(
                        payload,
                        team_id=team_id,
                        question_id=str(store["questionId"]),
                        workflow_run_id=str(store["workflowRunId"]),
                    )
                except Exception as exc:  # noqa: BLE001 - never restore unvalidated bytes
                    raise ReceiptResetPortError(
                        "receipt stage payload failed validation",
                        code="receipt_stage_corrupt",
                    ) from exc
                _receipt_atomic_write(path, raw_bytes)
                written.append(path)
                changed += 1
        else:
            raise ReceiptResetPortError(
                "receipt reset operation is unsupported", code="receipt_operation_invalid"
            )
    except Exception:
        if operation == "restore":
            for path in reversed(written):
                try:
                    if path.exists() and path.is_file() and not path.is_symlink():
                        path.unlink()
                except OSError:
                    pass
        raise
    if operation == "restore":
        restored = _receipt_store_rows(team_id, authority)
        restored_map = {str(item["relativePath"]): item for item in restored}
        if {
            key: item["storeHash"] for key, item in restored_map.items()
        } != {
            key: item["storeHash"] for key, item in staged_map.items()
        }:
            raise ReceiptResetPortError(
                "receipt restore verification failed", code="receipt_restore_failed"
            )
    with _RESET_LOCK:
        cached["status"] = "purged" if operation == "purge" else "restored"
    return {
        "ok": True,
        "kind": RECEIPT_RESET_PORT_KIND,
        "resetId": cached["resetId"],
        "teamId": team_id,
        "operation": operation,
        "storeCount": len(cached["stores"]),
        "recordCount": sum(int(item["recordCount"]) for item in cached["stores"]),
        "changedStores": changed,
        "alreadyAbsent": operation == "purge" and not current_map,
    }


def purge_model_invocation_receipt_reset_stage(
    stage: Mapping[str, Any],
    *,
    scope_authority: Any = None,
    reset_id: str | None = None,
) -> dict[str, Any]:
    """Delete only receipt files captured by this reset-bound stage."""

    return _receipt_mutate_stage(
        stage,
        operation="purge",
        scope_authority=scope_authority,
        reset_id=reset_id,
    )


def restore_model_invocation_receipt_reset_stage(
    stage: Mapping[str, Any],
    *,
    scope_authority: Any = None,
    reset_id: str | None = None,
) -> dict[str, Any]:
    """Restore staged receipt stores after a later reset port fails."""

    return _receipt_mutate_stage(
        stage,
        operation="restore",
        scope_authority=scope_authority,
        reset_id=reset_id,
    )


def destroy_model_invocation_receipt_reset_stage(
    stage: Mapping[str, Any],
    *,
    reset_id: str | None = None,
) -> dict[str, Any]:
    """Drop reset-owned receipt bytes after the enclosing reset succeeds."""

    cached = _receipt_stage_for_operation(stage)
    if reset_id is not None and str(reset_id).strip() != str(cached["resetId"]):
        raise ReceiptResetPortError(
            "receipt resetId does not match staged reset", code="receipt_stage_mismatch"
        )
    with _RESET_LOCK:
        status = str(cached.get("status") or "staged")
        if status not in {"purged", "destroyed"}:
            raise ReceiptResetPortError(
                "only a purged receipt stage can be finalized", code="receipt_stage_invalid"
            )
        cached["status"] = "destroyed"
        cached["stores"] = []
    return {**_receipt_stage_summary(stage), "operation": "destroy", "destroyed": True}


# Compatibility aliases for the parent reset adapter's port wiring.
list_receipts_for_team = list_team_scoped_model_invocation_receipts
list_team_scoped_receipts = list_team_scoped_model_invocation_receipts
prepare_receipt_reset_stage = prepare_model_invocation_receipt_reset_stage
purge_receipt_reset_stage = purge_model_invocation_receipt_reset_stage
restore_receipt_reset_stage = restore_model_invocation_receipt_reset_stage


__all__ = [
    "ALLOWED_OUTCOME_KINDS",
    "REQUIRED_OUTCOME_KINDS",
    "model_invocation_receipt_coverage",
    "model_invocation_receipt_evidence_entries",
    "question_model_invocation_receipt_refs",
    "register_question_model_invocation_receipts",
    "RECEIPT_RESET_PORT_KIND",
    "RECEIPT_RESET_PORT_SCHEMA_VERSION",
    "ReceiptResetPortError",
    "destroy_model_invocation_receipt_reset_stage",
    "list_team_model_invocation_latency_samples",
    "list_team_scoped_model_invocation_receipts",
    "prepare_model_invocation_receipt_reset_stage",
    "purge_model_invocation_receipt_reset_stage",
    "restore_model_invocation_receipt_reset_stage",
    "list_receipts_for_team",
    "list_team_scoped_receipts",
    "prepare_receipt_reset_stage",
    "purge_receipt_reset_stage",
    "restore_receipt_reset_stage",
]
