from __future__ import annotations

from typing import Any

from core.research.workflow import checkpoint_store
from core.research.workflow import ledger
from core.web.services import chat_room_service
from core.web.services.session import agent_sessions
from core.web.services.team_workflow import challenge_cup_reset_destructive_adapter as adapter_module
from core.web.services.team_workflow import research_projects
from core.web.services.team_workflow.research_runtime import (
    challenge_cup_maintenance_fence,
    model_invocation_receipt_registry,
    workflow_artifact_store,
)


def _plan(plan_id: str = "p" * 64) -> dict[str, Any]:
    return {
        "purgePlanId": plan_id,
        "inventoryHash": "i" * 64,
        "impact": {"deleteObjectCount": 3},
        "retained": {
            "agents": [
                {"agentId": f"agent-{index}", "roleKey": role}
                for index, role in enumerate(adapter_module.RETAINED_AGENT_ROLE_KEYS)
            ]
        },
    }


def _stage(plan_id: str) -> dict[str, Any]:
    return {
        "planId": plan_id,
        "teamId": "research-team",
        "status": "purged",
        "scopeAuthority": [{"teamId": "research-team", "runId": "run-1", "threadId": "run-1"}],
        "receiptScopeAuthority": [{"teamId": "research-team", "questionId": "SCI-096", "workflowRunId": "run-1"}],
        "handles": {
            "ledger": {"stageId": "ledger"},
            "receipts": {"stageId": "receipts"},
            "checkpoints": {"stageId": "checkpoints"},
            "artifacts": {"stageId": "artifacts"},
            "workspace": {"stageId": "workspace"},
            "sessions": {"stageId": "sessions"},
            "rooms": {"stageId": "rooms"},
        },
    }


def test_destroy_staging_finalizes_each_port_without_rebootstrapping(monkeypatch) -> None:
    plan = _plan()
    instance = adapter_module.ChallengeCupLiveDestructiveAdapter()
    stage = _stage(plan["purgePlanId"])
    instance._stages[plan["purgePlanId"]] = stage
    calls: list[str] = []

    monkeypatch.setattr(ledger, "destroy_team_ledger_reset_stage", lambda *_args, **_kwargs: calls.append("ledger") or {})
    monkeypatch.setattr(model_invocation_receipt_registry, "destroy_model_invocation_receipt_reset_stage", lambda *_args, **_kwargs: calls.append("receipts") or {})
    monkeypatch.setattr(checkpoint_store, "destroy_checkpoint_reset_stage", lambda *_args, **_kwargs: calls.append("checkpoints") or {})
    monkeypatch.setattr(workflow_artifact_store, "destroy_workflow_artifact_reset", lambda *_args, **_kwargs: calls.append("artifacts") or {})
    monkeypatch.setattr(research_projects, "destroy_challenge_cup_experiment_state_reset", lambda *_args, **_kwargs: calls.append("workspace") or {})
    monkeypatch.setattr(agent_sessions, "destroy_team_agent_session_reset", lambda *_args, **_kwargs: calls.append("sessions") or {})
    monkeypatch.setattr(chat_room_service, "destroy_team_chat_room_reset", lambda *_args, **_kwargs: calls.append("rooms") or {})
    monkeypatch.setattr(challenge_cup_maintenance_fence, "release_fence", lambda *_args, **_kwargs: calls.append("fence") or {"status": "released"})
    monkeypatch.setattr(adapter_module, "_write_result", lambda _payload: calls.append("result"))
    monkeypatch.setattr(instance, "rebootstrap", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not rebootstrap")))

    result = instance.destroy_staging("research-team", plan, {"planId": plan["purgePlanId"]})

    assert result["destroyed"] is True
    assert calls == ["ledger", "receipts", "checkpoints", "artifacts", "workspace", "sessions", "rooms", "result", "fence"]
    assert stage["status"] == "destroyed"


def test_restore_reuses_stage_scope_authority_instead_of_recalculating(monkeypatch) -> None:
    plan = _plan("q" * 64)
    instance = adapter_module.ChallengeCupLiveDestructiveAdapter()
    stage = _stage(plan["purgePlanId"])
    instance._stages[plan["purgePlanId"]] = stage
    observed: dict[str, Any] = {}

    monkeypatch.setattr(instance, "_ledger_store", lambda _path: (object(), None))
    monkeypatch.setattr(ledger, "restore_team_ledger_reset_stage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(model_invocation_receipt_registry, "restore_model_invocation_receipt_reset_stage", lambda *_args, **kwargs: observed.setdefault("receipts", kwargs["scope_authority"]))
    monkeypatch.setattr(checkpoint_store, "restore_checkpoint_reset_stage", lambda *_args, **kwargs: observed.setdefault("checkpoints", kwargs["scope_authority"]))

    instance._restore_handles(
        "research-team",
        plan["purgePlanId"],
        stage["handles"],
        ("checkpoints", "receipts"),
    )

    assert observed["checkpoints"] == stage["scopeAuthority"]
    assert observed["receipts"] == stage["receiptScopeAuthority"]
