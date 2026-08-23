"""Research scope envelope contract with fail-closed identity validation.

A formal scope is the tuple (program, theme, campaign, question, branch,
workflow) plus the owning agent.  Every one of those identity fields is
required: a formal scope missing any field is malformed and must be rejected
before any derived locator is trusted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._canonical import sha256_hex
from ._validation import ContractValidationError, require_sha256, require_text

REQUIRED_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")


class ScopeMode(str, Enum):
    FORMAL = "formal"
    DEV = "dev"
    PLATFORM = "platform"


def parse_scope_mode(payload: Mapping[str, Any]) -> ScopeMode:
    raw = require_text(payload, "mode")
    try:
        return ScopeMode(raw)
    except ValueError as exc:
        raise ContractValidationError(f"unsupported scope mode: {raw}") from exc


def scope_identity_seed(
    *,
    program: str,
    theme: str,
    campaign: str,
    question: str,
    branch: str,
    workflow: str,
    agent_id: str,
    mode: str,
) -> dict[str, Any]:
    """Canonical, derived-field-free identity seed used for hashing/locating.

    Derived fields (scopeHash, artifactLocator, ledgerRoot, cacheKey) are never
    part of the seed: they are a pure function of this seed and would otherwise
    create a self-referential, unstable hash.
    """
    return {
        "program": str(program or "").strip(),
        "theme": str(theme or "").strip(),
        "campaign": str(campaign or "").strip(),
        "question": str(question or "").strip(),
        "branch": str(branch or "").strip(),
        "workflow": str(workflow or "").strip(),
        "agentId": str(agent_id or "").strip(),
        "mode": str(mode or "").strip().lower(),
    }


def scope_hash_for(
    *,
    program: str,
    theme: str,
    campaign: str,
    question: str,
    branch: str,
    workflow: str,
    agent_id: str,
    mode: str,
) -> str:
    """Stable full scope hash over the canonical identity seed."""
    return sha256_hex(
        scope_identity_seed(
            program=program,
            theme=theme,
            campaign=campaign,
            question=question,
            branch=branch,
            workflow=workflow,
            agent_id=agent_id,
            mode=mode,
        )
    )


def scope_locators_for(
    *,
    program: str,
    theme: str,
    campaign: str,
    question: str,
    branch: str,
    agent_id: str,
    scope_hash: str,
) -> dict[str, str]:
    """Derive the stable artifact, ledger, and cache locators for a scope.

    Keeping these paths beside the scope identity contract prevents callers
    from independently rebuilding locator strings during snapshot validation.
    """

    identity = {
        "program": str(program or "").strip(),
        "theme": str(theme or "").strip(),
        "campaign": str(campaign or "").strip(),
        "question": str(question or "").strip(),
        "branch": str(branch or "").strip(),
    }
    normalized_hash = str(scope_hash or "").strip()
    normalized_agent = str(agent_id or "").strip()
    return {
        "artifactLocator": (
            f"research-artifact://{identity['program']}/{identity['theme']}/"
            f"{identity['campaign']}/{identity['branch']}/{identity['question']}/"
            f"{normalized_hash}"
        ),
        "ledgerRoot": (
            f"research-ledger://{identity['program']}/{identity['theme']}/"
            f"{identity['campaign']}/{normalized_hash}"
        ),
        "cacheKey": f"scope:{normalized_hash}:{identity['branch']}:{normalized_agent}",
    }


@dataclass(frozen=True, slots=True)
class ResearchScopeEnvelope:
    """Immutable scope envelope with a full-scope hash for read verification."""

    program: str
    theme: str
    campaign: str
    question: str
    branch: str
    workflow: str
    agentId: str
    mode: ScopeMode
    scopeHash: str
    artifactLocator: str
    ledgerRoot: str
    cacheKey: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ResearchScopeEnvelope:
        # Fail-closed: every identity field is required and must be non-empty.
        for field in REQUIRED_SCOPE_FIELDS:
            require_text(payload, field)
        return cls(
            program=require_text(payload, "program"),
            theme=require_text(payload, "theme"),
            campaign=require_text(payload, "campaign"),
            question=require_text(payload, "question"),
            branch=require_text(payload, "branch"),
            workflow=require_text(payload, "workflow"),
            agentId=require_text(payload, "agentId"),
            mode=parse_scope_mode(payload),
            scopeHash=require_sha256(payload, "scopeHash"),
            artifactLocator=require_text(payload, "artifactLocator"),
            ledgerRoot=require_text(payload, "ledgerRoot"),
            cacheKey=require_text(payload, "cacheKey"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "program": self.program,
            "theme": self.theme,
            "campaign": self.campaign,
            "question": self.question,
            "branch": self.branch,
            "workflow": self.workflow,
            "agentId": self.agentId,
            "mode": self.mode.value,
            "scopeHash": self.scopeHash,
            "artifactLocator": self.artifactLocator,
            "ledgerRoot": self.ledgerRoot,
            "cacheKey": self.cacheKey,
        }

    def is_dev_or_platform(self) -> bool:
        return self.mode is not ScopeMode.FORMAL
