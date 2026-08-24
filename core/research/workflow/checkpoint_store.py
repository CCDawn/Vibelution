"""Persistent SQLite checkpointer for research workflow runs."""

from __future__ import annotations

import os
import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def open_sqlite_checkpointer(path: Path | str | None = None) -> Any:
    """Return a context-manager SqliteSaver (use as `with open_sqlite_checkpointer() as cp:`)."""
    target = ensure_checkpoint_parent(Path(path) if path else default_checkpoint_path())
    return SqliteSaver.from_conn_string(str(target))


def assert_not_memory_saver(checkpointer: Any) -> None:
    name = type(checkpointer).__name__
    if name in {"MemorySaver", "InMemorySaver"}:
        raise RuntimeError("InMemorySaver is not allowed as delivery checkpointer (ADR 0006).")


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
    "discussion_scope_hash",
    "discussion_scope_identity",
    "validate_five_way_scope_binding",
    "validate_scope_bindings",
    "scope_without_agent_id",
    "assert_not_memory_saver",
    "default_checkpoint_path",
    "ensure_checkpoint_parent",
    "open_sqlite_checkpointer",
]
