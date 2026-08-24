from __future__ import annotations

import hashlib

import pytest

from core.web.services.team_workflow.research_runtime import (
    challenge_cup_maintenance_fence as fence,
)


def _inventory_hash(value: str = "inventory") -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_fence_is_persistent_idempotent_and_conflict_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(fence, "research_workflow_data_root", lambda: tmp_path)
    inventory_hash = _inventory_hash()

    acquired = fence.acquire_fence(
        "research-team",
        purge_plan_id="plan-1",
        inventory_hash=inventory_hash,
        acquired_by="reset-test",
    )
    assert acquired["status"] == "acquired"
    assert fence.read_fence("research-team")["purgePlanId"] == "plan-1"

    reused = fence.acquire_fence(
        "research-team",
        purge_plan_id="plan-1",
        inventory_hash=inventory_hash,
        acquired_by="another-retry",
    )
    assert reused["status"] == "reused"
    assert reused["acquiredBy"] == "reset-test"

    with pytest.raises(fence.ChallengeCupMaintenanceConflictError) as exc_info:
        fence.acquire_fence(
            "research-team",
            purge_plan_id="plan-2",
            inventory_hash=inventory_hash,
        )
    assert exc_info.value.code == "challenge_cup_maintenance_conflict"
    assert "plan-1" not in str(exc_info.value)
    assert inventory_hash not in str(exc_info.value)

    released = fence.release_fence(
        "research-team",
        purge_plan_id="plan-1",
        inventory_hash=inventory_hash,
    )
    assert released["status"] == "released"
    assert fence.read_fence("research-team") is None


def test_fence_scope_and_write_guard_are_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(fence, "research_workflow_data_root", lambda: tmp_path)
    inventory_hash = _inventory_hash("scope")

    with pytest.raises(fence.ChallengeCupMaintenanceScopeError):
        fence.acquire_fence(
            "other-team",
            purge_plan_id="plan-1",
            inventory_hash=inventory_hash,
        )
    assert fence.assert_writes_allowed("other-team", operation="question_launch") is None
    assert fence.assert_writes_allowed("research-team", operation="question_launch") is None

    acquired = fence.acquire_fence(
        "research-team",
        purge_plan_id="plan-1",
        inventory_hash=inventory_hash,
    )
    with pytest.raises(fence.ChallengeCupMaintenanceActiveError) as exc_info:
        fence.assert_writes_allowed("research-team", operation="question_launch")
    assert exc_info.value.code == "challenge_cup_maintenance_active"
    assert "challenge_cup_maintenance" in str(exc_info.value)

    # A dispatch that was accepted before the fence belongs to the drain set.
    assert (
        fence.assert_writes_allowed(
            "research-team",
            operation="workflow_dispatch",
            created_at_ms=acquired["acquiredAtMs"] - 1,
        )["purgePlanId"]
        == "plan-1"
    )


def test_fence_release_requires_exact_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(fence, "research_workflow_data_root", lambda: tmp_path)
    inventory_hash = _inventory_hash("release")
    fence.acquire_fence(
        "research-team",
        purge_plan_id="plan-1",
        inventory_hash=inventory_hash,
    )

    with pytest.raises(fence.ChallengeCupMaintenanceConflictError):
        fence.release_fence(
            "research-team",
            purge_plan_id="plan-1",
            inventory_hash=_inventory_hash("different"),
        )
    assert fence.read_fence("research-team") is not None
