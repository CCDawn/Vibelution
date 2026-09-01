"""Persistent SQLite checkpointer for research workflow runs."""

from __future__ import annotations

import os
import copy
import base64
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from threading import RLock
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.discussion_scope import (
    CANDIDATE_REVIEW_SCOPE_KIND,
    DISCUSSION_SCOPE_KINDS,
    DISCUSSION_SCOPE_VERSION,
    QUESTION_GENERATION_SCOPE_KIND,
    parse_discussion_scope,
)
from vibelution_storage import resolve_project_data_home

PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Challenge Cup discussion-scope binding
# ---------------------------------------------------------------------------
#
# LangGraph's SqliteSaver deliberately stores arbitrary channel values.  That
# is useful for ordinary workflow runs, but it also means that a workflow can
# be resumed after its room/session binding has silently changed unless the
# binding is part of the checkpoint contract.  The small adapter below keeps
# the checkpoint owner independent from the room/session implementations.  A
# newer ``contracts.discussion_scope`` module can provide the canonical hash;
# until that module is present we use the same canonical-json convention as
# the existing workflow contracts.

SCOPE_BINDING_MISMATCH = "scope_binding_mismatch"
_CHAT_CONTENT_KEYS = frozenset(
    {
        "content",
        "body",
        "message",
        "messages",
        "transcript",
        "conversation",
        "conversationLedger",
        "prompt",
        "completion",
        "rawText",
        "text",
        "summary",
    }
)
_SCOPE_FIELD_ALIASES = {
    "team_id": "teamId",
    "research_project_id": "researchProjectId",
    "projectId": "researchProjectId",
    "workflow_run_id": "workflowRunId",
    "workflow_node_id": "workflowNodeId",
    "question_id": "questionId",
    "selection_id": "selectionId",
    "candidate_id": "candidateId",
    "scope_hash": "scopeHash",
    "scope_ref": "scopeRef",
    "room_ref": "roomRef",
    "meeting_ref": "meetingRef",
    "business_checkpoint_ref": "businessCheckpointRef",
    "participant_binding_refs": "participantBindingRefs",
}


class ScopeBindingMismatch(ValueError):
    """Raised when a formal challenge checkpoint cannot be safely resumed."""

    code = SCOPE_BINDING_MISMATCH

    def __init__(
        self,
        detail: str,
        *,
        field: str = "",
        expected_scope_hash: str = "",
        observed_scope_hash: str = "",
    ) -> None:
        self.field = str(field or "").strip()
        self.expected_scope_hash = str(expected_scope_hash or "").strip().lower()
        self.observed_scope_hash = str(observed_scope_hash or "").strip().lower()
        self.detail = str(detail or "scope binding mismatch").strip()
        super().__init__(self.detail)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "detail": self.detail}
        if self.field:
            payload["field"] = self.field
        if self.expected_scope_hash:
            payload["expectedScopeHash"] = self.expected_scope_hash
        if self.observed_scope_hash:
            payload["observedScopeHash"] = self.observed_scope_hash
        return payload


@dataclass(frozen=True, slots=True)
class ScopeBindingValidation:
    """Small result object for callers that need a blocked, not thrown, path."""

    ok: bool
    code: str = ""
    detail: str = ""
    scope_hash: str = ""
    field: str = ""

    @property
    def blocked(self) -> bool:
        return not self.ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "blocked": self.blocked,
            "code": self.code,
            "detail": self.detail,
            "scopeHash": self.scope_hash,
            "field": self.field,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


def _as_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
        except Exception:  # noqa: BLE001 - adapter must fail closed below
            return None
        if isinstance(result, Mapping):
            return dict(result)
    return None


def discussion_scope_identity(scope: Any) -> dict[str, Any]:
    """Return the canonical identity from the single scope authority."""

    raw = _as_mapping(scope)
    if raw is None:
        raise ScopeBindingMismatch("discussion scope must be an object", field="scope")
    if isinstance(raw.get("discussionScope"), Mapping):
        raw = dict(raw["discussionScope"])
    elif isinstance(raw.get("scope"), Mapping) and not raw.get("kind"):
        raw = dict(raw["scope"])
    raw = {
        _SCOPE_FIELD_ALIASES.get(str(key), str(key)): value
        for key, value in raw.items()
        if str(key) not in {"scopeHash", "scope_hash", "agentId", "agent_id"}
    }
    try:
        return parse_discussion_scope(raw).to_dict()
    except ContractValidationError as exc:
        raise ScopeBindingMismatch(str(exc), field="scope") from exc


def discussion_scope_hash(scope: Any) -> str:
    """Return the stable hash from the canonical T1 authority."""

    return parse_discussion_scope(discussion_scope_identity(scope)).scope_hash


def canonical_discussion_scope(scope: Any, *, require_hash: bool = False) -> dict[str, Any]:
    """Normalize a scope and verify its supplied ``scopeHash`` when present."""

    raw = _as_mapping(scope)
    if raw is None:
        raise ScopeBindingMismatch("discussion scope must be an object", field="scope")
    supplied_value = raw.get("scopeHash") or raw.get("scope_hash") or ""
    nested_scope = raw.get("discussionScope")
    if not supplied_value and isinstance(nested_scope, Mapping):
        supplied_value = nested_scope.get("scopeHash") or nested_scope.get("scope_hash") or ""
    supplied = str(supplied_value).strip().lower()
    identity = discussion_scope_identity(raw)
    parsed = parse_discussion_scope(identity)
    expected = parsed.scope_hash
    if supplied and supplied != expected:
        raise ScopeBindingMismatch(
            "discussion scope hash does not match its identity",
            field="scopeHash",
            expected_scope_hash=expected,
            observed_scope_hash=supplied,
        )
    if require_hash and not supplied:
        raise ScopeBindingMismatch("discussion scope hash is missing", field="scopeHash")
    return {**parsed.to_dict(), "scopeHash": expected}


def scope_without_agent_id(scope: Any) -> dict[str, Any]:
    """Normalize a participant scope after removing its per-agent identity."""

    raw = _as_mapping(scope)
    if raw is None:
        raise ScopeBindingMismatch("participant scope must be an object", field="scope")
    if isinstance(raw.get("discussionScope"), Mapping):
        raw = dict(raw["discussionScope"])
    else:
        raw = dict(raw)
    raw.pop("agentId", None)
    raw.pop("agent_id", None)
    raw.pop("scopeHash", None)
    raw.pop("scope_hash", None)
    return canonical_discussion_scope(raw)


def _safe_ref(value: Any, *, field: str) -> Any:
    """Copy only durable reference metadata; never persist chat正文."""

    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ScopeBindingMismatch(f"{field} is empty", field=field)
        return normalized
    mapping = _as_mapping(value)
    if mapping is None:
        raise ScopeBindingMismatch(f"{field} must be a reference", field=field)
    cleaned: dict[str, Any] = {}
    for key, item in mapping.items():
        normalized_key = str(key)
        if normalized_key in _CHAT_CONTENT_KEYS:
            continue
        if isinstance(item, Mapping):
            cleaned[normalized_key] = _safe_ref(item, field=f"{field}.{normalized_key}")
        elif isinstance(item, (list, tuple)):
            cleaned[normalized_key] = [
                _safe_ref(entry, field=f"{field}.{normalized_key}")
                if isinstance(entry, (Mapping, str))
                else copy.deepcopy(entry)
                for entry in item
            ]
        else:
            cleaned[normalized_key] = copy.deepcopy(item)
    if not cleaned:
        raise ScopeBindingMismatch(f"{field} has no durable reference", field=field)
    return cleaned


def build_checkpoint_binding_payload(
    scope: Any,
    *,
    scope_ref: Any = None,
    room_ref: Any = None,
    meeting_ref: Any = None,
    business_checkpoint_ref: Any = None,
    participant_binding_refs: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Build the metadata-only binding stored in a workflow checkpoint."""

    # The hash is derived here so producers cannot accidentally persist a
    # caller-supplied hash for a different identity.  If a supplied hash is
    # present ``canonical_discussion_scope`` still verifies it.
    normalized_scope = canonical_discussion_scope(scope, require_hash=False)
    scope_identity = {
        key: value for key, value in normalized_scope.items() if key != "scopeHash"
    }
    payload: dict[str, Any] = {
        "scope": dict(normalized_scope),
        "scopeRef": _safe_ref(scope_ref, field="scopeRef") if scope_ref is not None else scope_identity,
        "scopeHash": normalized_scope["scopeHash"],
    }
    for key, value in (
        ("roomRef", room_ref),
        ("meetingRef", meeting_ref),
        ("businessCheckpointRef", business_checkpoint_ref),
    ):
        if value is not None:
            payload[key] = _safe_ref(value, field=key)
    if participant_binding_refs is not None:
        refs = list(participant_binding_refs)
        payload["participantBindingRefs"] = [
            _safe_ref(item, field=f"participantBindingRefs[{index}]")
            for index, item in enumerate(refs)
        ]
    return payload


def _extract_scope(value: Any, *, field: str) -> dict[str, Any] | None:
    raw = _as_mapping(value)
    if raw is None:
        return None
    for key in ("discussionScope", "scope"):
        candidate = raw.get(key)
        if isinstance(candidate, Mapping) or callable(getattr(candidate, "to_dict", None)):
            try:
                return canonical_discussion_scope(candidate, require_hash=False)
            except ScopeBindingMismatch as exc:
                raise ScopeBindingMismatch(
                    f"{field} has invalid discussion scope: {exc}", field=field
                ) from exc
    # A room config is frequently passed as the object itself.
    config = raw.get("config")
    if isinstance(config, Mapping):
        return _extract_scope(config, field=f"{field}.config")
    if raw.get("kind") in DISCUSSION_SCOPE_KINDS:
        return canonical_discussion_scope(raw, require_hash=False)
    return None


def _compare_scope(left: Any, right: Any, *, field: str) -> str:
    left_scope = canonical_discussion_scope(left, require_hash=True)
    right_scope = canonical_discussion_scope(right, require_hash=True)
    if left_scope["scopeHash"] != right_scope["scopeHash"] or {
        key: left_scope.get(key)
        for key in left_scope
        if key != "scopeHash"
    } != {
        key: right_scope.get(key)
        for key in right_scope
        if key != "scopeHash"
    }:
        raise ScopeBindingMismatch(
            f"{field} scope does not match workflow scope",
            field=field,
            expected_scope_hash=right_scope["scopeHash"],
            observed_scope_hash=left_scope["scopeHash"],
        )
    return str(right_scope["scopeHash"])


def assert_scope_bindings_match(
    *,
    workflow_checkpoint: Any,
    business_checkpoint: Any,
    meeting: Any,
    room: Any,
    participant_sessions: Iterable[Any],
    expected_scope: Any = None,
) -> dict[str, Any]:
    """Validate the five durable scope authorities before graph advancement."""

    workflow_scope = _extract_scope(workflow_checkpoint, field="workflowCheckpoint")
    if workflow_scope is None:
        raise ScopeBindingMismatch(
            "workflow checkpoint scope is missing", field="workflowCheckpoint.scope"
        )
    expected = (
        canonical_discussion_scope(expected_scope, require_hash=True)
        if expected_scope is not None
        else workflow_scope
    )
    _compare_scope(workflow_scope, expected, field="workflowCheckpoint")
    for field, source in (
        ("businessCheckpoint", business_checkpoint),
        ("meeting", meeting),
        ("room", room),
    ):
        scope = _extract_scope(source, field=field)
        if scope is None:
            raise ScopeBindingMismatch(f"{field} scope is missing", field=f"{field}.scope")
        _compare_scope(scope, expected, field=field)
    sessions = list(participant_sessions or [])
    if not sessions:
        raise ScopeBindingMismatch(
            "participant Child Session bindings are missing",
            field="participantSessions",
        )
    for index, session in enumerate(sessions):
        raw_session = _as_mapping(session) or {}
        if str(raw_session.get("directSessionId") or raw_session.get("direct_session_id") or "").strip():
            raise ScopeBindingMismatch(
                "formal challenge checkpoint cannot bind a direct Session",
                field=f"participantSessions[{index}].directSessionId",
            )
        child_scope = _extract_scope(session, field=f"participantSessions[{index}]")
        if child_scope is None:
            raise ScopeBindingMismatch(
                "participant Child Session scope is missing",
                field=f"participantSessions[{index}].scope",
            )
        # A participant scope may carry agentId and a hash over that physical
        # session.  The discussion authority is the same after removing it.
        _compare_scope(scope_without_agent_id(child_scope), expected, field=f"participantSessions[{index}]")
    return {
        "ok": True,
        "code": "",
        "scope": expected,
        "scopeHash": expected["scopeHash"],
        "validated": (
            "workflowCheckpoint",
            "businessCheckpoint",
            "meeting",
            "room",
            "participantSessions",
        ),
    }


def validate_scope_bindings(**kwargs: Any) -> ScopeBindingValidation:
    """Non-throwing facade for routes/workers that must mark a run blocked."""

    try:
        result = assert_scope_bindings_match(**kwargs)
    except ScopeBindingMismatch as exc:
        return ScopeBindingValidation(
            ok=False,
            code=exc.code,
            detail=exc.detail,
            scope_hash=exc.expected_scope_hash,
            field=exc.field,
        )
    return ScopeBindingValidation(
        ok=True,
        scope_hash=str(result.get("scopeHash") or ""),
    )


# Explicit aliases make the contract easy to discover without coupling the
# checkpoint lane to one particular T1 module name.
validate_five_way_scope_binding = validate_scope_bindings
assert_five_way_scope_binding = assert_scope_bindings_match


def default_checkpoint_path() -> Path:
    override = os.environ.get("VIBELUTION_RESEARCH_WORKFLOW_CHECKPOINT_PATH", "").strip()
    if override:
        return Path(override)
    data_root = os.environ.get("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", "").strip()
    if data_root:
        return Path(data_root) / "checkpoints.sqlite"
    return resolve_project_data_home(PROJECT_ROOT) / "research_workflows" / "checkpoints.sqlite"


def ensure_checkpoint_parent(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# Fixed per-connection pragma policy for the checkpoint SQLite store.  After
# parallelization the pump worker and HTTP threads open this store
# concurrently through short-lived, per-call connections, so every handle
# must run WAL with a busy timeout matching the workflow ledger policy
# (core/research/workflow/ledger/runtime.py) instead of the sqlite3 module
# default.  ``journal_size_limit`` only bounds WAL truncation after
# auto-checkpoints; it never changes the checkpoint schema.
CHECKPOINT_BUSY_TIMEOUT_MS = 5000
CHECKPOINT_WAL_JOURNAL_SIZE_LIMIT_BYTES = 67108864


def _connect_checkpoint_sqlite(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Single connection factory for every checkpoint SQLite handle.

    Connections are short-lived and owned by the opening call stack; none of
    them is ever shared across threads.  The pragma sequence is fixed so a
    connection cannot silently fall back to delete-journal defaults.
    """

    connection = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    try:
        # busy_timeout first so the pragma writes below wait on a competing
        # writer instead of failing fast.
        connection.execute(f"PRAGMA busy_timeout = {CHECKPOINT_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute(
            f"PRAGMA journal_size_limit = {CHECKPOINT_WAL_JOURNAL_SIZE_LIMIT_BYTES}"
        )
        connection.execute("PRAGMA foreign_keys = ON")
        if read_only:
            connection.execute("PRAGMA query_only = ON")
        return connection
    except sqlite3.Error:
        connection.close()
        raise


def open_sqlite_checkpointer(path: Path | str | None = None) -> Any:
    """Return a context-manager SqliteSaver (use as `with open_sqlite_checkpointer() as cp:`).

    The connection is created by :func:`_connect_checkpoint_sqlite` so the
    LangGraph saver never opens an unconfigured (delete-journal, no
    busy-timeout) handle behind our back.
    """

    target = ensure_checkpoint_parent(Path(path) if path else default_checkpoint_path())
    connection = _connect_checkpoint_sqlite(target, read_only=False)

    @contextmanager
    def _saver() -> Iterator[Any]:
        try:
            yield SqliteSaver(connection)
        finally:
            connection.close()

    return _saver()


def assert_not_memory_saver(checkpointer: Any) -> None:
    name = type(checkpointer).__name__
    if name in {"MemorySaver", "InMemorySaver"}:
        raise RuntimeError("InMemorySaver is not allowed as delivery checkpointer (ADR 0006).")


# ---------------------------------------------------------------------------
# Governed Challenge Cup reset port
# ---------------------------------------------------------------------------
#
# The reset service owns the destructive workflow, while this module owns the
# LangGraph checkpoint store.  Do not expose the SQLite path as an inventory
# object and do not let callers delete a thread by id alone: a checkpoint has
# no team column, so every row must be checked against the caller's durable
# workflow/run scope authority first.  Stage snapshots are kept behind an
# opaque token so a parent reset response can never accidentally include the
# serialized graph state (which may contain private prompt-adjacent values).

CHECKPOINT_RESET_PORT_SCHEMA_VERSION = 1
CHECKPOINT_RESET_PORT_KIND = "challenge_cup_checkpoint_reset"
CHECKPOINT_FULL_PURGE_PORT_KIND = "challenge_cup_checkpoint_full_purge"


class CheckpointResetPortError(ValueError):
    """Fail-closed error raised by the managed checkpoint reset port."""

    code = "checkpoint_reset_port_error"

    def __init__(self, detail: str, *, code: str | None = None) -> None:
        self.detail = str(detail or self.code).strip()
        if code:
            self.code = str(code).strip() or self.code
        super().__init__(self.detail)


_CHECKPOINT_RESET_LOCK = RLock()
_CHECKPOINT_RESET_STAGES: dict[str, dict[str, Any]] = {}


def _reset_text(value: Any, *, field: str, required: bool = True) -> str:
    normalized = str(value or "").strip()
    if required and not normalized:
        raise CheckpointResetPortError(
            f"{field} is required", code="checkpoint_scope_missing"
        )
    return normalized


def _reset_json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reset_path(path: Path | str | None) -> Path:
    resolved = Path(path) if path is not None else default_checkpoint_path()
    resolved = resolved.expanduser().resolve(strict=False)
    if resolved.exists() and (resolved.is_symlink() or not resolved.is_file()):
        raise CheckpointResetPortError(
            "checkpoint store path is not a regular file", code="checkpoint_store_unsafe"
        )
    return resolved


def _reset_authority_entries(authority: Any) -> dict[str, dict[str, Any]]:
    """Normalize a run/thread scope authority without accepting implicit scope."""

    if authority is None:
        raise CheckpointResetPortError(
            "checkpoint scope authority is required", code="checkpoint_scope_missing"
        )
    source: Any = authority
    if isinstance(source, Mapping):
        for key in ("threads", "runs", "records", "scopes"):
            if key in source:
                source = source[key]
                break
        else:
            # A single scope record is useful for one-thread fixtures; wrap it
            # so it still has to name its thread/run explicitly.
            if any(key in source for key in ("teamId", "team_id", "runId", "run_id")):
                source = [source]
    if isinstance(source, Mapping):
        iterable = list(source.items())
    elif isinstance(source, (list, tuple)):
        iterable = [(None, item) for item in source]
    else:
        raise CheckpointResetPortError(
            "checkpoint scope authority must be a mapping or list",
            code="checkpoint_scope_invalid",
        )

    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_value in iterable:
        if not isinstance(raw_value, Mapping):
            raise CheckpointResetPortError(
                "checkpoint scope authority contains a non-object entry",
                code="checkpoint_scope_invalid",
            )
        thread_id = _reset_text(
            raw_value.get("threadId")
            or raw_value.get("thread_id")
            or (raw_key if raw_key is not None else ""),
            field="threadId",
        )
        team_id = _reset_text(
            raw_value.get("teamId") or raw_value.get("team_id"),
            field="teamId",
        )
        run_id = _reset_text(
            raw_value.get("runId") or raw_value.get("run_id") or thread_id,
            field="runId",
        )
        if run_id != thread_id:
            raise CheckpointResetPortError(
                "checkpoint run/thread identity mismatch",
                code="checkpoint_scope_mismatch",
            )
        scope = raw_value.get("scope")
        scope = dict(scope) if isinstance(scope, Mapping) else {}
        scope_hash = _reset_text(
            raw_value.get("scopeHash")
            or raw_value.get("scope_hash")
            or scope.get("scopeHash")
            or scope.get("scope_hash"),
            field="scopeHash",
            required=False,
        ).lower()
        if scope_hash and (
            len(scope_hash) != 64
            or any(char not in "0123456789abcdef" for char in scope_hash)
        ):
            raise CheckpointResetPortError(
                "checkpoint scopeHash must be a lowercase sha256",
                code="checkpoint_scope_invalid",
            )
        item = {
            "threadId": thread_id,
            "runId": run_id,
            "teamId": team_id,
            "scopeHash": scope_hash,
        }
        for key, aliases in (
            ("questionId", ("questionId", "question_id")),
            ("projectId", ("projectId", "project_id", "researchProjectId")),
        ):
            value = _reset_text(
                next((raw_value.get(alias) for alias in aliases if raw_value.get(alias)), ""),
                field=key,
                required=False,
            )
            if value:
                item[key] = value
        previous = normalized.get(thread_id)
        if previous is not None and previous != item:
            raise CheckpointResetPortError(
                "checkpoint scope authority contains conflicting thread entries",
                code="checkpoint_scope_mismatch",
            )
        normalized[thread_id] = item
    if not normalized:
        raise CheckpointResetPortError(
            "checkpoint scope authority is empty", code="checkpoint_scope_missing"
        )
    return dict(sorted(normalized.items()))


def _checkpoint_blob(value: Any) -> dict[str, str]:
    if value is None:
        return {"kind": "null", "value": ""}
    if isinstance(value, bytes):
        return {"kind": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, str):
        return {"kind": "text", "value": value}
    try:
        raw = bytes(value)
    except (TypeError, ValueError) as exc:
        raise CheckpointResetPortError(
            "checkpoint SQLite blob has an unsupported type",
            code="checkpoint_store_corrupt",
        ) from exc
    return {"kind": "bytes", "value": base64.b64encode(raw).decode("ascii")}


def _checkpoint_blob_value(value: Mapping[str, Any]) -> Any:
    kind = str(value.get("kind") or "")
    if kind == "null":
        return None
    if kind == "text":
        return str(value.get("value") or "")
    if kind == "bytes":
        try:
            return base64.b64decode(str(value.get("value") or ""), validate=True)
        except (ValueError, TypeError) as exc:
            raise CheckpointResetPortError(
                "checkpoint staged blob is invalid", code="checkpoint_stage_corrupt"
            ) from exc
    raise CheckpointResetPortError(
        "checkpoint staged blob kind is invalid", code="checkpoint_stage_corrupt"
    )


def _checkpoint_row_hash(row: Mapping[str, Any]) -> str:
    return _reset_json_hash(
        {
            "threadId": row["threadId"],
            "checkpointNs": row["checkpointNs"],
            "checkpointId": row["checkpointId"],
            "parentCheckpointId": row.get("parentCheckpointId"),
            "type": row.get("type"),
            "checkpoint": row.get("checkpoint"),
            "metadata": row.get("metadata"),
            "writes": row.get("writes") or [],
        }
    )


def _checkpoint_row_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("threadId") or ""),
        str(row.get("checkpointNs") or ""),
        str(row.get("checkpointId") or ""),
    )


def _checkpoint_state_context(
    checkpoint: Any,
    metadata: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    if not isinstance(checkpoint, Mapping):
        raise CheckpointResetPortError(
            "checkpoint payload is not an object", code="checkpoint_store_corrupt"
        )
    channel_values = checkpoint.get("channel_values")
    state = channel_values if isinstance(channel_values, Mapping) else checkpoint
    observed_team = str(state.get("team_id") or state.get("teamId") or "").strip()
    observed_run = str(state.get("run_id") or state.get("runId") or "").strip()
    expected_team = str(expected.get("teamId") or "")
    expected_run = str(expected.get("runId") or "")
    if observed_team and observed_team != expected_team:
        raise CheckpointResetPortError(
            "checkpoint state team binding does not match authority",
            code="checkpoint_scope_mismatch",
        )
    if observed_run and observed_run != expected_run:
        raise CheckpointResetPortError(
            "checkpoint state run binding does not match authority",
            code="checkpoint_scope_mismatch",
        )
    discussion_scope = state.get("discussion_scope") or state.get("discussionScope")
    observed_hash = str(
        state.get("discussion_scope_hash")
        or state.get("scopeHash")
        or (discussion_scope.get("scopeHash") if isinstance(discussion_scope, Mapping) else "")
        or ""
    ).strip().lower()
    expected_hash = str(expected.get("scopeHash") or "").strip().lower()
    if expected_hash and observed_hash != expected_hash:
        raise CheckpointResetPortError(
            "checkpoint discussion scope does not match authority",
            code="checkpoint_scope_mismatch",
        )
    # Metadata is part of the durable row and must be parseable.  We only
    # inspect stable identity fields; prompt/transcript values never leave the
    # store through the list port.
    metadata_team = str(metadata.get("teamId") or metadata.get("team_id") or "").strip()
    if metadata_team and metadata_team != expected_team:
        raise CheckpointResetPortError(
            "checkpoint metadata team binding does not match authority",
            code="checkpoint_scope_mismatch",
        )


def _checkpoint_rows_from_connection(
    connection: sqlite3.Connection,
    authority: Mapping[str, Mapping[str, Any]],
    *,
    include_non_target: bool = True,
) -> list[dict[str, Any]]:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "checkpoints" not in tables or "writes" not in tables:
        if tables:
            raise CheckpointResetPortError(
                "checkpoint store schema is incomplete", code="checkpoint_store_corrupt"
            )
        return []
    checkpoint_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(checkpoints)").fetchall()
    }
    write_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(writes)").fetchall()
    }
    required_checkpoints = {
        "thread_id",
        "checkpoint_ns",
        "checkpoint_id",
        "parent_checkpoint_id",
        "type",
        "checkpoint",
        "metadata",
    }
    required_writes = {
        "thread_id",
        "checkpoint_ns",
        "checkpoint_id",
        "task_id",
        "idx",
        "channel",
        "type",
        "value",
    }
    if not required_checkpoints <= checkpoint_columns or not required_writes <= write_columns:
        raise CheckpointResetPortError(
            "checkpoint store schema is unsupported", code="checkpoint_store_corrupt"
        )
    rows = connection.execute(
        "SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, "
        "type, checkpoint, metadata FROM checkpoints "
        "ORDER BY thread_id, checkpoint_ns, checkpoint_id"
    ).fetchall()
    write_rows = connection.execute(
        "SELECT thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value "
        "FROM writes ORDER BY thread_id, checkpoint_ns, checkpoint_id, task_id, idx"
    ).fetchall()
    writes_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for raw in write_rows:
        key = (str(raw[0]), str(raw[1]), str(raw[2]))
        writes_by_key.setdefault(key, []).append(
            {
                "taskId": str(raw[3]),
                "idx": int(raw[4]),
                "channel": str(raw[5]),
                "type": raw[6],
                "value": _checkpoint_blob(raw[7]),
            }
        )
    checkpoint_keys = {(str(raw[0]), str(raw[1]), str(raw[2])) for raw in rows}
    orphan_keys = sorted(set(writes_by_key) - checkpoint_keys)
    if orphan_keys:
        raise CheckpointResetPortError(
            "checkpoint store contains orphan writes", code="checkpoint_store_corrupt"
        )
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    serializer = JsonPlusSerializer()
    result: list[dict[str, Any]] = []
    for raw in rows:
        thread_id, checkpoint_ns, checkpoint_id = (
            str(raw[0]),
            str(raw[1]),
            str(raw[2]),
        )
        expected = authority.get(thread_id)
        if expected is None:
            raise CheckpointResetPortError(
                f"checkpoint thread {thread_id} has no scope authority",
                code="checkpoint_scope_missing",
            )
        try:
            decoded = serializer.loads_typed((raw[4], raw[5]))
        except Exception as exc:  # noqa: BLE001 - corrupt state must block reset
            raise CheckpointResetPortError(
                f"checkpoint {checkpoint_id} cannot be decoded",
                code="checkpoint_store_corrupt",
            ) from exc
        metadata_raw = raw[6]
        if metadata_raw is None:
            metadata: dict[str, Any] = {}
        else:
            try:
                metadata_value = (
                    metadata_raw.decode("utf-8")
                    if isinstance(metadata_raw, bytes)
                    else str(metadata_raw)
                )
                parsed = json.loads(metadata_value)
            except (UnicodeError, TypeError, ValueError) as exc:
                raise CheckpointResetPortError(
                    f"checkpoint {checkpoint_id} metadata is corrupt",
                    code="checkpoint_store_corrupt",
                ) from exc
            if not isinstance(parsed, Mapping):
                raise CheckpointResetPortError(
                    f"checkpoint {checkpoint_id} metadata is not an object",
                    code="checkpoint_store_corrupt",
                )
            metadata = dict(parsed)
        _checkpoint_state_context(decoded, metadata, expected)
        row = {
            "threadId": thread_id,
            "checkpointNs": checkpoint_ns,
            "checkpointId": checkpoint_id,
            "parentCheckpointId": raw[3],
            "type": raw[4],
            "checkpoint": _checkpoint_blob(raw[5]),
            "metadata": _checkpoint_blob(raw[6]),
            "writes": writes_by_key.get((thread_id, checkpoint_ns, checkpoint_id), []),
            "teamId": expected["teamId"],
            "runId": expected["runId"],
            "scopeHash": expected.get("scopeHash", ""),
        }
        row["rowHash"] = _checkpoint_row_hash(row)
        if include_non_target:
            result.append(row)
    return result


def _checkpoint_open_connection(path: Path, *, read_only: bool) -> sqlite3.Connection:
    if not path.is_file():
        raise CheckpointResetPortError(
            "checkpoint store is not available", code="checkpoint_store_missing"
        )
    try:
        return _connect_checkpoint_sqlite(path, read_only=read_only)
    except sqlite3.Error as exc:
        raise CheckpointResetPortError(
            "checkpoint store cannot be opened", code="checkpoint_store_unavailable"
        ) from exc


def _checkpoint_full_purge_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    """Return a payload-free fingerprint for an operator-authorized full purge.

    This intentionally does not decode checkpoint state or infer ownership.
    It is reserved for clearing a store that an operator has explicitly
    classified as disposable, including rows that cannot satisfy the normal
    team-scoped authority contract. Blob values contribute only their digest
    to the preflight fingerprint and are never returned or retained.
    """

    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    required_tables = {"checkpoints", "writes"}
    if not required_tables <= tables:
        raise CheckpointResetPortError(
            "checkpoint store schema is incomplete", code="checkpoint_store_corrupt"
        )

    checkpoint_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(checkpoints)").fetchall()
    }
    write_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(writes)").fetchall()
    }
    required_checkpoints = {
        "thread_id",
        "checkpoint_ns",
        "checkpoint_id",
        "parent_checkpoint_id",
        "type",
        "checkpoint",
        "metadata",
    }
    required_writes = {
        "thread_id",
        "checkpoint_ns",
        "checkpoint_id",
        "task_id",
        "idx",
        "channel",
        "type",
        "value",
    }
    if not required_checkpoints <= checkpoint_columns or not required_writes <= write_columns:
        raise CheckpointResetPortError(
            "checkpoint store schema is unsupported", code="checkpoint_store_corrupt"
        )

    checkpoint_rows = connection.execute(
        "SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, "
        "type, checkpoint, metadata FROM checkpoints "
        "ORDER BY thread_id, checkpoint_ns, checkpoint_id"
    ).fetchall()
    write_rows = connection.execute(
        "SELECT thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value "
        "FROM writes ORDER BY thread_id, checkpoint_ns, checkpoint_id, task_id, idx"
    ).fetchall()
    checkpoints = [
        {
            "threadId": str(row[0]),
            "checkpointNs": str(row[1]),
            "checkpointId": str(row[2]),
            "parentCheckpointId": row[3],
            "type": row[4],
            "checkpointSha256": _reset_json_hash(_checkpoint_blob(row[5])),
            "metadataSha256": _reset_json_hash(_checkpoint_blob(row[6])),
        }
        for row in checkpoint_rows
    ]
    writes = [
        {
            "threadId": str(row[0]),
            "checkpointNs": str(row[1]),
            "checkpointId": str(row[2]),
            "taskId": str(row[3]),
            "idx": int(row[4]),
            "channel": str(row[5]),
            "type": row[6],
            "valueSha256": _reset_json_hash(_checkpoint_blob(row[7])),
        }
        for row in write_rows
    ]
    return {
        "checkpointCount": len(checkpoints),
        "writeCount": len(writes),
        "threadCount": len({row["threadId"] for row in checkpoints}),
        "storeFingerprint": _reset_json_hash(
            {"checkpoints": checkpoints, "writes": writes}
        ),
    }


def prepare_operator_checkpoint_full_purge(
    reset_id: str,
    *,
    checkpoint_path: Path | str | None = None,
) -> dict[str, Any]:
    """Capture an exact, payload-free preflight for a full checkpoint purge.

    This is deliberately separate from the normal scoped reset port. It may
    only be used when an operator has explicitly authorized discarding every
    checkpoint in this one store; the returned preflight must be presented
    unchanged to :func:`purge_operator_checkpoint_full_purge`.
    """

    normalized_reset_id = _reset_text(reset_id, field="resetId")
    path = _reset_path(checkpoint_path)
    if not path.exists():
        snapshot = {
            "checkpointCount": 0,
            "writeCount": 0,
            "threadCount": 0,
            "storeFingerprint": _reset_json_hash({"checkpoints": [], "writes": []}),
        }
        store_missing = True
    else:
        connection = _checkpoint_open_connection(path, read_only=True)
        try:
            snapshot = _checkpoint_full_purge_snapshot(connection)
        finally:
            connection.close()
        store_missing = False
    return {
        "schemaVersion": CHECKPOINT_RESET_PORT_SCHEMA_VERSION,
        "kind": CHECKPOINT_FULL_PURGE_PORT_KIND,
        "resetId": normalized_reset_id,
        "checkpointPath": str(path),
        "storeMissing": store_missing,
        **snapshot,
    }


def purge_operator_checkpoint_full_purge(
    preflight: Mapping[str, Any],
    *,
    checkpoint_path: Path | str | None = None,
    reset_id: str | None = None,
) -> dict[str, Any]:
    """Atomically clear every checkpoint and write captured by a preflight."""

    if not isinstance(preflight, Mapping):
        raise CheckpointResetPortError(
            "checkpoint full purge preflight must be an object",
            code="checkpoint_full_purge_invalid",
        )
    if (
        preflight.get("schemaVersion") != CHECKPOINT_RESET_PORT_SCHEMA_VERSION
        or preflight.get("kind") != CHECKPOINT_FULL_PURGE_PORT_KIND
    ):
        raise CheckpointResetPortError(
            "checkpoint full purge preflight schema is invalid",
            code="checkpoint_full_purge_invalid",
        )
    expected_reset_id = _reset_text(preflight.get("resetId"), field="resetId")
    if reset_id is not None and _reset_text(reset_id, field="resetId") != expected_reset_id:
        raise CheckpointResetPortError(
            "checkpoint full purge resetId does not match preflight",
            code="checkpoint_full_purge_invalid",
        )
    path = _reset_path(checkpoint_path or preflight.get("checkpointPath"))
    if str(path) != str(preflight.get("checkpointPath") or ""):
        raise CheckpointResetPortError(
            "checkpoint full purge path does not match preflight",
            code="checkpoint_full_purge_invalid",
        )
    expected = {
        key: preflight.get(key)
        for key in ("checkpointCount", "writeCount", "threadCount", "storeFingerprint")
    }
    if (
        not isinstance(expected["checkpointCount"], int)
        or not isinstance(expected["writeCount"], int)
        or not isinstance(expected["threadCount"], int)
        or not isinstance(expected["storeFingerprint"], str)
    ):
        raise CheckpointResetPortError(
            "checkpoint full purge preflight is incomplete",
            code="checkpoint_full_purge_invalid",
        )
    expected_missing = bool(preflight.get("storeMissing"))
    if not path.exists():
        if expected_missing and expected["checkpointCount"] == expected["writeCount"] == 0:
            return {
                "ok": True,
                "kind": CHECKPOINT_FULL_PURGE_PORT_KIND,
                "resetId": expected_reset_id,
                "checkpointCount": 0,
                "writeCount": 0,
                "deletedCheckpoints": 0,
                "deletedWrites": 0,
                "alreadyAbsent": True,
            }
        raise CheckpointResetPortError(
            "checkpoint store changed after full purge preflight",
            code="checkpoint_full_purge_stale",
        )
    if expected_missing:
        raise CheckpointResetPortError(
            "checkpoint store appeared after full purge preflight",
            code="checkpoint_full_purge_stale",
        )

    connection = _checkpoint_open_connection(path, read_only=False)
    try:
        connection.execute("BEGIN IMMEDIATE")
        observed = _checkpoint_full_purge_snapshot(connection)
        if observed != expected:
            raise CheckpointResetPortError(
                "checkpoint store changed after full purge preflight",
                code="checkpoint_full_purge_stale",
            )
        deleted_writes = int(connection.execute("DELETE FROM writes").rowcount or 0)
        deleted_checkpoints = int(connection.execute("DELETE FROM checkpoints").rowcount or 0)
        remaining = _checkpoint_full_purge_snapshot(connection)
        if remaining["checkpointCount"] or remaining["writeCount"]:
            raise CheckpointResetPortError(
                "checkpoint full purge verification failed",
                code="checkpoint_full_purge_failed",
            )
        connection.execute("COMMIT")
    except CheckpointResetPortError:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    except sqlite3.Error as exc:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise CheckpointResetPortError(
            "checkpoint full purge failed", code="checkpoint_full_purge_failed"
        ) from exc
    finally:
        connection.close()
    return {
        "ok": True,
        "kind": CHECKPOINT_FULL_PURGE_PORT_KIND,
        "resetId": expected_reset_id,
        "checkpointCount": expected["checkpointCount"],
        "writeCount": expected["writeCount"],
        "deletedCheckpoints": deleted_checkpoints,
        "deletedWrites": deleted_writes,
        "alreadyAbsent": False,
    }


def _checkpoint_store_rows(
    path: Path,
    authority: Mapping[str, Mapping[str, Any]],
    *,
    read_only: bool,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    connection = _checkpoint_open_connection(path, read_only=read_only)
    try:
        return _checkpoint_rows_from_connection(connection, authority)
    finally:
        connection.close()


def checkpoint_store_has_rows(
    checkpoint_path: Path | str | None = None,
) -> bool:
    """Return whether a managed checkpoint store has persisted checkpoint rows.

    This small presence probe deliberately does not infer team ownership.  It
    lets callers distinguish an initialized-but-empty SQLite file from one
    that contains rows but lacks the scope authority required to classify
    them.  Schema/read failures remain errors so reset preview stays
    fail-closed.
    """

    path = _reset_path(checkpoint_path)
    if not path.exists():
        return False
    connection = _checkpoint_open_connection(path, read_only=True)
    try:
        return connection.execute("SELECT 1 FROM checkpoints LIMIT 1").fetchone() is not None
    except sqlite3.Error as exc:
        raise CheckpointResetPortError(
            "checkpoint store presence cannot be determined",
            code="checkpoint_store_unavailable",
        ) from exc
    finally:
        connection.close()


def list_checkpoint_thread_ids(
    checkpoint_path: Path | str | None = None,
) -> list[str]:
    """Return only persisted checkpoint thread identities for authority joins.

    This is intentionally narrower than the readback API: callers receive no
    checkpoint payload, metadata, writes, or inferred team binding.  A reset
    may use these identities only when another canonical owner proves the
    matching thread scope.
    """

    path = _reset_path(checkpoint_path)
    if not path.exists():
        return []
    connection = _checkpoint_open_connection(path, read_only=True)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "checkpoints" not in tables:
            if tables:
                raise CheckpointResetPortError(
                    "checkpoint store schema is incomplete", code="checkpoint_store_corrupt"
                )
            return []
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(checkpoints)").fetchall()
        }
        if "thread_id" not in columns:
            raise CheckpointResetPortError(
                "checkpoint store schema is unsupported", code="checkpoint_store_corrupt"
            )
        return [
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
            ).fetchall()
            if str(row[0])
        ]
    except sqlite3.Error as exc:
        raise CheckpointResetPortError(
            "checkpoint thread identities cannot be read",
            code="checkpoint_store_unavailable",
        ) from exc
    finally:
        connection.close()


def _checkpoint_target_rows(
    rows: Iterable[Mapping[str, Any]], team_id: str
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if str(row.get("teamId") or "").strip() == team_id
    ]


def _checkpoint_stage_summary(stage: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: stage[key]
        for key in (
            "schemaVersion",
            "kind",
            "stageId",
            "resetId",
            "teamId",
            "checkpointPath",
            "authorityHash",
            "recordCount",
            "threadCount",
            "storeFingerprint",
            "recordIds",
        )
        if key in stage
    }


def list_team_scoped_checkpoints(
    team_id: str,
    *,
    checkpoint_path: Path | str | None = None,
    scope_authority: Any = None,
) -> list[dict[str, Any]]:
    """List compact checkpoint records after proving every row's team scope."""

    normalized_team = _reset_text(team_id, field="teamId")
    authority = _reset_authority_entries(scope_authority)
    path = _reset_path(checkpoint_path)
    rows = _checkpoint_store_rows(path, authority, read_only=True)
    return [
        {
            "id": f"{row['threadId']}:{row['checkpointNs']}:{row['checkpointId']}",
            "threadId": row["threadId"],
            "runId": row["runId"],
            "checkpointNs": row["checkpointNs"],
            "checkpointId": row["checkpointId"],
            "parentCheckpointId": row.get("parentCheckpointId"),
            "teamId": row["teamId"],
            "scopeHash": row.get("scopeHash", ""),
            "rowHash": row["rowHash"],
        }
        for row in _checkpoint_target_rows(rows, normalized_team)
    ]


def prepare_checkpoint_reset_stage(
    team_id: str,
    reset_id: str,
    *,
    checkpoint_path: Path | str | None = None,
    scope_authority: Any = None,
) -> dict[str, Any]:
    """Capture exact team rows behind an opaque, reset-bound stage token."""

    normalized_team = _reset_text(team_id, field="teamId")
    normalized_reset = _reset_text(reset_id, field="resetId")
    authority = _reset_authority_entries(scope_authority)
    path = _reset_path(checkpoint_path)
    rows = _checkpoint_store_rows(path, authority, read_only=True)
    target_rows = _checkpoint_target_rows(rows, normalized_team)
    target_rows = sorted(target_rows, key=_checkpoint_row_key)
    store_fingerprint = _reset_json_hash(
        [row["rowHash"] for row in rows]
    )
    stage_id = f"checkpoint-stage-{uuid4().hex}"
    with _CHECKPOINT_RESET_LOCK:
        _CHECKPOINT_RESET_STAGES[stage_id] = {
            "stageId": stage_id,
            "resetId": normalized_reset,
            "teamId": normalized_team,
            "checkpointPath": str(path),
            "authority": authority,
            "authorityHash": _reset_json_hash(authority),
            "rows": target_rows,
            "storeFingerprint": store_fingerprint,
            "storeMissing": not path.exists(),
            "status": "staged",
        }
    return {
        "schemaVersion": CHECKPOINT_RESET_PORT_SCHEMA_VERSION,
        "kind": CHECKPOINT_RESET_PORT_KIND,
        "stageId": stage_id,
        "resetId": normalized_reset,
        "teamId": normalized_team,
        "checkpointPath": str(path),
        "authorityHash": _reset_json_hash(authority),
        "recordCount": len(target_rows),
        "threadCount": len({row["threadId"] for row in target_rows}),
        "storeFingerprint": store_fingerprint,
        "recordIds": [
            f"{row['threadId']}:{row['checkpointNs']}:{row['checkpointId']}"
            for row in target_rows
        ],
    }


def _checkpoint_stage_for_operation(stage: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(stage, Mapping):
        raise CheckpointResetPortError(
            "checkpoint stage must be an object", code="checkpoint_stage_corrupt"
        )
    if stage.get("schemaVersion") != CHECKPOINT_RESET_PORT_SCHEMA_VERSION or stage.get("kind") != CHECKPOINT_RESET_PORT_KIND:
        raise CheckpointResetPortError(
            "checkpoint stage schema is invalid", code="checkpoint_stage_corrupt"
        )
    stage_id = _reset_text(stage.get("stageId"), field="stageId")
    with _CHECKPOINT_RESET_LOCK:
        cached = _CHECKPOINT_RESET_STAGES.get(stage_id)
    if cached is None:
        raise CheckpointResetPortError(
            "checkpoint stage is not available", code="checkpoint_stage_missing"
        )
    for key in ("resetId", "teamId", "checkpointPath", "authorityHash"):
        if str(stage.get(key) or "") != str(cached.get(key) or ""):
            raise CheckpointResetPortError(
                f"checkpoint stage {key} does not match cached stage",
                code="checkpoint_stage_mismatch",
            )
    if int(stage.get("recordCount") or -1) != len(cached["rows"]):
        raise CheckpointResetPortError(
            "checkpoint stage record count does not match cached stage",
            code="checkpoint_stage_mismatch",
        )
    return cached


def _checkpoint_assert_authority_matches(
    cached: Mapping[str, Any], scope_authority: Any = None
) -> dict[str, dict[str, Any]]:
    if scope_authority is None:
        return dict(cached["authority"])
    authority = _reset_authority_entries(scope_authority)
    if _reset_json_hash(authority) != str(cached["authorityHash"]):
        raise CheckpointResetPortError(
            "checkpoint scope authority changed after stage",
            code="checkpoint_scope_mismatch",
        )
    return authority


def _checkpoint_compare_stage_rows(
    current: Iterable[Mapping[str, Any]], staged: Iterable[Mapping[str, Any]], team_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current_target = {
        _checkpoint_row_key(row): dict(row)
        for row in _checkpoint_target_rows(current, team_id)
    }
    staged_target = {
        _checkpoint_row_key(row): dict(row)
        for row in staged
    }
    if set(current_target) != set(staged_target):
        raise CheckpointResetPortError(
            "checkpoint store changed after stage", code="checkpoint_stage_stale"
        )
    for key, row in current_target.items():
        if row.get("rowHash") != staged_target[key].get("rowHash"):
            raise CheckpointResetPortError(
                "checkpoint staged row changed", code="checkpoint_stage_stale"
            )
    return list(current_target.values()), list(staged_target.values())


def _checkpoint_mutate_stage(
    stage: Mapping[str, Any],
    *,
    operation: str,
    checkpoint_path: Path | str | None = None,
    scope_authority: Any = None,
    reset_id: str | None = None,
) -> dict[str, Any]:
    cached = _checkpoint_stage_for_operation(stage)
    if reset_id is not None and str(reset_id).strip() != str(cached["resetId"]):
        raise CheckpointResetPortError(
            "checkpoint resetId does not match staged reset",
            code="checkpoint_stage_mismatch",
        )
    authority = _checkpoint_assert_authority_matches(cached, scope_authority)
    path = _reset_path(checkpoint_path or cached["checkpointPath"])
    if str(path) != str(cached["checkpointPath"]):
        raise CheckpointResetPortError(
            "checkpoint path does not match staged path", code="checkpoint_stage_mismatch"
        )
    staged_rows = [dict(row) for row in cached["rows"]]
    if not path.exists():
        if staged_rows:
            raise CheckpointResetPortError(
                "checkpoint store disappeared after stage", code="checkpoint_stage_stale"
            )
        return {
            "ok": True,
            "kind": CHECKPOINT_RESET_PORT_KIND,
            "resetId": cached["resetId"],
            "teamId": cached["teamId"],
            "operation": operation,
            "recordCount": 0,
            "alreadyAbsent": True,
        }
    connection = _checkpoint_open_connection(path, read_only=False)
    changed = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        current_rows = _checkpoint_rows_from_connection(connection, authority)
        if operation == "restore":
            current_target_map = {
                _checkpoint_row_key(row): dict(row)
                for row in _checkpoint_target_rows(current_rows, str(cached["teamId"]))
            }
            staged_target_map = {
                _checkpoint_row_key(row): dict(row) for row in staged_rows
            }
            if not set(current_target_map) <= set(staged_target_map):
                raise CheckpointResetPortError(
                    "checkpoint store changed after stage", code="checkpoint_stage_stale"
                )
            for key, row in current_target_map.items():
                if row.get("rowHash") != staged_target_map[key].get("rowHash"):
                    raise CheckpointResetPortError(
                        "checkpoint staged row changed", code="checkpoint_stage_stale"
                    )
            current_target = list(current_target_map.values())
        else:
            current_target, _ = _checkpoint_compare_stage_rows(
                current_rows, staged_rows, str(cached["teamId"])
            )
        if operation == "purge":
            for row in current_target:
                thread_id, checkpoint_ns, checkpoint_id = _checkpoint_row_key(row)
                cursor = connection.execute(
                    "DELETE FROM writes WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?",
                    (thread_id, checkpoint_ns, checkpoint_id),
                )
                changed += int(cursor.rowcount if cursor.rowcount is not None else 0)
                cursor = connection.execute(
                    "DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?",
                    (thread_id, checkpoint_ns, checkpoint_id),
                )
                changed += int(cursor.rowcount if cursor.rowcount is not None else 0)
        elif operation == "restore":
            # A restore is normally called after purge, but keeping it
            # idempotent makes parent compensation safe after a retry.
            for row in staged_rows:
                key = _checkpoint_row_key(row)
                existing = {
                    _checkpoint_row_key(item): item
                    for item in current_target
                }.get(key)
                if existing is not None:
                    continue
                connection.execute(
                    "INSERT INTO checkpoints(thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["threadId"],
                        row["checkpointNs"],
                        row["checkpointId"],
                        row.get("parentCheckpointId"),
                        row.get("type"),
                        _checkpoint_blob_value(row["checkpoint"]),
                        _checkpoint_blob_value(row["metadata"]),
                    ),
                )
                for write in row.get("writes") or []:
                    connection.execute(
                        "INSERT INTO writes(thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            row["threadId"],
                            row["checkpointNs"],
                            row["checkpointId"],
                            write["taskId"],
                            int(write["idx"]),
                            write["channel"],
                            write.get("type"),
                            _checkpoint_blob_value(write["value"]),
                        ),
                    )
                changed += 1
        else:
            raise CheckpointResetPortError(
                "checkpoint reset operation is unsupported", code="checkpoint_operation_invalid"
            )
        connection.execute("COMMIT")
    except CheckpointResetPortError:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    except Exception as exc:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise CheckpointResetPortError(
            f"checkpoint {operation} failed", code="checkpoint_reset_failed"
        ) from exc
    finally:
        connection.close()
    if operation == "restore":
        restored_rows = _checkpoint_store_rows(path, authority, read_only=True)
        restored_target = _checkpoint_target_rows(restored_rows, str(cached["teamId"]))
        if {
            _checkpoint_row_key(row): row.get("rowHash") for row in restored_target
        } != {
            _checkpoint_row_key(row): row.get("rowHash") for row in staged_rows
        }:
            raise CheckpointResetPortError(
                "checkpoint restore verification failed", code="checkpoint_restore_failed"
            )
    with _CHECKPOINT_RESET_LOCK:
        cached["status"] = "purged" if operation == "purge" else "restored"
    return {
        "ok": True,
        "kind": CHECKPOINT_RESET_PORT_KIND,
        "resetId": cached["resetId"],
        "teamId": cached["teamId"],
        "operation": operation,
        "recordCount": len(staged_rows),
        "changedRows": changed,
        "alreadyAbsent": operation == "purge" and not current_target,
    }


def purge_checkpoint_reset_stage(
    stage: Mapping[str, Any],
    *,
    checkpoint_path: Path | str | None = None,
    scope_authority: Any = None,
    reset_id: str | None = None,
) -> dict[str, Any]:
    """Delete only the exact checkpoint rows captured by this reset stage."""

    return _checkpoint_mutate_stage(
        stage,
        operation="purge",
        checkpoint_path=checkpoint_path,
        scope_authority=scope_authority,
        reset_id=reset_id,
    )


def restore_checkpoint_reset_stage(
    stage: Mapping[str, Any],
    *,
    checkpoint_path: Path | str | None = None,
    scope_authority: Any = None,
    reset_id: str | None = None,
) -> dict[str, Any]:
    """Restore a previously staged checkpoint set after a later port fails."""

    return _checkpoint_mutate_stage(
        stage,
        operation="restore",
        checkpoint_path=checkpoint_path,
        scope_authority=scope_authority,
        reset_id=reset_id,
    )


def destroy_checkpoint_reset_stage(
    stage: Mapping[str, Any],
    *,
    reset_id: str | None = None,
) -> dict[str, Any]:
    """Discard only reset-owned recovery rows after a successful full reset."""

    cached = _checkpoint_stage_for_operation(stage)
    if reset_id is not None and str(reset_id).strip() != str(cached["resetId"]):
        raise CheckpointResetPortError(
            "checkpoint resetId does not match staged reset", code="checkpoint_stage_mismatch"
        )
    with _CHECKPOINT_RESET_LOCK:
        status = str(cached.get("status") or "staged")
        if status not in {"purged", "destroyed"}:
            raise CheckpointResetPortError(
                "only a purged checkpoint stage can be finalized", code="checkpoint_stage_invalid"
            )
        cached["status"] = "destroyed"
        cached["rows"] = []
    return {**_checkpoint_stage_summary(stage), "operation": "destroy", "destroyed": True}


# Compatibility aliases for the parent reset adapter's port wiring.  They are
# deliberately aliases, not second implementations or public route DTOs.
list_checkpoints_for_team = list_team_scoped_checkpoints
prepare_team_checkpoint_reset_stage = prepare_checkpoint_reset_stage
purge_team_checkpoint_reset_stage = purge_checkpoint_reset_stage
restore_team_checkpoint_reset_stage = restore_checkpoint_reset_stage


__all__ = [
    "CANDIDATE_REVIEW_SCOPE_KIND",
    "DISCUSSION_SCOPE_KINDS",
    "DISCUSSION_SCOPE_VERSION",
    "QUESTION_GENERATION_SCOPE_KIND",
    "SCOPE_BINDING_MISMATCH",
    "ScopeBindingMismatch",
    "ScopeBindingValidation",
    "assert_five_way_scope_binding",
    "assert_scope_bindings_match",
    "build_checkpoint_binding_payload",
    "canonical_discussion_scope",
    "checkpoint_store_has_rows",
    "destroy_checkpoint_reset_stage",
    "discussion_scope_hash",
    "discussion_scope_identity",
    "validate_five_way_scope_binding",
    "validate_scope_bindings",
    "scope_without_agent_id",
    "assert_not_memory_saver",
    "default_checkpoint_path",
    "ensure_checkpoint_parent",
    "open_sqlite_checkpointer",
    "CHECKPOINT_RESET_PORT_KIND",
    "CHECKPOINT_RESET_PORT_SCHEMA_VERSION",
    "CHECKPOINT_FULL_PURGE_PORT_KIND",
    "CheckpointResetPortError",
    "prepare_operator_checkpoint_full_purge",
    "purge_operator_checkpoint_full_purge",
    "list_team_scoped_checkpoints",
    "list_checkpoint_thread_ids",
    "prepare_checkpoint_reset_stage",
    "purge_checkpoint_reset_stage",
    "restore_checkpoint_reset_stage",
    "list_checkpoints_for_team",
    "prepare_team_checkpoint_reset_stage",
    "purge_team_checkpoint_reset_stage",
    "restore_team_checkpoint_reset_stage",
]
