from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.agent_plugins.virtual_human_life.companion_preferences import (
    CompanionPreferenceManager,
    CompanionPreferencePersistenceError,
    encode_companion_preference_episode,
    expression_preferences,
    project_companion_preferences,
)
from core.agent_plugins.virtual_human_life.interaction_expression import (
    build_companion_expression_decision,
)
from core.agent_plugins.virtual_human_life.service import (
    VirtualHumanLifeError,
    VirtualHumanLifeService,
)


def _episode(
    episode_id: str,
    preference_kind: str,
    value: object,
    *,
    agent_id: str = "agent-a",
    review_status: str = "user_confirmed",
) -> dict[str, object]:
    return {
        "agentId": agent_id,
        "episodeId": episode_id,
        "kind": "preference",
        "text": encode_companion_preference_episode(
            preference_kind,
            value,
            review_status=review_status,
        ),
        "occurredAt": "2026-09-01T02:00:00+00:00",
        "validUntil": "",
    }


def test_projection_accepts_only_reviewed_agent_scoped_structured_preferences() -> None:
    rows = project_companion_preferences(
        "agent-a",
        [
            _episode("episode-address", "address", "小岚"),
            _episode("episode-length", "response_length", "detailed"),
            _episode(
                "episode-unreviewed",
                "humor",
                "off",
                review_status="inferred",
            ),
            _episode(
                "episode-foreign",
                "privacy",
                "never_mention_memory",
                agent_id="agent-b",
            ),
            {
                "agentId": "agent-a",
                "episodeId": "episode-plain",
                "kind": "preference",
                "text": "The user probably prefers short answers.",
            },
            {
                **_episode("episode-unscoped", "privacy", "relevant_only"),
                "agentId": "",
            },
        ],
    )

    assert [item["preferenceKind"] for item in rows["cards"]] == [
        "address",
        "response_length",
    ]
    assert rows["values"] == {
        "address": "小岚",
        "response_length": "detailed",
    }
    assert "episode-unreviewed" not in json.dumps(rows, ensure_ascii=False)
    assert "episode-foreign" not in json.dumps(rows, ensure_ascii=False)
    assert "episode-unscoped" not in json.dumps(rows, ensure_ascii=False)


def test_expression_preferences_change_style_without_expanding_question_budget() -> None:
    projected = project_companion_preferences(
        "agent-a",
        [
            _episode("episode-address", "address", "阿澈"),
            _episode("episode-length", "response_length", "detailed"),
            _episode("episode-questions", "question_tolerance", "low"),
            _episode("episode-humor", "humor", "off"),
            _episode("episode-privacy", "privacy", "never_mention_memory"),
        ],
    )

    decision = build_companion_expression_decision(
        relationship={"relationshipStage": "close"},
        affect={"mood": {"valence": 18, "stability": 76}},
        energy=80,
        user_intent="small_talk",
        turn_ordinal=3,
        preferences=expression_preferences(projected),
    )

    assert decision["preferredAddress"] == "阿澈"
    assert decision["responseLength"] == "detailed"
    assert decision["questionBudget"] == 0
    assert decision["humorMode"] == "off"
    assert decision["memoryMention"] == "none"


def test_correction_and_delete_use_native_supersede_and_receipts_have_no_value(
    tmp_path: Path,
) -> None:
    current: list[dict[str, object]] = []
    supersede_calls: list[tuple[str, str]] = []

    def writer(
        agent_id: str,
        *,
        kind: str,
        text: str,
        refs: list[dict[str, str]],
        occurred_at: str = "",
    ) -> dict[str, object]:
        row = {
            "agentId": agent_id,
            "episodeId": f"episode-{len(current) + 1}",
            "kind": kind,
            "text": text,
            "refs": refs,
            "occurredAt": occurred_at,
            "validUntil": "",
        }
        current.append(row)
        return deepcopy(row)

    def lister(agent_id: str, *, limit: int = 500) -> list[dict[str, object]]:
        return [
            deepcopy(row)
            for row in current
            if row["agentId"] == agent_id and not row.get("validUntil")
        ][:limit]

    def superseder(
        agent_id: str,
        episode_id: str,
        *,
        successor_episode_id: str = "",
    ) -> dict[str, object]:
        supersede_calls.append((episode_id, successor_episode_id))
        for row in current:
            if row["agentId"] == agent_id and row["episodeId"] == episode_id:
                row["validUntil"] = "2026-09-01T02:01:00+00:00"
                row["supersededByEpisodeId"] = successor_episode_id
                return deepcopy(row)
        raise AssertionError("missing episode")

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
        episodic_writer=writer,
        episodic_lister=lister,
        episodic_superseder=superseder,
        now_provider=lambda: datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc),
    )
    service.set_binding(
        "agent-a",
        enabled=True,
        expected_version=0,
        config={"timezone": "Asia/Shanghai"},
    )

    first = service.execute_command(
        "agent-a",
        command="upsertCompanionPreference",
        expected_version=1,
        idempotency_key="preference-address-1",
        arguments={"preferenceKind": "address", "value": "小岚"},
    )
    second = service.execute_command(
        "agent-a",
        command="upsertCompanionPreference",
        expected_version=2,
        idempotency_key="preference-address-2",
        arguments={"preferenceKind": "address", "value": "岚岚"},
    )
    deleted = service.execute_command(
        "agent-a",
        command="deleteCompanionPreference",
        expected_version=3,
        idempotency_key="preference-address-delete",
        arguments={"preferenceKind": "address"},
    )

    assert first["result"]["preference"]["value"] == "小岚"
    assert second["result"]["preference"]["value"] == "岚岚"
    assert deleted["result"]["deleted"] is True
    assert supersede_calls == [
        ("episode-1", "episode-2"),
        ("episode-2", ""),
    ]
    assert service.list_companion_preferences("agent-a")["cards"] == []

    receipts = service.store.read_jsonl(
        "agent-a", "memory/preference_reconciliation_receipts.jsonl"
    )
    assert [receipt["operation"] for receipt in receipts] == [
        "create",
        "correct",
        "delete",
    ]
    serialized = json.dumps(receipts, ensure_ascii=False)
    assert "小岚" not in serialized
    assert "岚岚" not in serialized


def test_snapshot_projects_preferences_but_life_world_does_not_store_them(
    tmp_path: Path,
) -> None:
    episode = _episode("episode-address", "address", "小岚")
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
        episodic_lister=lambda agent_id, limit=500: (
            [episode] if agent_id == "agent-a" else []
        ),
        now_provider=lambda: datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc),
    )
    service.set_binding(
        "agent-a",
        enabled=True,
        expected_version=0,
        config={"timezone": "Asia/Shanghai"},
    )

    snapshot = service.snapshot("agent-a")
    prompt_segments = service.build_prompt_segments("agent-a")

    assert snapshot["causal"]["companionPreferences"]["values"]["address"] == "小岚"
    assert "companionPreferences" not in snapshot["lifeWorld"]
    assert '"preferredAddress": "小岚"' in prompt_segments[-1]["block"]


def test_supersede_failure_invalidates_the_new_native_episode() -> None:
    current = [
        _episode("episode-old", "address", "小岚"),
    ]
    calls: list[tuple[str, str]] = []

    def writer(agent_id: str, **_: object) -> dict[str, object]:
        created = _episode("episode-new", "address", "岚岚", agent_id=agent_id)
        current.insert(0, created)
        return created

    def superseder(
        agent_id: str,
        episode_id: str,
        *,
        successor_episode_id: str = "",
    ) -> dict[str, object]:
        calls.append((episode_id, successor_episode_id))
        if episode_id == "episode-old":
            raise RuntimeError("native supersede failed")
        for row in current:
            if row["agentId"] == agent_id and row["episodeId"] == episode_id:
                row["validUntil"] = "2026-09-01T02:01:00+00:00"
                return deepcopy(row)
        raise AssertionError("missing episode")

    manager = CompanionPreferenceManager(
        episodic_writer=writer,
        episodic_lister=lambda agent_id: [
            deepcopy(row)
            for row in current
            if row["agentId"] == agent_id and not row.get("validUntil")
        ],
        episodic_superseder=superseder,
        receipt_appender=lambda _agent_id, _receipt: None,
        now_iso=lambda: "2026-09-01T02:00:00+00:00",
    )

    with pytest.raises(
        CompanionPreferencePersistenceError,
        match="previous native preference",
    ):
        manager.upsert("agent-a", preference_kind="address", value="岚岚")

    assert calls == [
        ("episode-old", "episode-new"),
        ("episode-new", ""),
    ]
    assert manager.project("agent-a")["values"] == {"address": "小岚"}


def test_receipt_failure_does_not_turn_a_native_memory_success_into_a_retry() -> None:
    current: list[dict[str, object]] = []

    def writer(agent_id: str, **_: object) -> dict[str, object]:
        created = _episode("episode-new", "privacy", "relevant_only", agent_id=agent_id)
        current.insert(0, created)
        return created

    manager = CompanionPreferenceManager(
        episodic_writer=writer,
        episodic_lister=lambda agent_id: [
            deepcopy(row)
            for row in current
            if row["agentId"] == agent_id and not row.get("validUntil")
        ],
        episodic_superseder=lambda *_args, **_kwargs: {},
        receipt_appender=lambda _agent_id, _receipt: (_ for _ in ()).throw(
            OSError("disk unavailable")
        ),
        now_iso=lambda: "2026-09-01T02:00:00+00:00",
    )

    result = manager.upsert(
        "agent-a",
        preference_kind="privacy",
        value="relevant_only",
    )

    assert result["preference"]["value"] == "relevant_only"
    assert result["receipt"]["recorded"] is False
    assert result["receipt"]["recordingError"] == "OSError"
    assert manager.project("agent-a")["values"] == {"privacy": "relevant_only"}


def test_invalid_preference_command_fails_before_native_memory_write(
    tmp_path: Path,
) -> None:
    writes: list[dict[str, object]] = []
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
        episodic_writer=lambda *_args, **kwargs: writes.append(kwargs) or {},
        episodic_lister=lambda _agent_id, limit=500: [],
        episodic_superseder=lambda *_args, **_kwargs: {},
        now_provider=lambda: datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc),
    )
    service.set_binding(
        "agent-a",
        enabled=True,
        expected_version=0,
        config={"timezone": "Asia/Shanghai"},
    )

    with pytest.raises(VirtualHumanLifeError, match="Unsupported Companion preference"):
        service.execute_command(
            "agent-a",
            command="upsertCompanionPreference",
            expected_version=1,
            idempotency_key="invalid-preference",
            arguments={"preferenceKind": "favorite_secret", "value": "hidden"},
        )

    assert writes == []
