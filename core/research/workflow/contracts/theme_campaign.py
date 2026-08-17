"""Theme and campaign activation contracts for scoped research workflows.

A ``ThemeContract`` is the derived identity of one research theme under a
program, including its isolation policy and activation state.  A
``ResearchCampaignActivation`` is the formal, hash-bound record that promotes a
real theme + campaign pair out of the DEV/platform-only regime.

DEV themes (``dev-`` prefix or absent from the frozen program core) must never
be promoted to a real campaign: they only exist so explicit DEV/platform
contract tests have a stable, non-formal scope.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._validation import (
    ContractValidationError,
    require_sha256,
    require_text,
)
from ._canonical import canonical_json, sha256_hex
from .research_scope import scope_hash_for

DEV_THEME_PREFIX = "dev-"
DEV_PROGRAM_ID = "dev-program"
DEFAULT_PROGRAM_ID = "XH-202619"


class ThemeContractStatus(str, Enum):
    DRAFT = "draft"
    DEV = "dev"
    ACTIVE = "active"
    RETIRED = "retired"


class CampaignActivationStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    REVOKED = "revoked"


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _status(payload: Mapping[str, Any], key: str, *, enum: type[Enum]) -> Enum:
    raw = require_text(payload, key)
    try:
        return enum(raw)
    except ValueError as exc:
        raise ContractValidationError(
            f"unsupported {key}: {raw}"
        ) from exc


@dataclass(frozen=True, slots=True)
class ThemeContract:
    """Derived theme identity with activation state and isolation policy."""

    programId: str
    themeId: str
    themeName: str
    campaignId: str
    status: ThemeContractStatus
    isolationPolicy: dict[str, Any]
    activatedAt: str
    activatedBy: str
    activationRef: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ThemeContract:
        isolation_policy = payload.get("isolationPolicy")
        return cls(
            programId=require_text(payload, "programId"),
            themeId=require_text(payload, "themeId"),
            themeName=require_text(payload, "themeName"),
            campaignId=require_text(payload, "campaignId"),
            status=_status(payload, "status", enum=ThemeContractStatus),
            isolationPolicy=(
                dict(isolation_policy) if isinstance(isolation_policy, Mapping) else {}
            ),
            activatedAt=str(payload.get("activatedAt") or "").strip(),
            activatedBy=str(payload.get("activatedBy") or "").strip(),
            activationRef=str(payload.get("activationRef") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "programId": self.programId,
            "themeId": self.themeId,
            "themeName": self.themeName,
            "campaignId": self.campaignId,
            "status": self.status.value,
            "isolationPolicy": dict(self.isolationPolicy),
            "activatedAt": self.activatedAt,
            "activatedBy": self.activatedBy,
            "activationRef": self.activationRef,
        }

    def is_dev_theme(self) -> bool:
        return (
            self.status is ThemeContractStatus.DEV
            or self.themeId.startswith(DEV_THEME_PREFIX)
            or self.programId == DEV_PROGRAM_ID
        )

    def is_activated(self) -> bool:
        return (
            self.status is ThemeContractStatus.ACTIVE
            and bool(self.activatedAt)
            and bool(self.activationRef)
        )


@dataclass(frozen=True, slots=True)
class ResearchCampaignActivation:
    """Formal activation binding one theme to one campaign under a program."""

    programId: str
    themeId: str
    campaignId: str
    status: CampaignActivationStatus
    activatedBy: str
    activatedAt: str
    activationRef: str
    scopeHash: str
    activationHash: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ResearchCampaignActivation:
        return cls(
            programId=require_text(payload, "programId"),
            themeId=require_text(payload, "themeId"),
            campaignId=require_text(payload, "campaignId"),
            status=_status(payload, "status", enum=CampaignActivationStatus),
            activatedBy=require_text(payload, "activatedBy"),
            activatedAt=require_text(payload, "activatedAt"),
            activationRef=require_text(payload, "activationRef"),
            scopeHash=require_sha256(payload, "scopeHash"),
            activationHash=require_sha256(payload, "activationHash"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "programId": self.programId,
            "themeId": self.themeId,
            "campaignId": self.campaignId,
            "status": self.status.value,
            "activatedBy": self.activatedBy,
            "activatedAt": self.activatedAt,
            "activationRef": self.activationRef,
            "scopeHash": self.scopeHash,
            "activationHash": self.activationHash,
        }


def activation_scope_hash(*, program_id: str, theme_id: str, campaign_id: str) -> str:
    """Stable theme-scope hash a formal activation binds to.

    Uses the formal mode over the theme/campaign identity only; question,
    branch, and workflow stay empty because an activation is a theme-level fact.
    """
    return scope_hash_for(
        program=program_id,
        theme=theme_id,
        campaign=campaign_id,
        question="",
        branch="",
        workflow="",
        agent_id="activation",
        mode="formal",
    )


def build_campaign_activation_payload(
    *,
    program_id: str,
    theme_id: str,
    campaign_id: str,
    activated_by: str,
    activation_ref: str = "",
    activated_at: str = "",
    status: str = "active",
) -> dict[str, Any]:
    """Build a self-consistent, hash-bound activation payload for persistence.

    Shared by the research-project activation wiring and the research-scope
    facade so the recorded activation never diverges between the two entry
    points.
    """
    normalized_status = str(status or "active").strip().lower()
    if normalized_status not in {item.value for item in CampaignActivationStatus}:
        raise ContractValidationError(f"unsupported activation status: {status}")
    payload = {
        "programId": str(program_id or "").strip(),
        "themeId": str(theme_id or "").strip(),
        "campaignId": str(campaign_id or "").strip(),
        "status": normalized_status,
        "activatedBy": str(activated_by or "").strip(),
        "activatedAt": str(activated_at or "").strip() or _utc_now_iso(),
        "activationRef": str(activation_ref or "").strip(),
        "scopeHash": activation_scope_hash(
            program_id=program_id,
            theme_id=theme_id,
            campaign_id=campaign_id,
        ),
    }
    if not payload["programId"] or not payload["themeId"] or not payload["campaignId"]:
        raise ContractValidationError(
            "programId, themeId, and campaignId are required for activation."
        )
    if not payload["activatedBy"] or not payload["activationRef"]:
        raise ContractValidationError(
            "activatedBy and activationRef are required for activation."
        )
    activation_hash = sha256_hex(canonical_json(payload))
    payload["activationHash"] = activation_hash
    ResearchCampaignActivation.from_dict(payload)
    return payload