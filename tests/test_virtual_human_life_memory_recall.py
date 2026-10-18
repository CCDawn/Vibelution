"""Native episodic memory recall for Companion Dialogue V2 (PRD 32.9).

The selector may only surface current, sourced, non-sensitive episodes of the
character's own Agent memory; ranking favours topical relevance, and a
correction-like turn flips to recency first so a fresh correction is never
buried under stale memories. Recall failures must degrade to an empty list and
never block the dialogue.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.agent_plugins.virtual_human_life.dialogue_memory_recall import (
    RECALL_MAX_PER_TURN,
    dialogue_followup_matches,
    select_dialogue_memory_recalls,
)
from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService

NOW = datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc)


def _memory(
    episode_id: str,
    text: str,
    *,
    agent_id: str = "agent-a",
    occurred_at: str = "2026-08-20T12:00:00+00:00",
    salience: int = 50,
    **extra: object,
) -> dict[str, object]:
    return {
        "agentId": agent_id,
        "episodeId": episode_id,
        "text": text,
        "occurredAt": occurred_at,
        "salienceScore": salience,
        "sourceKind": "shared_experience",
        **extra,
    }


# ----------------------------------------------------------------------
# Pure selector semantics
# ----------------------------------------------------------------------


def test_selector_returns_only_relevant_current_sourced_memories() -> None:
    memories = [
        _memory(
            "episode-relevant",
            "和小岚一起去看了一场钢琴演出，她全程都很开心。",
        ),
        _memory("episode-irrelevant", "今天整理了书架上的旧杂志。"),
        _memory(
            "episode-superseded",
            "钢琴演出的旧版本记忆。",
            excludedFromRecall=True,
        ),
        _memory("episode-sensitive", "敏感的私人片段。", sensitive=True),
        _memory(
            "episode-preference",
            "VIBELUTION_COMPANION_PREFERENCE_V1:{\"preferenceKind\":\"address\"}",
        ),
        _memory("episode-foreign", "别的 Agent 的钢琴演出。", agent_id="agent-b"),
        _memory("episode-empty", "   "),
    ]

    recalls = select_dialogue_memory_recalls(
        memories,
        current_message="还记得我们一起看的那场钢琴演出吗",
        user_intent="small_talk",
        now=NOW,
        agent_id="agent-a",
    )

    assert [item["sourceKey"] for item in recalls] == ["memory:episode-relevant"]
    only = recalls[0]
    assert only["episodeId"] == "episode-relevant"
    assert "钢琴演出" in only["summary"]
    assert only["relevanceScore"] > 0
    assert only["occurredAt"] == "2026-08-20T12:00:00+00:00"
    assert only["sourceKind"] == "shared_experience"
    assert set(only) == {
        "sourceKey",
        "episodeId",
        "summary",
        "occurredAt",
        "sourceKind",
        "salienceScore",
        "relevanceScore",
    }


def test_selector_caps_at_three_and_ranks_relevance_then_salience() -> None:
    memories = [
        _memory("episode-strong", "钢琴演出非常难忘。", salience=90),
        _memory("episode-mid", "那场钢琴演出的灯光很美。", salience=50),
        _memory("episode-weak", "钢琴", salience=95, occurred_at="2026-08-25T10:00:00+00:00"),
        _memory("episode-fresh-low", "钢琴演出的票根还在。", salience=5),
        _memory("episode-irrelevant", "完全无关的一天。"),
    ]

    recalls = select_dialogue_memory_recalls(
        memories,
        current_message="钢琴演出怎么样",
        user_intent="small_talk",
        now=NOW,
        agent_id="agent-a",
    )

    assert len(recalls) == RECALL_MAX_PER_TURN == 3
    assert [item["episodeId"] for item in recalls] == [
        "episode-strong",
        "episode-mid",
        "episode-fresh-low",
    ]


def test_correction_like_intents_rank_recency_first() -> None:
    memories = [
        _memory(
            "episode-old-topical",
            "钢琴演出在五月，她当时说最喜欢钢琴。",
            salience=90,
            occurred_at="2026-05-01T10:00:00+00:00",
        ),
        _memory(
            "episode-fresh",
            "钢琴演出其实是六月，她后来纠正过日期。",
            salience=10,
            occurred_at="2026-08-30T10:00:00+00:00",
        ),
    ]

    plain = select_dialogue_memory_recalls(
        memories,
        current_message="钢琴演出",
        user_intent="small_talk",
        now=NOW,
        agent_id="agent-a",
    )
    corrected = select_dialogue_memory_recalls(
        memories,
        current_message="钢琴演出",
        user_intent="correction",
        now=NOW,
        agent_id="agent-a",
    )
    misunderstood = select_dialogue_memory_recalls(
        memories,
        current_message="钢琴演出",
        user_intent="misunderstanding",
        now=NOW,
        agent_id="agent-a",
    )

    assert [item["episodeId"] for item in plain] == [
        "episode-old-topical",
        "episode-fresh",
    ]
    assert [item["episodeId"] for item in corrected] == [
        "episode-fresh",
        "episode-old-topical",
    ]
    assert [item["episodeId"] for item in misunderstood] == [
        "episode-fresh",
        "episode-old-topical",
    ]


def test_dialogue_followup_matches_requires_real_overlap() -> None:
    assert (
        dialogue_followup_matches(
            "再说说那场钢琴演出吧", "和小岚一起去看钢琴演出，她很开心。"
        )
        is True
    )
    assert dialogue_followup_matches("今天天气不错", "钢琴演出很精彩") is False


# ----------------------------------------------------------------------
# Service wiring
# ----------------------------------------------------------------------


def _recall_service(
    tmp_path: Path,
    *,
    episodes: list[dict[str, object]],
    clock: list[datetime],
):
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
        conversation_submitter=lambda **payload: {
            "accepted": True,
            "turnId": f"turn-user-{str(payload.get('client_submission_id') or '0').rsplit('-', 1)[-1]}",
            "status": "running",
        },
        episodic_lister=lambda agent_id, limit=500: list(episodes),
        auto_mailbox_dispatch=False,
        now_provider=lambda: clock[0],
    )
    service.set_binding(
        "agent-a",
        enabled=True,
        expected_version=0,
        config={"timezone": "Asia/Shanghai"},
    )
    return service


def _seed_promotion_receipt(service: VirtualHumanLifeService) -> None:
    service.store.append_jsonl(
        "agent-a",
        "memory/promotion_receipts.jsonl",
        {
            "receiptId": "receipt-recall-1",
            "episodeId": "episode-recall-1",
            "sourceEventIds": [],
            "salienceScore": 80,
            "occurredAt": "2026-08-20T12:00:00+00:00",
            "promotedAt": "2026-08-20T13:00:00+00:00",
        },
    )


def test_service_recall_feeds_allowed_keys_and_prompt_payload(
    tmp_path: Path,
) -> None:
    clock = [NOW]
    episodes = [
        {
            "agentId": "agent-a",
            "episodeId": "episode-recall-1",
            "kind": "episodic",
            "text": "和小岚一起去看钢琴演出，她全程都很开心。",
            "occurredAt": "2026-08-20T12:00:00+00:00",
            "validUntil": "",
            "refs": [],
        }
    ]
    service = _recall_service(tmp_path, episodes=episodes, clock=clock)
    _seed_promotion_receipt(service)
    service.queue_conversation_message(
        "agent-a",
        session_id="session-agent-a",
        client_submission_id="submission-1",
        content="还记得我们一起看的那场钢琴演出吗",
    )

    recalls = service._dialogue_memory_recalls(
        "agent-a", session_id="session-agent-a"
    )
    assert [item["sourceKey"] for item in recalls] == ["memory:episode-recall-1"]
    assert "钢琴演出" in recalls[0]["summary"]
    assert set(recalls[0]) == {
        "sourceKey",
        "summary",
        "occurredAt",
        "sourceKind",
    }

    assert "memory:episode-recall-1" in service._dialogue_v2_allowed_source_keys(
        "agent-a"
    )

    segments = service.build_prompt_segments(
        "agent-a",
        session_id="session-agent-a",
        run_id="turn-user-1",
    )
    assert any("recalledMemories" in str(part) for part in segments)


def test_proactive_and_self_wake_turns_skip_recall(tmp_path: Path) -> None:
    clock = [NOW]
    episodes = [
        {
            "agentId": "agent-a",
            "episodeId": "episode-recall-1",
            "text": "和小岚一起去看钢琴演出。",
            "occurredAt": "2026-08-20T12:00:00+00:00",
            "validUntil": "",
            "refs": [],
        }
    ]
    service = _recall_service(tmp_path, episodes=episodes, clock=clock)
    _seed_promotion_receipt(service)
    service.queue_conversation_message(
        "agent-a",
        session_id="session-agent-a",
        client_submission_id="submission-1",
        content="还记得我们一起看的那场钢琴演出吗",
    )

    for kind in ("proactive", "self_wake"):
        assert (
            service._dialogue_memory_recalls(
                "agent-a", session_id="session-agent-a", proactive_delivery_kind=kind
            )
            == []
        )


def test_recall_failure_never_blocks_dialogue(tmp_path: Path) -> None:
    clock = [NOW]

    def broken_lister(agent_id: str, limit: int = 500):
        raise RuntimeError("episodic store unavailable")

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
        conversation_submitter=lambda **payload: {
            "accepted": True,
            "turnId": "turn-user-1",
            "status": "running",
        },
        episodic_lister=broken_lister,
        auto_mailbox_dispatch=False,
        now_provider=lambda: clock[0],
    )
    service.set_binding(
        "agent-a",
        enabled=True,
        expected_version=0,
        config={"timezone": "Asia/Shanghai"},
    )

    queued = service.queue_conversation_message(
        "agent-a",
        session_id="session-agent-a",
        client_submission_id="submission-1",
        content="还记得我们一起看的那场钢琴演出吗",
    )
    assert queued["accepted"] is True

    assert (
        service._dialogue_memory_recalls("agent-a", session_id="session-agent-a")
        == []
    )
    assert (
        "memory:episode-recall-1"
        not in service._dialogue_v2_allowed_source_keys("agent-a")
    )
