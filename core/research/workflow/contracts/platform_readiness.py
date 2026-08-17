"""Platform flow readiness report contract.

The report answers one question per theme/campaign: which flows are currently
allowed?  An unactivated theme only permits explicit DEV/platform contract
tests; real campaign activation and formal artifact read/write locators are
rejected until a formal ``ResearchCampaignActivation`` exists.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._validation import ContractValidationError, require_sha256, require_text
from .research_scope import ScopeMode, parse_scope_mode

BLOCKER_DEV_THEME_ONLY = "dev_theme_only"
BLOCKER_THEME_NOT_ACTIVATED = "theme_not_activated"
BLOCKER_CAMPAIGN_THEME_MISMATCH = "campaign_theme_mismatch"


@dataclass(frozen=True, slots=True)
class PlatformFlowReadinessReport:
    """Immutable readiness report for one theme/campaign flow."""

    programId: str
    themeId: str
    campaignId: str
    themeActivated: bool
    mode: ScopeMode
    devContractTestsAllowed: bool
    realCampaignAllowed: bool
    formalArtifactReadWriteAllowed: bool
    blockers: tuple[str, ...]
    scopeHash: str
    privateMemoryMigration: tuple[dict[str, Any], ...]
    generatedAt: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PlatformFlowReadinessReport:
        blockers = payload.get("blockers")
        if not isinstance(blockers, Sequence) or isinstance(blockers, (str, bytes)):
            raise ContractValidationError("blockers must be a list")
        migration = payload.get("privateMemoryMigration")
        if not isinstance(migration, Sequence) or isinstance(migration, (str, bytes)):
            raise ContractValidationError("privateMemoryMigration must be a list")
        for item in migration:
            if not isinstance(item, Mapping):
                raise ContractValidationError(
                    "privateMemoryMigration entries must be objects"
                )
        return cls(
            programId=require_text(payload, "programId"),
            themeId=require_text(payload, "themeId"),
            campaignId=require_text(payload, "campaignId"),
            themeActivated=payload.get("themeActivated") is True,
            mode=parse_scope_mode(payload),
            devContractTestsAllowed=payload.get("devContractTestsAllowed") is True,
            realCampaignAllowed=payload.get("realCampaignAllowed") is True,
            formalArtifactReadWriteAllowed=(
                payload.get("formalArtifactReadWriteAllowed") is True
            ),
            blockers=tuple(str(item) for item in blockers),
            scopeHash=require_sha256(payload, "scopeHash"),
            privateMemoryMigration=tuple(dict(item) for item in migration),
            generatedAt=require_text(payload, "generatedAt"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "programId": self.programId,
            "themeId": self.themeId,
            "campaignId": self.campaignId,
            "themeActivated": self.themeActivated,
            "mode": self.mode.value,
            "devContractTestsAllowed": self.devContractTestsAllowed,
            "realCampaignAllowed": self.realCampaignAllowed,
            "formalArtifactReadWriteAllowed": self.formalArtifactReadWriteAllowed,
            "blockers": list(self.blockers),
            "scopeHash": self.scopeHash,
            "privateMemoryMigration": [dict(item) for item in self.privateMemoryMigration],
            "generatedAt": self.generatedAt,
        }