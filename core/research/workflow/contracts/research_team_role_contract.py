"""Versioned Challenge Cup research-team role and participant contract.

The contract separates six long-lived product Agent identities from deterministic
system capabilities.  It is intentionally pure: team materialization, migration,
prompt/tool policy and meeting persistence consume this snapshot in later layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ._canonical import sha256_hex
from ._validation import ContractValidationError

RESEARCH_TEAM_ROLE_CONTRACT_ID = "challenge-cup-research-team"
RESEARCH_TEAM_ROLE_CONTRACT_VERSION = 2
RESEARCH_TEAM_ROLE_SEMANTIC_VERSION = "2.0.0"
RESEARCH_PARTICIPANT_POLICY_VERSION = 2
LEGACY_READ_MODE = "dual_read_append_only_history"

CANDIDATE_GENERATION_MEETING_TYPE = "hypothesis_candidate_generation"
HYPOTHESIS_REVIEW_MEETING_TYPE = "hypothesis_review"


def _require_text(value: Any, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ContractValidationError(f"{field_name} must be non-empty")
    return normalized


def _require_unique(values: tuple[str, ...], *, field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ContractValidationError(f"{field_name} must be unique")


@dataclass(frozen=True, slots=True)
class ProductAgentRole:
    """One product Agent identity; legacy aliases are read-only migration hints."""

    product_role_id: str
    label: str
    purpose: str
    legacy_role_aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.product_role_id, field_name="productRoleId")
        _require_text(self.label, field_name="product role label")
        _require_text(self.purpose, field_name="product role purpose")
        normalized_aliases = tuple(
            _require_text(alias, field_name="legacy role alias")
            for alias in self.legacy_role_aliases
        )
        _require_unique(normalized_aliases, field_name="legacy role aliases")

    def to_dict(self) -> dict[str, Any]:
        return {
            "productRoleId": self.product_role_id,
            "label": self.label,
            "purpose": self.purpose,
        }


@dataclass(frozen=True, slots=True)
class SystemCapability:
    """A deterministic/system-owned capability that is not a product Agent."""

    capability_id: str
    label: str
    purpose: str
    legacy_role_aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.capability_id, field_name="capabilityId")
        _require_text(self.label, field_name="system capability label")
        _require_text(self.purpose, field_name="system capability purpose")
        normalized_aliases = tuple(
            _require_text(alias, field_name="legacy role alias")
            for alias in self.legacy_role_aliases
        )
        _require_unique(normalized_aliases, field_name="legacy role aliases")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilityId": self.capability_id,
            "label": self.label,
            "purpose": self.purpose,
        }


@dataclass(frozen=True, slots=True)
class ResearchParticipantPolicy:
    """Required and optional product roles for one meeting type."""

    meeting_type: str
    required_product_role_ids: tuple[str, ...]
    optional_product_role_ids: tuple[str, ...] = ()
    coordinator_capability_id: str = "coordinator"

    def __post_init__(self) -> None:
        _require_text(self.meeting_type, field_name="meetingType")
        if not self.required_product_role_ids:
            raise ContractValidationError(
                "participant policy requires at least one product role"
            )
        required = tuple(
            _require_text(role_id, field_name="required product role")
            for role_id in self.required_product_role_ids
        )
        optional = tuple(
            _require_text(role_id, field_name="optional product role")
            for role_id in self.optional_product_role_ids
        )
        _require_unique(required, field_name="required product role ids")
        _require_unique(optional, field_name="optional product role ids")
        overlap = set(required) & set(optional)
        if overlap:
            raise ContractValidationError(
                "participant policy required and optional product roles must be disjoint"
            )
        _require_text(
            self.coordinator_capability_id,
            field_name="coordinatorCapabilityId",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "meetingType": self.meeting_type,
            "requiredProductRoleIds": list(self.required_product_role_ids),
            "optionalProductRoleIds": list(self.optional_product_role_ids),
            "coordinatorCapabilityId": self.coordinator_capability_id,
        }


@dataclass(frozen=True, slots=True)
class ResearchTeamRoleContract:
    """Fail-closed, deterministic role contract shared by team and workflow layers."""

    team_role_contract_id: str
    team_role_contract_version: int
    semantic_version: str
    participant_policy_version: int
    legacy_read_mode: str
    product_agents: tuple[ProductAgentRole, ...]
    system_capabilities: tuple[SystemCapability, ...]
    participant_policies: tuple[ResearchParticipantPolicy, ...]

    def __post_init__(self) -> None:
        _require_text(self.team_role_contract_id, field_name="teamRoleContractId")
        if self.team_role_contract_version < 1:
            raise ContractValidationError("teamRoleContractVersion must be positive")
        _require_text(self.semantic_version, field_name="semanticVersion")
        if self.participant_policy_version < 1:
            raise ContractValidationError("participantPolicyVersion must be positive")
        _require_text(self.legacy_read_mode, field_name="legacyReadMode")
        if not self.product_agents:
            raise ContractValidationError("research team requires product Agents")

        product_role_ids = self.product_role_ids
        system_capability_ids = self.system_capability_ids
        _require_unique(product_role_ids, field_name="product role ids")
        _require_unique(system_capability_ids, field_name="system capability ids")
        if set(product_role_ids) & set(system_capability_ids):
            raise ContractValidationError(
                "product role ids and system capability ids must be disjoint"
            )

        known_owner_ids = set(product_role_ids) | set(system_capability_ids)
        aliases_by_owner = [
            (role.product_role_id, role.legacy_role_aliases)
            for role in self.product_agents
        ] + [
            (capability.capability_id, capability.legacy_role_aliases)
            for capability in self.system_capabilities
        ]
        alias_owner: dict[str, str] = {}
        for owner_id, aliases in aliases_by_owner:
            for alias in aliases:
                if alias in known_owner_ids and alias != owner_id:
                    raise ContractValidationError(
                        f"legacy role alias '{alias}' conflicts with a canonical owner id"
                    )
                previous_owner = alias_owner.get(alias)
                if previous_owner is not None and previous_owner != owner_id:
                    raise ContractValidationError(
                        f"legacy role alias '{alias}' is assigned to more than one owner"
                    )
                alias_owner[alias] = owner_id

        meeting_types = tuple(policy.meeting_type for policy in self.participant_policies)
        _require_unique(meeting_types, field_name="participant policy meeting types")
        known_product_roles = set(product_role_ids)
        known_system_capabilities = set(system_capability_ids)
        for policy in self.participant_policies:
            for role_id in (
                *policy.required_product_role_ids,
                *policy.optional_product_role_ids,
            ):
                if role_id not in known_product_roles:
                    raise ContractValidationError(
                        f"participant policy references unknown product role: {role_id}"
                    )
            if policy.coordinator_capability_id not in known_system_capabilities:
                raise ContractValidationError(
                    "participant policy references unknown coordinator capability: "
                    f"{policy.coordinator_capability_id}"
                )

    @property
    def product_role_ids(self) -> tuple[str, ...]:
        return tuple(role.product_role_id for role in self.product_agents)

    @property
    def system_capability_ids(self) -> tuple[str, ...]:
        return tuple(
            capability.capability_id for capability in self.system_capabilities
        )

    def resolve_role_owner(
        self,
        role_key: Any,
    ) -> tuple[Literal["product_agent", "system_capability"], str] | None:
        """Resolve a canonical/legacy role key to its contract-owned identity.

        The contract is the only alias authority.  Callers must inspect the
        owner type instead of assuming every historical role represents a
        product Agent.
        """

        normalized = str(role_key or "").strip().lower()
        if not normalized:
            return None
        for role in self.product_agents:
            values = (role.product_role_id, *role.legacy_role_aliases)
            if normalized in {value.strip().lower() for value in values}:
                return ("product_agent", role.product_role_id)
        for capability in self.system_capabilities:
            values = (capability.capability_id, *capability.legacy_role_aliases)
            if normalized in {value.strip().lower() for value in values}:
                return ("system_capability", capability.capability_id)
        return None

    def resolve_product_role_id(self, role_key: Any) -> str | None:
        """Return the canonical product role, excluding system capabilities."""

        owner = self.resolve_role_owner(role_key)
        if owner is None or owner[0] != "product_agent":
            return None
        return owner[1]

    def participant_policy(self, meeting_type: str) -> ResearchParticipantPolicy:
        normalized = _require_text(meeting_type, field_name="meetingType")
        for policy in self.participant_policies:
            if policy.meeting_type == normalized:
                return policy
        raise ContractValidationError(
            f"participant policy is not defined for meeting type: {normalized}"
        )

    def _canonical_payload(self) -> dict[str, Any]:
        return {
            "teamRoleContractId": self.team_role_contract_id,
            "teamRoleContractVersion": self.team_role_contract_version,
            "semanticVersion": self.semantic_version,
            "productAgentCount": len(self.product_agents),
            "participantPolicyVersion": self.participant_policy_version,
            "legacyReadMode": self.legacy_read_mode,
            "productAgents": [role.to_dict() for role in self.product_agents],
            "systemCapabilities": [
                capability.to_dict() for capability in self.system_capabilities
            ],
            "legacyRoleAliases": {
                role.product_role_id: list(role.legacy_role_aliases)
                for role in self.product_agents
            },
            "systemRoleAliases": {
                capability.capability_id: list(capability.legacy_role_aliases)
                for capability in self.system_capabilities
            },
            "participantPolicies": [
                policy.to_dict() for policy in self.participant_policies
            ],
        }

    def fingerprint(self) -> str:
        return sha256_hex(self._canonical_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._canonical_payload(),
            "roleContractFingerprint": self.fingerprint(),
        }


_HYPOTHESIS_PARTICIPANT_ROLES = (
    "challenge_cup_search",
    "challenge_cup_knowledge_manager",
    "challenge_cup_experiment_revision",
    "challenge_cup_evaluator",
)

CURRENT_RESEARCH_TEAM_ROLE_CONTRACT = ResearchTeamRoleContract(
    team_role_contract_id=RESEARCH_TEAM_ROLE_CONTRACT_ID,
    team_role_contract_version=RESEARCH_TEAM_ROLE_CONTRACT_VERSION,
    semantic_version=RESEARCH_TEAM_ROLE_SEMANTIC_VERSION,
    participant_policy_version=RESEARCH_PARTICIPANT_POLICY_VERSION,
    legacy_read_mode=LEGACY_READ_MODE,
    product_agents=(
        ProductAgentRole(
            product_role_id="challenge_cup_search",
            label="搜索 Agent",
            purpose="将知识缺口转为可追溯检索计划并登记有效与无效来源。",
            legacy_role_aliases=("source_finder",),
        ),
        ProductAgentRole(
            product_role_id="challenge_cup_extractor",
            label="提炼 Agent",
            purpose="从候选来源提取证据、限制、反证与可定位引用。",
            legacy_role_aliases=("source_extractor",),
        ),
        ProductAgentRole(
            product_role_id="challenge_cup_knowledge_manager",
            label="知识管理 Agent",
            purpose="治理证据关系、作用域、lineage 与知识候选提升边界。",
            legacy_role_aliases=(
                "source_relation_mapper",
                "source_ingestor",
                "knowledge_steward",
            ),
        ),
        ProductAgentRole(
            product_role_id="challenge_cup_execution_steward",
            label="执行 Agent",
            purpose="提交冻结协议并观察受控运行，交付不可变 artifact locator。",
            legacy_role_aliases=("execution_steward",),
        ),
        ProductAgentRole(
            product_role_id="challenge_cup_experiment_revision",
            label="实验修订 Agent",
            purpose="生成与修订假说、协议、迭代提案和停止建议。",
            legacy_role_aliases=(
                "challenge_cup_experiment_planner",
                "experiment_planner",
                "challenge_cup_iteration_planner",
                "iteration_planner",
            ),
        ),
        ProductAgentRole(
            product_role_id="challenge_cup_evaluator",
            label="评估 Agent",
            purpose="独立审查协议、指标、稳健性、负结果和主张边界。",
            legacy_role_aliases=(
                "challenge_cup_experiment_ledger",
                "experiment_ledger",
            ),
        ),
    ),
    system_capabilities=(
        SystemCapability(
            capability_id="coordinator",
            label="系统协调",
            purpose="选择参与者、维护议程、阶段路由和 readiness。",
            legacy_role_aliases=(
                "research_coordination",
                "challenge_cup_coordinator",
            ),
        ),
        SystemCapability(
            capability_id="formal_runner",
            label="Formal Runner",
            purpose="只接受冻结协议并输出不可变运行 artifact。",
            legacy_role_aliases=("formal_runner",),
        ),
        SystemCapability(
            capability_id="versioning_service",
            label="版本治理服务",
            purpose="依据批准提案写入 lineage、supersedes、rollback 与归档。",
            legacy_role_aliases=(
                "challenge_cup_versioning",
                "iteration_versioning",
            ),
        ),
        SystemCapability(
            capability_id="package_builder",
            label="结果打包服务",
            purpose="按 manifest 组装结果包且不生成科研结论。",
        ),
    ),
    participant_policies=(
        ResearchParticipantPolicy(
            meeting_type=CANDIDATE_GENERATION_MEETING_TYPE,
            required_product_role_ids=_HYPOTHESIS_PARTICIPANT_ROLES,
        ),
        ResearchParticipantPolicy(
            meeting_type=HYPOTHESIS_REVIEW_MEETING_TYPE,
            required_product_role_ids=_HYPOTHESIS_PARTICIPANT_ROLES,
        ),
    ),
)


def current_research_team_role_contract_snapshot() -> dict[str, Any]:
    """Return the deterministic v2 contract snapshot for downstream projections."""

    return CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.to_dict()
