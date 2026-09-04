import json

from core.web.services import data_processing_service


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(data_processing_service, "PROJECT_ROOT", tmp_path)


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_data_processing_profile_lists_generic_contract():
    profiles = data_processing_service.list_profiles()

    assert profiles["defaultProfileId"] == "generic_document_processing"
    profile = profiles["profiles"][0]
    assert profile["profileId"] == "generic_document_processing"
    assert profile["publishBoundary"]["writesFormalKnowledge"] is False
    assert profile["publishBoundary"]["writesRag"] is False
    assert profile["publishBoundary"]["writesKnowledgeGraph"] is False
    assert {role["agentRole"] for role in profile["collectionRoles"]} >= {
        "data_intake_coordinator",
        "source_finder",
        "source_extractor",
        "source_relation_mapper",
        "source_ingestor",
        "intake_review",
    }


def test_processing_run_records_intake_to_workspace(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    run = data_processing_service.create_processing_run(
        "generic_document_processing",
        title="First intake",
        scope={"topic": "any domain"},
    )

    record = data_processing_service.add_record(
        run["runId"],
        {
            "sourceType": "file",
            "sourceRef": "local-paper.pdf",
            "title": "Candidate source",
            "qualitySignals": {"readable": True},
        },
    )
    records = data_processing_service.list_records(run["runId"])
    runs = data_processing_service.list_processing_runs()
    status = data_processing_service.get_processing_status(run["runId"])

    run_path = tmp_path / "workspace" / "data_processing" / "runs" / run["runId"] / "run.json"
    records_path = tmp_path / "workspace" / "data_processing" / "runs" / run["runId"] / "records.jsonl"
    assert run_path.exists()
    assert records_path.exists()
    assert record["sourceType"] == "file"
    assert records["summary"]["recordCount"] == 1
    assert runs["runs"][0]["runId"] == run["runId"]
    assert status["summary"]["recordCount"] == 1
    assert status["boundaries"]["writesFormalKnowledge"] is False
    assert _read_jsonl(records_path)[0]["recordId"] == record["recordId"]


def test_processing_run_exposes_reusable_status_payload(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    run = data_processing_service.create_processing_run(
        "generic_document_processing",
        title="Reusable status run",
        scope={"topic": "any domain"},
    )
    data_processing_service.add_record(
        run["runId"],
        {
            "sourceType": "file",
            "sourceRef": "local-paper.pdf",
            "title": "Candidate source",
        },
    )

    payload = data_processing_service.get_processing_run(run["runId"])

    assert payload["processingStatus"]["runId"] == run["runId"]
    assert payload["summary"] == payload["processingStatus"]["summary"]
    assert payload["processingStatus"]["summary"]["recordCount"] == 1
    assert payload["processingStatus"]["boundaries"]["writesFormalKnowledge"] is False


def test_processing_run_list_filters_before_limit(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    target = data_processing_service.create_processing_run(
        title="Team source collection",
        scope={"teamId": "research-team"},
        metadata={"startedFrom": "team_workflow_source_collection", "teamId": "research-team"},
    )
    for index in range(5):
        data_processing_service.create_processing_run(
            title=f"Other run {index}",
            scope={"teamId": f"other-team-{index}"},
            metadata={"startedFrom": "other_flow", "teamId": f"other-team-{index}"},
        )

    runs = data_processing_service.list_processing_runs(
        limit=1,
        metadata_filters={
            "startedFrom": "team_workflow_source_collection",
            "teamId": "research-team",
        },
    )

    assert runs["summary"]["filtered"] is True
    assert runs["summary"]["runCount"] == 1
    assert runs["summary"]["returnedCount"] == 1
    assert runs["runs"][0]["runId"] == target["runId"]


def test_processing_run_list_hydrates_status_after_limit(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    for index in range(5):
        data_processing_service.create_processing_run(title=f"Historical run {index}")

    real_get_processing_status = data_processing_service.get_processing_status
    status_calls: list[str] = []

    def counted_get_processing_status(run_id):
        status_calls.append(run_id)
        return real_get_processing_status(run_id)

    monkeypatch.setattr(data_processing_service, "get_processing_status", counted_get_processing_status)

    runs = data_processing_service.list_processing_runs(limit=2)

    assert runs["summary"]["runCount"] == 5
    assert runs["summary"]["returnedCount"] == 2
    assert status_calls == [run["runId"] for run in runs["runs"]]


def test_collection_assignment_records_agent_output_without_publishing(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    run = data_processing_service.create_processing_run(title="Agent collection")
    assignment = data_processing_service.create_collection_assignment(
        run["runId"],
        {
            "agentRole": "source_finder",
            "agentId": "agent-source-finder",
            "scope": {"query": "find useful sources"},
            "expectedRecordTypes": ["source_manifest"],
        },
    )

    result = data_processing_service.record_collection_output(
        run["runId"],
        assignment["assignmentId"],
        {
            "status": "completed",
            "records": [
                {
                    "sourceType": "url",
                    "sourceRef": "https://example.test/source",
                    "title": "Example source",
                }
            ],
            "qualitySignals": {"confidence": 0.8},
        },
    )
    status = data_processing_service.get_processing_status(run["runId"])
    assignments = data_processing_service.list_collection_assignments(run["runId"])
    events_path = tmp_path / "workspace" / "data_processing" / "runs" / run["runId"] / "events.jsonl"
    events = _read_jsonl(events_path)

    assert result["output"]["recordIds"] == [result["createdRecords"][0]["recordId"]]
    assert result["createdRecords"][0]["collectionTrace"]["assignmentId"] == assignment["assignmentId"]
    assert assignments["assignments"][0]["status"] == "completed"
    assert status["summary"]["recordCount"] == 1
    assert status["runStatus"] == "reviewing"
    assert status["boundaries"]["writesRag"] is False
    assert [event["eventCode"] for event in events] == [
        "data_processing.run.created",
        "data_processing.collection_assignment.created",
        "data_processing.collection_output.recorded",
    ]


def test_processing_run_stays_active_until_all_collection_assignments_close(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    run = data_processing_service.create_processing_run(title="Multi-agent collection")
    first = data_processing_service.create_collection_assignment(
        run["runId"],
        {
            "agentRole": "source_finder",
            "agentId": "agent-source-finder",
        },
    )
    second = data_processing_service.create_collection_assignment(
        run["runId"],
        {
            "agentRole": "source_ingestor",
            "agentId": "agent-source-ingestor",
        },
    )

    data_processing_service.record_collection_output(
        run["runId"],
        first["assignmentId"],
        {
            "status": "completed",
            "records": [{"sourceType": "paper", "sourceRef": "https://doi.org/10.1/demo", "title": "Demo paper"}],
        },
    )

    active_status = data_processing_service.get_processing_status(run["runId"])
    assert active_status["runStatus"] == "processing"
    assert active_status["summary"]["openAssignmentCount"] == 1

    data_processing_service.record_collection_output(
        run["runId"],
        second["assignmentId"],
        {
            "status": "completed",
            "records": [{"sourceType": "paper", "sourceRef": "https://doi.org/10.2/demo", "title": "Second paper"}],
        },
    )

    ready_status = data_processing_service.get_processing_status(run["runId"])
    assignments = data_processing_service.list_collection_assignments(run["runId"])
    assert ready_status["runStatus"] == "reviewing"
    assert ready_status["summary"]["recordCount"] == 2
    assert ready_status["summary"]["openAssignmentCount"] == 0
    assert {item["status"] for item in assignments["assignments"]} == {"completed"}


def test_collection_assignment_rejects_unknown_agent_role(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    run = data_processing_service.create_processing_run()

    try:
        data_processing_service.create_collection_assignment(run["runId"], {"agentRole": "research_only_role"})
    except data_processing_service.DataProcessingError as exc:
        assert "Unsupported collection agent role" in str(exc)
    else:
        raise AssertionError("Expected DataProcessingError")


def _events_for(tmp_path, run_id):
    events_path = tmp_path / "workspace" / "data_processing" / "runs" / run_id / "events.jsonl"
    return _read_jsonl(events_path)


def test_complete_collection_batch_advances_drained_run_with_records_to_reviewing(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    run = data_processing_service.create_processing_run()
    assignment = data_processing_service.create_collection_assignment(run["runId"], {"agentRole": "source_finder"})
    data_processing_service.record_collection_output(
        run["runId"],
        assignment["assignmentId"],
        {
            "status": "completed",
            "records": [{"sourceType": "paper", "sourceRef": "https://doi.org/10.1/batch", "title": "Batch paper"}],
        },
    )

    advanced = data_processing_service.complete_collection_batch(
        run["runId"],
        terminal_status="completed",
    )

    assert advanced["status"] == "reviewing"
    assert data_processing_service.get_processing_run(run["runId"])["status"] == "reviewing"
    batch_events = [
        event for event in _events_for(tmp_path, run["runId"])
        if event["eventCode"] == "data_processing.run.collection_batch_completed"
    ]
    assert len(batch_events) == 1
    assert batch_events[0]["fields"]["terminalStatus"] == "completed"
    assert batch_events[0]["fields"]["runStatus"] == "reviewing"
    assert batch_events[0]["fields"]["recordCount"] == 1
    assert batch_events[0]["fields"]["openAssignmentCount"] == 0


def test_complete_collection_batch_keeps_collecting_while_assignments_open(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    run = data_processing_service.create_processing_run()
    data_processing_service.create_collection_assignment(run["runId"], {"agentRole": "source_finder"})
    data_processing_service.add_record(
        run["runId"],
        {"sourceType": "paper", "sourceRef": "https://doi.org/10.2/open", "title": "Open batch paper"},
    )

    advanced = data_processing_service.complete_collection_batch(
        run["runId"],
        terminal_status="needs_continue",
    )

    assert advanced["status"] == "collecting"
    batch_events = [
        event for event in _events_for(tmp_path, run["runId"])
        if event["eventCode"] == "data_processing.run.collection_batch_completed"
    ]
    assert len(batch_events) == 1
    assert batch_events[0]["fields"]["terminalStatus"] == "needs_continue"
    assert batch_events[0]["fields"]["runStatus"] == "collecting"
    assert batch_events[0]["fields"]["openAssignmentCount"] == 1


def test_complete_collection_batch_completes_drained_run_without_records(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    run = data_processing_service.create_processing_run()
    assignment = data_processing_service.create_collection_assignment(run["runId"], {"agentRole": "source_finder"})
    data_processing_service.record_collection_output(
        run["runId"],
        assignment["assignmentId"],
        {"status": "completed", "records": []},
    )

    advanced = data_processing_service.complete_collection_batch(run["runId"])

    assert advanced["status"] == "completed"


def test_complete_collection_batch_preserves_terminal_statuses(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    failed_run = data_processing_service.create_processing_run()
    data_processing_service.fail_processing_run(failed_run["runId"], reason="earlier_failure")
    cancelled_run = data_processing_service.create_processing_run()
    data_processing_service.cancel_processing_run(cancelled_run["runId"])

    failed_advanced = data_processing_service.complete_collection_batch(
        failed_run["runId"],
        terminal_status="needs_continue",
    )
    cancelled_advanced = data_processing_service.complete_collection_batch(
        cancelled_run["runId"],
        terminal_status="completed",
    )

    assert failed_advanced["status"] == "failed"
    assert cancelled_advanced["status"] == "cancelled"
