"""Auditable authorization records for real catalog batches.

The authorization is deliberately separate from the DEV control snapshot.  A
snapshot answers what the platform currently reports; this module records who
approved a concrete batch scope, when they approved it, and the exact readiness
evidence hash they relied on.  Future readiness reports can use the same API
without changing the Ledger schema or accepting a boolean confirmation as
evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from config.llm_security import validate_llm_provider_target
from config.settings import get_config
from core.llm.agent_runtime import AgentLlmResolutionError, resolve_agent_llm
from core.research.competition.question_result_package import (
    QuestionResultPackageError,
    canonical_model_policy,
    model_family_for_model_id,
)
from core.research.competition.real_control_batch import RealBatchError, real_plan
from core.research.competition.stage_one_completion_policy import (
    StageOneCompletionPolicyError,
    require_current_stage_one_policy_snapshot,
)
from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.catalog_hypothesis_flow_readiness import (
    CATALOG_HYPOTHESIS_FLOW_REPORT_KIND,
    RESEARCH_AUTHORIZATION_REQUIRED_ACTION,
    CatalogHypothesisFlowReadinessReport,
    catalog_hypothesis_flow_report_hash,
)
from core.research.workflow.contracts.research_team_role_contract import (
    CURRENT_RESEARCH_TEAM_ROLE_CONTRACT,
)
from core.research.workflow.ledger import CatalogRunAuthorization
from core.web.services import agent_directory_service
from core.web.services.team_workflow.research_runtime.team_role_source import (
    resolve_team_role_bindings,
)

from .formal_write_runtime import get_write_store

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OFFICIAL_DASHSCOPE_HOST = "dashscope.aliyuncs.com"

# Workflow purpose and product ownership are separate authorities. A purpose
# may have more than one product role (extraction), so the route snapshot
# keeps a role-indexed map instead of choosing a model by purpose alone.
_CATALOG_MODEL_PURPOSE_ROLES: dict[str, tuple[str, ...]] = {
    "source_discovery": ("challenge_cup_search",),
    "extraction": (
        "challenge_cup_extractor",
        "challenge_cup_knowledge_manager",
    ),
    "reasoning": ("challenge_cup_experiment_revision",),
    "review": ("challenge_cup_evaluator",),
    "governance": ("challenge_cup_knowledge_manager",),
    # The execution steward is frozen and validated with the six-Agent
    # contract, but its controlled_run node remains system-owned until the
    # governed deep-experiment phase.
    "execution": ("challenge_cup_execution_steward",),
}


class CatalogRunAuthorizationError(ValueError):
    """The approval evidence is malformed, stale, or unavailable."""


def canonical_sha256(value: Mapping[str, Any] | list[Any] | str) -> str:
    """Hash JSON evidence with one stable representation."""

    if isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _require_sha256(value: str, *, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise CatalogRunAuthorizationError(
            f"{label} must be a lowercase sha256 hex digest."
        )
    return normalized


def readiness_report_sha256(
    evidence: Mapping[str, Any] | list[Any] | str,
    *,
    trusted_authority: Any | None = None,
) -> str:
    """Return the canonical hash of a readiness report/evidence object.

    Formal catalog reports are validated before hashing.  Their hash excludes
    the self-reference and generated timestamp according to the formal
    contract; ordinary DEV evidence keeps the generic canonical JSON hash.
    """

    if isinstance(evidence, str) and _SHA256_RE.fullmatch(evidence.strip().lower()):
        return evidence.strip().lower()
    if isinstance(evidence, Mapping) and evidence.get("reportKind") == CATALOG_HYPOTHESIS_FLOW_REPORT_KIND:
        try:
            report = CatalogHypothesisFlowReadinessReport.from_dict(
                evidence,
                trusted_authority=trusted_authority,
            )
        except (ContractValidationError, TypeError, ValueError, KeyError) as exc:
            raise CatalogRunAuthorizationError(
                "formal catalog readiness report is invalid"
            ) from exc
        return catalog_hypothesis_flow_report_hash(report.to_dict())
    return canonical_sha256(evidence)


def require_readiness_report_sha256(value: str) -> str:
    """Validate a caller-provided digest rather than hashing the text again."""

    return _require_sha256(value, label="readiness_report_sha256")


def batch_scope_sha256(batch_scope: Mapping[str, Any] | list[Any]) -> str:
    return canonical_sha256(batch_scope)


def _model_policy_from_scope(
    scope: Mapping[str, Any],
    *,
    required: bool,
) -> dict[str, Any] | None:
    raw = scope.get("modelPolicy")
    if raw is None:
        if required:
            raise CatalogRunAuthorizationError(
                "catalog authorization model policy snapshot is required"
            )
        return None
    if not isinstance(raw, Mapping):
        raise CatalogRunAuthorizationError(
            "catalog authorization model policy snapshot is malformed"
        )
    try:
        normalized = canonical_model_policy(dict(raw))
    except QuestionResultPackageError as exc:
        raise CatalogRunAuthorizationError(
            "catalog authorization model policy snapshot is invalid"
        ) from exc
    if dict(raw) != normalized:
        raise CatalogRunAuthorizationError(
            "catalog authorization model policy snapshot is not canonical"
        )
    return normalized


def _provider_target_is_valid(provider: Any) -> bool:
    try:
        validate_llm_provider_target(
            provider,
            context="formal_research_dialogue_provider",
        )
    except (TypeError, ValueError):
        return False
    return True


def _official_provider(provider: Any) -> bool:
    service_class = str(getattr(provider, "service_class", "") or "").strip().lower()
    vendor = str(getattr(provider, "vendor", "") or "").strip().lower()
    provider_kind = str(getattr(provider, "kind", "") or "").strip().lower()
    endpoint_host = (
        urlparse(str(getattr(provider, "base_url", "") or "").strip()).hostname
        or ""
    ).strip().lower().rstrip(".")
    if not _provider_target_is_valid(provider):
        return False
    return (
        service_class == "official_api"
        and (vendor == "aliyun" or provider_kind == "aliyun")
        and endpoint_host == _OFFICIAL_DASHSCOPE_HOST
    )


def _resolve_dialogue_model_binding(
    agent_id: str,
    agent: Mapping[str, Any],
    config: Any,
) -> dict[str, Any]:
    """Resolve one server-owned Agent dialogue route without fallback.

    resolve_agent_llm selects the Agent binding, while the effective model
    library entry supplies the canonical upstream id. A missing library entry
    is a hard failure: using resolved.model here would allow a display or
    legacy profile value to become formal evidence without a resolvable model
    reference.
    """

    try:
        resolved = resolve_agent_llm(dict(agent), "dialogue", config=config)
    except (AgentLlmResolutionError, KeyError, TypeError, ValueError) as exc:
        raise CatalogRunAuthorizationError(
            "a formal research Agent dialogue LLM binding cannot be resolved"
        ) from exc
    runtime_config = resolved.config or config
    try:
        model_ref = runtime_config.llm.resolve_model_ref(
            resolved.model_ref or resolved.model_id
        )
        provider = runtime_config.llm.get_provider(resolved.provider_id)
    except (KeyError, TypeError, ValueError) as exc:
        raise CatalogRunAuthorizationError(
            "a formal research Agent dialogue LLM binding is not canonical"
        ) from exc
    normalized_agent_id = str(agent_id or "").strip()
    resolved_agent_id = str(getattr(resolved, "agent_id", "") or "").strip()
    if (
        normalized_agent_id
        and resolved_agent_id
        and resolved_agent_id != normalized_agent_id
    ):
        raise CatalogRunAuthorizationError(
            "formal research Agent dialogue binding does not match the team role"
        )
    provider_id = str(
        getattr(provider, "provider_id", "") or getattr(resolved, "provider_id", "")
    ).strip()
    if not model_ref or not provider_id or not _provider_target_is_valid(provider):
        raise CatalogRunAuthorizationError(
            "formal research Agent dialogue LLM must use a valid configured provider"
        )
    ref_provider, separator, _ = str(model_ref).partition("/")
    if not separator or ref_provider.strip().casefold() != provider_id.casefold():
        raise CatalogRunAuthorizationError(
            "formal research Agent dialogue modelRef is not a canonical provider/model ref"
        )
    model_library = getattr(runtime_config.llm, "model_library", {}) or {}
    entry = model_library.get(model_ref) if isinstance(model_library, Mapping) else None
    if not isinstance(entry, Mapping):
        raise CatalogRunAuthorizationError(
            "a formal research Agent dialogue LLM binding has no effective upstream model"
        )
    model_id = str(
        entry.get("upstream_id")
        or entry.get("model")
    ).strip()
    entry_provider_id = str(entry.get("provider_id") or "").strip()
    if entry_provider_id and entry_provider_id.casefold() != provider_id.casefold():
        raise CatalogRunAuthorizationError(
            "formal research Agent dialogue model library provider does not match binding"
        )
    return {
        "agentId": normalized_agent_id or resolved_agent_id,
        "modelRef": str(model_ref).strip(),
        "providerId": provider_id,
        "modelId": model_id,
        "officialProvider": _official_provider(provider),
    }


def _dialogue_model_identity(agent: Mapping[str, Any], config: Any) -> tuple[str, str]:
    route = _resolve_dialogue_model_binding(
        str(agent.get("agentId") or "").strip(),
        agent,
        config,
    )
    return route["providerId"], route["modelId"]


def _resolve_catalog_dialogue_routes(team_id: str) -> dict[str, dict[str, Any]]:
    """Resolve every current product Agent binding exactly once for a launch."""

    bindings = resolve_team_role_bindings(str(team_id or "").strip())
    if not bindings:
        raise CatalogRunAuthorizationError(
            "formal six-Agent team dialogue bindings are unavailable"
        )
    config = get_config()
    routes: dict[str, dict[str, Any]] = {}
    seen_agents: set[str] = set()
    for role in CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.product_agents:
        agent_id = next(
            (
                str(bindings.get(key) or "").strip()
                for key in (role.product_role_id, *role.legacy_role_aliases)
                if str(bindings.get(key) or "").strip()
            ),
            "",
        )
        if not agent_id or agent_id in seen_agents:
            raise CatalogRunAuthorizationError(
                f"formal six-Agent binding is missing or duplicated: {role.product_role_id}"
            )
        seen_agents.add(agent_id)
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        if not isinstance(agent, Mapping):
            raise CatalogRunAuthorizationError(
                f"formal six-Agent binding references an unavailable Agent: {agent_id}"
            )
        routes[role.product_role_id] = _resolve_dialogue_model_binding(
            agent_id,
            agent,
            config,
        )
    return routes


def _canonical_model_policy_for_routes(
    routes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    provider_ids = sorted(
        {str(route["providerId"]).strip() for route in routes.values()}
    )
    model_ids = sorted({str(route["modelId"]).strip() for route in routes.values()})
    families = sorted(
        {
            model_family_for_model_id(model_id)
            for model_id in model_ids
            if model_family_for_model_id(model_id)
        }
    )
    if len(families) != 1:
        raise CatalogRunAuthorizationError(
            "formal six-Agent dialogue routes must use one model family"
        )
    try:
        return canonical_model_policy(
            {
                "family": families[0],
                "providerIds": provider_ids,
                "modelIds": model_ids,
                "requireOfficialProvider": all(
                    route.get("officialProvider") is True
                    for route in routes.values()
                ),
            }
        )
    except QuestionResultPackageError as exc:
        raise CatalogRunAuthorizationError(
            "server model policy snapshot could not be canonicalized"
        ) from exc


def resolve_catalog_model_policy(team_id: str) -> dict[str, Any]:
    """Resolve the server-owned six-Agent dialogue model allowlist.

    The returned snapshot is derived from the current team bindings and
    operator LLM config.  It never consumes a package or client-supplied hash.
    """

    routes = _resolve_catalog_dialogue_routes(team_id)
    return _canonical_model_policy_for_routes(routes)


def resolve_catalog_model_routing_policy(team_id: str) -> dict[str, Any]:
    """Build the immutable formal route snapshot for a Challenge Cup launch.

    The snapshot is derived only from the server role bindings and the
    effective Agent dialogue model library. modelPolicySha256 is the
    canonical policy digest, not a digest of this envelope, so receipts and
    authorization records share one stable identity.
    """

    role_routes = _resolve_catalog_dialogue_routes(team_id)
    required_policy = _canonical_model_policy_for_routes(role_routes)
    routes: dict[str, Any] = {}
    for purpose, role_ids in _CATALOG_MODEL_PURPOSE_ROLES.items():
        by_role: dict[str, dict[str, Any]] = {}
        for role_id in role_ids:
            route = role_routes.get(role_id)
            if route is None:
                raise CatalogRunAuthorizationError(
                    f"formal model route is missing product role: {role_id}"
                )
            normalized_route = dict(route)
            normalized_route["productRoleId"] = role_id
            by_role[role_id] = normalized_route
        routes[purpose] = {"byProductRole": by_role}
    return {
        "requiredModelPolicy": required_policy,
        "modelPolicySha256": required_policy["policySha256"],
        "routes": routes,
    }


def _canonical_batch_scope(
    plan_id: str,
    batch_scope: Mapping[str, Any] | list[Any],
    *,
    require_model_policy: bool = False,
    require_stage_one_policy: bool = False,
) -> dict[str, Any]:
    """Validate a scope against the frozen real-batch plan definition."""

    normalized_plan = str(plan_id or "").strip()
    try:
        plan = real_plan(normalized_plan)
    except (RealBatchError, ValueError) as exc:
        raise CatalogRunAuthorizationError(
            "catalog authorization plan does not match a canonical real plan"
        ) from exc
    if not isinstance(batch_scope, Mapping):
        raise CatalogRunAuthorizationError(
            "catalog authorization scope must be a JSON object"
        )
    scope_plan = str(batch_scope.get("planId") or "").strip()
    scope_gate = str(batch_scope.get("gateId") or "").strip()
    question_ids = batch_scope.get("questionIds")
    expected_question_ids = [str(question_id) for question_id in plan.question_ids]
    if (
        scope_plan != normalized_plan
        or scope_gate != str(plan.gate_id)
        or not isinstance(question_ids, list)
        or question_ids != expected_question_ids
    ):
        raise CatalogRunAuthorizationError(
            "catalog authorization scope does not match the canonical plan"
        )
    allowed_fields = {"planId", "gateId", "questionIds"}
    if "modelPolicy" in batch_scope:
        allowed_fields.add("modelPolicy")
    if "stageOneCompletionPolicy" in batch_scope:
        allowed_fields.add("stageOneCompletionPolicy")
    unknown = sorted(set(batch_scope) - allowed_fields)
    if unknown:
        raise CatalogRunAuthorizationError(
            "catalog authorization scope contains unsupported fields: "
            + ", ".join(str(field) for field in unknown)
        )
    normalized = {
        "planId": normalized_plan,
        "gateId": str(plan.gate_id),
        "questionIds": expected_question_ids,
    }
    model_policy = _model_policy_from_scope(batch_scope, required=require_model_policy)
    if model_policy is not None:
        normalized["modelPolicy"] = model_policy
    raw_stage_one_policy = batch_scope.get("stageOneCompletionPolicy")
    if raw_stage_one_policy is None:
        if require_stage_one_policy:
            raise CatalogRunAuthorizationError(
                "catalog authorization stage-one completion policy is required"
            )
    else:
        if not isinstance(raw_stage_one_policy, Mapping):
            raise CatalogRunAuthorizationError(
                "catalog authorization stage-one completion policy is malformed"
            )
        try:
            stage_one_policy = require_current_stage_one_policy_snapshot(
                raw_stage_one_policy
            )
        except StageOneCompletionPolicyError as exc:
            raise CatalogRunAuthorizationError(
                "catalog authorization stage-one completion policy is invalid"
            ) from exc
        if not set(expected_question_ids) <= set(stage_one_policy["questionIds"]):
            raise CatalogRunAuthorizationError(
                "catalog authorization stage-one completion policy question scope "
                "does not cover the plan"
            )
        normalized["stageOneCompletionPolicy"] = stage_one_policy
    return normalized


def readiness_hash_from_snapshot(
    snapshot: Mapping[str, Any],
    *,
    expected_team_id: str | None = None,
) -> str:
    """Resolve one fail-closed readiness hash from a server snapshot.

    A snapshot may carry a top-level digest, a report body, or both.  When both
    are present they must agree; a stale top-level digest never overrides a
    changed report body.  The platform action and optional team projection are
    checked here so every launch surface shares the same trust boundary.
    """

    if not isinstance(snapshot, Mapping):
        raise CatalogRunAuthorizationError("readiness snapshot must be an object")
    expected_team = str(expected_team_id or "").strip()
    snapshot_team = str(snapshot.get("teamId") or "").strip()
    if expected_team and snapshot_team and snapshot_team != expected_team:
        raise CatalogRunAuthorizationError("readiness snapshot teamId does not match request")
    if str(snapshot.get("nextLegalAction") or "").strip() != RESEARCH_AUTHORIZATION_REQUIRED_ACTION:
        raise CatalogRunAuthorizationError(
            "readiness snapshot is not at RESEARCH_AUTHORIZATION_REQUIRED"
        )

    report_values = [
        snapshot.get(key)
        for key in ("readinessReport", "report")
        if isinstance(snapshot.get(key), (Mapping, list))
    ]
    body_hashes = [readiness_report_sha256(value) for value in report_values]
    if body_hashes and any(value != body_hashes[0] for value in body_hashes[1:]):
        raise CatalogRunAuthorizationError(
            "readiness snapshot contains conflicting report bodies"
        )

    supplied_hashes: list[str] = []
    for key in (
        "readinessReportSha256",
        "readinessReportHash",
        "catalogReadinessReportSha256",
    ):
        if key in snapshot:
            value = str(snapshot.get(key) or "").strip()
            if not value:
                raise CatalogRunAuthorizationError(
                    f"{key} must be a sha256 hex digest"
                )
            supplied_hashes.append(_require_sha256(value, label=key))
    if supplied_hashes and any(value != supplied_hashes[0] for value in supplied_hashes[1:]):
        raise CatalogRunAuthorizationError(
            "readiness snapshot contains conflicting report hashes"
        )
    if supplied_hashes and body_hashes and supplied_hashes[0] != body_hashes[0]:
        raise CatalogRunAuthorizationError(
            "readiness snapshot report hash does not match report body"
        )
    if supplied_hashes:
        return supplied_hashes[0]
    if body_hashes:
        return body_hashes[0]
    raise CatalogRunAuthorizationError(
        "readiness snapshot has no canonical report/hash"
    )


def _record_hash_payload(record: CatalogRunAuthorization) -> dict[str, Any]:
    try:
        scope = json.loads(record.batch_scope_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CatalogRunAuthorizationError("catalog authorization scope is invalid") from exc
    return {
        "authorizationId": record.authorization_id,
        "teamId": record.team_id,
        "planId": record.plan_id,
        "batchScope": scope,
        "scopeHash": record.scope_hash,
        "approvedBy": record.approved_by,
        "approvedAtMs": record.approved_at_ms,
        "readinessReportSha256": record.readiness_report_sha256,
        "createdAtMs": record.created_at_ms,
    }


def expected_record_hash(record: CatalogRunAuthorization) -> str:
    return canonical_sha256(_record_hash_payload(record))


def validate_catalog_run_authorization(
    record: CatalogRunAuthorization,
    *,
    team_id: str | None = None,
    plan_id: str | None = None,
    scope_hash: str | None = None,
    readiness_sha256: str | None = None,
    question_id: str | None = None,
    require_model_policy: bool = False,
    require_stage_one_policy: bool = False,
) -> bool:
    """Validate immutable content and optional lookup scope before use."""

    if team_id is not None and record.team_id != str(team_id):
        return False
    if plan_id is not None and record.plan_id != str(plan_id):
        return False
    try:
        report_hash = _require_sha256(
            record.readiness_report_sha256, label="readiness_report_sha256"
        )
        expected_scope_hash = _require_sha256(record.scope_hash, label="scope_hash")
        scope = json.loads(record.batch_scope_json)
        canonical_scope = _canonical_batch_scope(
            record.plan_id,
            scope,
            require_model_policy=require_model_policy,
            require_stage_one_policy=require_stage_one_policy,
        )
    except (CatalogRunAuthorizationError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if batch_scope_sha256(canonical_scope) != expected_scope_hash:
        return False
    if question_id is not None:
        authorized_question_ids = {
            str(value).strip() for value in canonical_scope["questionIds"]
        }
        # The stage-one policy scope covers the plan, so every question the
        # approved policy snapshot names is inside the authorized batch scope.
        policy_scope = canonical_scope.get("stageOneCompletionPolicy") or {}
        authorized_question_ids.update(
            str(value).strip() for value in policy_scope.get("questionIds") or ()
        )
        if str(question_id).strip() not in authorized_question_ids:
            return False
    if scope_hash is not None and expected_scope_hash != str(scope_hash):
        return False
    if readiness_sha256 is not None and report_hash != str(readiness_sha256):
        return False
    if not record.authorization_id or not record.team_id or not record.plan_id:
        return False
    if not record.approved_by.strip() or record.approved_at_ms <= 0 or record.created_at_ms <= 0:
        return False
    return record.record_hash == expected_record_hash(record)


def find_catalog_run_authorization(
    team_id: str,
    *,
    plan_id: str,
    batch_scope: Mapping[str, Any] | list[Any],
    readiness_report_sha256_value: str | None = None,
    readiness_report_hash: str | None = None,
    require_model_policy: bool = False,
    require_stage_one_policy: bool = False,
) -> CatalogRunAuthorization | None:
    """Find and validate the exact approval for a current scope/evidence hash."""

    normalized_team = str(team_id or "").strip()
    normalized_plan = str(plan_id or "").strip()
    if not normalized_team or not normalized_plan:
        return None
    try:
        canonical_scope = _canonical_batch_scope(
            normalized_plan,
            batch_scope,
            require_model_policy=require_model_policy,
            require_stage_one_policy=require_stage_one_policy,
        )
    except CatalogRunAuthorizationError:
        return None
    scope_hash = batch_scope_sha256(canonical_scope)
    raw_report_hash = readiness_report_sha256_value or readiness_report_hash
    if not raw_report_hash:
        return None
    if (
        readiness_report_sha256_value is not None
        and readiness_report_hash is not None
        and readiness_report_sha256_value != readiness_report_hash
    ):
        return None
    report_hash = _require_sha256(raw_report_hash, label="readiness_report_sha256")
    store = get_write_store()
    record = store.find_catalog_run_authorization(
        team_id=normalized_team,
        plan_id=normalized_plan,
        scope_hash=scope_hash,
        readiness_report_sha256=report_hash,
    )
    if record is None or not validate_catalog_run_authorization(
        record,
        team_id=normalized_team,
        plan_id=normalized_plan,
        scope_hash=scope_hash,
        readiness_sha256=report_hash,
        require_model_policy=require_model_policy,
        require_stage_one_policy=require_stage_one_policy,
    ):
        return None
    return record


def record_catalog_run_authorization(
    team_id: str,
    *,
    plan_id: str,
    batch_scope: Mapping[str, Any] | list[Any],
    approved_by: str,
    readiness_evidence: Mapping[str, Any] | list[Any] | str | None = None,
    readiness_report_sha256_value: str | None = None,
    readiness_report_hash: str | None = None,
    approved_at_ms: int | None = None,
    authorization_id: str | None = None,
    require_model_policy: bool = False,
    require_stage_one_policy: bool = False,
) -> CatalogRunAuthorization:
    """Persist one approval, idempotently, for an exact scope/evidence pair.

    Callers that already have a trusted report hash may pass it directly.  If
    raw readiness evidence is supplied, its hash is computed here; supplying
    both is allowed only when they agree.  No platform marker or ``confirmed``
    boolean is read by this generic API.
    """

    normalized_team = str(team_id or "").strip()
    normalized_plan = str(plan_id or "").strip()
    approver = str(approved_by or "").strip()
    if not normalized_team or not normalized_plan:
        raise CatalogRunAuthorizationError("team_id and plan_id are required")
    if not approver:
        raise CatalogRunAuthorizationError("approved_by is required")
    if not isinstance(batch_scope, (Mapping, list)):
        raise CatalogRunAuthorizationError("batch_scope must be JSON object/array")
    canonical_scope = _canonical_batch_scope(
        normalized_plan,
        batch_scope,
        require_model_policy=require_model_policy,
        require_stage_one_policy=require_stage_one_policy,
    )
    if (
        readiness_report_sha256_value is not None
        and readiness_report_hash is not None
        and readiness_report_sha256_value != readiness_report_hash
    ):
        raise CatalogRunAuthorizationError(
            "readiness_report_sha256 and readiness_report_hash do not agree"
        )
    explicit_report_hash = readiness_report_sha256_value or readiness_report_hash
    if readiness_evidence is None and explicit_report_hash is None:
        raise CatalogRunAuthorizationError("readiness evidence/hash is required")
    evidence_hash = (
        readiness_report_sha256(readiness_evidence)
        if readiness_evidence is not None
        else None
    )
    supplied_hash = (
        _require_sha256(
            explicit_report_hash,
            label="readiness_report_sha256",
        )
        if explicit_report_hash is not None
        else None
    )
    if evidence_hash and supplied_hash and evidence_hash != supplied_hash:
        raise CatalogRunAuthorizationError(
            "readiness evidence does not match readiness_report_sha256"
        )
    report_hash = supplied_hash or evidence_hash
    assert report_hash is not None
    scope_hash = batch_scope_sha256(canonical_scope)
    store = get_write_store()
    existing = store.find_catalog_run_authorization(
        team_id=normalized_team,
        plan_id=normalized_plan,
        scope_hash=scope_hash,
        readiness_report_sha256=report_hash,
    )
    if existing is not None:
        if not validate_catalog_run_authorization(
            existing,
            team_id=normalized_team,
            plan_id=normalized_plan,
            scope_hash=scope_hash,
            readiness_sha256=report_hash,
            require_model_policy=require_model_policy,
            require_stage_one_policy=require_stage_one_policy,
        ):
            raise CatalogRunAuthorizationError("existing catalog authorization is corrupt")
        return existing

    now_ms = int(approved_at_ms if approved_at_ms is not None else time.time() * 1000)
    if now_ms <= 0:
        raise CatalogRunAuthorizationError("approved_at_ms must be positive")
    auth_id = str(authorization_id or "").strip() or (
        "auth-" + canonical_sha256(
            {
                "teamId": normalized_team,
                "planId": normalized_plan,
                "scopeHash": scope_hash,
                "readinessReportSha256": report_hash,
            }
        )[:32]
    )
    scope_json = json.dumps(
        canonical_scope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    record = CatalogRunAuthorization(
        authorization_id=auth_id,
        team_id=normalized_team,
        plan_id=normalized_plan,
        batch_scope_json=scope_json,
        scope_hash=scope_hash,
        approved_by=approver,
        approved_at_ms=now_ms,
        readiness_report_sha256=report_hash,
        record_hash="",
        created_at_ms=now_ms,
    )
    record = CatalogRunAuthorization(
        **{**record.__dict__, "record_hash": expected_record_hash(record)}
    )

    def mutate(uow):
        uow.repository.insert_catalog_run_authorization(record)
        return uow.repository.find_catalog_run_authorization(
            team_id=normalized_team,
            plan_id=normalized_plan,
            scope_hash=scope_hash,
            readiness_report_sha256=report_hash,
        )

    persisted = store.submit(mutate, force_flush=True).result(timeout=15)
    if persisted is None or not validate_catalog_run_authorization(
        persisted,
        team_id=normalized_team,
        plan_id=normalized_plan,
        scope_hash=scope_hash,
        readiness_sha256=report_hash,
        require_model_policy=require_model_policy,
        require_stage_one_policy=require_stage_one_policy,
    ):
        raise CatalogRunAuthorizationError("catalog authorization was not persisted")
    return persisted


def authorization_to_dict(record: CatalogRunAuthorization) -> dict[str, Any]:
    return {
        "authorizationId": record.authorization_id,
        "teamId": record.team_id,
        "planId": record.plan_id,
        "batchScope": json.loads(record.batch_scope_json),
        "scopeHash": record.scope_hash,
        "approvedBy": record.approved_by,
        "approvedAtMs": record.approved_at_ms,
        "readinessReportSha256": record.readiness_report_sha256,
        "recordHash": record.record_hash,
        "createdAtMs": record.created_at_ms,
    }


def authorized_model_policy_sha256(record: CatalogRunAuthorization) -> str:
    """Return the policy hash only from a validated durable authorization."""

    try:
        scope = json.loads(record.batch_scope_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CatalogRunAuthorizationError(
            "catalog authorization scope is invalid"
        ) from exc
    policy = _model_policy_from_scope(scope, required=True)
    assert policy is not None
    return _require_sha256(policy["policySha256"], label="model_policy_sha256")


__all__ = [
    "CatalogRunAuthorizationError",
    "authorization_to_dict",
    "authorized_model_policy_sha256",
    "batch_scope_sha256",
    "canonical_sha256",
    "expected_record_hash",
    "find_catalog_run_authorization",
    "readiness_hash_from_snapshot",
    "readiness_report_sha256",
    "record_catalog_run_authorization",
    "require_readiness_report_sha256",
    "resolve_catalog_model_policy",
    "resolve_catalog_model_routing_policy",
    "validate_catalog_run_authorization",
]
