from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.agent_plugins.virtual_human_life.embodiment import resolve_embodiment
from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService


UTC = timezone.utc


def _resolve(**overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "config": {"enabled": True, "mode": "portrait"},
        "authorized_assets": [],
        "provider_health": {},
        "state": {
            "energy": 72,
            "currentLocation": "home",
            "locationSource": {"sourceRef": "binding:home"},
        },
        "affect": {
            "mood": {"label": "calm", "valence": 10, "arousal": 30},
            "activeEpisodeIds": [],
        },
        "current_activity": None,
        "environment": {"currentFacts": []},
        "local_time": datetime(2026, 9, 1, 10, 20, tzinfo=UTC),
        "prefers_reduced_motion": False,
    }
    arguments.update(overrides)
    return resolve_embodiment(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    (
        "activity",
        "affect",
        "energy",
        "location",
        "hour",
        "expression",
        "motion",
        "scene",
    ),
    [
        (
            {
                "activityId": "activity-study",
                "activityKind": "study",
                "title": "复习课程",
            },
            {
                "mood": {"label": "bright", "valence": 70, "arousal": 65},
                "activeEpisodeIds": ["affect-happy"],
            },
            88,
            "school-library",
            10,
            "focused",
            "attentive",
            "campus-day",
        ),
        (
            None,
            {
                "mood": {"label": "bright", "valence": 48, "arousal": 55},
                "activeEpisodeIds": ["affect-happy"],
            },
            76,
            "office",
            14,
            "happy",
            "celebrating",
            "office-day",
        ),
        (
            None,
            {
                "mood": {"label": "low", "valence": -45, "arousal": 24},
                "activeEpisodeIds": ["affect-low"],
            },
            74,
            "home",
            20,
            "low",
            "breathing",
            "home-evening",
        ),
        (
            None,
            {
                "mood": {"label": "bright", "valence": 62, "arousal": 70},
                "activeEpisodeIds": ["affect-happy"],
            },
            22,
            "home",
            23,
            "tired",
            "resting",
            "home-night",
        ),
    ],
)
def test_embodiment_state_is_deterministic_from_activity_affect_energy_and_place(
    activity: dict[str, object] | None,
    affect: dict[str, object],
    energy: int,
    location: str,
    hour: int,
    expression: str,
    motion: str,
    scene: str,
) -> None:
    result = _resolve(
        state={
            "energy": energy,
            "currentLocation": location,
            "locationSource": {"sourceRef": f"location:{location}"},
        },
        affect=affect,
        current_activity=activity,
        local_time=datetime(2026, 9, 1, hour, 20, tzinfo=UTC),
    )

    assert result["expressionId"] == expression
    assert result["motionPreset"] == motion
    assert result["sceneKey"] == scene
    assert result["textChatUnaffected"] is True
    assert result == _resolve(
        state={
            "energy": energy,
            "currentLocation": location,
            "locationSource": {"sourceRef": f"location:{location}"},
        },
        affect=affect,
        current_activity=activity,
        local_time=datetime(2026, 9, 1, hour, 20, tzinfo=UTC),
    )


def test_fresh_weather_can_shape_scene_but_stale_weather_cannot() -> None:
    fresh_fact = {
        "factId": "weather-fresh",
        "factKey": "weather.condition",
        "value": "rain",
        "observedAt": "2026-09-01T08:45:00+00:00",
    }
    stale_fact = {
        **fresh_fact,
        "factId": "weather-stale",
        "observedAt": "2026-09-01T01:00:00+00:00",
    }
    now = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)

    fresh = _resolve(
        state={"energy": 70, "currentLocation": "city-park"},
        environment={"currentFacts": [fresh_fact]},
        local_time=now,
    )
    stale = _resolve(
        state={"energy": 70, "currentLocation": "city-park"},
        environment={"currentFacts": [stale_fact]},
        local_time=now,
    )

    assert fresh["sceneKey"] == "outdoors-rain"
    assert {item["ref"] for item in fresh["sourceRefs"]} == {"weather-fresh"}
    assert stale["sceneKey"] == "outdoors-day"
    assert stale["fallbackReason"] == "stale_source"
    assert stale["sourceRefs"] == []


def test_reduced_motion_disables_nonessential_animation_without_losing_state() -> None:
    result = _resolve(
        affect={
            "mood": {"label": "bright", "valence": 55, "arousal": 70},
            "activeEpisodeIds": ["affect-bright"],
        },
        prefers_reduced_motion=True,
    )

    assert result["expressionId"] == "happy"
    assert result["motionPreset"] == "still"
    assert result["blinkProfile"] == {
        "enabled": False,
        "minIntervalMs": 0,
        "maxIntervalMs": 0,
    }
    assert result["fallbackReason"] == "reduced_motion"


def test_only_licensed_manifest_assets_enter_embodiment_state() -> None:
    config = {
        "enabled": True,
        "providerId": "live2d-local",
        "mode": "live2d",
        "assetRef": "assets/model.model3.json",
    }
    manifest = [
        {
            "assetRef": "assets/model.model3.json",
            "assetKind": "model",
            "licenseReceipt": "license:model",
            "sourceRef": "user-import:model",
        },
        {
            "assetRef": "assets/happy.png",
            "assetKind": "expression",
            "stateKey": "happy",
            "licenseReceipt": "license:happy",
            "sourceRef": "user-import:happy",
        },
        {
            "assetRef": "assets/office.png",
            "assetKind": "background",
            "stateKey": "office-day",
            "licenseReceipt": "license:office",
            "sourceRef": "user-import:office",
        },
        {
            "assetRef": "assets/unlicensed.png",
            "assetKind": "expression",
            "stateKey": "happy",
            "sourceRef": "unknown",
        },
        {
            "assetRef": "assets/unsourced.png",
            "assetKind": "expression",
            "stateKey": "happy",
            "licenseReceipt": "license:unsourced",
        },
    ]

    healthy = _resolve(
        config=config,
        authorized_assets=manifest,
        provider_health={"live2d-local": {"available": True}},
        affect={
            "mood": {"label": "bright", "valence": 55, "arousal": 60},
            "activeEpisodeIds": ["affect-happy"],
        },
        state={"energy": 80, "currentLocation": "office"},
        local_time=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    unauthorized = _resolve(
        config={**config, "assetRef": "assets/unlicensed.png"},
        authorized_assets=manifest,
        provider_health={"live2d-local": {"available": True}},
    )
    wrong_slot = _resolve(
        config={**config, "assetRef": "assets/happy.png"},
        authorized_assets=manifest,
        provider_health={"live2d-local": {"available": True}},
    )

    assert healthy["activeMode"] == "live2d"
    assert healthy["assetRefs"] == {
        "primary": "assets/model.model3.json",
        "expression": "assets/happy.png",
        "background": "assets/office.png",
    }
    assert healthy["assetLicenseReceipt"] == "license:model"
    assert "assets/unlicensed.png" not in str(healthy)
    assert "assets/unsourced.png" not in str(healthy)
    assert healthy["assetReceipts"]["expression"] == {
        "licenseReceipt": "license:happy",
        "sourceRef": "user-import:happy",
    }
    assert unauthorized["activeMode"] == "portrait"
    assert unauthorized["fallbackReason"] == "asset_not_authorized"
    assert wrong_slot["activeMode"] == "portrait"
    assert wrong_slot["fallbackReason"] == "asset_not_authorized"


def test_provider_failure_keeps_text_chat_and_portrait_fallback() -> None:
    result = _resolve(
        config={
            "enabled": True,
            "providerId": "live2d-local",
            "mode": "live2d",
            "assetRef": "assets/model.model3.json",
        },
        authorized_assets=[
            {
                "assetRef": "assets/model.model3.json",
                "licenseReceipt": "license:model",
            }
        ],
        provider_health={"live2d-local": {"available": False}},
    )

    assert result["activeMode"] == "portrait"
    assert result["fallbackReason"] == "provider_unavailable"
    assert result["textChatUnaffected"] is True
    assert result["validUntil"] == "2026-09-01T10:30:00+00:00"


def test_service_snapshot_projects_embodiment_from_existing_life_state(
    tmp_path: Path,
) -> None:
    current = datetime(2026, 9, 1, 10, 20, tzinfo=UTC)
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-agent-a",
    }
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        embodiment_health_provider=lambda _agent_id: {
            "live2d-local": {"available": True}
        },
        now_provider=lambda: current,
    )
    service.set_binding(
        "agent-a",
        enabled=True,
        expected_version=0,
        config={"timezone": "UTC"},
    )
    state = service.store.read_json("agent-a", "state.json") or {}
    state.update(
        {
            "energy": 82,
            "currentActivityId": "activity-work",
            "currentLocation": "office",
            "locationSource": {"sourceRef": "calendar:office"},
        }
    )
    service.store.write_json("agent-a", "state.json", state)
    service.store.write_json(
        "agent-a",
        "schedules/2026-09-01.json",
        {
            "localDate": "2026-09-01",
            "activities": [
                {
                    "activityId": "activity-work",
                    "activityKind": "work",
                    "title": "整理项目资料",
                    "status": "active",
                    "startAt": "09:00",
                    "endAt": "12:00",
                }
            ],
        },
    )
    service.store.write_json(
        "agent-a",
        "embodiment/config.json",
        {
            "enabled": True,
            "providerId": "live2d-local",
            "mode": "live2d",
            "assetRef": "assets/model.model3.json",
        },
    )
    service.store.write_json(
        "agent-a",
        "embodiment/assets.json",
        {
            "schemaVersion": 1,
            "assets": [
                {
                    "assetRef": "assets/model.model3.json",
                    "assetKind": "model",
                    "licenseReceipt": "license:model",
                    "sourceRef": "user-import:model",
                },
                {
                    "assetRef": "assets/focused.png",
                    "assetKind": "expression",
                    "stateKey": "focused",
                    "licenseReceipt": "license:focused",
                    "sourceRef": "user-import:focused",
                },
            ],
        },
    )

    embodiment = service.snapshot("agent-a")["causal"]["embodiment"]

    assert embodiment["expressionId"] == "focused"
    assert embodiment["motionPreset"] == "attentive"
    assert embodiment["sceneKey"] == "office-day"
    assert embodiment["activeMode"] == "live2d"
    assert embodiment["assetRefs"]["expression"] == "assets/focused.png"
    assert {item["ref"] for item in embodiment["sourceRefs"]} == {
        "activity-work",
        "calendar:office",
    }
