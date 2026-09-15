"""Evidence-bound structured output for the operator decision Agent."""

from __future__ import annotations

import json
from collections.abc import Mapping

from core.llm.semantic_messages import SemanticOutputSchema
from core.research.operator_optimization.decision import (
    OPTIMIZATION_DECISION_ARTIFACT_KIND,
    OperatorIterationDecision,
    OperatorIterationDecisionArtifact,
    OperatorIterationDecisionProposal,
    decision_id_for,
    is_stage3_operator_run,
)
from core.research.workflow.contracts._canonical import sha256_hex

from .discussion import _write_readback
from .knowledge import read_ref, round_context
from .store import CampaignConflict


def decision_task_input(team_id: str, run_id: str) -> dict:
    from .knowledge import get_write_store

    run = get_write_store().get_run(run_id)
    if run is None or not is_stage3_operator_run(run):
        raise CampaignConflict("Historical operator workflow is read-only")
    campaign, record, _ = round_context(team_id, run_id)
    if record.feedbackRef is None or record.evaluationRef is None:
        raise CampaignConflict("Decision requires canonical feedback and evaluation")
    feedback = read_ref(team_id, run_id, record.feedbackRef)
    evaluation = read_ref(team_id, run_id, record.evaluationRef)
    target_parent = campaign.bestCandidateRef or campaign.baselineCandidateRef
    lineage_reusable = target_parent == record.parentCandidateRef
    available_actions = ["discuss"]
    blocked_actions = {
        "repair_baseline": "baseline revision flow is not connected",
    }
    if lineage_reusable and record.hypothesisRef is not None:
        available_actions.append("collect_knowledge")
    else:
        blocked_actions["collect_knowledge"] = (
            "parent candidate changed" if not lineage_reusable else "no selected hypothesis"
        )
    if (
        lineage_reusable
        and record.hypothesisRef is not None
        and record.knowledgeRef is not None
    ):
        available_actions.append("plan_candidate")
    else:
        blocked_actions["plan_candidate"] = (
            "parent candidate changed"
            if not lineage_reusable
            else "no verified hypothesis and knowledge handoff"
        )
    if lineage_reusable and record.planRef is not None:
        available_actions.append("retest")
    else:
        blocked_actions["retest"] = (
            "parent candidate changed" if not lineage_reusable else "no frozen plan"
        )
    available_actions.append("stop")
    frozen = {
        "optimizationCampaignId": campaign.optimizationCampaignId,
        "roundId": record.roundId,
        "runId": run_id,
        "feedbackRef": record.feedbackRef.model_dump(mode="json"),
        "evaluationRef": record.evaluationRef.model_dump(mode="json"),
        "feedback": feedback,
        "evaluation": evaluation,
        "actionPolicy": {
            "availableActions": available_actions,
            "blockedActions": blocked_actions,
        },
    }
    return {**frozen, "inputHash": sha256_hex(frozen)}


def parse_decision_output(value) -> OperatorIterationDecisionProposal:
    if isinstance(value, str):
        value = json.loads(value)
    elif isinstance(value, OperatorIterationDecisionProposal):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        raise TypeError("Decision output must be a structured JSON object")
    return OperatorIterationDecisionProposal.model_validate(dict(value))


def decision_output_contract() -> SemanticOutputSchema:
    return SemanticOutputSchema(
        name="operator_iteration_decision_proposal_v2",
        schema=OperatorIterationDecisionProposal.model_json_schema(),
        validator=lambda value: parse_decision_output(value).model_dump(mode="json"),
    )


def materialize_iteration_decision(
    team_id: str, run_id: str, output, *, decided_by: str
):
    proposal = parse_decision_output(output)
    inputs = decision_task_input(team_id, run_id)
    if proposal.inputHash != inputs["inputHash"]:
        raise CampaignConflict("Decision output belongs to different feedback evidence")
    if proposal.kind not in inputs["actionPolicy"]["availableActions"]:
        raise CampaignConflict("Decision action is unavailable for the frozen evidence")
    decision_id = decision_id_for(run_id, inputs["feedbackRef"])
    artifact = OperatorIterationDecisionArtifact(
        optimizationCampaignId=inputs["optimizationCampaignId"],
        roundId=inputs["roundId"],
        runId=run_id,
        inputHash=inputs["inputHash"],
        feedbackRef=inputs["feedbackRef"],
        evaluationRef=inputs["evaluationRef"],
        decision=OperatorIterationDecision(
            decisionId=decision_id,
            kind=proposal.kind,
            reason=proposal.reason,
            decidedBy=decided_by,
        ),
    )
    _, ref = _write_readback(
        team_id,
        run_id,
        kind=OPTIMIZATION_DECISION_ARTIFACT_KIND,
        identity=decision_id,
        payload=artifact.model_dump(mode="json"),
    )
    return ref


__all__ = [
    "decision_output_contract",
    "decision_task_input",
    "materialize_iteration_decision",
    "parse_decision_output",
]
