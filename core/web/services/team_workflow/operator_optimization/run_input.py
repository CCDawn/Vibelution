"""Build run input from the persisted activity, without a science catalog ID."""
from __future__ import annotations

from core.research.operator_optimization.candidate import CudaCandidateRef
from core.research.operator_optimization.contracts import (
    OperatorRunContext,
    OptimizationCampaign,
    OptimizationRound,
)
from core.research.operator_optimization.measurement import (
    MEASUREMENT_PROTOCOL_ARTIFACT_KIND,
    MeasurementProtocolRef,
)
from core.research.workflow.contracts._canonical import sha256_hex
from core.research.workflow.contracts.research_scope import (
    scope_hash_for,
    scope_identity_seed,
    scope_locators_for,
)
from core.research.workflow.operator_optimization_definition import (
    OPERATOR_BASELINE_WORKFLOW_ID,
    OPERATOR_WORKFLOW_ID,
)


def build_operator_run_input(campaign: OptimizationCampaign, round_record: OptimizationRound | None = None, *,
    environment_ref: str = "operator-environment:unverified", protocol_artifact_hash: str = "",
    protocol_hash: str = "", protocol_artifact_id: str = "", protocol_run_id: str = "",
    baseline_candidate_ref: CudaCandidateRef | None = None,
    workload_ref: str = "", observation_refs: tuple = ()) -> dict:
    baseline = round_record is None
    workflow_id = OPERATOR_BASELINE_WORKFLOW_ID if baseline else OPERATOR_WORKFLOW_ID
    branch = campaign.baselineSetupId if baseline else round_record.roundId
    baseline_candidate = baseline_candidate_ref or campaign.baselineCandidateRef
    if baseline_candidate is None:
        raise ValueError("An operator run requires a recoverable baseline candidate reference")
    if protocol_artifact_hash and not protocol_run_id:
        raise ValueError("A frozen protocol reference requires its owning run ID")
    protocol_ref = None
    if protocol_artifact_hash:
        protocol_ref = MeasurementProtocolRef(
            artifactId=protocol_artifact_id or "protocol-" + protocol_artifact_hash[:24],
            runId=protocol_run_id,
            sha256=protocol_artifact_hash,
        )
    question = f"OPERATOR-{campaign.objective.operator.upper()}"
    identity = {"program": "operator-experiments", "theme": "operator-optimization",
        "campaign": campaign.optimizationCampaignId, "question": question, "branch": branch,
        "workflow": workflow_id, "agent_id": "operator-coordinator", "mode": "formal"}
    scope_hash = scope_hash_for(**identity)
    scope = {**scope_identity_seed(**identity), "scopeHash": scope_hash,
        **scope_locators_for(**{key: value for key, value in identity.items() if key not in {"workflow", "mode"}}, scope_hash=scope_hash)}
    context = OperatorRunContext(
        optimizationCampaignId=campaign.optimizationCampaignId, researchProjectId=campaign.researchProjectId,
        objective=campaign.objective, baselineSetupId=branch if baseline else "",
        roundId="" if baseline else branch,
        baselineCandidateRef=baseline_candidate,
        parentCandidateRef=None if baseline else round_record.parentCandidateRef,
        baselineRef=campaign.baselineRef, observationRefs=observation_refs,
    )
    budget = campaign.budget.model_dump(mode="json")
    return {
        "teamId": campaign.teamId, "projectId": campaign.researchProjectId, "questionId": question,
        "researchScopeEnvelope": scope, "researchBriefHash": sha256_hex(context.model_dump(mode="json")),
        "datasetRefs": [workload_ref] if workload_ref else [], "metricContract": {"primary": "latency_ms", "direction": "minimize"},
        "constraintSnapshot": {"preserveSemantics": True, "submissionEligible": False},
        "competitionRuleRef": "operator-optimization-protocol", "competitionRuleVersion": "1",
        "trackAndRubricSnapshot": {"purpose": "independent_operator_experiment", "submissionEligible": False},
        "researchObjectiveContract": context.model_dump(mode="json"),
        "sourcePolicy": {"requireCounterEvidence": True, "targetedCollection": True},
        "budgetPolicy": {**budget, "maxParallelTasks": 1},
        "stopPolicy": {"maxRounds": campaign.budget.maxRounds, "stopOnBudgetExhaustion": True},
        "environmentSnapshotRef": environment_ref,
        "modelRoutingPolicy": {"requiredFamily": "qwen", "source": "team-role-bindings"},
        "evaluationContract": {"correctnessRequired": True, "rawPairedTimingsRequired": True,
            "holdoutRequired": True, "protocolArtifactKind": MEASUREMENT_PROTOCOL_ARTIFACT_KIND,
            "protocolArtifactHash": protocol_artifact_hash, "protocolHash": protocol_hash,
            "protocolRef": protocol_ref.model_dump(mode="json") if protocol_ref else {}},
        "createdBy": "operator-coordinator",
    }
