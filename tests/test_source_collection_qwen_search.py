"""Run-level Qwen deep-search supplement (DashScope Responses API) tests.

The layered scheme: the per-query Crossref/arXiv/OpenAlex scans stay the
default provider set untouched; exactly once per source-collection run the
execution fires one non-streaming Responses API web_search call whose
``web_search_call.action.sources`` URLs enter the shared record pipeline
(same mappers, identity-key dedupe, exclusion ledger, candidate import).
Covers: task/payload construction, live-shape response parsing, URL-to-record
mapping with identity dedupe, once-per-run idempotency, fail-open semantics
(missing key / transport failure), and answer-text persistence on the event.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from core.web.services import (
    data_processing_service,
    team_service,
    team_workflow_orchestration_service as s,
)
from core.web.services.team_workflow.source_collection import residual
from core.web.services.team_workflow.source_collection import search_execution

from tests._support.team_workflow.helpers import (  # noqa: F401
    _fake_source_search_response,
    _use_fake_local_research_config,
    _use_tmp_project_root,
)


# Mirrors the live response shape verified 2026-09-03 (qwen3.8-flash,
# non-streaming): output mixes reasoning / web_search_call / message items,
# sources are {type, url} dicts, usage carries token counts plus
# x_tools.web_search.count.
_QWEN_RESPONSES_PAYLOAD = {
    "id": "resp_smoke_verified",
    "status": "completed",
    "output": [
        {"type": "reasoning", "id": "rs_1", "summary": []},
        {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
            "action": {
                "type": "search",
                "query": "arxiv quant-ph/9908043",
                "queries": ["arxiv quant-ph/9908043", "site:arxiv.org abs quant-ph/9908043"],
                "sources": [
                    {"type": "url", "url": "https://arxiv.org/abs/quant-ph/9908043"},
                    {"type": "url", "url": "https://arxiv.org/pdf/quant-ph/9908043"},
                    {"type": "url", "url": "https://doi.org/10.0000/predictive-coding"},
                    {"type": "url", "url": "https://example.org/quantum-repeater-notes"},
                    "https://arxiv.org/abs/quant-ph/9908043",
                ],
            },
        },
        {"type": "reasoning", "id": "rs_2", "summary": []},
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [
                {
                    "type": "output_text",
                    "text": (
                        "The identifier quant-ph/9908043 refers to 'Ultimate physical limits to "
                        "computation' by Seth Lloyd. Canonical abstract URL: "
                        "https://arxiv.org/abs/quant-ph/9908043."
                    ),
                }
            ],
        },
    ],
    "usage": {
        "input_tokens": 7017,
        "output_tokens": 851,
        "total_tokens": 7868,
        "output_tokens_details": {"reasoning_tokens": 476},
        "x_tools": {"web_search": {"count": 2}},
    },
}

_UNIQUE_SOURCE_URLS = [
    "https://arxiv.org/abs/quant-ph/9908043",
    "https://arxiv.org/pdf/quant-ph/9908043",
    "https://doi.org/10.0000/predictive-coding",
    "https://example.org/quantum-repeater-notes",
]


@pytest.fixture
def dashscope_key(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-key-for-unit-tests")


@pytest.fixture
def captured_post(monkeypatch):
    """Stub the Responses API POST transport with the smoke-verified payload."""
    calls = []

    def fake_post(url, *, payload, headers, provider, timeout):
        calls.append({"url": url, "payload": payload, "headers": headers, "provider": provider, "timeout": timeout})
        return json.dumps(_QWEN_RESPONSES_PAYLOAD).encode("utf-8")

    monkeypatch.setattr(search_execution, "_source_collection_rate_limited_http_post_json", fake_post)
    return calls


def _stub_academic_providers(monkeypatch):
    """Replace the three per-query academic providers with offline fixtures."""

    def dispatch(query, *, max_results, provider):
        assert provider != "qwen_web_search", "qwen must never run as a per-query provider"
        return _fake_source_search_response(query, max_results=max_results, provider=provider)

    monkeypatch.setattr(s, "_execute_source_collection_query", dispatch)


def _create_run(team_id: str, *, query_seeds: list[str] | None = None):
    return s.start_source_collection_run(
        team_id,
        {
            "title": "Qwen deep-search batch",
            "topic": "predictive coding",
            "goal": "collect predictive coding evidence",
            "querySeeds": query_seeds or ["predictive coding"],
            "searchLanguages": ["en"],
            "sourceTypes": ["paper"],
            "maxResultsPerQuery": 2,
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": "Source Finder Agent"},
        },
    )


# ---------------------------------------------------------------------------
# Registry and transport knobs
# ---------------------------------------------------------------------------


def test_qwen_web_search_is_not_a_per_query_provider():
    assert s.SOURCE_COLLECTION_SEARCH_PROVIDER_QWEN_WEB_SEARCH == "qwen_web_search"
    # Layered scheme: qwen is the run-level supplement, never a per-query
    # provider; the academic scans keep their default order.
    assert "qwen_web_search" not in s.SOURCE_COLLECTION_SEARCH_PROVIDERS
    assert s.SOURCE_COLLECTION_SEARCH_PROVIDERS == ("crossref_rest_api", "arxiv_api", "openalex_api")


def test_qwen_provider_has_rate_limit_entry():
    assert "qwen_web_search" in search_execution._SOURCE_COLLECTION_PROVIDER_RATE_LIMITS


def test_qwen_deep_search_helpers_are_bound_into_orchestration_service_namespace():
    assert hasattr(s, "_execute_qwen_deep_search_for_run")
    assert hasattr(s, "_source_collection_result_from_qwen_source_url")
    assert hasattr(s, "_source_collection_qwen_url_doi")
    assert hasattr(s, "_source_collection_qwen_url_arxiv_id")
    assert hasattr(s, "_qwen_deep_search_request_payload")
    assert hasattr(s, "_qwen_deep_search_task")
    assert hasattr(s, "_qwen_deep_search_max_output_tokens")
    assert hasattr(s, "_dashscope_search_api_key")
    assert s._DASHSCOPE_RESPONSES_ENDPOINT == "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"


# ---------------------------------------------------------------------------
# Task and request construction
# ---------------------------------------------------------------------------


def test_qwen_deep_search_task_composes_goal_and_directions():
    run = {
        "runId": "dprun-1",
        "scope": {
            "goal": "collect predictive coding evidence",
            "topic": "predictive coding",
            "searchEnvelope": {"keywords": ["predictive coding", "free energy"]},
        },
    }
    assignments = [
        {"scope": {"assignedQueries": [{"query": "predictive coding cortical"}, {"query": "free energy principle brain"}]}},
    ]
    task = s._qwen_deep_search_task(run, assignments)
    assert "Collection goal: collect predictive coding evidence" in task
    assert "Topic: predictive coding" in task
    assert "Keywords: predictive coding, free energy" in task
    assert "- predictive coding cortical" in task
    assert "arXiv" in task


def test_qwen_deep_search_task_resolves_question_en_from_catalog(monkeypatch):
    monkeypatch.setattr(
        "core.research.competition.resources.load_science_question_catalog",
        lambda: {
            "questions": [
                {"id": "q-001", "question_en": "How does predictive coding explain cortical hierarchy?"},
            ]
        },
    )
    run = {"runId": "dprun-2", "scope": {"questionId": "q-001", "topic": "predictive coding"}}
    task = s._qwen_deep_search_task(run, [])
    assert "Research question: How does predictive coding explain cortical hierarchy?" in task
    # Unknown id degrades to the topic line instead of failing the task.
    run_unknown = {"runId": "dprun-3", "scope": {"questionId": "missing", "topic": "predictive coding"}}
    assert "Research question:" not in s._qwen_deep_search_task(run_unknown, [])


def test_qwen_deep_search_task_empty_without_any_signal():
    assert s._qwen_deep_search_task({"runId": "dprun-4", "scope": {}}, []) == ""
    assert s._qwen_deep_search_task({"runId": "dprun-5"}, []) == ""


def test_qwen_deep_search_request_payload_shape(dashscope_key):
    payload = s._qwen_deep_search_request_payload("find primary sources")
    assert payload["model"] == "qwen3.8-flash"
    assert payload["input"] == "find primary sources"
    assert payload["tools"] == [{"type": "web_search"}]
    assert payload["max_output_tokens"] == 4096


def test_qwen_deep_search_request_env_overrides(monkeypatch):
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_QWEN_SEARCH_MODEL", "qwen3.8-max")
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_QWEN_DEEP_SEARCH_MAX_OUTPUT_TOKENS", "2048")
    payload = s._qwen_deep_search_request_payload("x")
    assert payload["model"] == "qwen3.8-max"
    assert payload["max_output_tokens"] == 2048


# ---------------------------------------------------------------------------
# Response parsing (live-verified shape)
# ---------------------------------------------------------------------------


def test_qwen_deep_search_parse_response_dedupes_urls_and_extracts_answer():
    parsed = search_execution._qwen_deep_search_parse_response(_QWEN_RESPONSES_PAYLOAD)
    assert parsed["sourceUrls"] == _UNIQUE_SOURCE_URLS
    assert parsed["searchQueries"] == ["arxiv quant-ph/9908043", "site:arxiv.org abs quant-ph/9908043"]
    assert parsed["searchCallCount"] == 1
    assert "Ultimate physical limits to computation" in parsed["answerText"]
    assert parsed["usage"] == {
        "inputTokens": 7017,
        "outputTokens": 851,
        "totalTokens": 7868,
        "webSearchCount": 2,
    }
    assert parsed["responseStatus"] == "completed"


def test_qwen_deep_search_parse_response_tolerates_malformed_payload():
    parsed = search_execution._qwen_deep_search_parse_response({"output": "unexpected", "usage": None})
    assert parsed["sourceUrls"] == []
    assert parsed["answerText"] == ""
    assert parsed["usage"]["webSearchCount"] == ""


# ---------------------------------------------------------------------------
# URL parsers and the URL -> shared-record mapper
# ---------------------------------------------------------------------------


def test_qwen_url_parsers_extract_doi_and_arxiv_id():
    assert residual._source_collection_qwen_url_doi("https://doi.org/10.1038/s41586-021-03819-2") == "10.1038/s41586-021-03819-2"
    assert (
        residual._source_collection_qwen_url_doi("https://example.test/view?doi=10.5555/paper-1")
        == "10.5555/paper-1"
    )
    assert residual._source_collection_qwen_url_doi("https://example.test/papers/10.1038/in-path") == ""
    assert residual._source_collection_qwen_url_arxiv_id("http://arxiv.org/abs/2210.15752") == "2210.15752"
    assert residual._source_collection_qwen_url_arxiv_id("https://arxiv.org/abs/quant-ph/9908043") == "quant-ph/9908043"
    assert residual._source_collection_qwen_url_arxiv_id("https://arxiv.org/pdf/2401.12345v2") == "2401.12345v2"
    assert residual._source_collection_qwen_url_arxiv_id("https://example.test/abs/2210.15752") == ""


def test_qwen_source_url_mapper_produces_shared_result_shape():
    result = s._source_collection_result_from_qwen_source_url(
        "https://arxiv.org/abs/quant-ph/9908043",
        answer_text="Canonical abstract URL: https://arxiv.org/abs/quant-ph/9908043 — Ultimate physical limits to computation.",
    )
    assert result["sourceRef"] == "https://arxiv.org/abs/quant-ph/9908043"
    assert result["rawLocation"] == "https://arxiv.org/abs/quant-ph/9908043"
    # The shared pipeline normalizes preprints to the record-level "paper"
    # sourceType; the arXiv provenance survives in metadata.arxivId.
    assert result["sourceType"] == "paper"
    assert result["providerType"] == "qwen_web_search"
    assert result["metadata"]["arxivId"] == "quant-ph/9908043"
    assert result["metadata"]["doi"] == ""
    assert result["metadata"]["siteName"] == "arxiv.org"
    # The model synthesis supplies the summary context, but it is prose —
    # never an abstract.
    assert "Ultimate physical limits" in result["summary"]
    assert result["qualitySignals"]["hasDoi"] is False
    assert result["qualitySignals"]["hasAbstract"] is False


def test_qwen_source_url_mapper_without_answer_context_keeps_summary_empty():
    result = s._source_collection_result_from_qwen_source_url("https://example.org/quantum-repeater-notes")
    assert result["summary"] == ""
    assert result["sourceType"] == "url"
    assert result["title"] == "Quantum repeater notes"
    assert result["qualitySignals"]["hasAbstract"] is False


def test_qwen_doi_url_and_crossref_result_share_identity_key():
    qwen_result = s._source_collection_result_from_qwen_source_url("https://doi.org/10.0000/predictive-coding")
    crossref_result = s._source_collection_result_from_crossref_item(
        {"DOI": "10.0000/predictive-coding", "title": ["Same Paper Real Title"], "URL": "https://api.example.test/works/x"},
        fallback_source_type="paper",
    )
    assert qwen_result["sourceType"] == "paper"
    assert qwen_result["metadata"]["doi"] == "10.0000/predictive-coding"
    qwen_key = s._source_collection_result_identity_key(qwen_result)
    crossref_key = s._source_collection_result_identity_key(crossref_result)
    assert qwen_key == crossref_key == "doi:10.0000/predictive-coding"


# ---------------------------------------------------------------------------
# Execute path: once-per-run supplement through the shared pipeline
# ---------------------------------------------------------------------------


def test_deep_search_executes_once_and_merges_through_identity_dedupe(
    tmp_path, monkeypatch, dashscope_key, captured_post
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_academic_providers(monkeypatch)
    # The fake crossref response carries DOI 10.0000/predictive-coding, which
    # the deep-search fixture also discovers as a doi.org URL: the layered
    # records must merge into one source via the identity key.
    team = team_service.create_team(name="qwen deep-search 团队")
    run_response = _create_run(team["teamId"])
    run_id = run_response["run"]["runId"]

    execution = s.execute_source_collection_search(
        team["teamId"],
        run_id,
        {"maxQueries": 1, "maxResultsPerQuery": 2},
    )

    # Exactly one Responses API call per run, shaped for the verified endpoint.
    assert len(captured_post) == 1
    call = captured_post[0]
    assert call["provider"] == "qwen_web_search"
    assert call["headers"]["Authorization"] == "Bearer sk-test-key-for-unit-tests"
    assert call["payload"]["tools"] == [{"type": "web_search"}]
    assert call["payload"]["model"] == "qwen3.8-flash"
    assert "predictive coding" in call["payload"]["input"]

    deep = execution["qwenDeepSearch"]
    assert deep["status"] == "executed"
    assert deep["urlCount"] == len(_UNIQUE_SOURCE_URLS)
    # The deep search runs before the per-query loop, so nothing pre-exists:
    # all four unique URLs become records, and the later Crossref/arXiv/
    # OpenAlex replays of the shared DOI are deduped onto the qwen record.
    assert deep["duplicateCount"] == 0
    records = data_processing_service.list_records(run_id)["records"]
    qwen_records = [item for item in records if item.get("metadata", {}).get("searchProvider") == "qwen_web_search"]
    assert len(qwen_records) == len(_UNIQUE_SOURCE_URLS)
    assert deep["recordCount"] == len(_UNIQUE_SOURCE_URLS)
    assert deep["importedCount"] == len(_UNIQUE_SOURCE_URLS)
    # Natural merge: the DOI the fake crossref also returns exists exactly
    # once, under the qwen provider that discovered it first.
    shared = [item for item in records if item.get("metadata", {}).get("doi") == "10.0000/predictive-coding"]
    assert len(shared) == 1
    assert shared[0]["metadata"]["searchProvider"] == "qwen_web_search"
    assert execution["skippedDuplicateCount"] == 3  # one deduped replay per academic provider

    event_types = [event["eventType"] for event in execution["executionEvents"]]
    assert "search.qwen_deep_search.executed" in event_types
    assert event_types.count("search.qwen_deep_search.executed") == 1


def test_deep_search_runs_only_once_across_executions(tmp_path, monkeypatch, dashscope_key, captured_post):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_academic_providers(monkeypatch)
    team = team_service.create_team(name="qwen once-per-run 团队")
    run_response = _create_run(team["teamId"], query_seeds=["predictive coding", "free energy principle"])
    run_id = run_response["run"]["runId"]

    first = s.execute_source_collection_search(team["teamId"], run_id, {"maxQueries": 1, "maxResultsPerQuery": 2})
    second = s.execute_source_collection_search(team["teamId"], run_id, {"maxQueries": 1, "maxResultsPerQuery": 2})

    assert first["qwenDeepSearch"]["status"] == "executed"
    assert second["qwenDeepSearch"]["status"] == "not_attempted"
    assert len(captured_post) == 1


def test_deep_search_skipped_for_targeted_provider_execution(tmp_path, monkeypatch, dashscope_key, captured_post):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_academic_providers(monkeypatch)
    team = team_service.create_team(name="qwen targeted 团队")
    run_response = _create_run(team["teamId"])
    run_id = run_response["run"]["runId"]

    execution = s.execute_source_collection_search(
        team["teamId"],
        run_id,
        {"provider": "crossref_rest_api", "maxQueries": 1, "maxResultsPerQuery": 2},
    )

    assert captured_post == []
    assert execution["qwenDeepSearch"]["status"] == "not_attempted"


def test_deep_search_missing_api_key_fails_open(tmp_path, monkeypatch, captured_post):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_academic_providers(monkeypatch)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    team = team_service.create_team(name="qwen no-key 团队")
    run_response = _create_run(team["teamId"], query_seeds=["predictive coding", "free energy principle"])
    run_id = run_response["run"]["runId"]

    execution = s.execute_source_collection_search(team["teamId"], run_id, {"maxQueries": 1, "maxResultsPerQuery": 2})

    assert captured_post == []
    assert execution["qwenDeepSearch"]["status"] == "skipped"
    assert execution["qwenDeepSearch"]["reason"] == "missing_api_key"
    # Fail-open: the academic providers still collected records for the query.
    assert execution["status"] == "executed"
    records = data_processing_service.list_records(run_id)["records"]
    assert records
    skip_events = [event for event in execution["executionEvents"] if event["eventType"] == "search.qwen_deep_search.skipped"]
    assert len(skip_events) == 1
    assert skip_events[0]["reason"] == "missing_api_key"


def test_deep_search_transport_failure_fails_open(tmp_path, monkeypatch, dashscope_key):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_academic_providers(monkeypatch)

    def failing_post(url, *, payload, headers, provider, timeout):
        raise urllib.error.URLError("dashscope unreachable")

    monkeypatch.setattr(search_execution, "_source_collection_rate_limited_http_post_json", failing_post)
    team = team_service.create_team(name="qwen transport 团队")
    run_response = _create_run(team["teamId"], query_seeds=["predictive coding", "free energy principle"])
    run_id = run_response["run"]["runId"]

    execution = s.execute_source_collection_search(team["teamId"], run_id, {"maxQueries": 1, "maxResultsPerQuery": 2})

    assert execution["qwenDeepSearch"]["status"] == "skipped"
    assert execution["qwenDeepSearch"]["reason"] == "transport_failed"
    assert execution["status"] == "executed"
    records = data_processing_service.list_records(run_id)["records"]
    assert records and all(
        item.get("metadata", {}).get("searchProvider") != "qwen_web_search" for item in records
    )


def test_deep_search_executed_event_persists_answer_text_and_metrics(
    tmp_path, monkeypatch, dashscope_key, captured_post
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    _stub_academic_providers(monkeypatch)
    team = team_service.create_team(name="qwen answer 团队")
    run_response = _create_run(team["teamId"])
    run_id = run_response["run"]["runId"]

    execution = s.execute_source_collection_search(team["teamId"], run_id, {"maxQueries": 1, "maxResultsPerQuery": 2})

    events_file = tmp_path / execution["storageArtifacts"]["searchEventsPath"]
    with open(events_file, encoding="utf-8") as handle:
        persisted = [json.loads(line) for line in handle if line.strip()]
    deep_events = [event for event in persisted if event["eventType"] == "search.qwen_deep_search.executed"]
    assert len(deep_events) == 1
    event = deep_events[0]
    assert event["provider"] == "qwen_web_search"
    assert "Ultimate physical limits to computation" in event["answerText"]
    assert event["metrics"]["model"] == "qwen3.8-flash"
    assert event["metrics"]["sourceUrlCount"] == len(_UNIQUE_SOURCE_URLS)
    assert event["metrics"]["usage"]["webSearchCount"] == 2
    # Non-deep-search events stay free of the run-level answer field.
    assert all("answerText" not in persisted_event for persisted_event in persisted if persisted_event["eventType"] != "search.qwen_deep_search.executed")
