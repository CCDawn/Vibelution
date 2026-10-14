"""Companion projections must retain the boundary between report and execution."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from core.agent_plugins.virtual_human_life.dialogue_context import (
    project_companion_dialogue_context,
)
from core.agent_plugins.virtual_human_life.interests import project_interests
from core.agent_plugins.virtual_human_life.reflection import (
    build_nightly_reflection_proposals,
)
from core.agent_plugins.virtual_human_life.reunion import project_shared_experiences


NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)
LOCAL_DATE = NOW.date().isoformat()
UNVERIFIED_SOURCES = [
    "simulation",
    "restart_simulation",
    "character_report",
    "world_experience",
    "unknown",
    "kind_only",
    "missing_kind",
    "missing_session",
    "missing_turn",
    "missing_calls",
    "missing_receipts",
]


def _event(source: str, *, event_id: str = "event-1") -> dict:
    outcome = {
        "status": "succeeded",
        "kind": "verified_tool_outcome",
        "summary": "已整理出旋律片段。",
        "evidence": {
            "kind": "native_tool_execution",
            "sessionId": "native-session",
            "turnId": "native-turn",
            "toolCallIds": ["call-1"],
            "receiptEventIds": ["receipt-1"],
        },
    }
    event = {
        "eventId": event_id,
        "kind": "activity_completed",
        "title": "整理旋律",
        "occurredAt": "2026-10-14T10:00:00+00:00",
        "outcome": outcome,
    }
    if source == "simulation":
        outcome["kind"] = "deterministic_simulation"
    elif source == "restart_simulation":
        event["simulatedAfterRestart"] = True
    elif source in {"character_report", "world_experience"}:
        outcome["kind"] = source
    elif source == "unknown":
        outcome.pop("kind")
        outcome.pop("evidence")
    elif source == "kind_only":
        outcome.pop("evidence")
    elif source.startswith("missing_"):
        outcome["evidence"].pop(
            {
                "missing_kind": "kind",
                "missing_session": "sessionId",
                "missing_turn": "turnId",
                "missing_calls": "toolCallIds",
                "missing_receipts": "receiptEventIds",
            }[source]
        )
    return event


def _reflect(events: list[dict]) -> list[dict]:
    # Even a historical promotion receipt cannot turn an unverified source
    # into a real experience when the pure builder is called directly.
    return build_nightly_reflection_proposals(
        events,
        promoted_source_ids={event["eventId"] for event in events},
        existing_proposal_ids=set(),
        local_date=LOCAL_DATE,
        now=NOW,
    )


def _shared(events: list[dict]) -> list[dict]:
    return project_shared_experiences(
        open_loops=[
            {
                "loopId": "shared-loop",
                "status": "open",
                "sourceSessionId": "companion-session",
                "sourceTurnIds": ["conversation-turn"],
                "sourceEventIds": [event["eventId"] for event in events],
            }
        ],
        completed_events=events,
        session_id="companion-session",
        now=NOW,
    )


class _ReadOnlyStore:
    def __init__(self, events: list[dict]):
        self.events = events

    def read_json(self, agent_id: str, path: str):
        return None

    def read_jsonl(self, agent_id: str, path: str):
        return deepcopy(self.events) if path == f"events/{LOCAL_DATE}.jsonl" else []


def _dialogue(events: list[dict]) -> dict:
    return project_companion_dialogue_context(
        _ReadOnlyStore(events),
        "agent-a",
        binding={"timezone": "UTC"},
        state={},
        causal={},
        today_schedule={},
        tomorrow_schedule={},
        local_now=NOW,
        session_id="companion-session",
        run_id="conversation-turn",
        proactive=False,
    )


@pytest.mark.parametrize("source", UNVERIFIED_SOURCES)
def test_direct_reflection_rejects_unverified_events_despite_promotion(source):
    assert _reflect([_event(source)]) == []


@pytest.mark.parametrize("source", UNVERIFIED_SOURCES)
def test_direct_shared_projection_rejects_unverified_linked_events(source):
    assert _shared([_event(source)]) == []


@pytest.mark.parametrize("source", UNVERIFIED_SOURCES)
def test_direct_dialogue_does_not_present_unverified_events_as_completed(source):
    assert _dialogue([_event(source)])["completedExperiences"] == []


def test_verified_native_event_survives_all_projections_without_mutation():
    event = _event("verified_action")
    original = deepcopy(event)

    proposals = _reflect([event])
    assert len(proposals) == 1
    assert proposals[0]["sourceKind"] == "lived_event"
    assert proposals[0]["sourceEventIds"] == ["event-1"]
    assert "真实经历" in proposals[0]["text"]
    assert [row["eventId"] for row in _shared([event])] == ["event-1"]
    assert [row["eventId"] for row in _dialogue([event])["completedExperiences"]] == [
        "event-1"
    ]
    assert event == original


@pytest.mark.parametrize("source", ["character_report", "world_experience"])
def test_dialogue_preserves_character_narrative_with_explicit_unverified_source(source):
    payload = _dialogue([_event(source)])

    assert payload["completedExperiences"] == []
    assert payload["characterReports"] == [
        {
            "eventId": "event-1",
            "title": "整理旋律",
            "occurredAt": "2026-10-14T10:00:00+00:00",
            "outcomeSummary": "已整理出旋律片段。",
            "sourceKind": "character_report",
            "factStatus": "self_reported_not_verified",
        }
    ]


def test_simulated_and_verified_events_do_not_leak_into_character_reports():
    payload = _dialogue([_event("simulation"), _event("verified_action")])
    assert payload["characterReports"] == []


@pytest.mark.parametrize("status", ["failed", "cancelled", "skipped"])
def test_native_evidence_alone_does_not_make_failed_outcome_a_success(status):
    event = _event("verified_action")
    event["outcome"]["status"] = status
    assert _reflect([event]) == []
    assert _shared([event]) == []
    assert _dialogue([event])["completedExperiences"] == []


def test_report_projection_is_bounded_and_does_not_rewrite_storage():
    events = [
        _event("character_report", event_id=f"reported-{index}")
        for index in range(12)
    ]
    original = deepcopy(events)
    payload = _dialogue(events)

    assert [row["eventId"] for row in payload["characterReports"]] == [
        f"reported-{index}" for index in range(4, 12)
    ]
    assert events == original


@pytest.mark.parametrize("source", UNVERIFIED_SOURCES)
def test_direct_interest_projection_requires_native_execution_evidence(source):
    event = _event(source)
    event["activityKind"] = "creative"
    projected = project_interests([event])
    assert projected["items"] == []
    assert projected["processedEventIds"] == []


@pytest.mark.parametrize(
    "kind", ["artifact_created", "reading_completed", "news_explored", "skill_practiced", "verified"]
)
def test_legacy_kind_labels_without_native_proof_do_not_grow_interests(kind):
    event = _event("kind_only")
    event["activityKind"] = "creative"
    event["outcome"]["kind"] = kind
    assert project_interests([event])["items"] == []


def test_verified_native_interest_progress_preserves_sources_and_deduplicates():
    event = _event("verified_action")
    event["activityKind"] = "creative"
    original = deepcopy(event)

    projection = project_interests([event, event])
    assert projection["processedEventIds"] == ["event-1"]
    assert projection["items"][0]["experience"] == 7
    assert projection["items"][0]["completedCount"] == 1
    assert projection["items"][0]["sourceEventIds"] == ["event-1"]
    assert event == original
