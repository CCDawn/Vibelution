"""Canonical identity for Challenge Cup discussion rooms.

``WorkflowSessionScopeV3`` identifies one Agent's session.  A discussion room
is shared by several Agents, so it must have a separate identity that does not
contain ``agentId``.  This module is the only owner of that shared identity;
callers must not rebuild the pipe-delimited key or hash themselves.

The contract intentionally contains only logical identity.  Round numbers,
attempts and runtime status are persisted beside the scope by their owning
workflow and are never part of the room/session identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._canonical import canonical_json, sha256_hex
from ._validation import ContractValidationError

DISCUSSION_SCOPE_VERSION = 1
QUESTION_GENERATION_SCOPE_KIND = "question_generation"
CANDIDATE_REVIEW_SCOPE_KIND = "candidate_review"
DISCUSSION_SCOPE_KINDS = frozenset(
    {
        QUESTION_GENERATION_SCOPE_KIND,
        CANDIDATE_REVIEW_SCOPE_KIND,
    }
)

# Candidate selection can open a review room before a formal research run has
# been created.  Keep that identity separate from the formal scope rather
# than manufacturing a workflowRunId for the pre-run state.
PREFORMAL_DISCUSSION_SCOPE_VERSION = 1
PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND = "preformal_candidate_review"
PREFORMAL_DISCUSSION_SCOPE_KINDS = frozenset(
    {PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND}
)

_BASE_FIELDS = frozenset(
    {
        "version",
        "kind",
        "teamId",
        "researchProjectId",
        "workflowRunId",
        "workflowNodeId",
        "questionId",
    }
)
_REVIEW_FIELDS = _BASE_FIELDS | {"selectionId", "candidateId"}


def _factory_fields(
    fields: Mapping[str, Any], *, allowed: frozenset[str]
) -> dict[str, Any]:
    unknown = sorted(str(key) for key in set(fields) - allowed)
    if unknown:
        raise ContractValidationError(
            "Discussion scope contains unsupported fields: "
            + ", ".join(str(item) for item in unknown)
        )
    return dict(fields)


def _required_text(value: Any, field: str, *, limit: int = 160) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ContractValidationError(f"{field} is required")
    if len(normalized) > limit:
        raise ContractValidationError(f"{field} exceeds {limit} characters")
    # The key format below is intentionally simple and diagnosable.  Reject
    # values that could make two scopes serialize to an ambiguous key.
    if any(char in normalized for char in ("|", "\r", "\n")):
        raise ContractValidationError(f"{field} contains a reserved separator")
    return normalized


@dataclass(frozen=True, slots=True)
class WorkflowDiscussionScopeV1:
    """Immutable question-generation or one-candidate-review identity."""

    version: int
    kind: str
    teamId: str
    researchProjectId: str
    workflowRunId: str
    workflowNodeId: str
    questionId: str
    selectionId: str = ""
    candidateId: str = ""

    def __post_init__(self) -> None:
        try:
            version = int(self.version)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(
                "Discussion scope version must be an integer"
            ) from exc
        if version != DISCUSSION_SCOPE_VERSION:
            raise ContractValidationError(
                f"Discussion scope version must be {DISCUSSION_SCOPE_VERSION}"
            )
        normalized_kind = str(self.kind or "").strip()
        if normalized_kind not in DISCUSSION_SCOPE_KINDS:
            raise ContractValidationError(
                "Discussion scope kind must be question_generation or candidate_review"
            )

        object.__setattr__(self, "version", DISCUSSION_SCOPE_VERSION)
        object.__setattr__(self, "kind", normalized_kind)
        for field, limit in (
            ("teamId", 160),
            ("researchProjectId", 160),
            ("workflowRunId", 160),
            ("workflowNodeId", 80),
            ("questionId", 160),
        ):
            object.__setattr__(
                self,
                field,
                _required_text(getattr(self, field), field, limit=limit),
            )

        selection_id = str(self.selectionId or "").strip()
        candidate_id = str(self.candidateId or "").strip()
        if normalized_kind == QUESTION_GENERATION_SCOPE_KIND:
            if selection_id or candidate_id:
                raise ContractValidationError(
                    "question_generation scope must not carry selectionId or candidateId"
                )
        elif not selection_id or not candidate_id:
            raise ContractValidationError(
                "candidate_review scope requires both selectionId and candidateId"
            )
        if len(selection_id) > 160 or len(candidate_id) > 160:
            raise ContractValidationError(
                "selectionId and candidateId must be at most 160 characters"
            )
        if any(char in selection_id for char in ("|", "\r", "\n")):
            raise ContractValidationError("selectionId contains a reserved separator")
        if any(char in candidate_id for char in ("|", "\r", "\n")):
            raise ContractValidationError("candidateId contains a reserved separator")
        object.__setattr__(self, "selectionId", selection_id)
        object.__setattr__(self, "candidateId", candidate_id)

    @classmethod
    def generation(cls, **fields: Any) -> WorkflowDiscussionScopeV1:
        """Create a question-generation scope from canonical camelCase fields."""

        fields = _factory_fields(fields, allowed=_BASE_FIELDS - {"version", "kind"})
        return cls(
            version=DISCUSSION_SCOPE_VERSION,
            kind=QUESTION_GENERATION_SCOPE_KIND,
            teamId=fields.get("teamId"),
            researchProjectId=fields.get("researchProjectId"),
            workflowRunId=fields.get("workflowRunId"),
            workflowNodeId=fields.get("workflowNodeId"),
            questionId=fields.get("questionId"),
        )

    @classmethod
    def review(cls, **fields: Any) -> WorkflowDiscussionScopeV1:
        """Create a one-candidate review scope from canonical camelCase fields."""

        fields = _factory_fields(fields, allowed=_REVIEW_FIELDS - {"version", "kind"})
        return cls(
            version=DISCUSSION_SCOPE_VERSION,
            kind=CANDIDATE_REVIEW_SCOPE_KIND,
            teamId=fields.get("teamId"),
            researchProjectId=fields.get("researchProjectId"),
            workflowRunId=fields.get("workflowRunId"),
            workflowNodeId=fields.get("workflowNodeId"),
            questionId=fields.get("questionId"),
            selectionId=fields.get("selectionId"),
            candidateId=fields.get("candidateId"),
        )

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, Any]
    ) -> WorkflowDiscussionScopeV1:
        """Parse a scope and reject missing or unknown fields fail-closed."""

        if not isinstance(payload, Mapping):
            raise ContractValidationError("Discussion scope must be an object")
        kind = str(payload.get("kind") or "").strip()
        allowed = _REVIEW_FIELDS if kind == CANDIDATE_REVIEW_SCOPE_KIND else _BASE_FIELDS
        unknown = sorted(str(key) for key in set(payload) - allowed)
        if unknown:
            raise ContractValidationError(
                "Discussion scope contains unsupported fields: "
                + ", ".join(str(item) for item in unknown)
            )
        if kind not in DISCUSSION_SCOPE_KINDS:
            raise ContractValidationError(
                "Discussion scope kind must be question_generation or candidate_review"
            )
        return cls(
            version=payload.get("version"),
            kind=kind,
            teamId=payload.get("teamId"),
            researchProjectId=payload.get("researchProjectId"),
            workflowRunId=payload.get("workflowRunId"),
            workflowNodeId=payload.get("workflowNodeId"),
            questionId=payload.get("questionId"),
            selectionId=payload.get("selectionId") or "",
            candidateId=payload.get("candidateId") or "",
        )

    from_payload = from_mapping
    from_dict = from_mapping

    @property
    def is_candidate_review(self) -> bool:
        return self.kind == CANDIDATE_REVIEW_SCOPE_KIND

    @property
    def key(self) -> str:
        """Stable, human-diagnosable identity key."""

        values = [
            "v1",
            self.kind,
            self.teamId,
            self.researchProjectId,
            self.workflowRunId,
            self.workflowNodeId,
            self.questionId,
        ]
        if self.is_candidate_review:
            values.extend((self.selectionId, self.candidateId))
        return "|".join(values)

    @property
    def scope_hash(self) -> str:
        """SHA-256 over the canonical identity payload."""

        return sha256_hex(self.to_dict())

    @property
    def scopeHash(self) -> str:  # noqa: N802 - persisted API uses camelCase
        return self.scope_hash

    def to_dict(self) -> dict[str, str | int]:
        payload: dict[str, str | int] = {
            "version": DISCUSSION_SCOPE_VERSION,
            "kind": self.kind,
            "teamId": self.teamId,
            "researchProjectId": self.researchProjectId,
            "workflowRunId": self.workflowRunId,
            "workflowNodeId": self.workflowNodeId,
            "questionId": self.questionId,
        }
        if self.is_candidate_review:
            payload["selectionId"] = self.selectionId
            payload["candidateId"] = self.candidateId
        return payload

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def validate_candidate_membership(
        self, selected_candidate_ids: Sequence[Any] | None
    ) -> None:
        """Require review candidates to belong to the current selection."""

        if not self.is_candidate_review:
            if selected_candidate_ids:
                raise ContractValidationError(
                    "question_generation scope cannot carry selected candidates"
                )
            return
        if selected_candidate_ids is None:
            raise ContractValidationError(
                "candidate_review scope requires selectedCandidateIds for membership validation"
            )
        selected = {
            _required_text(item, "selectedCandidateId")
            for item in selected_candidate_ids
        }
        if self.candidateId not in selected:
            raise ContractValidationError(
                "candidateId must belong to the selected candidate set"
            )

    @property
    def question_generation_scope(self) -> WorkflowDiscussionScopeV1:
        """Return the question-level parent scope for a candidate review."""

        if not self.is_candidate_review:
            return self
        return WorkflowDiscussionScopeV1.generation(
            teamId=self.teamId,
            researchProjectId=self.researchProjectId,
            workflowRunId=self.workflowRunId,
            workflowNodeId=self.workflowNodeId,
            questionId=self.questionId,
        )

    def session_scope_payload(self, agent_id: Any) -> dict[str, Any]:
        """Compose the v3 Agent-session projection without changing room identity.

        The existing session service stores the v3 projection in its allowlisted
        ``scope`` field.  ``discussionScope`` and its hash are included here so
        owning writers can persist the complete binding where their storage
        supports it; the room identity remains this object's key/hash.
        """

        normalized_agent_id = _required_text(agent_id, "agentId")
        payload: dict[str, Any] = {
            "version": 3,
            "kind": (
                "workflow_candidate"
                if self.is_candidate_review
                else "workflow_node_root"
            ),
            "teamId": self.teamId,
            "researchProjectId": self.researchProjectId,
            "agentId": normalized_agent_id,
            "workflowRunId": self.workflowRunId,
            "workflowNodeId": self.workflowNodeId,
            "discussionScope": self.to_dict(),
            "discussionScopeHash": self.scope_hash,
        }
        if self.is_candidate_review:
            payload["selectionId"] = self.selectionId
            payload["candidateId"] = self.candidateId
        return payload

    to_session_scope = session_scope_payload


@dataclass(frozen=True, slots=True)
class PreformalCandidateReviewScopeV1:
    """Exact identity for a candidate-review room before a formal run exists.

    The preformal envelope is intentionally not a ``WorkflowDiscussionScopeV1``:
    there is no honest ``researchProjectId``/``workflowRunId``/node binding at
    this stage.  It still carries the concrete meeting and room references so
    a projector can cross-check all three persisted records instead of
    guessing from a team room or a question alone.
    """

    version: int
    kind: str
    teamId: str
    questionId: str
    selectionId: str
    candidateId: str
    meetingRoundId: str
    roomId: str

    def __post_init__(self) -> None:
        try:
            version = int(self.version)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(
                "Preformal discussion scope version must be an integer"
            ) from exc
        if version != PREFORMAL_DISCUSSION_SCOPE_VERSION:
            raise ContractValidationError(
                "Preformal discussion scope version must be "
                f"{PREFORMAL_DISCUSSION_SCOPE_VERSION}"
            )
        normalized_kind = str(self.kind or "").strip()
        if normalized_kind != PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND:
            raise ContractValidationError(
                "Preformal discussion scope kind must be "
                f"{PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND}"
            )
        object.__setattr__(self, "version", PREFORMAL_DISCUSSION_SCOPE_VERSION)
        object.__setattr__(self, "kind", normalized_kind)
        for field, limit in (
            ("teamId", 160),
            ("questionId", 160),
            ("selectionId", 160),
            ("candidateId", 160),
            ("meetingRoundId", 160),
            ("roomId", 200),
        ):
            object.__setattr__(
                self,
                field,
                _required_text(getattr(self, field), field, limit=limit),
            )

    @classmethod
    def review(cls, **fields: Any) -> PreformalCandidateReviewScopeV1:
        """Create an exact preformal candidate-review binding."""

        allowed = {
            "teamId",
            "questionId",
            "selectionId",
            "candidateId",
            "meetingRoundId",
            "roomId",
        }
        fields = _factory_fields(fields, allowed=allowed)
        return cls(
            version=PREFORMAL_DISCUSSION_SCOPE_VERSION,
            kind=PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND,
            teamId=fields.get("teamId"),
            questionId=fields.get("questionId"),
            selectionId=fields.get("selectionId"),
            candidateId=fields.get("candidateId"),
            meetingRoundId=fields.get("meetingRoundId"),
            roomId=fields.get("roomId"),
        )

    candidate_review = review

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, Any]
    ) -> PreformalCandidateReviewScopeV1:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("Preformal discussion scope must be an object")
        allowed = {
            "version",
            "kind",
            "teamId",
            "questionId",
            "selectionId",
            "candidateId",
            "meetingRoundId",
            "roomId",
        }
        unknown = sorted(str(key) for key in set(payload) - allowed)
        if unknown:
            raise ContractValidationError(
                "Preformal discussion scope contains unsupported fields: "
                + ", ".join(unknown)
            )
        return cls(
            version=payload.get("version"),
            kind=str(payload.get("kind") or "").strip(),
            teamId=payload.get("teamId"),
            questionId=payload.get("questionId"),
            selectionId=payload.get("selectionId"),
            candidateId=payload.get("candidateId"),
            meetingRoundId=payload.get("meetingRoundId"),
            roomId=payload.get("roomId"),
        )

    from_payload = from_mapping
    from_dict = from_mapping

    @property
    def is_candidate_review(self) -> bool:
        return True

    @property
    def key(self) -> str:
        return (
            f"v1|{self.kind}|{self.teamId}|{self.questionId}|{self.selectionId}|"
            f"{self.candidateId}|{self.meetingRoundId}|{self.roomId}"
        )

    @property
    def scope_hash(self) -> str:
        return sha256_hex(self.to_dict())

    @property
    def scopeHash(self) -> str:
        return self.scope_hash

    def to_dict(self) -> dict[str, str | int]:
        return {
            "version": PREFORMAL_DISCUSSION_SCOPE_VERSION,
            "kind": PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND,
            "teamId": self.teamId,
            "questionId": self.questionId,
            "selectionId": self.selectionId,
            "candidateId": self.candidateId,
            "meetingRoundId": self.meetingRoundId,
            "roomId": self.roomId,
        }

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())


DiscussionScopeEnvelope = WorkflowDiscussionScopeV1 | PreformalCandidateReviewScopeV1


def parse_discussion_scope(
    payload: WorkflowDiscussionScopeV1 | Mapping[str, Any],
) -> WorkflowDiscussionScopeV1:
    if isinstance(payload, WorkflowDiscussionScopeV1):
        return payload
    return WorkflowDiscussionScopeV1.from_mapping(payload)


def parse_discussion_scope_envelope(
    payload: DiscussionScopeEnvelope | Mapping[str, Any],
) -> DiscussionScopeEnvelope:
    """Parse formal or preformal scope without weakening formal parsing."""

    if isinstance(payload, (WorkflowDiscussionScopeV1, PreformalCandidateReviewScopeV1)):
        return payload
    if not isinstance(payload, Mapping):
        raise ContractValidationError("Discussion scope must be an object")
    kind = str(payload.get("kind") or payload.get("scopeKind") or "").strip()
    if kind == PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND:
        return PreformalCandidateReviewScopeV1.from_mapping(payload)
    return WorkflowDiscussionScopeV1.from_mapping(payload)


def canonical_discussion_scope(
    payload: DiscussionScopeEnvelope | Mapping[str, Any],
) -> str:
    return canonical_json(parse_discussion_scope_envelope(payload).to_dict())


def discussion_scope_key(
    payload: DiscussionScopeEnvelope | Mapping[str, Any],
) -> str:
    return parse_discussion_scope_envelope(payload).key


def discussion_scope_hash(
    payload: DiscussionScopeEnvelope | Mapping[str, Any],
) -> str:
    return parse_discussion_scope_envelope(payload).scope_hash


# Explicit ``*_for``/``*_json`` spellings mirror the older workflow contract
# helpers and make the single authority easy to discover at call sites.
discussion_scope_hash_for = discussion_scope_hash
discussion_scope_key_for = discussion_scope_key
canonical_discussion_scope_json = canonical_discussion_scope


def session_scope_key(
    payload: DiscussionScopeEnvelope | Mapping[str, Any], agent_id: Any
) -> str:
    """Derive the one canonical Agent-session key for a formal or preformal room scope.

    Preformal candidate reviews resolve hidden Child Sessions too, so they must
    share this serializer instead of inventing a second key formula.
    """

    scope = parse_discussion_scope_envelope(payload)
    return f"v3|session|{_required_text(agent_id, 'agentId')}|{scope.key}"


DiscussionScopeV1 = WorkflowDiscussionScopeV1


__all__ = [
    "CANDIDATE_REVIEW_SCOPE_KIND",
    "DISCUSSION_SCOPE_KINDS",
    "DISCUSSION_SCOPE_VERSION",
    "PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND",
    "PREFORMAL_DISCUSSION_SCOPE_KINDS",
    "PREFORMAL_DISCUSSION_SCOPE_VERSION",
    "QUESTION_GENERATION_SCOPE_KIND",
    "DiscussionScopeEnvelope",
    "DiscussionScopeV1",
    "PreformalCandidateReviewScopeV1",
    "WorkflowDiscussionScopeV1",
    "canonical_discussion_scope",
    "canonical_discussion_scope_json",
    "discussion_scope_hash",
    "discussion_scope_hash_for",
    "discussion_scope_key",
    "discussion_scope_key_for",
    "parse_discussion_scope",
    "parse_discussion_scope_envelope",
    "session_scope_key",
]
