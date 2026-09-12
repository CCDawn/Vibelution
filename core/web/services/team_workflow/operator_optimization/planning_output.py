"""Validated planning decisions to canonical candidates and frozen plans.

This service does not attest to a model invocation or complete a workflow node.
The native task adapter must verify that evidence before calling it.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from core.llm.semantic_messages import SemanticOutputSchema
from core.research.operator_optimization.candidate import (
    CudaCandidateArtifact,
    candidate_ref_from_artifact,
)
from core.research.operator_optimization.plan import (
    OptimizationPlan,
    OptimizationPlanContent,
    OptimizationPlanProposal,
)
from core.research.workflow.contracts._canonical import sha256_hex

from ..storage_durability import inter_process_lock
from . import planning
from .discussion import _write_readback
from .knowledge import read_ref, round_context
from .store import CampaignConflict, campaign_root


_INPUT_FIELDS = (
    "optimizationCampaignId", "roundId", "runId", "hypothesisRef", "knowledgeRef",
    "protocolRef", "baselineCandidateRef", "parentCandidateRef",
)


def planning_task_input(team_id: str, run_id: str) -> dict:
    inputs = planning.planning_input(team_id, run_id)
    # Budget availability can change while a task runs. It is checked again on
    # publication, but is not part of the immutable source identity.
    inputs["inputHash"] = sha256_hex({key: inputs[key] for key in _INPUT_FIELDS})
    return inputs


def parse_planning_output(value) -> OptimizationPlanProposal:
    if isinstance(value, str):
        value = json.loads(value)
    elif isinstance(value, OptimizationPlanProposal):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        raise ValueError("Planning output must be a structured JSON object")
    # Validate model instances too: model_copy(update=...) skips validation.
    return OptimizationPlanProposal.model_validate(dict(value))


def planning_output_contract() -> SemanticOutputSchema:
    return SemanticOutputSchema(
        name="operator_plan_proposal_v1",
        schema=OptimizationPlanProposal.model_json_schema(),
        validator=lambda value: parse_planning_output(value).model_dump(mode="json"),
    )


def materialize_optimization_plan(team_id: str, run_id: str, output):
    """Save a real managed candidate, then bind one immutable plan to the round."""
    proposal = parse_planning_output(output)
    campaign, record, _ = round_context(team_id, run_id)
    lock = campaign_root(team_id, campaign.researchProjectId) / f"{record.roundId}.planning"
    with inter_process_lock(lock):
        inputs = planning_task_input(team_id, run_id)
        campaign, record, _ = round_context(team_id, run_id)
        if proposal.inputHash != inputs["inputHash"]:
            raise CampaignConflict("Planning output belongs to different frozen inputs")
        planning.validate_plan_decisions(inputs, proposal)
        planning.validate_plan_candidates(team_id, run_id, campaign, record,
            (record.baselineCandidateRef, record.parentCandidateRef))
        decisions = {key: getattr(proposal, key) for key in OptimizationPlanContent.model_fields}
        bindings = {key: inputs[key] for key in _INPUT_FIELDS if key != "runId"}
        plan_id = "operator-plan:" + record.roundId

        if record.planRef is not None:
            existing = OptimizationPlan.model_validate(read_ref(team_id, run_id, record.planRef))
            expected = OptimizationPlan(planId=plan_id, **bindings, **decisions,
                candidateRef=existing.candidateRef)
            if existing != expected or existing.candidateRef.candidate != proposal.candidate:
                raise CampaignConflict("Planning output differs from the frozen plan")
            return planning.freeze_optimization_plan(team_id, run_id, existing)

        candidate_ref = next((ref for ref in (record.parentCandidateRef, record.baselineCandidateRef)
            if ref.candidate == proposal.candidate), None)
        if candidate_ref is None:
            # One deterministic identity per round/configuration; a replay after
            # a crash between candidate publication and plan binding reuses it.
            candidate_id = "operator-candidate:" + sha256_hex({
                "runId": run_id, "roundId": record.roundId,
                "candidate": proposal.candidate.model_dump(mode="json"),
            })
            candidate = CudaCandidateArtifact.from_candidate(
                candidate_id=candidate_id,
                optimization_campaign_id=campaign.optimizationCampaignId,
                run_id=run_id, round_id=record.roundId, candidate=proposal.candidate,
            )
            envelope, _ = _write_readback(team_id, run_id, kind="operator_candidate",
                identity=candidate_id, payload=candidate.model_dump(mode="json"))
            candidate_ref = candidate_ref_from_artifact(envelope)
        plan = OptimizationPlan(planId=plan_id, **bindings, **decisions, candidateRef=candidate_ref)
        # Recheck source validity and current budget at the publication boundary.
        return planning.freeze_optimization_plan(team_id, run_id, plan)
