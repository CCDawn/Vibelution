"""ISS-064: corrupt transfer (交接) records stay skipped fail-soft, but the
coordination status surface must report the skip through the existing
workflow event channel instead of silently dropping the lines."""

from __future__ import annotations

import json

from core.web.services import team_workflow_orchestration_service
from core.web.services.team_workflow.knowledge_kernel import _load_transfer_records


def _capture_workflow_event(monkeypatch) -> list[dict]:
    events: list[dict] = []

    def _capture(event_code, team_id, *, fields, **kwargs):
        events.append(
            {"eventCode": event_code, "teamId": team_id, "fields": fields, **kwargs}
        )

    monkeypatch.setattr(
        team_workflow_orchestration_service, "_record_workflow_event", _capture
    )
    return events


def test_corrupt_transfer_lines_are_skipped_with_observable_event(
    tmp_path, monkeypatch
) -> None:
    records_path = tmp_path / "transfer_records.jsonl"
    records_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "transferId": "tr-1",
                        "candidateId": "cand-1",
                        "status": "requested",
                    }
                ),
                "{corrupt line",
                "",
                json.dumps(
                    {
                        "transferId": "tr-2",
                        "candidateId": "cand-2",
                        "status": "approved",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_transfer_records_path",
        lambda team_id: records_path,
    )
    events = _capture_workflow_event(monkeypatch)

    records = _load_transfer_records("team-1")

    assert [record["transferId"] for record in records] == ["tr-1", "tr-2"]
    assert len(events) == 1
    event = events[0]
    assert event["eventCode"] == "workflow.transfer_records_corrupt_lines_skipped"
    assert event["teamId"] == "team-1"
    assert event["outcome"] == "degraded"
    assert event["level"] == "warning"
    assert event["fields"]["skippedLineCount"] == 1
    assert event["fields"]["skippedReasons"] == ["line 2: Expecting property name enclosed in double quotes"]


def test_clean_transfer_records_write_no_degraded_event(
    tmp_path, monkeypatch
) -> None:
    records_path = tmp_path / "transfer_records.jsonl"
    records_path.write_text(
        json.dumps({"transferId": "tr-ok", "status": "requested"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_transfer_records_path",
        lambda team_id: records_path,
    )
    events = _capture_workflow_event(monkeypatch)

    records = _load_transfer_records("team-1")

    assert [record["transferId"] for record in records] == ["tr-ok"]
    assert events == []
