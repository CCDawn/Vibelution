"""Focused contract tests for the Challenge Cup reset owner.

These tests use injected in-memory reader/ports only.  They must never touch
the operator data home or invoke a real room/session lifecycle.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.web.services.team_workflow.challenge_cup_reset_service import (
    CONFIRMATION_PHRASE,
    GOLDEN_SAMPLE_BOOTSTRAP_ID,
    GOLDEN_SAMPLE_PROJECT_ID,
    GOLDEN_SAMPLE_QUESTION_ID,
    RETAINED_AGENT_ROLE_KEYS,
    ChallengeCupResetService,
    ResetBlockedError,
    ResetCapabilityError,
    ResetConfirmationError,
    ResetPlanStaleError,
)


def test_retained_agent_roles_match_the_canonical_challenge_cup_contract() -> None:
    assert RETAINED_AGENT_ROLE_KEYS == (
        "challenge_cup_search",
        "challenge_cup_extractor",
        "challenge_cup_knowledge_manager",
        "challenge_cup_execution_steward",
        "challenge_cup_experiment_revision",
        "challenge_cup_evaluator",
    )


def _inventory(*, active_work: dict[str, Any] | None = None) -> dict[str, Any]:
    agents = [
        {"agentId": f"agent-{role}", "teamId": "research-team", "roleKey": role}
        for role in RETAINED_AGENT_ROLE_KEYS
    ]
    return {
        "teamId": "research-team",
        "objects": {
            "teams": [{"teamId": "research-team"}],
            "agents": agents,
            "catalog": [{"catalogId": "science-125", "immutable": True}],
            "program": [{"programId": "competition-program-v2", "immutable": True}],
            "policy": [{"policyId": "full-catalog-v1", "immutable": True}],
            "rooms": [{"roomId": "legacy-room", "teamId": "research-team"}],
            "projects": [{"projectId": "legacy-project", "teamId": "research-team"}],
            "workflowRuns": [{"runId": "legacy-run", "teamId": "research-team"}],
            "sessions": [
                {
                    "sessionId": "legacy-session",
                    "agentId": "agent-challenge_cup_search",
                    "legacyChallenge": True,
                }
            ],
            "otherTeamRooms": [{"roomId": "do-not-touch", "teamId": "other-team"}],
        },
        "activeWork": active_work or {"authorityPresent": True, "activeCount": 0},
        "otherTeamProtection": {
            "authorityPresent": True,
            "snapshot": {"other-team": {"rooms": 1, "projects": 2}},
        },
    }


class _Reader:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def read_inventory(self, team_id: str) -> dict[str, Any]:
        assert team_id == "research-team"
        return self.payload


class _Ports:
    def __init__(
        self,
        *,
        bootstrap_ok: bool = True,
        bootstrap_raises: bool = False,
        destroy_raises: bool = False,
    ) -> None:
        self.calls: list[str] = []
        self.bootstrap_ok = bootstrap_ok
        self.bootstrap_raises = bootstrap_raises
        self.destroy_raises = destroy_raises

    def lookup_completed(self, purge_plan_id: str) -> None:
        self.calls.append("LOOKUP")
        return None

    def fence(self, team_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("FENCE")
        return {"fenceId": "fence-1"}

    def drain_check(self, team_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("DRAIN")
        return {"authorityPresent": True, "activeCount": 0}

    def stage(self, team_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("STAGE")
        return {"stageId": "stage-1"}

    def commit(self, team_id: str, plan: dict[str, Any], stage: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("COMMIT")
        return {"committed": True}

    def verify_zero(self, team_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("VERIFY_ZERO")
        return {"verified": True, "remainingCount": 0}

    def rebootstrap(self, team_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("REBOOTSTRAP")
        if self.bootstrap_raises:
            raise RuntimeError("catalog unavailable")
        if not self.bootstrap_ok:
            return {"projectId": GOLDEN_SAMPLE_PROJECT_ID, "questionId": GOLDEN_SAMPLE_QUESTION_ID, "status": "failed"}
        return {
            "projectId": GOLDEN_SAMPLE_PROJECT_ID,
            "questionId": GOLDEN_SAMPLE_QUESTION_ID,
            "bootstrapId": GOLDEN_SAMPLE_BOOTSTRAP_ID,
            "status": "initialized",
            "counts": {
                "plans": 0,
                "runs": 0,
                "results": 0,
                "rooms": 0,
                "checkpoints": 0,
                "artifacts": 0,
                "receipts": 0,
                "candidates": 0,
                "selections": 0,
                "meetings": 0,
                "rounds": 0,
                "legacyParticipantBindings": 0,
            },
        }

    def destroy_staging(self, team_id: str, plan: dict[str, Any], stage: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("DESTROY_STAGING")
        if self.destroy_raises:
            raise FileNotFoundError("staging child vanished")
        return {"destroyed": True}


def test_preview_is_deterministic_and_only_deletes_team_owned_runtime_objects() -> None:
    service = ChallengeCupResetService(inventory_reader=_Reader(_inventory()))

    first = service.preview().to_dict()
    second = service.preview().to_dict()

    assert first["purgePlanId"] == second["purgePlanId"]
    assert first["inventoryHash"] == second["inventoryHash"]
    assert first["safeToConfirm"] is True
    assert first["deleteSet"] == {
        "projects": ["legacy-project"],
        "rooms": ["legacy-room"],
        "sessions": ["legacy-session"],
        "workflow_runs": ["legacy-run"],
    }
    assert first["otherTeamProtectionHash"]
    assert first["retained"]["goldenSample"]["bootstrapId"] == GOLDEN_SAMPLE_BOOTSTRAP_ID
    # A preview never echoes private record bodies or transcript fields.
    assert "prompt" not in str(first)
    assert "transcript" not in str(first)


def test_active_work_and_unscoped_objects_fail_closed() -> None:
    payload = _inventory(active_work={"authorityPresent": True, "activeCount": 1})
    payload["objects"]["artifacts"] = [{"artifactId": "unscoped-artifact"}]

    preview = ChallengeCupResetService(inventory_reader=_Reader(payload)).preview().to_dict()

    assert preview["safeToConfirm"] is False
    codes = {item["code"] for item in preview["blockers"]}
    assert "active_work_present" in codes
    assert "unowned_or_unscoped_runtime_object" in codes

    with pytest.raises(ResetBlockedError):
        ChallengeCupResetService(inventory_reader=_Reader(payload)).confirm(
            purge_plan_id=preview["purgePlanId"],
            confirmation_phrase=CONFIRMATION_PHRASE,
        )


def test_typed_phrase_and_inventory_freshness_are_required() -> None:
    payload = _inventory()
    service = ChallengeCupResetService(inventory_reader=_Reader(payload))
    preview = service.preview().to_dict()

    with pytest.raises(ResetConfirmationError):
        service.confirm(
            purge_plan_id=preview["purgePlanId"],
            confirmation_phrase="RESET research-team KEEP SCI-097",
        )

    payload["objects"]["rooms"].append({"roomId": "new-room", "teamId": "research-team"})
    with pytest.raises(ResetPlanStaleError):
        service.confirm(
            purge_plan_id=preview["purgePlanId"],
            confirmation_phrase=CONFIRMATION_PHRASE,
        )


def test_unbound_destructive_adapter_is_fail_closed() -> None:
    service = ChallengeCupResetService(inventory_reader=_Reader(_inventory()))
    preview = service.preview().to_dict()

    with pytest.raises(ResetCapabilityError):
        service.execute(
            purge_plan_id=preview["purgePlanId"],
            confirmation_phrase=CONFIRMATION_PHRASE,
        )


def test_execute_follows_guarded_order_and_rebootstrap_contract() -> None:
    ports = _Ports()
    service = ChallengeCupResetService(inventory_reader=_Reader(_inventory()), destructive_adapter=ports)
    preview = service.preview().to_dict()

    result = service.execute(
        purge_plan_id=preview["purgePlanId"],
        confirmation_phrase=CONFIRMATION_PHRASE,
    )

    assert result["status"] == "succeeded"
    assert ports.calls == [
        "LOOKUP",
        "FENCE",
        "DRAIN",
        "STAGE",
        "COMMIT",
        "VERIFY_ZERO",
        "REBOOTSTRAP",
        "DESTROY_STAGING",
    ]
    assert result["stagingDestroyed"] is True


def test_rebootstrap_failure_does_not_destroy_staging() -> None:
    ports = _Ports(bootstrap_ok=False)
    service = ChallengeCupResetService(inventory_reader=_Reader(_inventory()), destructive_adapter=ports)
    preview = service.preview().to_dict()

    result = service.execute(
        purge_plan_id=preview["purgePlanId"],
        confirmation_phrase=CONFIRMATION_PHRASE,
    )

    assert result["status"] == "needs_rebootstrap"
    assert result["stagingDestroyed"] is False
    assert "DESTROY_STAGING" not in ports.calls


def test_rebootstrap_exception_preserves_purged_state_without_restore() -> None:
    ports = _Ports(bootstrap_raises=True)
    service = ChallengeCupResetService(inventory_reader=_Reader(_inventory()), destructive_adapter=ports)
    preview = service.preview().to_dict()

    result = service.execute(
        purge_plan_id=preview["purgePlanId"],
        confirmation_phrase=CONFIRMATION_PHRASE,
    )

    assert result["status"] == "needs_rebootstrap"
    assert result["stagingDestroyed"] is False
    assert ports.calls == ["LOOKUP", "FENCE", "DRAIN", "STAGE", "COMMIT", "VERIFY_ZERO", "REBOOTSTRAP"]
    assert result["steps"][-1] == {"step": "REBOOTSTRAP", "status": "blocked", "error": "RuntimeError"}


def test_finalization_exception_preserves_purged_state_without_restore() -> None:
    ports = _Ports(destroy_raises=True)
    service = ChallengeCupResetService(inventory_reader=_Reader(_inventory()), destructive_adapter=ports)
    preview = service.preview().to_dict()

    result = service.execute(
        purge_plan_id=preview["purgePlanId"],
        confirmation_phrase=CONFIRMATION_PHRASE,
    )

    assert result["status"] == "needs_finalize"
    assert result["stagingDestroyed"] is False
    assert ports.calls == [
        "LOOKUP", "FENCE", "DRAIN", "STAGE", "COMMIT", "VERIFY_ZERO", "REBOOTSTRAP", "DESTROY_STAGING"
    ]
    assert result["steps"][-1] == {"step": "DESTROY_STAGING", "status": "blocked", "error": "FileNotFoundError"}
