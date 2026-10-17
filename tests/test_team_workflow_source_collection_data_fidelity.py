"""Source-collection data fidelity regressions (E2E defects, 2026-10-17).

Defect 1 (challenge-sci-002, P0): executor-written data records carry only
``queryId`` on their trace.  ``import_data_record_as_source_candidate`` must
resolve the run's frozen query plan (assignments mirror ``search_plan.json``
queries into ``scope.assignedQueries``) into ``metadata.perspective`` (flat
key plus the embedded ``sourceCollectionTrace``) or the source-finding
receipt gate blocks the whole node with ``source_search_receipt_missing``.
Supplemental query ids never enter the frozen plan; their perspective must
come from the canonical search-event projection.

Defect 2 (challenge-sci-009/049/085/091): extraction ``keyFindings`` items
are contract dicts carrying ``fact``/``quote``/``evidenceRef``.  They must
materialize as readable text through the extraction normalizers, never as a
truncated Python dict repr via the ``str()`` fallback.

Defect 3 (candidate-20260950-ba9f6135): DOI-registered sources are a
structural dead end for quote supply — fetching the ``doi.org`` locator is
rejected as a cross-host redirect while the fetched publisher mirror
(`/EN/10.x/...`) never string-matches the DOI locator.  Both locator sides
must emit a scheme-free ``doi:<doi>`` bridge key so the mirror receipt binds.
"""

from __future__ import annotations

from core.web.services.team_workflow.source_collection.extraction_quote_anchor_supply import (
    source_quotable_blocks,
)
from tests._support.team_workflow.helpers import *  # noqa: F403


def _fetch_receipt(locator: str, text: str) -> dict:
    return {"text": text, "locator": locator, "resolvedUrl": locator, "eventId": "evt-doi", "sessionId": "s", "turnId": "t"}


def _executor_search_record_payload(run_id: str, query: dict, source_ref: str) -> dict:
    """Mirror the executor's data-record shape: queryId-only nested trace."""
    trace = {
        "runId": run_id,
        "planId": str(query.get("queryId") or "").split("-q", 1)[0],
        "queryId": query.get("queryId"),
        "query": query.get("query"),
        "assignmentId": query.get("assignmentId", ""),
        "agentRole": query.get("assignedAgentRole", "source_finder"),
        "searchProvider": "test_provider",
        "searchUrl": source_ref,
        "storageTarget": "data_processing.records",
    }
    return {
        "sourceType": "url",
        "sourceRef": source_ref,
        "title": "Executor found source",
        "summary": "A data record produced by the search executor.",
        "metadata": {"sourceCollectionTrace": trace, "searchProvider": "test_provider"},
        "collectionTrace": trace,
    }


def _planned_perspective_query(run_id: str) -> tuple[dict, dict]:
    assignments = data_processing_service.list_collection_assignments(run_id)["assignments"]
    planned = [
        (assignment, query)
        for assignment in assignments
        if isinstance(assignment, dict)
        for query in list((assignment.get("scope") or {}).get("assignedQueries") or [])
        if isinstance(query, dict) and query.get("perspective")
    ]
    assert planned, "challenge-cup search plan must freeze perspective-tagged queries"
    return planned[0]


def test_import_resolves_perspective_from_run_query_plan(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _capture_workflow_events(monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="数据保真回归团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    assignment, query = _planned_perspective_query(run_id)
    query = {**query, "assignmentId": assignment["assignmentId"]}
    record = data_processing_service.add_record(
        run_id,
        _executor_search_record_payload(run_id, query, "https://example.test/plan-perspective"),
    )

    response = team_workflow_orchestration_service.import_data_record_as_source_candidate(
        team["teamId"],
        run_id,
        record["recordId"],
        {"createdByAgent": "data_intake_coordinator"},
    )

    assert response.get("created") is True
    metadata = response["candidate"]["metadata"]
    assert metadata["perspective"] == query["perspective"]
    assert metadata["sourceCollectionTrace"]["perspective"] == query["perspective"]
    assert metadata["queryId"] == query["queryId"]


def test_import_resolves_supplemental_query_perspective_from_search_events(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _capture_workflow_events(monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="数据保真回归团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    assignment, _parent = _planned_perspective_query(run_id)
    source_ref = "https://example.test/supplemental-perspective"
    # Supplemental query ids are digests that never appear in the frozen
    # plan; only the canonical search-event projection knows their perspective.
    supplemental_query = {
        "queryId": "supplemental-a1b2c3d4e5f60718293a4b5c",
        "query": "supplemental predictive coding paper",
        "assignmentId": assignment["assignmentId"],
        "assignedAgentRole": "source_finder",
    }
    events_path = team_workflow_orchestration_service._source_collection_storage_artifact_paths(
        team["teamId"], run_id
    )["searchEventsPath"]
    team_workflow_orchestration_service._append_jsonl(
        events_path,
        [
            {
                "eventId": "srcevt-test-supplemental",
                "eventType": "search.tool_result_returned",
                "status": "completed",
                "assignmentId": assignment["assignmentId"],
                "queryId": supplemental_query["queryId"],
                "query": supplemental_query["query"],
                "perspective": "mechanism",
                "provider": "test_provider",
                "refs": [source_ref],
                "createdAt": "2026-10-17T00:00:00Z",
            }
        ],
    )
    record = data_processing_service.add_record(
        run_id,
        _executor_search_record_payload(run_id, supplemental_query, source_ref),
    )

    response = team_workflow_orchestration_service.import_data_record_as_source_candidate(
        team["teamId"],
        run_id,
        record["recordId"],
        {"createdByAgent": "data_intake_coordinator"},
    )

    assert response.get("created") is True
    metadata = response["candidate"]["metadata"]
    assert metadata["perspective"] == "mechanism"
    assert metadata["sourceCollectionTrace"]["perspective"] == "mechanism"


def test_import_without_resolvable_perspective_keeps_historical_shape(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _capture_workflow_events(monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    team = team_service.create_team(name="数据保真回归团队")
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "predictive coding",
            "agentRoles": ["source_finder"],
            "querySeeds": ["predictive coding"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    unknown_query = {
        "queryId": "searchplan-missing-q999",
        "query": "unknown query",
        "assignedAgentRole": "source_finder",
    }
    record = data_processing_service.add_record(
        run_id,
        _executor_search_record_payload(run_id, unknown_query, "https://example.test/unresolved-perspective"),
    )

    response = team_workflow_orchestration_service.import_data_record_as_source_candidate(
        team["teamId"],
        run_id,
        record["recordId"],
        {"createdByAgent": "data_intake_coordinator"},
    )

    # Unresolvable queryId must not raise, not block the import, and must not
    # regress the historical metadata shape (no perspective key, no error).
    assert response.get("created") is True
    metadata = response["candidate"]["metadata"]
    assert not metadata.get("perspective")
    assert "perspective" not in metadata["sourceCollectionTrace"]


def test_key_finding_fact_dicts_extract_readable_text():
    extraction = {
        "keyFindings": [
            {
                "fact": "Predictive coding models reduce surprise via hierarchical precision weighting.",
                "quote": "A raw DataRecord",
                "evidenceRef": "Abstract",
            }
        ]
    }

    texts = team_workflow_orchestration_service._source_collection_extraction_key_finding_texts(extraction)

    assert texts == ["Predictive coding models reduce surprise via hierarchical precision weighting."]


def test_normalize_text_list_extracts_dict_text_fields_without_repr():
    values = [
        {"fact": "fact one", "quote": "q"},
        {"title": "title text", "name": "name text"},
        {"unrelated": 1},
        "plain scalar",
    ]

    normalized = team_workflow_orchestration_service._normalize_text_list(
        values, max_items=10, max_length=240
    )

    assert normalized[0] == "fact one"
    assert normalized[1] == "title text"
    # Keyless dicts keep the legacy str() shape so existing callers are unchanged.
    assert normalized[2].startswith("{")
    assert normalized[3] == "plain scalar"


def test_record_extraction_writeback_materializes_fact_dict_key_findings(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="AI科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "神经预测编码资料提炼",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["predictive coding neural algorithm"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    record = data_processing_service.add_record(
        run_id,
        {
            "sourceType": "paper",
            "sourceRef": "https://doi.org/10.0000/fact-dict-findings",
            "title": "Predictive coding raw record with fact-dict findings",
            "summary": "A raw DataRecord whose keyFindings only carry the contract fact field.",
            "metadata": {"doi": "10.0000/fact-dict-findings"},
        },
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-fact-dict", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    append_conversation_event(
        tmp_path, task["sessionId"], task["turn"]["turnId"], "tool_result", status="done",
        payload={"toolCall": {"name": "web_fetch_tool", "status": "done",
            "arguments": {"url": record["sourceRef"]},
            "result": "[网页内容] " + record["sourceRef"] + "\n\n" + record["summary"]}},
    )

    fact = "原始记录只携带契约 fact 字段，也必须物化为可读结论文本。"
    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "完成 DataRecord 提炼。",
            "result": {
                "recordExtractions": [
                    {
                        "recordId": record["recordId"],
                        "decision": "keep",
                        "valueSummary": "原始记录可作为预测编码机制候选来源。",
                        "title": "Predictive coding raw record with fact-dict findings",
                        "source_type": "preprint",
                        "source_url": "https://doi.org/10.0000/fact-dict-findings",
                        "retrieved_at": "2026-09-01T08:00:00Z",
                        "relation": "supports",
                        "verification_status": "metadata_checked",
                        "claims": [
                            {
                                "claim": "Predictive coding raw record supports hierarchical control analogy.",
                                "fact": "Predictive coding raw record supports hierarchical control analogy.",
                                "quote": "A raw DataRecord",
                                "sourceRef": "record-source-1",
                                "supportLevel": "medium",
                            }
                        ],
                        # Defect shape: every item carries only the contract
                        # text field `fact` (no legacy `finding` key), so the
                        # pre-fix normalizers fell through to the str() repr.
                        "keyFindings": [
                            {
                                "fact": fact,
                                "quote": "A raw DataRecord",
                                "sourceRef": "record-source-1",
                                "evidenceRef": "Abstract",
                            }
                        ],
                        "sourceRefs": [{"type": "record", "id": "record-source-1", "label": "Fact Dict Source"}],
                        "evidenceRefs": [{"type": "record_anchor", "id": "record-source-1-abstract", "label": "abstract"}],
                    }
                ]
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert response["writeback"]["materializedSources"]["importedCandidateCount"] == 1
    candidates = team_workflow_orchestration_service.list_candidate_store(team["teamId"], candidate_type="source_manifest")["candidates"]
    extraction = candidates[0]["metadata"]["contentExtraction"]
    assert extraction["keyFindings"] == [fact]
    assert "{'" not in str(extraction["keyFindings"])
    ledger = extraction["evidenceLedger"]
    assert ledger["keyFindings"][0]["finding"] == fact
    assert ledger["keyFindings"][0]["evidenceRef"] == "Abstract"


def test_doi_locator_bridges_publisher_mirror_receipt():
    """E2E shape (candidate-20260950-ba9f6135): the candidate locator is the
    doi.org URL while the agent fetched the publisher mirror — only the DOI
    bridge key binds them."""
    text = "应用数学与力学镜像页正文：预测编码层级误差控制摘要。"
    fetched = {
        "http://www.applmathmech.cn/EN/10.21656/1000-0887.390245": _fetch_receipt(
            "http://www.applmathmech.cn/EN/10.21656/1000-0887.390245", text
        )
    }
    candidate = {
        "candidateId": "c1",
        "sourceUrl": "https://doi.org/10.21656/1000-0887.390245",
        "metadata": {"sourceUrl": "https://doi.org/10.21656/1000-0887.390245"},
    }

    blocks = source_quotable_blocks(candidate, {}, fetched_text_by_locator=fetched)

    assert [block["text"] for block in blocks] == [text]
    # Block provenance keeps pointing at the original receipt, unrewritten.
    assert blocks[0]["locator"] == "http://www.applmathmech.cn/EN/10.21656/1000-0887.390245"


def test_doi_locator_bridge_does_not_overmatch():
    """Different DOIs (or DOI-free URLs) must not cross-bind via the key."""
    text = "Unrelated mirror body."
    fetched = {
        "http://www.applmathmech.cn/EN/10.21656/1000-0887.999999": _fetch_receipt(
            "http://www.applmathmech.cn/EN/10.21656/1000-0887.999999", text
        )
    }
    other_doi_candidate = {
        "candidateId": "c1",
        "sourceUrl": "https://doi.org/10.21656/1000-0887.390245",
    }
    assert source_quotable_blocks(other_doi_candidate, {}, fetched_text_by_locator=fetched) == []
    # DOI-free publisher URLs never gain a bridge key.
    plain_candidate = {"candidateId": "c2", "sourceUrl": "https://example.org/paper"}
    plain_fetched = {"https://example.org/other": _fetch_receipt("https://example.org/other", text)}
    assert source_quotable_blocks(plain_candidate, {}, fetched_text_by_locator=plain_fetched) == []


def test_doi_locator_bridge_matches_doi_style_path_variants():
    """`/doi/<doi>` and `/article/doi/<doi>` publisher paths bridge as well."""
    text = "Publisher DOI-path body."
    doi = "10.21656/1000-0887.390245"
    for receipt_locator in (
        f"https://publisher.example/doi/{doi}",
        f"https://publisher.example/article/doi/{doi}",
        f"https://doi.org/{doi}",
    ):
        fetched = {receipt_locator: _fetch_receipt(receipt_locator, text)}
        candidate = {"candidateId": "c1", "sourceUrl": f"https://doi.org/{doi}"}
        blocks = source_quotable_blocks(candidate, {}, fetched_text_by_locator=fetched)
        assert [block["text"] for block in blocks] == [text], receipt_locator
