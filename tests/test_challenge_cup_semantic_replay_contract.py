import json

from core.research.workflow.contracts.challenge_cup_stage_one_v3 import (
    ActivityExecution, RecordLifecycle, ScientificSemanticRecord,
)
from core.web.services.team_workflow.research_runtime.scientific_semantic_ledger import (
    append_scientific_semantic_record,
)
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, build_run_record
from tests._support.workflow_ledger_http import ledger_http_client


def test_semantic_facts_survive_scoped_http_pagination_without_mutation(tmp_path, monkeypatch):
    with ledger_http_client(tmp_path, monkeypatch) as (client, runtime):
        run = build_run_record(workflow_id="challenge-cup-research", last_event_sequence=0)
        runtime.store.submit(lambda uow: uow.repository.insert_run(run), force_flush=True).result(timeout=10)
        facts = [
            ScientificSemanticRecord(execution=ActivityExecution(status="running", waitReason="human_input")),
            ScientificSemanticRecord(execution=ActivityExecution(status="succeeded")),
            ScientificSemanticRecord(record=RecordLifecycle(availability="archived")),
        ]
        expected = []
        for index, semantic in enumerate(facts):
            expected.append(append_scientific_semantic_record(
                runtime.store, run_id=run.run_id, record_ref=f"semantic:http:{index}",
                subject_ref="activity-1", semantic=semantic,
                actor_type="software_agent", actor_ref="agent-test",
                recorded_at_ms=FIXED_NOW_MS + index + 1,
            ))
        before_events = runtime.store.list_events(run.run_id)
        before_run = runtime.store.get_run(run.run_id)
        url = f"/api/research/workflow-runs/{run.run_id}/events"

        first = client.get(url, params={"teamId": run.team_id, "limit": 2})
        assert first.status_code == 200, first.text
        page = first.json()
        assert page["latestEventSequence"] == 3
        assert page["hasMore"] is True
        assert page["nextAfterSequence"] == 2
        second = client.get(url, params={"teamId": run.team_id, "afterSequence": 2, "limit": 2})
        assert second.status_code == 200, second.text
        assert second.json()["hasMore"] is False
        assert second.json()["nextAfterSequence"] is None
        events = page["events"] + second.json()["events"]
        assert [event["sequence"] for event in events] == [1, 2, 3]
        assert [event["eventId"] for event in events] == [record["eventId"] for record in expected]
        for event, stored in zip(events, before_events, strict=True):
            assert event["type"] == "scientific_semantic_recorded.v3"
            assert event["payload"] == json.loads(stored.payload_json)
            assert event["payload"]["subjectRef"] == "activity-1"
            assert "assessment" not in event["payload"]["semantic"]
        assert events[-1]["payload"]["semantic"]["record"] == {"availability": "archived"}
        assert "execution" not in events[-1]["payload"]["semantic"]

        denied = client.get(url, params={"teamId": "another-team", "limit": 2})
        assert denied.status_code == 404
        assert "semantic:http" not in denied.text
        assert client.get(url, params={"teamId": run.team_id, "limit": 2}).json() == page
        assert runtime.store.list_events(run.run_id) == before_events
        assert runtime.store.get_run(run.run_id) == before_run
