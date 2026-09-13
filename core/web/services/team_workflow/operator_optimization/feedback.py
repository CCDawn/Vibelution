"""Canonical feedback and atomic best-candidate selection for the next round."""

from .execution import require_active_node
from .evaluation import evaluate_round
from .knowledge import read_ref
from .discussion import _write_readback
from .store import CampaignConflict, update_campaign


def publish_feedback(action, snapshot):
    run = require_active_node(action, snapshot, "optimization_feedback")
    campaign, record, plan, expected = evaluate_round(run)
    if (
        record.evaluationRef is None
        or record.evaluationRef.kind != "operator_evaluation"
    ):
        raise CampaignConflict("Feedback requires the canonical numerical evaluation")
    evaluation = read_ref(run.team_id, run.run_id, record.evaluationRef)
    if evaluation != expected:
        raise CampaignConflict(
            "Evaluation differs from the frozen plan and measured evidence"
        )
    promote = evaluation["promote"]
    selected = plan.candidateRef if promote else plan.parentCandidateRef
    payload = {
        "schemaVersion": 1,
        "optimizationCampaignId": campaign.optimizationCampaignId,
        "roundId": record.roundId,
        "runId": run.run_id,
        "planRef": record.planRef.model_dump(mode="json"),
        "evaluationRef": record.evaluationRef.model_dump(mode="json"),
        "hypothesisRef": record.hypothesisRef.model_dump(mode="json"),
        "candidateDecision": "promote" if promote else "retain_parent",
        "selectedCandidateRef": selected.model_dump(mode="json"),
        "policy": evaluation["policy"],
        "gpuSeconds": evaluation["gpuSeconds"],
        "trialResults": [
            {
                key: t[key]
                for key in (
                    "measurementRef",
                    "executionStatus",
                    "failureReason",
                    "comparable",
                    "promote",
                    "reasons",
                )
            }
            for t in evaluation["trials"]
        ],
        "hypothesisAssessment": {
            "status": "requires_discussion",
            "prediction": plan.prediction,
            "counterevidence": plan.counterevidence,
            "note": "工程测量不自动证明机制假设；下一轮讨论依据逐次评价判断支持、反驳或不确定。",
        },
        "nextRoundInstruction": "保留失败和未达标证据，优先讨论高 ROI 改进；没有新理由不重复已知失败。",
    }
    _, ref = _write_readback(
        run.team_id,
        run.run_id,
        kind="optimization_feedback",
        identity="operator-feedback:" + record.roundId,
        payload=payload,
    )

    def attach(current):
        active = next(r for r in current.rounds if r.roundId == record.roundId)
        if (
            current.status != "running"
            or current.activeRunId != run.run_id
            or active.planRef != record.planRef
            or active.evaluationRef != record.evaluationRef
            or active.feedbackRef not in (None, ref)
            or (current.bestCandidateRef or current.baselineCandidateRef)
            != plan.parentCandidateRef
        ):
            raise CampaignConflict(
                "Feedback selection no longer matches the active round"
            )
        return current.model_copy(
            update={
                "bestCandidateRef": selected,
                "rounds": tuple(
                    r.model_copy(update={"feedbackRef": ref})
                    if r.roundId == record.roundId
                    else r
                    for r in current.rounds
                ),
            }
        )

    update_campaign(
        run.team_id,
        run.project_id,
        campaign.optimizationCampaignId,
        expected_version=None,
        command_key="operator-feedback-selection:" + record.roundId,
        command={"feedbackRef": ref.model_dump(mode="json")},
        transform=attach,
    )
    return ref
