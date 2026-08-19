from __future__ import annotations


def test_state_refresh_maps_electron_window_truth_and_keeps_cleanup_dry_run(monkeypatch):
    from core.launcher import service as launcher_service
    from core.launcher import state_refresh
    from core.runtime_manager import instances_registry

    branch_instances = {
        "currentId": "worktree:current",
        "items": [
            {
                "id": "worktree:current",
                "kind": "worktree",
                "path": "C:/repo/current",
                "checkedOut": True,
                "current": True,
                "cleanupEligible": False,
            },
            {
                "id": "worktree:old",
                "kind": "worktree",
                "path": "C:/repo/old",
                "branch": "codex/old",
                "checkedOut": True,
                "current": False,
                "dirty": True,
                "mergedToMain": False,
                "cleanupEligible": True,
                "cleanupRisks": ["discard_dirty", "delete_unmerged"],
            },
        ],
    }
    seen = {}

    monkeypatch.setattr(
        launcher_service,
        "list_launcher_branch_instances",
        lambda *, include_cleanup_metadata=False: branch_instances,
    )
    monkeypatch.setattr(launcher_service, "get_launcher_status", lambda: {"status": "ok"})
    monkeypatch.setattr(launcher_service, "get_launcher_freshness", lambda: {"current": True})

    def fake_reconcile(**kwargs):
        seen.update(kwargs)
        return {
            "observedAt": "2026-08-19T07:00:00Z",
            "instances": [
                {
                    "instanceId": "worktree:external",
                    "classification": "conflict",
                    "reasons": ["external_listener"],
                    "windowOpen": False,
                    "listener": ["external"],
                }
            ],
            "removedInstanceIds": [],
            "worktreeDryRun": [
                {
                    "instanceId": "worktree:missing",
                    "projectRoot": "C:/repo/missing",
                    "reason": "path_missing",
                    "action": "dry_run_only",
                }
            ],
        }

    monkeypatch.setattr(instances_registry, "reconcile_registry", fake_reconcile)
    monkeypatch.setattr(
        instances_registry,
        "load_registry",
        lambda: {"instances": {"worktree:external": {"port": 8765, "controlPort": 0}}},
    )

    payload = state_refresh.build_launcher_state_refresh(
        electron_window_instance_ids=["main", "worktree:isolated"],
    )

    assert seen["git_worktree_roots"] == ["C:/repo/current", "C:/repo/old"]
    assert seen["electron_window_instance_ids"] == ["worktree:current", "worktree:isolated"]
    assert payload["status"] == {"status": "ok"}
    assert payload["cleanup"]["instances"][0]["classification"] == "conflict"
    assert payload["cleanup"]["instances"][0]["ports"] == [8765]
    assert payload["cleanup"]["removedInstanceIds"] == []
    assert [item["instanceId"] for item in payload["cleanup"]["worktreeDryRun"]] == [
        "worktree:missing",
        "worktree:old",
    ]
    assert all(item["action"] == "dry_run_only" for item in payload["cleanup"]["worktreeDryRun"])
    assert "two_identical_observations_at_least_10_seconds_apart" in payload["cleanup"]["orphanCriteria"]
