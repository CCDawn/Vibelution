"""Public v2.1 workflow contract surface.

Each independently changing contract stays in its owning module; callers import
from this package boundary instead of growing ``models.py``.
"""

from ._canonical import canonical_json, sha256_hex
from ._validation import ContractValidationError
from .artifact_manifest import ArtifactManifest
from .artifact_receipt import ArtifactReceipt, BudgetReceipt
from .budget import ResearchBudgetLedger
from .claim_ledger import (
    ACCEPTED_REVIEW_STATUS,
    CLAIM_SOURCES,
    CLAIM_STATUSES,
    ClaimEvidenceRef,
    ClaimLedgerEntry,
    SUPPORT_LEVELS,
)
from .competition_evaluation import CompetitionEvaluationSnapshot
from .decision_record import (
    DECISION_KINDS,
    DECISION_STATUSES,
    DecisionRecord,
)
from .execution import NodeExecutionEnvelope, TaskLease, TaskLeaseStatus
from .execution_anchor import ExecutionAnchor
from .experiment_campaign import ExperimentCampaign, ExperimentCampaignStage
from .hypothesis import HypothesisCandidate, HypothesisPortfolio
from .hypothesis_fragment import (
    HYPOTHESIS_FRAGMENT_KIND,
    HYPOTHESIS_FRAGMENT_SCHEMA_VERSION,
    HypothesisFragment,
    canonical_fragment_payload,
)
from .hypothesis_round import (
    COMPARISON_OUTCOMES,
    LINEAGE_KINDS,
    MEETING_REF_KINDS,
    MIN_CANDIDATES,
    ROUND_STATUSES,
    SCORE_DIMENSIONS,
    HypothesisLineageRef,
    HypothesisMeetingRef,
    HypothesisMetaReview,
    HypothesisPairwiseComparison,
    HypothesisParetoAnalysis,
    HypothesisRound,
    HypothesisRoundCandidate,
)
from .hypothesis_selection import MAX_SELECTED_CANDIDATES, HypothesisSelectionRecord
from .meeting_digest import MeetingDigest
from .meeting_round import MEETING_STATUSES, MEETING_TYPES, MeetingRound
from .personal_memory_candidate import (
    EVIDENCE_STATUSES,
    MEMORY_CLASSES,
    REUSE_POLICIES,
    PersonalMemoryCandidate,
)
from .research_template import (
    ADDENDUM_STATUSES,
    BASELINE_STATUSES,
    TemplateAddendum,
    TemplateBaseline,
)
from .node_readiness import (
    ActorReadiness,
    BudgetReadiness,
    NodeReadiness,
    ReadinessBlocker,
)
from .pending_action import ExecutionReceipt, PendingAction
from .platform_readiness import (
    BLOCKER_CAMPAIGN_THEME_MISMATCH,
    BLOCKER_DEV_THEME_ONLY,
    BLOCKER_THEME_NOT_ACTIVATED,
    PlatformFlowReadinessReport,
)
from .research_scope import (
    REQUIRED_SCOPE_FIELDS,
    ResearchScopeEnvelope,
    ScopeMode,
    parse_scope_mode,
    scope_hash_for,
    scope_identity_seed,
)
from .research_team_role_contract import (
    CANDIDATE_GENERATION_MEETING_TYPE,
    CURRENT_RESEARCH_TEAM_ROLE_CONTRACT,
    HYPOTHESIS_REVIEW_MEETING_TYPE,
    LEGACY_READ_MODE,
    RESEARCH_PARTICIPANT_POLICY_VERSION,
    RESEARCH_TEAM_ROLE_CONTRACT_ID,
    RESEARCH_TEAM_ROLE_CONTRACT_VERSION,
    RESEARCH_TEAM_ROLE_SEMANTIC_VERSION,
    ProductAgentRole,
    ResearchParticipantPolicy,
    ResearchTeamRoleContract,
    SystemCapability,
    current_research_team_role_contract_snapshot,
)
from .run_input import WorkflowRunInputSnapshot
from .session_scope import (
    SESSION_SCOPE_KINDS,
    SESSION_SCOPE_VERSION,
    WORKFLOW_CANDIDATE_SCOPE_KIND,
    WORKFLOW_NODE_ROOT_SCOPE_KIND,
    WorkflowSessionScopeV3,
)
from .task_bundle import ResearchSubtask, ResearchTaskBundle
from .theme_campaign import (
    CampaignActivationStatus,
    DEV_PROGRAM_ID,
    DEV_THEME_PREFIX,
    DEFAULT_PROGRAM_ID,
    ResearchCampaignActivation,
    ThemeContract,
    ThemeContractStatus,
    activation_scope_hash,
    build_campaign_activation_payload,
)
from .workflow_command import (
    ActorRef,
    CommandOffer,
    CommandReceipt,
    CommandRequest,
    ConfirmationContract,
    WorkflowCommandKind,
)
from .workflow_event import WorkflowEventEnvelope, WorkflowEventType
from .workflow_problem import (
    Remediation,
    RemediationKind,
    WorkflowProblem,
    WorkflowProblemCategory,
)
from .workflow_snapshot import (
    AgentBindingSummary,
    BudgetSummary,
    HandoffSummary,
    HumanTaskSummary,
    NodeAttemptSummary,
    ResearchWorkflowNodeDetail,
    ResearchWorkflowSnapshot,
    WorkflowRunSummary,
)

__all__ = [
    "ACCEPTED_REVIEW_STATUS",
    "ADDENDUM_STATUSES",
    "ActorReadiness",
    "ActorRef",
    "AgentBindingSummary",
    "ArtifactManifest",
    "ArtifactReceipt",
    "BASELINE_STATUSES",
    "BLOCKER_CAMPAIGN_THEME_MISMATCH",
    "BLOCKER_DEV_THEME_ONLY",
    "BLOCKER_THEME_NOT_ACTIVATED",
    "BudgetReadiness",
    "BudgetReceipt",
    "BudgetSummary",
    "CLAIM_SOURCES",
    "CLAIM_STATUSES",
    "COMPARISON_OUTCOMES",
    "CampaignActivationStatus",
    "CANDIDATE_GENERATION_MEETING_TYPE",
    "ClaimEvidenceRef",
    "ClaimLedgerEntry",
    "CommandOffer",
    "CommandReceipt",
    "CommandRequest",
    "CompetitionEvaluationSnapshot",
    "ConfirmationContract",
    "ContractValidationError",
    "CURRENT_RESEARCH_TEAM_ROLE_CONTRACT",
    "DECISION_KINDS",
    "DECISION_STATUSES",
    "DEFAULT_PROGRAM_ID",
    "DEV_PROGRAM_ID",
    "DEV_THEME_PREFIX",
    "DecisionRecord",
    "EVIDENCE_STATUSES",
    "ExecutionAnchor",
    "ExecutionReceipt",
    "ExperimentCampaign",
    "ExperimentCampaignStage",
    "HandoffSummary",
    "HumanTaskSummary",
    "HypothesisCandidate",
    "HypothesisFragment",
    "HypothesisLineageRef",
    "HypothesisMeetingRef",
    "HypothesisMetaReview",
    "HypothesisPairwiseComparison",
    "HypothesisParetoAnalysis",
    "HypothesisPortfolio",
    "HypothesisRound",
    "HypothesisRoundCandidate",
    "HypothesisSelectionRecord",
    "HYPOTHESIS_REVIEW_MEETING_TYPE",
    "HYPOTHESIS_FRAGMENT_KIND",
    "HYPOTHESIS_FRAGMENT_SCHEMA_VERSION",
    "LINEAGE_KINDS",
    "LEGACY_READ_MODE",
    "MAX_SELECTED_CANDIDATES",
    "MEETING_REF_KINDS",
    "MEETING_STATUSES",
    "MEETING_TYPES",
    "MEMORY_CLASSES",
    "MIN_CANDIDATES",
    "MeetingDigest",
    "MeetingRound",
    "NodeAttemptSummary",
    "NodeExecutionEnvelope",
    "NodeReadiness",
    "PendingAction",
    "PersonalMemoryCandidate",
    "PlatformFlowReadinessReport",
    "ProductAgentRole",
    "REQUIRED_SCOPE_FIELDS",
    "RESEARCH_PARTICIPANT_POLICY_VERSION",
    "RESEARCH_TEAM_ROLE_CONTRACT_ID",
    "RESEARCH_TEAM_ROLE_CONTRACT_VERSION",
    "RESEARCH_TEAM_ROLE_SEMANTIC_VERSION",
    "REUSE_POLICIES",
    "ROUND_STATUSES",
    "ReadinessBlocker",
    "Remediation",
    "RemediationKind",
    "ResearchBudgetLedger",
    "ResearchCampaignActivation",
    "ResearchScopeEnvelope",
    "ResearchParticipantPolicy",
    "ResearchSubtask",
    "ResearchTaskBundle",
    "ResearchTeamRoleContract",
    "SESSION_SCOPE_KINDS",
    "SESSION_SCOPE_VERSION",
    "ResearchWorkflowNodeDetail",
    "ResearchWorkflowSnapshot",
    "SCORE_DIMENSIONS",
    "SUPPORT_LEVELS",
    "SystemCapability",
    "ScopeMode",
    "TaskLease",
    "TaskLeaseStatus",
    "TemplateAddendum",
    "TemplateBaseline",
    "ThemeContract",
    "ThemeContractStatus",
    "WorkflowCommandKind",
    "WorkflowEventEnvelope",
    "WorkflowEventType",
    "WorkflowProblem",
    "WorkflowProblemCategory",
    "WorkflowRunInputSnapshot",
    "WorkflowRunSummary",
    "WORKFLOW_CANDIDATE_SCOPE_KIND",
    "WORKFLOW_NODE_ROOT_SCOPE_KIND",
    "WorkflowSessionScopeV3",
    "activation_scope_hash",
    "build_campaign_activation_payload",
    "canonical_fragment_payload",
    "canonical_json",
    "current_research_team_role_contract_snapshot",
    "parse_scope_mode",
    "scope_hash_for",
    "scope_identity_seed",
    "sha256_hex",
]
