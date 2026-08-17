"""Frozen template baseline and addendum contracts.

A ``TemplateBaseline`` is a frozen, approval-bound method contract.  Once
frozen it must never be modified in place: any legitimate follow-up is an
append-only ``TemplateAddendum``.  A *semantic* change is not an addendum — it
must be a new baseline version that links back to its frozen parent via
``parentBaselineId`` and carries a fresh approval.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._validation import (
    ContractValidationError,
    require_int,
    require_mapping,
    require_text,
)
from .research_scope import REQUIRED_SCOPE_FIELDS, scope_hash_for

BASELINE_STATUSES = {"draft", "frozen", "superseded"}
ADDENDUM_STATUSES = {"active", "superseded"}


def _scope_identity(payload: Mapping[str, Any]) -> dict[str, str]:
    identity = {field: require_text(payload, field) for field in REQUIRED_SCOPE_FIELDS}
    identity["agentId"] = require_text(payload, "agentId")
    identity["mode"] = require_text(payload, "mode").lower()
    return identity


def _validated_scope_hash(payload: Mapping[str, Any], identity: Mapping[str, str]) -> str:
    supplied = require_text(payload, "scopeHash").lower()
    expected = scope_hash_for(
        **{field: identity[field] for field in REQUIRED_SCOPE_FIELDS},
        agent_id=identity["agentId"],
        mode=identity["mode"],
    )
    if supplied != expected:
        raise ContractValidationError("scopeHash does not match the template scope identity")
    return supplied


@dataclass(frozen=True, slots=True)
class TemplateBaseline:
    """An immutable method template baseline under one scope."""

    baselineId: str
    templateId: str
    version: int
    parentBaselineId: str
    parentVersion: int
    status: str
    content: dict[str, Any]
    program: str
    theme: str
    campaign: str
    question: str
    branch: str
    workflow: str
    agentId: str
    mode: str
    scopeHash: str
    approvedBy: str
    approvedAt: str
    approvalRef: str
    semanticChangeReason: str
    frozenAt: str
    createdAt: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> TemplateBaseline:
        status = require_text(payload, "status").lower()
        if status not in BASELINE_STATUSES:
            raise ContractValidationError(
                "baseline status must be one of: " + ", ".join(sorted(BASELINE_STATUSES))
            )
        identity = _scope_identity(payload)
        frozen = status == "frozen"
        approved_by = str(payload.get("approvedBy") or "").strip()
        approved_at = str(payload.get("approvedAt") or "").strip()
        approval_ref = str(payload.get("approvalRef") or "").strip()
        frozen_at = str(payload.get("frozenAt") or "").strip()
        if frozen and not (approved_by and approved_at and approval_ref and frozen_at):
            raise ContractValidationError(
                "a frozen baseline requires approvedBy, approvedAt, approvalRef, and frozenAt"
            )
        return cls(
            baselineId=require_text(payload, "baselineId"),
            templateId=require_text(payload, "templateId"),
            version=require_int(payload, "version", minimum=1),
            parentBaselineId=str(payload.get("parentBaselineId") or "").strip(),
            parentVersion=require_int(payload, "parentVersion", minimum=0),
            status=status,
            content=require_mapping(payload, "content"),
            **identity,
            scopeHash=_validated_scope_hash(payload, identity),
            approvedBy=approved_by,
            approvedAt=approved_at,
            approvalRef=approval_ref,
            semanticChangeReason=str(payload.get("semanticChangeReason") or "").strip(),
            frozenAt=frozen_at,
            createdAt=require_text(payload, "createdAt"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "baselineId": self.baselineId,
            "templateId": self.templateId,
            "version": self.version,
            "parentBaselineId": self.parentBaselineId,
            "parentVersion": self.parentVersion,
            "status": self.status,
            "content": dict(self.content),
            "program": self.program,
            "theme": self.theme,
            "campaign": self.campaign,
            "question": self.question,
            "branch": self.branch,
            "workflow": self.workflow,
            "agentId": self.agentId,
            "mode": self.mode,
            "scopeHash": self.scopeHash,
            "approvedBy": self.approvedBy,
            "approvedAt": self.approvedAt,
            "approvalRef": self.approvalRef,
            "semanticChangeReason": self.semanticChangeReason,
            "frozenAt": self.frozenAt,
            "createdAt": self.createdAt,
        }

    def is_frozen(self) -> bool:
        return self.status == "frozen"

    def semantic_change_from(self, other: "TemplateBaseline") -> bool:
        """A content change is semantic when a substantive method key differs."""
        changed = set(self.content) ^ set(other.content)
        for key in set(self.content) & set(other.content):
            if self.content[key] != other.content[key]:
                changed.add(key)
        return bool(changed)


@dataclass(frozen=True, slots=True)
class TemplateAddendum:
    """An append-only, non-semantic amendment layered over a frozen baseline."""

    addendumId: str
    baselineId: str
    templateId: str
    version: int
    reason: str
    deltas: dict[str, Any]
    semanticChange: bool
    appendedBy: str
    appendedAt: str
    status: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> TemplateAddendum:
        status = require_text(payload, "status").lower()
        if status not in ADDENDUM_STATUSES:
            raise ContractValidationError(
                "addendum status must be one of: " + ", ".join(sorted(ADDENDUM_STATUSES))
            )
        semantic_change = bool(payload.get("semanticChange"))
        if semantic_change:
            raise ContractValidationError(
                "a semantic change must be a new baseline version with parent and re-approval"
            )
        return cls(
            addendumId=require_text(payload, "addendumId"),
            baselineId=require_text(payload, "baselineId"),
            templateId=require_text(payload, "templateId"),
            version=require_int(payload, "version", minimum=1),
            reason=require_text(payload, "reason"),
            deltas=require_mapping(payload, "deltas", non_empty=False),
            semanticChange=False,
            appendedBy=require_text(payload, "appendedBy"),
            appendedAt=require_text(payload, "appendedAt"),
            status=status,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "addendumId": self.addendumId,
            "baselineId": self.baselineId,
            "templateId": self.templateId,
            "version": self.version,
            "reason": self.reason,
            "deltas": dict(self.deltas),
            "semanticChange": self.semanticChange,
            "appendedBy": self.appendedBy,
            "appendedAt": self.appendedAt,
            "status": self.status,
        }
