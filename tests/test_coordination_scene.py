from __future__ import annotations

from pathlib import Path

from core.infrastructure import coordination_scene


def test_notify_registry_written_records_new_claim(monkeypatch):
    events = []
    monkeypatch.setattr(
        coordination_scene,
        "_record_scene_event",
        lambda event_code, **kwargs: events.append({"event_code": event_code, **kwargs}),
    )

    coordination_scene.notify_registry_written(
        ".",
        {"claims": []},
        {
            "claims": [
                {
                    "id": "claim-abc",
                    "agentId": "agent-one",
                    "laneId": "git",
                    "status": "active",
                    "scopes": ["core/web/services/git_status_service.py"],
                    "task": "Add git read logging",
                }
            ]
        },
    )

    assert len(events) == 1
    assert events[0]["event_code"] == "coordination.claim.claimed"
    assert events[0]["level"] == "info"
    assert events[0]["outcome"] == "claimed"
    assert events[0]["fields"]["claimId"] == "claim-abc"
    assert events[0]["fields"]["agentId"] == "agent-one"
    assert events[0]["fields"]["laneId"] == "git"


def test_notify_registry_written_skips_unchanged_and_refreshed_claims(monkeypatch):
    events = []
    monkeypatch.setattr(
        coordination_scene,
        "_record_scene_event",
        lambda event_code, **kwargs: events.append(event_code),
    )
    claim = {
        "id": "claim-abc",
        "agentId": "agent-one",
        "laneId": "git",
        "status": "active",
        "scopes": ["core/web/services/git_status_service.py"],
        "task": "Add git read logging",
    }

    coordination_scene.notify_registry_written(
        ".",
        {"claims": [claim]},
        {"claims": [{**claim, "scopes": [*claim["scopes"], "tests/test_git_status_service.py"]}]},
    )

    assert events == []


def test_notify_registry_written_records_release_expire_and_yield(monkeypatch):
    events = []
    monkeypatch.setattr(
        coordination_scene,
        "_record_scene_event",
        lambda event_code, **kwargs: events.append({"event_code": event_code, **kwargs}),
    )

    coordination_scene.notify_registry_written(
        ".",
        {
            "claims": [
                {"id": "claim-a", "status": "active", "agentId": "agent-a", "laneId": "git"},
                {"id": "claim-b", "status": "active", "agentId": "agent-b", "laneId": "web"},
                {"id": "claim-c", "status": "active", "agentId": "agent-c", "laneId": "docs"},
            ]
        },
        {
            "claims": [
                {
                    "id": "claim-a",
                    "status": "completed",
                    "agentId": "agent-a",
                    "laneId": "git",
                    "releaseReason": "merged",
                },
                {"id": "claim-b", "status": "expired", "agentId": "agent-b", "laneId": "web"},
                {"id": "claim-c", "status": "yielded", "agentId": "agent-c", "laneId": "docs"},
            ]
        },
    )

    codes = [event["event_code"] for event in events]
    assert codes == [
        "coordination.claim.released",
        "coordination.claim.expired",
        "coordination.claim.yielded",
    ]
    released = events[0]
    assert released["fields"]["status"] == "completed"
    assert released["fields"]["reason"] == "merged"
    assert released["outcome"] == "released"


def test_notify_claim_blocked_records_overlap_without_full_task_text(monkeypatch):
    events = []
    monkeypatch.setattr(
        coordination_scene,
        "_record_scene_event",
        lambda event_code, **kwargs: events.append({"event_code": event_code, **kwargs}),
    )

    coordination_scene.notify_claim_blocked(
        ".",
        [
            {
                "claim": {
                    "id": "claim-hot",
                    "agentId": "agent-peer",
                    "scopes": ["core/infrastructure/storage_migration.py"],
                    "task": "secret-looking task text that must stay out of overlap payload",
                },
                "reasons": ["scope overlap: core/infrastructure/storage_migration.py"],
            }
        ],
        "Requested work overlaps an active claim.",
    )

    assert len(events) == 1
    event = events[0]
    assert event["event_code"] == "coordination.claim.blocked"
    assert event["level"] == "warning"
    assert event["outcome"] == "blocked"
    assert event["fields"]["overlappingClaimIds"] == ["claim-hot"]
    assert event["fields"]["overlappingAgentIds"] == ["agent-peer"]
    assert "secret-looking" not in str(event)
    assert event["fields"]["claimId"] == ""


def test_record_scene_event_uses_quietly_lifecycle_and_swallows_failures(monkeypatch):
    captured = {}

    def fake_quietly(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        raise RuntimeError("scene unavailable")

    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event_quietly",
        fake_quietly,
    )
    warnings = []
    monkeypatch.setattr(
        coordination_scene._debug_logger,
        "warning",
        lambda message, tag="": warnings.append((message, tag)),
    )

    coordination_scene._record_scene_event(
        "coordination.claim.claimed",
        message="Coordination claim claim-abc is active.",
        level="info",
        outcome="claimed",
        fields={"claimId": "claim-abc"},
    )

    assert captured["args"][0] == "coordination"
    assert captured["kwargs"]["lifecycle"] is True
    assert warnings
    assert warnings[0][1] == "SCENE"


def test_skill_hook_loader_can_exec_coordination_scene_module(tmp_path, monkeypatch):
    import importlib.util
    import hashlib

    events = []
    monkeypatch.setattr(
        coordination_scene,
        "_record_scene_event",
        lambda event_code, **kwargs: events.append(event_code),
    )
    hook_path = Path(coordination_scene.__file__).resolve()
    spec = importlib.util.spec_from_file_location(
        f"_hook_{hashlib.sha256(str(hook_path).encode()).hexdigest()[:8]}",
        hook_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._record_scene_event = lambda event_code, **kwargs: events.append(event_code)
    module.notify_registry_written(
        tmp_path,
        {"claims": []},
        {"claims": [{"id": "claim-hook", "status": "active", "agentId": "agent-x", "laneId": "git"}]},
    )
    assert events == ["coordination.claim.claimed"]
