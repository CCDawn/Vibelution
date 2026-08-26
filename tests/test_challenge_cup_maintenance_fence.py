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


def test_fence_lease_reclaims_expired_marker_and_records_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(fence, "research_workflow_data_root", lambda: tmp_path)
    inventory_hash = _inventory_hash("lease")
    acquired = fence.acquire_fence(
        "research-team",
        purge_plan_id="plan-lease",
        inventory_hash=inventory_hash,
        acquired_by="reset-test",
        ttl_ms=100,
        owner_pid=4242,
        now_ms=1_750_000_000_000,
    )

    assert acquired["ownerPid"] == 4242
    assert acquired["expiresAtMs"] == 1_750_000_000_100
    assert acquired["ttlMs"] == 100
    live = fence.inspect_fence(
        "research-team",
        now_ms=1_750_000_000_099,
        owner_alive=lambda _pid: True,
    )
    assert live["status"] == "active"
    assert live["activeFence"]["purgePlanId"] == "plan-lease"

    expired = fence.inspect_fence(
        "research-team",
        now_ms=1_750_000_000_100,
        owner_alive=lambda _pid: True,
    )
    assert expired["status"] == "expired"
    assert expired["reclaimed"] is True
    assert expired["activeFence"] is None
    assert fence.read_fence("research-team") is None


def test_fence_reclaims_known_dead_owner_before_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(fence, "research_workflow_data_root", lambda: tmp_path)
    inventory_hash = _inventory_hash("orphan")
    fence.acquire_fence(
        "research-team",
        purge_plan_id="plan-orphan",
        inventory_hash=inventory_hash,
        ttl_ms=60_000,
        owner_pid=4242,
        now_ms=1_750_000_000_000,
    )

    state = fence.inspect_fence(
        "research-team",
        now_ms=1_750_000_000_001,
        owner_alive=lambda _pid: False,
    )
    assert state["status"] == "orphaned"
    assert state["ownerAlive"] is False
    assert state["reclaimed"] is True
    assert fence.read_fence("research-team") is None


def test_fence_unknown_owner_stays_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(fence, "research_workflow_data_root", lambda: tmp_path)
    inventory_hash = _inventory_hash("unknown-owner")
    fence.acquire_fence(
        "research-team",
        purge_plan_id="plan-unknown-owner",
        inventory_hash=inventory_hash,
        ttl_ms=100,
        owner_pid=4242,
        now_ms=1_750_000_000_000,
    )

    state = fence.inspect_fence(
        "research-team",
        now_ms=1_750_000_000_100,
        owner_alive=lambda _pid: None,
    )
    assert state["status"] == "unknown"
    assert state["activeFence"] is not None
    with pytest.raises(fence.ChallengeCupMaintenanceActiveError):
        fence.assert_writes_allowed(
            "research-team",
            operation="question_launch",
            now_ms=1_750_000_000_100,
            owner_alive=lambda _pid: None,
        )
