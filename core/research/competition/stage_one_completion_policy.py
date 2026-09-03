"""Tracked completion policy for the current Challenge Cup stage-one G1 scope."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


STAGE_ONE_POLICY_KIND = "challenge_cup_stage_one_completion_policy"
STAGE_ONE_POLICY_SCHEMA_VERSION = 1
STAGE_ONE_POLICY_QUESTION_IDS = ("SCI-003", "SCI-091")
STAGE_ONE_POLICY_WORKFLOW_DEFINITION_ID = "challenge-cup-research@2.1.0"
STAGE_ONE_POLICY_RESOURCE_PATH = (
    Path(__file__).resolve().parent / "data" / "challenge_cup_stage_one_scope_v1.json"
)
STAGE_ONE_POLICY_RESOURCE_SHA256 = (
    "A5180088754EFE2D5F1F1DD29181AF54578E5B3E6CD1251CF8CA8CAB73F63153"
)

_QUESTION_ID_RE = re.compile(r"SCI-\d{3}")
_RESOURCE_FIELDS = {
    "schemaVersion",
    "kind",
    "policyVersion",
    "scopeId",
    "workflowDefinitionId",
    "questionIds",
    "closureNodeId",
    "completionState",
    "requiredArtifactKinds",
    "requiredReceiptStages",
    "deferredNodeIds",
    "allowPhaseTwoAdvance",
}
_SNAPSHOT_FIELDS = _RESOURCE_FIELDS | {"policySha256"}


class StageOneCompletionPolicyError(ValueError):
    """The tracked or frozen stage-one completion policy is invalid."""


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _required_text(payload: Mapping[str, Any], field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise StageOneCompletionPolicyError(f"{field} must be non-empty text")
    return value


def _unique_text_list(payload: Mapping[str, Any], field: str) -> tuple[str, ...]:
    raw = payload.get(field)
    if not isinstance(raw, list) or not raw:
        raise StageOneCompletionPolicyError(f"{field} must be a non-empty array")
    values = tuple(str(item or "").strip() for item in raw)
    if any(not item for item in values) or len(set(values)) != len(values):
        raise StageOneCompletionPolicyError(
            f"{field} must contain unique non-empty text values"
        )
    return values


@dataclass(frozen=True, slots=True)
class StageOneCompletionPolicy:
    schemaVersion: int
    kind: str
    policyVersion: str
    scopeId: str
    workflowDefinitionId: str
    questionIds: tuple[str, ...]
    closureNodeId: str
    completionState: str
    requiredArtifactKinds: tuple[str, ...]
    requiredReceiptStages: tuple[str, ...]
    deferredNodeIds: tuple[str, ...]
    allowPhaseTwoAdvance: bool
    policySha256: str

    @classmethod
    def _parse(
        cls,
        payload: Mapping[str, Any],
        *,
        require_policy_sha256: bool,
    ) -> StageOneCompletionPolicy:
        if not isinstance(payload, Mapping):
            raise StageOneCompletionPolicyError(
                "stage-one completion policy must be an object"
            )
        allowed = _SNAPSHOT_FIELDS if require_policy_sha256 else _RESOURCE_FIELDS
        unknown = sorted(set(payload) - allowed)
        missing = sorted(allowed - set(payload))
        if unknown:
            raise StageOneCompletionPolicyError(
                "stage-one completion policy contains unsupported fields: "
                + ", ".join(unknown)
            )
        if missing:
            raise StageOneCompletionPolicyError(
                "stage-one completion policy is missing fields: " + ", ".join(missing)
            )
        if payload.get("schemaVersion") != STAGE_ONE_POLICY_SCHEMA_VERSION:
            raise StageOneCompletionPolicyError(
                "stage-one completion policy schema is unsupported"
            )
        if payload.get("kind") != STAGE_ONE_POLICY_KIND:
            raise StageOneCompletionPolicyError(
                "stage-one completion policy kind is invalid"
            )

        question_ids = _unique_text_list(payload, "questionIds")
        if any(not _QUESTION_ID_RE.fullmatch(item) for item in question_ids):
            raise StageOneCompletionPolicyError(
                "questionIds must use canonical SCI-NNN ids"
            )
        required_artifacts = _unique_text_list(payload, "requiredArtifactKinds")
        required_receipts = _unique_text_list(payload, "requiredReceiptStages")
        deferred_nodes = _unique_text_list(payload, "deferredNodeIds")
        closure_node = _required_text(payload, "closureNodeId")
        if closure_node in deferred_nodes:
            raise StageOneCompletionPolicyError(
                "closureNodeId must not also be a deferred node"
            )
        if payload.get("allowPhaseTwoAdvance") is not False:
            raise StageOneCompletionPolicyError(
                "allowPhaseTwoAdvance must remain false for stage one"
            )
        if _required_text(payload, "completionState") != "STAGE1_G1_ACCEPTED":
            raise StageOneCompletionPolicyError(
                "completionState must be STAGE1_G1_ACCEPTED"
            )

        canonical = {field: payload[field] for field in _RESOURCE_FIELDS}
        expected_hash = _canonical_sha256(canonical)
        supplied_hash = str(payload.get("policySha256") or "").strip().lower()
        if require_policy_sha256 and supplied_hash != expected_hash:
            raise StageOneCompletionPolicyError(
                "policySha256 does not match the stage-one completion policy"
            )
        return cls(
            schemaVersion=STAGE_ONE_POLICY_SCHEMA_VERSION,
            kind=STAGE_ONE_POLICY_KIND,
            policyVersion=_required_text(payload, "policyVersion"),
            scopeId=_required_text(payload, "scopeId"),
            workflowDefinitionId=_required_text(payload, "workflowDefinitionId"),
            questionIds=question_ids,
            closureNodeId=closure_node,
            completionState="STAGE1_G1_ACCEPTED",
            requiredArtifactKinds=required_artifacts,
            requiredReceiptStages=required_receipts,
            deferredNodeIds=deferred_nodes,
            allowPhaseTwoAdvance=False,
            policySha256=expected_hash,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StageOneCompletionPolicy:
        return cls._parse(payload, require_policy_sha256=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "kind": self.kind,
            "policyVersion": self.policyVersion,
            "scopeId": self.scopeId,
            "workflowDefinitionId": self.workflowDefinitionId,
            "questionIds": list(self.questionIds),
            "closureNodeId": self.closureNodeId,
            "completionState": self.completionState,
            "requiredArtifactKinds": list(self.requiredArtifactKinds),
            "requiredReceiptStages": list(self.requiredReceiptStages),
            "deferredNodeIds": list(self.deferredNodeIds),
            "allowPhaseTwoAdvance": self.allowPhaseTwoAdvance,
            "policySha256": self.policySha256,
        }


def load_stage_one_completion_policy() -> StageOneCompletionPolicy:
    try:
        raw = STAGE_ONE_POLICY_RESOURCE_PATH.read_bytes()
    except OSError as exc:
        raise StageOneCompletionPolicyError(
            "tracked stage-one completion policy is unavailable"
        ) from exc
    actual = hashlib.sha256(raw).hexdigest().upper()
    if actual != STAGE_ONE_POLICY_RESOURCE_SHA256:
        raise StageOneCompletionPolicyError(
            "tracked stage-one completion policy resource hash has drifted"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageOneCompletionPolicyError(
            "tracked stage-one completion policy is not valid UTF-8 JSON"
        ) from exc
    policy = StageOneCompletionPolicy._parse(
        payload,
        require_policy_sha256=False,
    )
    if (
        policy.questionIds != STAGE_ONE_POLICY_QUESTION_IDS
        or policy.workflowDefinitionId != STAGE_ONE_POLICY_WORKFLOW_DEFINITION_ID
    ):
        raise StageOneCompletionPolicyError(
            "tracked stage-one completion policy identity has drifted"
        )
    return policy


def stage_one_policy_snapshot_for(
    question_id: str,
    workflow_definition_id: str,
) -> dict[str, Any] | None:
    normalized_question = str(question_id or "").strip().upper()
    normalized_workflow = str(workflow_definition_id or "").strip()
    if (
        normalized_question not in STAGE_ONE_POLICY_QUESTION_IDS
        or normalized_workflow != STAGE_ONE_POLICY_WORKFLOW_DEFINITION_ID
    ):
        return None
    policy = load_stage_one_completion_policy()
    return policy.to_dict()


def require_current_stage_one_policy_snapshot(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    parsed = StageOneCompletionPolicy.from_dict(payload)
    current = load_stage_one_completion_policy()
    if parsed != current:
        raise StageOneCompletionPolicyError(
            "stage-one completion policy does not match the tracked current policy"
        )
    return parsed.to_dict()


def _policy_dict_with_definition_id(
    policy: StageOneCompletionPolicy,
    workflow_definition_id: str,
) -> dict[str, Any]:
    payload = policy.to_dict()
    payload["workflowDefinitionId"] = str(workflow_definition_id)
    canonical = {field: payload[field] for field in _RESOURCE_FIELDS}
    payload["policySha256"] = _canonical_sha256(canonical)
    return payload


def _equivalent_modulo_definition_id(
    policy: StageOneCompletionPolicy,
    tracked: StageOneCompletionPolicy,
) -> bool:
    def _without_identity(item: StageOneCompletionPolicy) -> dict[str, Any]:
        payload = item.to_dict()
        payload.pop("workflowDefinitionId")
        payload.pop("policySha256")
        return payload

    return _without_identity(policy) == _without_identity(tracked)


def stage_one_policy_snapshot_for_definition(
    payload: Mapping[str, Any],
    *,
    workflow_definition_id: str,
) -> dict[str, Any]:
    """The tracked current stage-one policy re-targeted at one definition id.

    The tracked resource stays pinned to
    ``STAGE_ONE_POLICY_WORKFLOW_DEFINITION_ID`` (authorization scopes and
    historical runs keep that identity).  Runs created against the truncated
    stage-one definition (``challenge-cup-research@2.2.0-stage-one``) embed a
    re-targeted copy whose ``workflowDefinitionId`` names the definition that
    actually drives the run, so the run-input contract and the stage-one
    closeout identity check both keep matching exactly.

    Fail-closed: ``payload`` must be the tracked current policy — either
    verbatim or already re-targeted at ``workflow_definition_id`` (identical
    policy fields, only the definition identity differs).  The returned
    snapshot is self-consistent (``policySha256`` recomputed).
    """
    parsed = StageOneCompletionPolicy.from_dict(payload)
    current = load_stage_one_completion_policy()
    if parsed != current and not (
        parsed.workflowDefinitionId == workflow_definition_id
        and _equivalent_modulo_definition_id(parsed, current)
    ):
        raise StageOneCompletionPolicyError(
            "stage-one completion policy does not match the tracked current policy"
        )
    if parsed.workflowDefinitionId == workflow_definition_id:
        return parsed.to_dict()
    return _policy_dict_with_definition_id(parsed, workflow_definition_id)


def matches_current_stage_one_policy(
    payload: Mapping[str, Any],
    *,
    workflow_definition_id: str = "",
) -> bool:
    """Whether payload is the tracked current policy, optionally re-targeted.

    Read-path companion of :func:`stage_one_policy_snapshot_for_definition`:
    a run input snapshot embedding the re-targeted truncated-definition copy
    stays a valid stage-one policy authorization, while any other drift
    fails closed.
    """
    try:
        parsed = StageOneCompletionPolicy.from_dict(payload)
        current = load_stage_one_completion_policy()
    except (StageOneCompletionPolicyError, KeyError, TypeError, ValueError):
        return False
    if parsed == current:
        return True
    return bool(
        workflow_definition_id
        and parsed.workflowDefinitionId == workflow_definition_id
        and _equivalent_modulo_definition_id(parsed, current)
    )


__all__ = [
    "STAGE_ONE_POLICY_KIND",
    "STAGE_ONE_POLICY_QUESTION_IDS",
    "STAGE_ONE_POLICY_RESOURCE_PATH",
    "STAGE_ONE_POLICY_RESOURCE_SHA256",
    "STAGE_ONE_POLICY_SCHEMA_VERSION",
    "STAGE_ONE_POLICY_WORKFLOW_DEFINITION_ID",
    "StageOneCompletionPolicy",
    "StageOneCompletionPolicyError",
    "load_stage_one_completion_policy",
    "matches_current_stage_one_policy",
    "require_current_stage_one_policy_snapshot",
    "stage_one_policy_snapshot_for",
    "stage_one_policy_snapshot_for_definition",
]
