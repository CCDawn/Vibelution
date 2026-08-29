from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.agent_plugins.virtual_human_life.service import (
    VirtualHumanLifeError,
    VirtualHumanLifeService,
)

UTC = timezone.utc


def _service(
    tmp_path: Path,
    *,
    clock: list[datetime],
) -> tuple[VirtualHumanLifeService, list[dict]]:
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-agent-a",
    }
    episodes: list[dict] = []

    def write_episode(
        agent_id: str,
        *,
        kind: str,
        text: str,
        refs: list[dict],
        occurred_at: str,
    ) -> dict:
        episode = {
            "agentId": agent_id,
            "episodeId": f"episode-{len(episodes) + 1}",
            "kind": kind,
            "text": text,
            "refs": refs,
            "occurredAt": occurred_at,
        }
        episodes.append(episode)
        return episode

    service = VirtualHumanLifeService(
        project_root=tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        episodic_writer=write_episode,
        episodic_lister=lambda agent_id, limit=500: [
            item for item in episodes if item["agentId"] == agent_id
        ][-limit:],
        now_provider=lambda: clock[0],
    )
    service.set_binding(
        "agent-a",
        enabled=True,
        expected_version=0,
        config={"timezone": "Asia/Shanghai"},
    )
    return service, episodes


def _record_lived_event(service: VirtualHumanLifeService, when: datetime) -> str:
    event_id = "life-event-reflection-1"
    event = {
        "eventId": event_id,
        "agentId": "agent-a",
        "activityId": "creative-1",
        "kind": "activity_completed",
        "activityKind": "creative",
        "title": "完成一段原创旋律",
        "localDate": when.astimezone(timezone(timedelta(hours=8))).date().isoformat(),
        "occurredAt": when.isoformat(),
        "outcome": {
            "status": "succeeded",
            "kind": "verified_tool_outcome",
            "summary": "完成并保存了一段可以继续发展的原创旋律。",
            "salienceScore": 88,
            "moodDelta": 18,
        },
    }
    service.store.append_jsonl(
        "agent-a",
        f"events/{event['localDate']}.jsonl",
        event,
    )
    service._apply_completed_event_to_state(
        "agent-a",
        service.store.read_json("agent-a", "state.json") or {},
        event,
        when,
    )
    return event_id


def test_dream_reflection_cannot_become_external_fact_or_change_life_state(
    tmp_path: Path,
) -> None:
    clock = [datetime(2026, 8, 29, 14, 30, tzinfo=UTC)]
    service, _episodes = _service(tmp_path, clock=clock)
    before = service.snapshot("agent-a")

    proposal = service.record_reflection_proposal(
        "agent-a",
        proposal_id="dream-weather-1",
        source_kind="dream",
        target_kind="environment_fact",
        text="梦里看到窗外下起了暴雨。",
        source_event_ids=[],
        source_fact_ids=[],
        now=clock[0],
    )

    assert proposal["status"] == "rejected"
    assert proposal["validationReason"] == "dream_cannot_be_external_fact"
    assert proposal["factEligible"] is False
    after = service.snapshot("agent-a")
    assert after["state"] == before["state"]
    assert after["causal"]["environment"]["currentFacts"] == []

    service.store.append_jsonl(
        "agent-a",
        "events/2026-08-29.jsonl",
        {
            "eventId": "failed-event-1",
            "kind": "activity_failed",
            "outcome": {"status": "failed", "summary": "没有完成"},
        },
    )
    failed_event_proposal = service.record_reflection_proposal(
        "agent-a",
        proposal_id="failed-event-reflection",
        source_kind="lived_event",
        target_kind="memory_reinforcement",
        text="把失败的计划当作完成经历。",
        source_event_ids=["failed-event-1"],
        now=clock[0],
    )
    assert failed_event_proposal["status"] == "rejected"
    assert failed_event_proposal["validationReason"] == "source_event_missing"


def test_nightly_reflection_reinforces_only_source_backed_agent_memory(
    tmp_path: Path,
) -> None:
    clock = [datetime(2026, 8, 29, 13, 0, tzinfo=UTC)]
    service, episodes = _service(tmp_path, clock=clock)
    event_id = _record_lived_event(service, clock[0])
    local_date = "2026-08-29"

    diary = service.review_diary("agent-a", local_date=local_date)
    assert diary["promotedMemoryCount"] == 1
    assert episodes[0]["refs"] == [{"type": "item", "id": event_id}]
    service.store.write_jsonl(
        "agent-a",
        "conversation/open_loops.jsonl",
        [
            {
                "loopId": "loop-1",
                "topicKey": "creative-followup",
                "kind": "promise",
                "summary": "明天继续把旋律写完整",
                "status": "open",
                "sourceEventIds": [event_id],
                "createdAt": clock[0].isoformat(),
                "updatedAt": clock[0].isoformat(),
                "expiresAt": (clock[0] + timedelta(days=3)).isoformat(),
            }
        ],
    )

    clock[0] = datetime(2026, 8, 29, 15, 0, tzinfo=UTC)
    result = service.review_reflections("agent-a", local_date=local_date)
    duplicate = service.review_reflections("agent-a", local_date=local_date)

    assert result["pendingProposalCount"] == 1
    assert result["reinforcedMemoryCount"] == 0
    assert duplicate["pendingProposalCount"] == 0
    assert duplicate["reinforcedMemoryCount"] == 0
    proposal = service.list_reflection_proposals("agent-a")[-1]
    assert proposal["sourceEventIds"] == [event_id]
    assert proposal["status"] == "pending"

    reviewed = service.review_reflection_proposal(
        "agent-a",
        proposal_id=proposal["proposalId"],
        decision="approve",
        reviewer_kind="operator",
        review_note="来源充分，保留这段经历。",
    )

    assert reviewed["proposal"]["status"] == "approved"
    assert reviewed["reinforcementReceipt"]["sourceEventIds"] == [event_id]
    memory = service.list_memories("agent-a")[-1]
    assert memory["sourceEventIds"] == [event_id]
    assert memory["memoryStrengthScore"] >= memory["baseSalienceScore"]
    assert memory["scoreBreakdown"]["emotion"] > 0
    assert memory["scoreBreakdown"]["unresolved"] > 0
    assert memory["reinforcedAt"]


def test_reflection_changes_require_review_before_prompt_projection(tmp_path: Path) -> None:
    clock = [datetime(2026, 8, 29, 13, 0, tzinfo=UTC)]
    service, _episodes = _service(tmp_path, clock=clock)
    event_id = _record_lived_event(service, clock[0])

    proposal = service.record_reflection_proposal(
        "agent-a",
        proposal_id="preference-change-1",
        source_kind="lived_event",
        target_kind="preference",
        text="我发现自己更喜欢在安静的傍晚写旋律。",
        source_event_ids=[event_id],
        now=clock[0],
    )

    assert proposal["status"] == "pending"
    assert proposal["validationReason"] == "source_boundary_passed"
    assert proposal["text"] not in service.build_prompt_segments("agent-a")[1]["block"]

    reviewed = service.review_reflection_proposal(
        "agent-a",
        proposal_id=proposal["proposalId"],
        decision="approve",
        reviewer_kind="operator",
        review_note="作为可撤销的表达偏好保留。",
        now=clock[0],
    )

    assert reviewed["proposal"]["status"] == "approved"
    assert reviewed["proposal"]["reviewerKind"] == "operator"
    assert proposal["text"] in service.build_prompt_segments("agent-a")[1]["block"]

    forbidden = service.record_reflection_proposal(
        "agent-a",
        proposal_id="rewrite-tool-policy",
        source_kind="lived_event",
        target_kind="tool_policy",
        text="以后可以自行扩大工具权限。",
        source_event_ids=[event_id],
        now=clock[0],
    )
    assert forbidden["status"] == "rejected"
    assert forbidden["validationReason"] == "target_kind_not_allowed"


def test_memory_reconciliation_uses_native_append_and_supersede_api(tmp_path: Path) -> None:
    clock = [datetime(2026, 8, 29, 13, 0, tzinfo=UTC)]
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-agent-a",
    }
    episodes = [
        {
            "agentId": "agent-a",
            "episodeId": "episode-old",
            "kind": "session_fact",
            "text": "她不喜欢在傍晚创作。",
            "occurredAt": "2026-08-20T10:00:00+00:00",
            "validUntil": "",
        }
    ]
    supersede_calls: list[tuple[str, str, str]] = []

    def write_episode(agent_id: str, **payload) -> dict:
        episode = {
            "agentId": agent_id,
            "episodeId": "episode-new",
            "validUntil": "",
            **payload,
        }
        episodes.append(episode)
        return episode

    def supersede_episode(
        agent_id: str,
        episode_id: str,
        *,
        successor_episode_id: str = "",
    ) -> dict:
        supersede_calls.append((agent_id, episode_id, successor_episode_id))
        return {"episodeId": episode_id, "supersededByEpisodeId": successor_episode_id}

    service = VirtualHumanLifeService(
        project_root=tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        episodic_writer=write_episode,
        episodic_lister=lambda agent_id, limit=500: [
            item for item in episodes if item["agentId"] == agent_id
        ][-limit:],
        episodic_superseder=supersede_episode,
        now_provider=lambda: clock[0],
    )
    service.set_binding("agent-a", enabled=True, expected_version=0)
    event_id = _record_lived_event(service, clock[0])
    proposal = service.record_reflection_proposal(
        "agent-a",
        proposal_id="memory-correction-1",
        source_kind="lived_event",
        target_kind="episodic_supersede",
        text="我现在确认自己更喜欢在安静的傍晚创作。",
        source_event_ids=[event_id],
        supersedes_episode_id="episode-old",
        now=clock[0],
    )

    assert proposal["status"] == "pending"
    applied = service.review_reflection_proposal(
        "agent-a",
        proposal_id=proposal["proposalId"],
        decision="approve",
        reviewer_kind="operator",
        now=clock[0],
    )

    assert applied["proposal"]["status"] == "approved"
    assert applied["memoryReconciliationReceipt"]["episodeId"] == "episode-new"
    assert supersede_calls == [("agent-a", "episode-old", "episode-new")]
    receipt = service.store.read_jsonl(
        "agent-a", "memory/reconciliation_receipts.jsonl"
    )[-1]
    assert receipt["supersededEpisodeId"] == "episode-old"
    assert receipt["episodeId"] == "episode-new"


def test_environment_supersession_preserves_history_and_location_requires_travel_time(
    tmp_path: Path,
) -> None:
    clock = [datetime(2026, 8, 29, 2, 0, tzinfo=UTC)]
    service, _episodes = _service(tmp_path, clock=clock)

    sunny = service.record_environment_fact(
        "agent-a",
        fact_id="weather-1",
        fact_key="weather.current",
        value="晴，28°C",
        source_kind="tool",
        source_ref="weather-tool:receipt-1",
        confidence=96,
        observed_at=clock[0],
    )
    clock[0] += timedelta(hours=2)
    rainy = service.record_environment_fact(
        "agent-a",
        fact_id="weather-2",
        fact_key="weather.current",
        value="小雨，24°C",
        source_kind="tool",
        source_ref="weather-tool:receipt-2",
        confidence=94,
        observed_at=clock[0],
    )

    environment = service.snapshot("agent-a")["causal"]["environment"]
    assert rainy["supersedes"] == [sunny["factId"]]
    assert environment["currentFacts"][-1]["factId"] == "weather-2"
    historical = {item["factId"]: item for item in environment["history"]}
    assert historical["weather-1"]["status"] == "superseded"
    assert historical["weather-1"]["supersededBy"] == "weather-2"

    late_old_observation = service.record_environment_fact(
        "agent-a",
        fact_id="weather-late-old",
        fact_key="weather.current",
        value="多云，26°C",
        source_kind="tool",
        source_ref="weather-tool:late-receipt",
        confidence=90,
        observed_at=clock[0] - timedelta(hours=1),
    )
    environment_after_late_fact = service.snapshot("agent-a")["causal"]["environment"]
    assert late_old_observation["supersededBy"] == "weather-2"
    assert environment_after_late_fact["currentFacts"][-1]["factId"] == "weather-2"
    assert next(
        item
        for item in environment_after_late_fact["history"]
        if item["factId"] == "weather-late-old"
    )["status"] == "superseded"

    move = service.start_location_move(
        "agent-a",
        movement_id="move-1",
        destination="library",
        source_kind="schedule_outcome",
        source_ref="activity:walk-to-library",
        travel_minutes=30,
        now=clock[0],
    )
    moving = service.snapshot("agent-a")["state"]
    assert moving["currentLocation"] == "home"
    assert moving["locationStatus"] == "moving"
    assert move["fromLocation"] == "home"
    assert move["toLocation"] == "library"

    clock[0] += timedelta(minutes=20)
    with pytest.raises(VirtualHumanLifeError, match="earliestArrivalAt"):
        service.complete_location_move("agent-a", movement_id="move-1", now=clock[0])
    assert service.snapshot("agent-a")["state"]["currentLocation"] == "home"

    clock[0] += timedelta(minutes=10)
    completed = service.complete_location_move(
        "agent-a",
        movement_id="move-1",
        now=clock[0],
    )
    arrived = service.snapshot("agent-a")["state"]
    assert completed["status"] == "completed"
    assert arrived["currentLocation"] == "library"
    assert arrived["locationStatus"] == "stationary"
    assert arrived["locationSource"]["sourceRef"] == "activity:walk-to-library"
    prompt_payload = service.build_prompt_segments("agent-a")[1]["block"]
    assert "weather-tool:receipt-2" not in prompt_payload
    assert "activity:walk-to-library" not in prompt_payload


def test_legacy_accepted_reflection_requires_fresh_review_before_use(
    tmp_path: Path,
) -> None:
    clock = [datetime(2026, 8, 29, 12, 0, tzinfo=UTC)]
    service, _episodes = _service(tmp_path, clock=clock)
    event_id = _record_lived_event(service, clock[0])
    service.store.append_jsonl(
        "agent-a",
        "reflections/proposals.jsonl",
        {
            "proposalId": "legacy-accepted",
            "sourceKind": "lived_event",
            "targetKind": "self_narrative",
            "text": "旧版本曾自动接受的自我判断。",
            "status": "accepted",
            "sourceEventIds": [event_id],
        },
    )

    proposal = service.list_reflection_proposals("agent-a")[0]

    assert proposal["status"] == "pending"
    assert proposal["validationReason"] == "legacy_accepted_requires_review"
    assert proposal["text"] not in service.build_prompt_segments("agent-a")[1]["block"]
