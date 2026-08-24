from __future__ import annotations

from typing import Any

from core.research.competition import resources
from core.research.workflow import checkpoint_store
from core.research.workflow import ledger
from core.web.services import agent_directory_service, session_service
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


def _stage(plan_id: str, *, with_receipts: bool = True) -> dict[str, Any]:
    handles = {
        "ledger": {"stageId": "ledger"},
        "checkpoints": {"stageId": "checkpoints"},
        "artifacts": {"stageId": "artifacts"},
        "workspace": {"stageId": "workspace"},
        "sessions": {"stageId": "sessions"},
        "rooms": {"stageId": "rooms"},
    }
    if with_receipts:
        handles["receipts"] = {"stageId": "receipts"}
    return {
        "planId": plan_id,
        "teamId": "research-team",
        "status": "purged",
        "scopeAuthority": [{"teamId": "research-team", "runId": "run-1", "threadId": "run-1"}],
        "receiptScopeAuthority": [{"teamId": "research-team", "questionId": "SCI-096", "workflowRunId": "run-1"}],
        "handles": handles,
    }


def test_rebootstrap_accepts_catalog_id_for_sci_096(monkeypatch) -> None:
    instance = adapter_module.ChallengeCupLiveDestructiveAdapter()
    plan = _plan("b" * 64)
    ensure_calls: list[str] = []

    monkeypatch.setattr(
        resources,
        "load_science_question_catalog",
        lambda: {"questions": [{"id": "SCI-096", "question_en": "Golden sample"}]},
    )
    monkeypatch.setattr(
        research_projects,
        "ensure_challenge_question_project",
        lambda *_args, **_kwargs: {"project": {"projectId": adapter_module.GOLDEN_SAMPLE_PROJECT_ID}},
    )
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **_kwargs: {"agentId": agent_id, "name": agent_id},
    )
    monkeypatch.setattr(session_service, "update_agent_instance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        session_service,
        "ensure_agent_direct_session",
        lambda agent_id, **_kwargs: ensure_calls.append(agent_id) or {"id": f"session-{agent_id}"},
    )

    result = instance.rebootstrap("research-team", plan)

    assert result["status"] == "initialized"
    assert result["questionId"] == "SCI-096"
    assert result["directSessionCount"] == len(adapter_module.RETAINED_AGENT_ROLE_KEYS)
    assert ensure_calls == [f"agent-{index}" for index in range(len(adapter_module.RETAINED_AGENT_ROLE_KEYS))]


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


def test_restore_discards_verified_recovery_staging_before_retry(monkeypatch) -> None:
    plan = _plan("s" * 64)
    instance = adapter_module.ChallengeCupLiveDestructiveAdapter()
    stage = _stage(plan["purgePlanId"])
    instance._stages[plan["purgePlanId"]] = stage
    calls: list[str] = []

    monkeypatch.setattr(instance, "_restore_handles", lambda *_args, **_kwargs: calls.append("restore"))
    monkeypatch.setattr(instance, "_discard_recovered_staging", lambda *_args, **_kwargs: calls.append("discard"))

    restored = instance.restore("research-team", plan, {"planId": plan["purgePlanId"]})

    assert restored["status"] == "restored"
    assert calls == ["restore", "discard"]
    assert plan["purgePlanId"] not in instance._stages


def test_stage_captures_scope_authority_before_artifact_staging(monkeypatch) -> None:
    plan = _plan("r" * 64)
    instance = adapter_module.ChallengeCupLiveDestructiveAdapter()
    order: list[str] = []
    authority = [
        {
            "teamId": "research-team",
            "runId": "thread-run-legacy",
            "threadId": "thread-run-legacy",
            "scopeHash": "",
            "questionId": "",
            "projectId": "",
        }
    ]
    monkeypatch.setattr(
        adapter_module,
        "_run_scope_authority",
        lambda _team_id: order.append("authority") or authority,
    )
    monkeypatch.setattr(instance, "_discard_recovered_staging", lambda *_args, **_kwargs: order.append("discard"))
    monkeypatch.setattr(chat_room_service, "prepare_team_chat_room_reset", lambda *_args, **_kwargs: {"stageId": "rooms"})
    monkeypatch.setattr(agent_sessions, "stage_team_agent_session_reset", lambda *_args, **_kwargs: {"stageId": "sessions"})
    monkeypatch.setattr(research_projects, "prepare_challenge_cup_experiment_state_reset", lambda *_args, **_kwargs: {"stageId": "workspace"})
    monkeypatch.setattr(
        workflow_artifact_store,
        "prepare_workflow_artifact_reset",
        lambda *_args, **_kwargs: order.append("artifacts") or {"stageId": "artifacts"},
    )
    monkeypatch.setattr(checkpoint_store, "prepare_checkpoint_reset_stage", lambda *_args, **_kwargs: {"stageId": "checkpoints"})
    monkeypatch.setattr(
        model_invocation_receipt_registry,
        "prepare_model_invocation_receipt_reset_stage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("empty receipts must not stage")),
    )
    monkeypatch.setattr(ledger, "prepare_team_ledger_reset_stage", lambda *_args, **_kwargs: {"stageId": "ledger"})
    monkeypatch.setattr(instance, "_ledger_store", lambda _path: (object(), None))

    staged = instance.stage("research-team", plan)

    assert staged["status"] == "staged"
    assert "receipts" not in staged["ports"]
    assert order == ["discard", "authority", "artifacts"]


def test_stage_skips_empty_checkpoint_port_without_scope_authority(monkeypatch) -> None:
    plan = _plan("u" * 64)
    instance = adapter_module.ChallengeCupLiveDestructiveAdapter()

    monkeypatch.setattr(adapter_module, "_run_scope_authority", lambda _team_id: [])
    monkeypatch.setattr(instance, "_discard_recovered_staging", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(chat_room_service, "prepare_team_chat_room_reset", lambda *_args, **_kwargs: {"stageId": "rooms"})
    monkeypatch.setattr(agent_sessions, "stage_team_agent_session_reset", lambda *_args, **_kwargs: {"stageId": "sessions"})
    monkeypatch.setattr(research_projects, "prepare_challenge_cup_experiment_state_reset", lambda *_args, **_kwargs: {"stageId": "workspace"})
    monkeypatch.setattr(workflow_artifact_store, "prepare_workflow_artifact_reset", lambda *_args, **_kwargs: {"stageId": "artifacts"})
    monkeypatch.setattr(
        checkpoint_store,
        "prepare_checkpoint_reset_stage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("empty checkpoints must not stage")),
    )
    monkeypatch.setattr(ledger, "prepare_team_ledger_reset_stage", lambda *_args, **_kwargs: {"stageId": "ledger"})
    monkeypatch.setattr(instance, "_ledger_store", lambda _path: (object(), None))

    staged = instance.stage("research-team", plan)

    assert "checkpoints" not in staged["ports"]


def test_stage_requires_real_receipt_authority_when_receipts_are_planned(monkeypatch) -> None:
    plan = _plan("t" * 64)
    plan["deleteSet"] = {"receipts": ["receipt-1"]}
    instance = adapter_module.ChallengeCupLiveDestructiveAdapter()
    authority = [{"teamId": "research-team", "runId": "run-1", "questionId": "SCI-096"}]
    observed: dict[str, Any] = {}

    monkeypatch.setattr(adapter_module, "_run_scope_authority", lambda _team_id: authority)
    monkeypatch.setattr(instance, "_discard_recovered_staging", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(chat_room_service, "prepare_team_chat_room_reset", lambda *_args, **_kwargs: {"stageId": "rooms"})
    monkeypatch.setattr(agent_sessions, "stage_team_agent_session_reset", lambda *_args, **_kwargs: {"stageId": "sessions"})
    monkeypatch.setattr(research_projects, "prepare_challenge_cup_experiment_state_reset", lambda *_args, **_kwargs: {"stageId": "workspace"})
    monkeypatch.setattr(workflow_artifact_store, "prepare_workflow_artifact_reset", lambda *_args, **_kwargs: {"stageId": "artifacts"})
    monkeypatch.setattr(checkpoint_store, "prepare_checkpoint_reset_stage", lambda *_args, **_kwargs: {"stageId": "checkpoints"})
    def prepare_receipts(*_args, **kwargs):
        observed["authority"] = kwargs["scope_authority"]
        return {"stageId": "receipts"}

    monkeypatch.setattr(
        model_invocation_receipt_registry,
        "prepare_model_invocation_receipt_reset_stage",
        prepare_receipts,
    )
    monkeypatch.setattr(ledger, "prepare_team_ledger_reset_stage", lambda *_args, **_kwargs: {"stageId": "ledger"})
    monkeypatch.setattr(instance, "_ledger_store", lambda _path: (object(), None))

    staged = instance.stage("research-team", plan)

    assert "receipts" in staged["ports"]
    assert observed["authority"] == [{"teamId": "research-team", "questionId": "SCI-096", "workflowRunId": "run-1"}]
