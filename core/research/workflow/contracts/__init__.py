"""Public v2.1 workflow contract surface.

Each independently changing contract stays in its owning module; callers import
from this package boundary instead of growing ``models.py``.
"""

from ._canonical import canonical_json, sha256_hex
from ._validation import ContractValidationError
from .artifact_manifest import ArtifactManifest
from .artifact_receipt import ArtifactReceipt, BudgetReceipt
from .budget import ResearchBudgetLedger
from .competition_evaluation import CompetitionEvaluationSnapshot
from .execution import NodeExecutionEnvelope, TaskLease, TaskLeaseStatus
from .execution_anchor import ExecutionAnchor
from .experiment_campaign import ExperimentCampaign, ExperimentCampaignStage
from .hypothesis import HypothesisCandidate, HypothesisPortfolio
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
from .run_input import WorkflowRunInputSnapshot
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
    "ActorReadiness",
    "ActorRef",
    "AgentBindingSummary",
    "ArtifactManifest",
    "ArtifactReceipt",
    "BLOCKER_CAMPAIGN_THEME_MISMATCH",
    "BLOCKER_DEV_THEME_ONLY",
    "BLOCKER_THEME_NOT_ACTIVATED",
    "BudgetReadiness",
    "BudgetReceipt",
    "BudgetSummary",
    "CampaignActivationStatus",
    "CommandOffer",
    "CommandReceipt",
    "CommandRequest",
    "CompetitionEvaluationSnapshot",
    "ConfirmationContract",
    "ContractValidationError",
    "DEFAULT_PROGRAM_ID",
    "DEV_PROGRAM_ID",
    "DEV_THEME_PREFIX",
    "ExecutionAnchor",
    "ExecutionReceipt",
    "ExperimentCampaign",
    "ExperimentCampaignStage",
    "HandoffSummary",
    "HumanTaskSummary",
    "HypothesisCandidate",
    "HypothesisPortfolio",
    "NodeAttemptSummary",
    "NodeExecutionEnvelope",
    "NodeReadiness",
    "PendingAction",
    "PlatformFlowReadinessReport",
    "REQUIRED_SCOPE_FIELDS",
    "ReadinessBlocker",
    "Remediation",
    "RemediationKind",
    "ResearchBudgetLedger",
    "ResearchCampaignActivation",
    "ResearchScopeEnvelope",
    "ResearchSubtask",
    "ResearchTaskBundle",
    "ResearchWorkflowNodeDetail",
    "ResearchWorkflowSnapshot",
    "ScopeMode",
    "TaskLease",
    "TaskLeaseStatus",
    "ThemeContract",
    "ThemeContractStatus",
    "WorkflowCommandKind",
    "WorkflowEventEnvelope",
    "WorkflowEventType",
    "WorkflowProblem",
    "WorkflowProblemCategory",
    "WorkflowRunInputSnapshot",
    "WorkflowRunSummary",
    "activation_scope_hash",
    "build_campaign_activation_payload",
    "canonical_json",
    "parse_scope_mode",
    "scope_hash_for",
    "scope_identity_seed",
    "sha256_hex",
]
