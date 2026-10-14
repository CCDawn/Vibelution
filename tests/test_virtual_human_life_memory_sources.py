"""Historical simulation correction stays within exact native episode sources."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from core.agent_plugins.virtual_human_life.memory_sources import (
    CORRECTION_LEDGER,
    LifeMemorySourceReconciler,
)


NOW = "2026-10-14T12:00:00+00:00"
PROMOTIONS = "memory/promotion_receipts.jsonl"


def test_real_native_memory_is_preserved_but_excluded_before_companion_admission(tmp_path, monkeypatch):
    from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService
    from core.web.services import agent_directory_service as directory
    from core.web.services.agent_directory.episodic_memory import list_episodic_events
    from core.web.services.virtual_human_life_service import (
        _default_episodic_history_lister, _default_episodic_superseder,
    )

    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(directory, "PROJECT_ROOT", tmp_path)
    agent = directory.create_agent_instance(display_name="Life source acceptance")
    agent["directSessionId"] = "memory-acceptance-session"
    agent_id = agent["agentId"]
    source_id = "simulation-acceptance"
    original = directory.append_episodic_event(
        agent_id, kind="private_note", text="完成了创作。",
        refs=[{"type": "item", "id": source_id}],
    )
    user_note = directory.append_episodic_event(agent_id, kind="note", text="完成了创作。")
    admissions = []

    def submit(**payload):
        current = directory.list_current_episodic_events(agent_id, limit=200)
        admissions.append([row["episodeId"] for row in current])
        return {"accepted": True, "turnId": "acceptance-turn"}

    service = VirtualHumanLifeService(
        tmp_path, agent_loader=lambda target, **_kwargs: agent if target == agent_id else None,
        agent_lister=lambda: [agent], plugin_root_resolver=lambda target: tmp_path / "plugin" / target,
        episodic_lister=directory.list_current_episodic_events,
        episodic_history_lister=_default_episodic_history_lister,
        episodic_superseder=_default_episodic_superseder,
        conversation_submitter=submit, auto_mailbox_dispatch=False,
    )
    service.set_binding(agent_id, enabled=True, expected_version=0)
    service.store.append_jsonl(agent_id, "events/2026-10-14.jsonl", _event(source_id))
    service.store.append_jsonl(agent_id, PROMOTIONS, {
        "receiptId": "acceptance-receipt", "episodeId": original["episodeId"],
        "sourceEventIds": [source_id],
    })
    service.queue_conversation_message(
        agent_id, session_id=agent["directSessionId"], client_submission_id="acceptance-message",
        content="继续聊聊",)
    assert admissions
    assert original["episodeId"] not in admissions[0]
    assert user_note["episodeId"] in admissions[0]
    history = list_episodic_events(agent_id, include_superseded=True)
    retained = next(row for row in history if row["episodeId"] == original["episodeId"])
    assert retained["text"] == original["text"] and retained["validUntil"]
    projected = service.list_memories(agent_id)
    assert projected[0]["sourceKind"] == "simulation"
    assert projected[0]["excludedFromRecall"] is True
    assert projected[0]["text"] == original["text"]
    assert service.snapshot(agent_id)["health"]["memoryPromotionCount"] == 0
    assert "完成了创作" not in str(service.store.read_jsonl(agent_id, CORRECTION_LEDGER))


def _receipt(episode_id="episode-1", sources=None):
    return {
        "receiptId": f"receipt-{episode_id}",
        "episodeId": episode_id,
        "sourceEventIds": sources if sources is not None else ["simulation-1"],
    }


def _episode(episode_id="episode-1", *, agent_id="agent-a", kind="private_note", refs=None):
    return {
        "schemaVersion": 1,
        "episodeId": episode_id,
        "eventId": episode_id,
        "agentId": agent_id,
        "kind": kind,
        "text": "我今天完成了创作。",
        "refs": refs if refs is not None else [{"type": "item", "id": "simulation-1"}],
        "validFrom": "2026-10-13T12:00:00+00:00",
        "validUntil": "",
        "supersededByEpisodeId": "",
    }


def _event(event_id="simulation-1", source="simulation"):
    return {
        "eventId": event_id,
        "kind": "activity_completed",
        "outcome": {
            "status": "succeeded",
            "kind": {
                "simulation": "deterministic_simulation",
                "character_report": "character_report",
                "unknown": "verified_tool_outcome",
            }.get(source, source),
        },
    }


class _Ledger:
    def __init__(self, receipts, corrections=None):
        self.rows = {PROMOTIONS: deepcopy(receipts), CORRECTION_LEDGER: deepcopy(corrections or [])}
        self.append_failures = 0
        self.appends = []

    def read_jsonl(self, agent_id, path):
        assert agent_id == "agent-a"
        return deepcopy(self.rows[path])

    def append_jsonl(self, agent_id, path, row):
        assert agent_id == "agent-a"
        assert path == CORRECTION_LEDGER
        if self.append_failures:
            self.append_failures -= 1
            raise OSError("correction ledger unavailable")
        self.appends.append(deepcopy(row))
        self.rows[path].append(deepcopy(row))


def _harness(episodes=None, receipts=None, events=None):
    episodes = deepcopy(episodes if episodes is not None else [_episode()])
    ledger = _Ledger(receipts if receipts is not None else [_receipt()])
    history_calls = []
    supersede_calls = []

    def history(agent_id, *, limit, include_superseded, episode_ids):
        assert agent_id == "agent-a"
        assert limit == 500
        assert include_superseded is True
        assert 0 < len(episode_ids) <= 500
        history_calls.append(list(episode_ids))
        return [deepcopy(row) for row in episodes if row["episodeId"] in episode_ids]

    def supersede(agent_id, episode_id):
        supersede_calls.append((agent_id, episode_id))
        episode = next(row for row in episodes if row["episodeId"] == episode_id)
        episode["validUntil"] = NOW
        return deepcopy(episode)

    reconciler = LifeMemorySourceReconciler(
        ledger,
        history_lister=history,
        superseder=supersede,
        event_lister=lambda agent_id: deepcopy(events if events is not None else [_event()]),
        now_iso=lambda: NOW,
    )
    return reconciler, ledger, episodes, history_calls, supersede_calls


def test_only_exact_plugin_receipt_and_simulation_sources_are_corrected_idempotently():
    reconciler, ledger, episodes, history_calls, supersede_calls = _harness(
        receipts=[_receipt(), _receipt()]
    )

    first = reconciler.reconcile("agent-a")
    second = reconciler.reconcile("agent-a")

    assert first == second == [
        {
            "episodeId": "episode-1",
            "receiptId": "receipt-episode-1",
            "sourceEventIds": ["simulation-1"],
            "reason": "schedule_simulation",
            "status": "applied",
            "correctedAt": NOW,
        }
    ]
    assert len(ledger.appends) == 1
    assert supersede_calls == [("agent-a", "episode-1")]
    assert history_calls == [["episode-1"]]
    assert episodes[0]["text"] == "我今天完成了创作。"
    assert episodes[0]["validUntil"] == NOW
    assert "text" not in first[0]


@pytest.mark.parametrize("kind", ["note", "session_fact", "preference"])
def test_same_text_user_episode_of_other_kind_is_untouched(kind):
    reconciler, ledger, episodes, _, supersede_calls = _harness(episodes=[_episode(kind=kind)])
    assert reconciler.reconcile("agent-a") == []
    assert supersede_calls == ledger.appends == []
    assert episodes[0]["validUntil"] == ""


def test_same_id_and_text_from_another_agent_is_untouched():
    reconciler, ledger, episodes, _, supersede_calls = _harness(
        episodes=[_episode(agent_id="agent-b")]
    )
    assert reconciler.reconcile("agent-a") == []
    assert supersede_calls == ledger.appends == []
    assert episodes[0]["validUntil"] == ""


def test_same_text_without_plugin_promotion_receipt_is_untouched():
    reconciler, ledger, episodes, history_calls, supersede_calls = _harness(receipts=[])
    assert reconciler.reconcile("agent-a") == []
    assert supersede_calls == ledger.appends == history_calls == []
    assert episodes[0]["validUntil"] == ""


@pytest.mark.parametrize(
    "refs",
    [
        [],
        [{"type": "item", "id": "another-event"}],
        [{"type": "item", "id": "simulation-1"}, {"type": "item", "id": "extra-event"}],
        [{"type": "item", "id": "simulation-1"}, {"type": "session", "id": "user-session"}],
        [{"type": "item", "id": "simulation-1"}, "malformed"],
    ],
)
def test_source_refs_must_match_exactly_without_other_user_refs(refs):
    reconciler, ledger, _, _, supersede_calls = _harness(episodes=[_episode(refs=refs)])
    assert reconciler.reconcile("agent-a") == []
    assert supersede_calls == ledger.appends == []


@pytest.mark.parametrize("source", ["missing", "unknown", "character_report"])
def test_missing_or_unverified_source_is_never_invalidated(source):
    events = [] if source == "missing" else [_event(source=source)]
    reconciler, ledger, _, _, supersede_calls = _harness(events=events)
    assert reconciler.reconcile("agent-a") == []
    assert supersede_calls == ledger.appends == []


def test_mixed_simulation_and_unknown_source_is_untouched():
    sources = ["simulation-1", "unknown-1"]
    reconciler, ledger, _, _, supersede_calls = _harness(
        receipts=[_receipt(sources=sources)],
        episodes=[_episode(refs=[{"type": "item", "id": source} for source in sources])],
        events=[_event(), _event("unknown-1", "unknown")],
    )
    assert reconciler.reconcile("agent-a") == []
    assert supersede_calls == ledger.appends == []


def test_missing_native_history_is_a_read_only_noop():
    reconciler, ledger, _, _, supersede_calls = _harness()
    reconciler.history_lister = None
    assert reconciler.reconcile("agent-a") == []
    assert supersede_calls == ledger.appends == []


def test_missing_native_superseder_cannot_claim_correction():
    reconciler, ledger, _, _, _ = _harness()
    reconciler.superseder = None
    with pytest.raises(RuntimeError, match="unavailable"):
        reconciler.reconcile("agent-a")
    assert ledger.appends == []


@pytest.mark.parametrize("result", [None, {}, {"validUntil": ""}, {"episode": {"validUntil": NOW}}])
def test_supersession_without_native_invalidation_confirmation_is_not_applied(result):
    reconciler, ledger, _, _, _ = _harness()
    reconciler.superseder = lambda *_: result
    with pytest.raises(RuntimeError, match="did not confirm"):
        reconciler.reconcile("agent-a")
    assert ledger.appends == []


def test_native_supersession_response_schema_is_accepted(tmp_path, monkeypatch):
    from core.web.services.agent_directory import episodic_memory

    monkeypatch.setattr(
        episodic_memory,
        "_service",
        lambda: SimpleNamespace(utc_now_iso=lambda: NOW, AgentEpisodicEventNotFoundError=LookupError),
    )
    native_episode = _episode()
    transaction = episodic_memory.EpisodicMemoryTransaction(
        {"agentId": "agent-a"}, tmp_path / "episodic_events.jsonl", [native_episode]
    )
    reconciler, ledger, _, _, _ = _harness()
    reconciler.superseder = lambda agent_id, episode_id: transaction.supersede(episode_id)

    assert reconciler.reconcile("agent-a")[0]["status"] == "applied"
    assert native_episode["validUntil"] == NOW
    assert len(ledger.appends) == 1


def test_correction_ledger_failure_recovers_from_native_supersession_on_retry():
    reconciler, ledger, episodes, _, supersede_calls = _harness()
    ledger.append_failures = 1
    with pytest.raises(OSError, match="ledger unavailable"):
        reconciler.reconcile("agent-a")
    assert episodes[0]["validUntil"] == NOW
    assert ledger.rows[CORRECTION_LEDGER] == []

    recovered = reconciler.reconcile("agent-a")
    assert recovered[0]["status"] == "applied"
    assert supersede_calls == [("agent-a", "episode-1")]
    assert reconciler.reconcile("agent-a") == recovered
    assert len(ledger.appends) == 1


def test_history_is_fetched_in_full_500_id_batches_without_losing_older_promotions():
    count = 1001
    episode_ids = [f"episode-{index:04d}" for index in range(count)]
    reconciler, ledger, _, history_calls, supersede_calls = _harness(
        receipts=[_receipt(episode_id) for episode_id in episode_ids],
        episodes=[_episode(episode_id) for episode_id in episode_ids],
    )

    corrections = reconciler.reconcile("agent-a")
    assert [len(batch) for batch in history_calls] == [500, 500, 1]
    assert [episode_id for batch in history_calls for episode_id in batch] == episode_ids
    assert [row["episodeId"] for row in corrections] == episode_ids
    assert len(supersede_calls) == len(ledger.appends) == count
