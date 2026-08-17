"""Derived research-scope validation facade for Challenge Cup workflows.

This module is the *only* derived validation surface for scoped research
identity.  It derives theme contracts, formal scope envelopes, platform flow
readiness, and cross-theme private-memory migration decisions from:

1. the frozen competition program core (real theme/campaign registry), and
2. the existing research-project store (activation ledger).

It never builds a second state store: every read goes through
``research_projects`` and every write delegates back to it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.research.workflow.contracts import (
    BLOCKER_CAMPAIGN_THEME_MISMATCH,
    BLOCKER_DEV_THEME_ONLY,
    BLOCKER_THEME_NOT_ACTIVATED,
    DEFAULT_PROGRAM_ID,
    DEV_PROGRAM_ID,
    DEV_THEME_PREFIX,
    ContractValidationError,
    PlatformFlowReadinessReport,
    ResearchScopeEnvelope,
    ScopeMode,
    ThemeContract,
    ThemeContractStatus,
    build_campaign_activation_payload,
    scope_hash_for,
)
from core.web.services.team_workflow.research_projects import (
    get_theme_activation,
    record_theme_campaign_activation,
)

FORMAL_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")
MIGRATION_REUSE_POLICY = "migratable_advisory"


class ResearchScopeError(RuntimeError):
    """Base error for scoped research identity resolution."""


class ResearchScopeNotActivatedError(ResearchScopeError):
    code = "theme_not_activated"


class ResearchScopeDevThemeNotActivatableError(ResearchScopeError):
    code = "dev_theme_not_activatable"


class ResearchScopeCampaignMismatchError(ResearchScopeError):
    code = "campaign_theme_mismatch"


class ResearchScopeInvalidModeError(ResearchScopeError):
    code = "invalid_scope_mode"


class ResearchScopeHashMismatchError(ResearchScopeError):
    code = "scope_hash_mismatch"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any, *, limit: int = 0) -> str:
    text = str(value or "").strip()
    return text[:limit] if limit else text


def _frozen_program_snapshot() -> dict[str, Any]:
    """Load and shape the frozen program core once per derivation call."""
    from core.research.competition.resources import load_competition_program_core

    program = load_competition_program_core()
    body = program.get("program") if isinstance(program.get("program"), dict) else {}
    isolation = program.get("isolationPolicy") if isinstance(program.get("isolationPolicy"), dict) else {}
    themes: dict[str, dict[str, Any]] = {}
    for item in program.get("requiredDeepExperiments") or []:
        if not isinstance(item, dict):
            continue
        theme_id = _text(item.get("themeId"))
        campaign_id = _text(item.get("campaignId"))
        if not theme_id or not campaign_id:
            continue
        themes[theme_id] = {
            "themeId": theme_id,
            "themeName": _text(item.get("name")) or theme_id,
            "campaignId": campaign_id,
            "questionId": _text(item.get("questionId")).upper(),
            "experimentId": _text(item.get("experimentId")),
            "isolationPolicy": dict(isolation),
        }
    return {
        "problemId": _text(body.get("problemId")) or DEFAULT_PROGRAM_ID,
        "isolationPolicy": dict(isolation),
        "themes": themes,
    }


def frozen_theme_registry() -> dict[str, dict[str, Any]]:
    """Return the real theme/campaign registry derived from the frozen core."""
    return dict(_frozen_program_snapshot()["themes"])


def frozen_isolation_policy() -> dict[str, Any]:
    """Return the frozen isolation policy for scope derivation decisions."""
    return dict(_frozen_program_snapshot()["isolationPolicy"])


def resolve_theme_contract(
    team_id: str,
    *,
    theme_id: str,
    campaign_id: str = "",
) -> ThemeContract:
    """Derive a theme contract from the frozen registry and the activation ledger."""
    normalized_theme_id = _text(theme_id)
    normalized_campaign_id = _text(campaign_id)
    registry = frozen_theme_registry()
    record = registry.get(normalized_theme_id)
    program_id = _frozen_program_snapshot()["problemId"]
    if record is None:
        return ThemeContract(
            programId=DEV_PROGRAM_ID,
            themeId=normalized_theme_id or f"{DEV_THEME_PREFIX}unset",
            themeName=f"DEV theme {normalized_theme_id}" if normalized_theme_id else "DEV theme",
            campaignId=normalized_campaign_id or f"{DEV_THEME_PREFIX}campaign",
            status=ThemeContractStatus.DEV,
            isolationPolicy={},
            activatedAt="",
            activatedBy="",
            activationRef="",
        )
    activation = get_theme_activation(team_id, normalized_theme_id)
    activated = (
        bool(activation)
        and str(activation.get("status") or "") == "active"
        and str(activation.get("campaignId") or "") == record["campaignId"]
    )
    return ThemeContract(
        programId=program_id,
        themeId=record["themeId"],
        themeName=record["themeName"],
        campaignId=record["campaignId"],
        status=ThemeContractStatus.ACTIVE if activated else ThemeContractStatus.DRAFT,
        isolationPolicy=dict(record["isolationPolicy"]),
        activatedAt=_text(activation.get("activatedAt")) if activated else "",
        activatedBy=_text(activation.get("activatedBy")) if activated else "",
        activationRef=_text(activation.get("activationRef")) if activated else "",
    )


def activate_research_campaign(
    team_id: str,
    *,
    program_id: str,
    theme_id: str,
    campaign_id: str,
    activated_by: str,
    activation_ref: str = "",
) -> dict[str, Any]:
    """Formally activate one real theme + campaign pair.

    DEV themes are never activatable; a real campaign activation requires the
    theme to exist in the frozen program core and the campaign to match it.
    """
    theme = resolve_theme_contract(team_id, theme_id=theme_id, campaign_id=campaign_id)
    if theme.is_dev_theme():
        raise ResearchScopeDevThemeNotActivatableError(
            "DEV themes cannot be activated as real campaigns."
        )
    if _text(program_id) and _text(program_id) != theme.programId:
        raise ResearchScopeCampaignMismatchError(
            "activation program does not match the theme contract."
        )
    if _text(campaign_id) and _text(campaign_id) != theme.campaignId:
        raise ResearchScopeCampaignMismatchError(
            "campaign does not match the theme contract."
        )
    payload = build_campaign_activation_payload(
        program_id=theme.programId,
        theme_id=theme.themeId,
        campaign_id=theme.campaignId,
        activated_by=_text(activated_by) or "operator",
        activation_ref=_text(activation_ref) or f"research-campaign://{theme.themeId}",
    )
    return record_theme_campaign_activation(team_id, activation=payload)


def _derive_mode(
    theme: ThemeContract,
    requested_mode: str,
    *,
    campaign_id: str,
) -> ScopeMode:
    if theme.is_dev_theme():
        mode = ScopeMode.DEV
    elif theme.is_activated():
        mode = ScopeMode.FORMAL
    else:
        mode = ScopeMode.PLATFORM
    if requested_mode:
        if requested_mode == "formal":
            if theme.is_dev_theme():
                raise ResearchScopeDevThemeNotActivatableError(
                    "DEV themes cannot produce a formal scope."
                )
            if not theme.is_activated():
                raise ResearchScopeNotActivatedError(
                    "Formal scope requires an activated theme and campaign."
                )
            mode = ScopeMode.FORMAL
        elif requested_mode == "platform":
            mode = ScopeMode.PLATFORM
        elif requested_mode == "dev":
            if not theme.is_dev_theme():
                raise ResearchScopeInvalidModeError(
                    "dev mode is reserved for DEV themes."
                )
            mode = ScopeMode.DEV
        else:
            raise ResearchScopeInvalidModeError(
                f"unsupported scope mode: {requested_mode}"
            )
    if theme.is_dev_theme() and not campaign_id.startswith(DEV_THEME_PREFIX):
        raise ResearchScopeDevThemeNotActivatableError(
            "a DEV theme cannot bind a real campaign."
        )
    if not theme.is_dev_theme() and campaign_id and campaign_id != theme.campaignId:
        raise ResearchScopeCampaignMismatchError(
            "campaign does not match the theme contract."
        )
    return mode


def _artifact_locator(identity: dict[str, str], scope_hash: str) -> str:
    return (
        f"research-artifact://{identity['program']}/{identity['theme']}/"
        f"{identity['campaign']}/{identity['branch']}/{identity['question']}/{scope_hash}"
    )


def _ledger_root(identity: dict[str, str], scope_hash: str) -> str:
    return (
        f"research-ledger://{identity['program']}/{identity['theme']}/"
        f"{identity['campaign']}/{scope_hash}"
    )


def _cache_key(identity: dict[str, str], agent_id: str, scope_hash: str) -> str:
    return f"scope:{scope_hash}:{identity['branch']}:{agent_id}"


def resolve_research_scope(
    team_id: str,
    *,
    agent_id: str,
    scope_seed: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive the full scope envelope for one agent/question scope seed.

    Fails closed when any of the six formal scope fields is missing or empty.
    """
    seed = _mapping(scope_seed)
    identity: dict[str, str] = {}
    for field in FORMAL_SCOPE_FIELDS:
        value = _text(seed.get(field))
        if not value:
            raise ContractValidationError(
                f"formal scope requires a non-empty '{field}' field"
            )
        identity[field] = value
    agent = _text(seed.get("agentId") or agent_id)
    if not agent:
        raise ContractValidationError("scope requires a non-empty agentId")
    requested_mode = _text(seed.get("mode")).lower()
    theme = resolve_theme_contract(
        team_id,
        theme_id=identity["theme"],
        campaign_id=identity["campaign"],
    )
    mode = _derive_mode(theme, requested_mode, campaign_id=identity["campaign"])
    scope_hash = scope_hash_for(
        **identity,
        agent_id=agent,
        mode=mode.value,
    )
    envelope = ResearchScopeEnvelope(
        program=identity["program"],
        theme=identity["theme"],
        campaign=identity["campaign"],
        question=identity["question"],
        branch=identity["branch"],
        workflow=identity["workflow"],
        agentId=agent,
        mode=mode,
        scopeHash=scope_hash,
        artifactLocator=_artifact_locator(identity, scope_hash),
        ledgerRoot=_ledger_root(identity, scope_hash),
        cacheKey=_cache_key(identity, agent, scope_hash),
    )
    return envelope.to_dict()


def validate_scope_read(envelope: Mapping[str, Any]) -> bool:
    """Verify a persisted scope read against its full scope hash.

    Fails closed on shape defects and raises when the recomputed full scope
    hash does not match the stored one.
    """
    if not isinstance(envelope, Mapping):
        raise ContractValidationError("scope envelope must be an object")
    parsed = ResearchScopeEnvelope.from_dict(envelope)
    expected = scope_hash_for(
        program=parsed.program,
        theme=parsed.theme,
        campaign=parsed.campaign,
        question=parsed.question,
        branch=parsed.branch,
        workflow=parsed.workflow,
        agent_id=parsed.agentId,
        mode=parsed.mode.value,
    )
    if expected != parsed.scopeHash:
        raise ResearchScopeHashMismatchError(
            f"scope hash mismatch: stored {parsed.scopeHash}, derived {expected}"
        )
    return True


def platform_flow_readiness(
    team_id: str,
    *,
    program_id: str,
    theme_id: str,
    campaign_id: str,
    generated_at: str = "",
) -> dict[str, Any]:
    """Derive the platform flow readiness report for one theme/campaign."""
    from datetime import datetime, timezone

    theme = resolve_theme_contract(team_id, theme_id=theme_id, campaign_id=campaign_id)
    program = _text(program_id) or theme.programId
    campaign = _text(campaign_id) or theme.campaignId
    blockers: list[str] = []
    theme_activated = False
    if theme.is_dev_theme():
        mode = ScopeMode.DEV
        blockers = [BLOCKER_DEV_THEME_ONLY]
        if campaign and not campaign.startswith(DEV_THEME_PREFIX):
            blockers.append(BLOCKER_CAMPAIGN_THEME_MISMATCH)
    elif theme.is_activated():
        if campaign and campaign != theme.campaignId:
            mode = ScopeMode.PLATFORM
            blockers = [BLOCKER_CAMPAIGN_THEME_MISMATCH]
        else:
            mode = ScopeMode.FORMAL
            theme_activated = True
    else:
        mode = ScopeMode.PLATFORM
        blockers = [BLOCKER_THEME_NOT_ACTIVATED]

    scope_hash = scope_hash_for(
        program=program,
        theme=theme.themeId,
        campaign=theme.campaignId,
        question="",
        branch="",
        workflow="",
        agent_id="platform",
        mode=mode.value,
    )
    report = PlatformFlowReadinessReport(
        programId=program,
        themeId=theme.themeId,
        campaignId=theme.campaignId,
        themeActivated=theme_activated,
        mode=mode,
        devContractTestsAllowed=mode in {ScopeMode.DEV, ScopeMode.PLATFORM},
        realCampaignAllowed=theme_activated,
        formalArtifactReadWriteAllowed=theme_activated,
        blockers=tuple(blockers),
        scopeHash=scope_hash,
        privateMemoryMigration=(),
        generatedAt=_text(generated_at) or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    return report.to_dict()


def _classification_complete(item: Mapping[str, Any]) -> bool:
    classification = str(item.get("classificationStatus") or item.get("classification") or "").lower()
    return classification in {"complete", "completed"}


def _is_migratable_advisory_candidate(item: Mapping[str, Any]) -> bool:
    if not _classification_complete(item):
        return False
    if str(item.get("reusePolicy") or "").lower() != MIGRATION_REUSE_POLICY:
        return False
    if not str(item.get("evidenceStatus") or "").strip():
        return False
    return bool(item.get("needsRevalidation"))


def _advisory_candidate_pack(item: Mapping[str, Any], target_scope_hash: str) -> dict[str, Any]:
    return {
        "candidateId": str(item.get("candidateId") or item.get("memoryId") or item.get("id") or "").strip(),
        "summary": str(item.get("summary") or item.get("title") or "").strip()[:600],
        "sourceScopeHash": str(item.get("scopeHash") or "").strip()[:64],
        "reusePolicy": MIGRATION_REUSE_POLICY,
        "evidenceStatus": str(item.get("evidenceStatus") or "").strip()[:80],
        "needsRevalidation": True,
        "advisoryOnly": True,
        "promptInjected": False,
        "scientificEvidencePromotion": False,
        "targetScopeHash": target_scope_hash,
    }


def private_memory_migration_candidates(
    *,
    target_scope: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Decide which cross-theme private memory records may be migrated.

    Only fully classified, advisory-only, evidence-declared records that
    explicitly require revalidation are returned.  The result never injects a
    prompt by default and never promotes a record to scientific evidence.
    """
    if not isinstance(target_scope, Mapping):
        raise ContractValidationError("target_scope must be an object")
    envelope = ResearchScopeEnvelope.from_dict(target_scope)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in candidates or []:
        if not isinstance(raw, Mapping):
            rejected.append(dict(raw) if isinstance(raw, Mapping) else {})
            continue
        if _is_migratable_advisory_candidate(raw):
            accepted.append(_advisory_candidate_pack(raw, envelope.scopeHash))
        else:
            rejected.append(dict(raw))
    return {
        "targetScopeHash": envelope.scopeHash,
        "candidateCount": len(accepted),
        "rejectedCount": len(rejected),
        "candidates": accepted,
        "policy": {
            "reuse": "advisory_only",
            "promptInjection": "forbidden",
            "scientificEvidencePromotion": "forbidden",
            "revalidation": "required",
            "allowedReusePolicy": MIGRATION_REUSE_POLICY,
        },
    }