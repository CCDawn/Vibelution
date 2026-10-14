from copy import deepcopy
from datetime import datetime, timezone

import pytest

from core.agent_plugins.virtual_human_life.drives import (
    apply_completed_event_to_drives,
    default_drive_projection,
    project_drive_progress,
    prompt_drive_summary,
)
from core.agent_plugins.virtual_human_life.life_feed import build_life_feed


NOW = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)


def _event(event_id="event-a", *, provenance="verified_action", kind="creative"):
    outcome = {"status": "succeeded", "summary": "完成今天的创作练习"}
    if provenance == "verified_action":
        outcome.update({
            "kind": "verified_tool_outcome",
            "evidence": {
                "kind": "native_tool_execution",
                "sessionId": "session-a",
                "turnId": "turn-a",
                "toolCallIds": ["tool-a"],
                "receiptEventIds": ["receipt-a"],
            },
        })
    elif provenance == "simulation":
        outcome["kind"] = "deterministic_simulation"
    elif provenance == "character_report":
        outcome["kind"] = "character_report"
    return {
        "eventId": event_id,
        "kind": "activity_completed",
        "activityKind": kind,
        "title": "今天的练习",
        "occurredAt": NOW.isoformat(),
        "localDate": NOW.date().isoformat(),
        "outcome": outcome,
    }


@pytest.mark.parametrize("provenance", ["simulation", "character_report", "unknown"])
@pytest.mark.parametrize("kind", ["creative", "reflection"])
def test_unverified_events_do_not_advance_any_drive(provenance, kind):
    projection = default_drive_projection(now=NOW)
    before = deepcopy(projection)
    event = _event(provenance=provenance, kind=kind)

    result = apply_completed_event_to_drives(projection, event, now=NOW)

    assert result == {"projection": before, "change": None}
    assert projection == before


def test_verified_actions_count_without_inventing_goal_or_project_completion():
    projection = default_drive_projection(now=NOW)
    for index in range(55):
        projection = apply_completed_event_to_drives(
            projection, _event(f"creative-{index}"), now=NOW
        )["projection"]

    for bucket in ("goals", "projects"):
        assert projection[bucket][0]["progressBasis"] == "ongoing"
        assert projection[bucket][0]["progress"] == 0
        assert projection[bucket][0]["verifiedActivityCount"] == 55
        assert projection[bucket][0]["status"] == "active"
        assert "progress" not in prompt_drive_summary(projection)[bucket][0]
    assert projection["skills"][0]["practiceCount"] == 55
    assert projection["habits"][0]["completionCount"] == 0

    reflection = _event("reflection", kind="reflection")
    reflection["title"] = "晚间回顾"
    projection = apply_completed_event_to_drives(projection, reflection, now=NOW)["projection"]
    assert projection["habits"][0]["completionCount"] == 1
    assert projection["projects"][0]["verifiedActivityCount"] == 55


def test_legacy_completed_projection_repairs_only_default_drives_without_mutation():
    stored = default_drive_projection(now=NOW)
    for bucket in ("goals", "projects"):
        stored[bucket][0].update({
            "progress": 100,
            "status": "completed",
            "verifiedActivityCount": 999,
            "title": "用户改过的标题",
            "notes": {"custom": "保留"},
        })
    custom_project = {"driveId": "custom", "origin": "user", "progress": 40, "title": "写一本书"}
    stored["projects"].append(custom_project)
    before = deepcopy(stored)
    creative = _event()
    wellness = _event("wellness", kind="wellness")
    wellness["title"] = "散步"

    result = project_drive_progress(
        stored, [creative, deepcopy(creative), wellness, _event("sim", provenance="simulation")]
    )

    assert stored == before
    assert result["goals"][0]["verifiedActivityCount"] == 2
    assert result["projects"][0]["verifiedActivityCount"] == 1
    for bucket in ("goals", "projects"):
        assert result[bucket][0]["progress"] == 0
        assert result[bucket][0]["progressBasis"] == "ongoing"
        assert result[bucket][0]["status"] == "active"
        assert result[bucket][0]["title"] == "用户改过的标题"
        assert result[bucket][0]["notes"] == {"custom": "保留"}
    assert result["projects"][1] == custom_project
    assert result["habits"] == stored["habits"]
    assert result["skills"] == stored["skills"]


def test_user_origin_with_default_id_is_preserved():
    projection = default_drive_projection(now=NOW)
    projection["projects"][0].update({"origin": "user", "progress": 70, "status": "completed"})
    before = deepcopy(projection["projects"])

    assert project_drive_progress(projection, [_event()])["projects"] == before
    assert apply_completed_event_to_drives(projection, _event(), now=NOW)["projection"]["projects"] == before


@pytest.mark.parametrize("invalid", ["failed", "missing_receipt", "restart_simulation"])
def test_verification_requires_success_and_complete_execution_evidence(invalid):
    event = _event()
    if invalid == "failed":
        event["outcome"]["status"] = "failed"
    elif invalid == "missing_receipt":
        event["outcome"]["evidence"]["receiptEventIds"] = []
    else:
        event["simulatedAfterRestart"] = True
    projection = default_drive_projection(now=NOW)

    assert apply_completed_event_to_drives(projection, event, now=NOW) == {
        "projection": projection, "change": None,
    }
    assert project_drive_progress(projection, [event])["goals"][0]["verifiedActivityCount"] == 0


@pytest.mark.parametrize("provenance", ["simulation", "character_report", "verified_action", "unknown"])
def test_feed_exposes_event_provenance(provenance):
    event = _event(provenance=provenance)
    before = deepcopy(event)

    feed = build_life_feed(events=[event], diary_entries=[], artifact_receipts=[])

    assert len(feed) == 1
    assert feed[0]["sourceKind"] == provenance
    assert event == before


def test_feed_prefers_event_over_identical_same_source_diary():
    event = _event()
    diary = {
        "diaryEntryId": "diary-a",
        "sourceEventIds": ["event-a", "event-a"],
        "content": event["outcome"]["summary"],
        "writtenAt": NOW.isoformat(),
    }

    feed = build_life_feed(events=[event], diary_entries=[diary], artifact_receipts=[])

    assert [row["kind"] for row in feed] == ["life_event"]


def test_feed_preserves_same_title_and_summary_from_distinct_events():
    feed = build_life_feed(
        events=[_event("a"), _event("b")], diary_entries=[], artifact_receipts=[]
    )

    assert len(feed) == 2
    assert {row["feedId"] for row in feed} == {"life-event:a", "life-event:b"}


@pytest.mark.parametrize("source_ids", [["event-a", "event-b"], ["event-a", "missing"]])
def test_same_summary_diary_is_preserved_when_source_ids_differ(source_ids):
    event = _event()
    diary = {
        "diaryEntryId": "multiple-sources",
        "sourceEventIds": source_ids,
        "content": event["outcome"]["summary"],
    }

    feed = build_life_feed(
        events=[event, _event("event-b")], diary_entries=[diary], artifact_receipts=[]
    )

    assert any(row["feedId"] == "diary:multiple-sources" for row in feed)


def test_feed_keeps_distinct_diary_body_and_does_not_deduplicate_truncated_text():
    event = _event(provenance="simulation")
    event["outcome"]["summary"] = "记" * 600 + "事件结尾"
    diary = {
        "diaryEntryId": "different-body",
        "sourceEventIds": ["event-a"],
        "content": "记" * 600 + "日记结尾",
    }

    feed = build_life_feed(events=[event], diary_entries=[diary], artifact_receipts=[])

    assert len(feed) == 2
    assert {row["kind"] for row in feed} == {"life_event", "diary"}
    assert all(row["sourceKind"] == "simulation" for row in feed)


def test_feed_keeps_artifact_success_and_source_link_contract():
    artifact = {
        "artifactId": "artifact-a",
        "status": "succeeded",
        "sourceEventIds": ["event-a", "missing"],
        "kind": "text",
        "localRef": "artifacts/a.md",
        "summary": "本地作品",
    }
    failed = {**artifact, "artifactId": "failed", "status": "failed"}

    feed = build_life_feed(events=[_event()], diary_entries=[], artifact_receipts=[artifact, failed])

    rows = [row for row in feed if row["kind"] == "artifact"]
    assert len(rows) == 1
    assert rows[0]["sourceEventIds"] == ["event-a"]
    assert rows[0]["artifactKind"] == "text"
    assert rows[0]["localRef"] == "artifacts/a.md"
    assert rows[0]["sourceKind"] == "unknown"
