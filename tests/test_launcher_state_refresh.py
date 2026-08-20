from __future__ import annotations

from core.launcher.state_refresh import bounded_source_error_message


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
    list_kwargs = {}

    def fake_list(*, include_cleanup_metadata=False):
        list_kwargs["include_cleanup_metadata"] = include_cleanup_metadata
        return branch_instances

    monkeypatch.setattr(launcher_service, "list_launcher_branch_instances", fake_list)
    monkeypatch.setattr(launcher_service, "get_launcher_status", lambda: {"status": "ok"})
    monkeypatch.setattr(launcher_service, "get_launcher_freshness", lambda: {"current": True})

    def fake_reconcile(**kwargs):
        seen.update(kwargs)
        return {
            "observedAt": "2026-08-19T07:00:00Z",
            "nextReconcileAt": "2026-08-19T07:00:10Z",
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

    monkeypatch.setattr(instances_registry, "preview_reconcile_registry", fake_reconcile)
    monkeypatch.setattr(
        instances_registry,
        "load_registry",
        lambda: {"instances": {"worktree:external": {"port": 8765, "controlPort": 0}}},
    )

    payload = state_refresh.build_launcher_state_refresh(
        electron_window_instance_ids=["main", "worktree:isolated"],
    )

    assert list_kwargs["include_cleanup_metadata"] is False
    assert seen["git_worktree_roots"] == ["C:/repo/current", "C:/repo/old"]
    assert seen["electron_window_instance_ids"] == ["worktree:current", "worktree:isolated"]
    assert payload["status"] == {"ok": True, "value": {"status": "ok"}}
    assert payload["nextReconcileAt"] == "2026-08-19T07:00:10Z"
    assert payload["branchInstances"]["ok"] is True
    cleanup = payload["cleanup"]["value"]
    assert cleanup["instances"][0]["classification"] == "conflict"
    assert cleanup["instances"][0]["ports"] == [8765]
    assert cleanup["removedInstanceIds"] == []
    assert [item["instanceId"] for item in cleanup["worktreeDryRun"]] == [
        "worktree:missing",
        "worktree:old",
    ]
    assert all(item["action"] == "dry_run_only" for item in cleanup["worktreeDryRun"])
    assert "two_identical_observations_at_least_10_seconds_apart" in cleanup["orphanCriteria"]


def test_cleanup_timeout_still_returns_status_and_bounds_error(monkeypatch):
    from core.launcher import service as launcher_service
    from core.launcher import state_refresh
    from core.runtime_manager import instances_registry

    monkeypatch.setattr(
        launcher_service,
        "list_launcher_branch_instances",
        lambda *, include_cleanup_metadata=False: {"currentId": "main", "items": []},
    )
    monkeypatch.setattr(launcher_service, "get_launcher_status", lambda: {"status": "running"})
    monkeypatch.setattr(launcher_service, "get_launcher_freshness", lambda: {"current": True})

    def boom(**_kwargs):
        raise TimeoutError("git merge-base timed out stdout=" + ("OUT" * 400) + " stderr=" + ("ERR" * 400))

    monkeypatch.setattr(instances_registry, "preview_reconcile_registry", boom)

    payload = state_refresh.build_launcher_state_refresh(electron_window_instance_ids=["main"])

    assert payload["status"] == {"ok": True, "value": {"status": "running"}}
    assert payload["branchInstances"]["ok"] is True
    assert payload["cleanup"]["ok"] is False
    assert payload["cleanup"]["errorType"] == "TimeoutError"
    message = payload["cleanup"]["message"]
    assert "stdout" not in message.lower()
    assert "stderr" not in message.lower()
    assert "OUT" not in message
    assert "ERR" not in message
    assert len(message) <= state_refresh.SOURCE_ERROR_LIMIT


def test_status_failure_keeps_branch_success_envelope(monkeypatch):
    from core.launcher import service as launcher_service
    from core.launcher import state_refresh
    from core.runtime_manager import instances_registry

    monkeypatch.setattr(
        launcher_service,
        "list_launcher_branch_instances",
        lambda *, include_cleanup_metadata=False: {"currentId": "main", "items": [{"id": "worktree:ok"}]},
    )

    def boom_status():
        raise RuntimeError("status probe failed")

    monkeypatch.setattr(launcher_service, "get_launcher_status", boom_status)
    monkeypatch.setattr(launcher_service, "get_launcher_freshness", lambda: {"current": False})
    monkeypatch.setattr(
        instances_registry,
        "preview_reconcile_registry",
        lambda **_kwargs: {"instances": [], "removedInstanceIds": [], "worktreeDryRun": []},
    )
    monkeypatch.setattr(instances_registry, "load_registry", lambda: {"instances": {}})

    payload = state_refresh.build_launcher_state_refresh()

    assert payload["status"]["ok"] is False
    assert payload["status"]["errorType"] == "RuntimeError"
    assert payload["branchInstances"]["ok"] is True
    assert payload["branchInstances"]["value"]["items"][0]["id"] == "worktree:ok"
    assert payload["cleanup"]["ok"] is True


def test_state_refresh_preview_does_not_write_registry(monkeypatch):
    from core.launcher import service as launcher_service
    from core.launcher import state_refresh
    from core.runtime_manager import instances_registry

    monkeypatch.setattr(
        launcher_service,
        "list_launcher_branch_instances",
        lambda *, include_cleanup_metadata=False: {"currentId": "main", "items": []},
    )
    monkeypatch.setattr(launcher_service, "get_launcher_status", lambda: {"status": "ok"})
    monkeypatch.setattr(launcher_service, "get_launcher_freshness", lambda: {"current": True})
    monkeypatch.setattr(
        instances_registry,
        "preview_reconcile_registry",
        lambda **_kwargs: {"instances": [], "removedInstanceIds": [], "worktreeDryRun": []},
    )
    monkeypatch.setattr(instances_registry, "load_registry", lambda: {"instances": {}})

    def boom_save(_payload):
        raise AssertionError("state refresh must not save instances.json")

    monkeypatch.setattr(instances_registry, "save_registry", boom_save)
    payload = state_refresh.build_launcher_state_refresh()
    assert payload["cleanup"]["ok"] is True


def test_bounded_source_error_message_strips_stdio_dumps():
    err = TimeoutError("cleanup failed stdout=secret-out stderr=secret-err")
    message = bounded_source_error_message(err)
    assert "stdout" not in message.lower()
    assert "stderr" not in message.lower()
    assert "secret-out" not in message
    assert len(message) <= 180
