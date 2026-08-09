"""Public v2.1 workflow contract surface.

Each independently changing contract stays in its owning module; callers import
from this package boundary instead of growing ``models.py``.
"""

from ._validation import ContractValidationError
from .artifact_manifest import ArtifactManifest
from .budget import ResearchBudgetLedger
from .competition_evaluation import CompetitionEvaluationSnapshot
from .execution import NodeExecutionEnvelope, TaskLease, TaskLeaseStatus
from .experiment_campaign import ExperimentCampaign, ExperimentCampaignStage
from .hypothesis import HypothesisCandidate, HypothesisPortfolio
from .run_input import WorkflowRunInputSnapshot
from .task_bundle import ResearchSubtask, ResearchTaskBundle

__all__ = [
    "ArtifactManifest",
    "CompetitionEvaluationSnapshot",
    "ContractValidationError",
    "ExperimentCampaign",
    "ExperimentCampaignStage",
    "HypothesisCandidate",
    "HypothesisPortfolio",
    "NodeExecutionEnvelope",
    "ResearchBudgetLedger",
    "ResearchSubtask",
    "ResearchTaskBundle",
    "TaskLease",
    "TaskLeaseStatus",
    "WorkflowRunInputSnapshot",
]
