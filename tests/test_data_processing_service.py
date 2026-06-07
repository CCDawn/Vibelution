import json

from core.web.services import data_processing_service


def _use_tmp_project_root(tmp_path, monkeypatch):
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
        "data_discovery",
        "content_extraction",
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


def test_collection_assignment_records_agent_output_without_publishing(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    run = data_processing_service.create_processing_run(title="Agent collection")
    assignment = data_processing_service.create_collection_assignment(
        run["runId"],
        {
            "agentRole": "data_discovery",
            "agentId": "agent-data-discovery",
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
    assert status["boundaries"]["writesRag"] is False
    assert [event["eventCode"] for event in events] == [
        "data_processing.run.created",
        "data_processing.collection_assignment.created",
        "data_processing.collection_output.recorded",
    ]


def test_collection_assignment_rejects_unknown_agent_role(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    run = data_processing_service.create_processing_run()

    try:
        data_processing_service.create_collection_assignment(run["runId"], {"agentRole": "research_only_role"})
    except data_processing_service.DataProcessingError as exc:
        assert "Unsupported collection agent role" in str(exc)
    else:
        raise AssertionError("Expected DataProcessingError")
