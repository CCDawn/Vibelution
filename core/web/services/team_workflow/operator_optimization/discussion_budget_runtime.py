"""Connect frozen discussion authority to the existing Ledger budget row."""
from __future__ import annotations

from .model_budget import admit_model_invocation, reserve_model_budget


def speaker_receipt_sink(authority: dict, binding):
    """Deliver failed attempts even when no final speaker outcome is returned."""
    def persist(receipt: dict) -> None:
        from ..research_runtime.formal_write_runtime import get_write_store
        from ..research_runtime.receipt_persistence import enqueue_question_model_invocation_receipt

        scope = receipt.get("scope") or {}
        if any(scope.get(key) != getattr(binding, key) for key in
                ("sessionId", "turnId", "taskId", "formalNodeRunId")):
            raise ValueError("Operator receipt differs from its bound speaker")
        enqueue_question_model_invocation_receipt(get_write_store(),
            team_id=authority["teamId"], question_id=authority["questionId"],
            workflow_run_id=authority["workflowRunId"], receipt=receipt)
    return persist


def reserve_discussion_budget(store, authority: dict) -> dict:
    from decimal import Decimal

    result = reserve_model_budget(store, run_id=authority["workflowRunId"],
        node_run_id=authority["nodeRunId"], optimization_campaign_id=authority["optimizationCampaignId"],
        round_id=authority["roundId"], campaign_budget=authority["budget"],
        policy_hash=authority["modelPolicySha256"])
    return {key: str(value) if isinstance(value, Decimal) else value for key, value in result.items()}


def speaker_budget_preflight(authority: dict, model_ref: str):
    """Return an ephemeral hook; no callable is persisted in room config."""
    def preflight(*, invocation_id: str, estimated_input_tokens: int, max_output_tokens: int) -> dict:
        from ..research_runtime.formal_write_runtime import get_write_store
        from .discussion_authority import validate_operator_authority

        validate_operator_authority(authority)
        policy = authority["budget"]["discussion"]
        output_tokens = min(max_output_tokens, policy["maxOutputTokensPerCall"])
        result = admit_model_invocation(get_write_store(),
            reservation={"reservationId": "reservation-" + authority["nodeRunId"],
                "runId": authority["workflowRunId"], "nodeRunId": authority["nodeRunId"]},
            invocation_id=invocation_id, model_ref=model_ref,
            input_tokens=estimated_input_tokens, output_tokens=output_tokens)
        return {"maxOutputTokens": output_tokens,
            "remainingTokens": max(0, policy["tokenLimit"] - result["tokensUsed"])}
    return preflight
