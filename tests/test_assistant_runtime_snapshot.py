"""Version-bound runtime pages never silently skip a changing native set."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from core.web.services.external_management import runtime_operations as runtime
from core.web.services.external_management.runtime_contracts import RuntimeOperationsQuery, RuntimeOperationsResponse
from core.web.services.external_management.service import ManagementError


@pytest.fixture
def source(monkeypatch):
    state = SimpleNamespace(ids=["A", "B", "C"], revision="1", complete=True)

    def snapshot(gateway, kind):
        return [{"kind": kind, "resourceId": rid, "revision": state.revision, "status": "running",
                 "agentId": "", "sessionId": "", "teamId": "", "flowId": "", "commands": ["stop"]}
                for rid in state.ids], {"source": kind, "state": "available" if state.complete else "partial",
                                       "complete": state.complete}

    monkeypatch.setattr(runtime, "_snapshot", snapshot)
    return state, SimpleNamespace(_owners=lambda: None)


def page(gateway, **kwargs):
    return runtime.read_operations(gateway, {"kind": "runtime_task", "limit": 1, **kwargs})


def test_bound_page_rejects_equal_total_set_change_that_would_skip_b(source):
    state, gateway = source
    first = page(gateway)
    assert first["operations"][0]["resourceId"] == "A"
    state.ids = ["B", "C", "D"]
    # Old unbound callers retain their offset behavior: B is silently skipped.
    assert page(gateway, offset=1)["operations"][0]["resourceId"] == "C"
    with pytest.raises(ManagementError, match="RUNTIME_SNAPSHOT_CHANGED") as error:
        page(gateway, offset=1, expected_snapshot=first["snapshot"])
    assert error.value.status_code == 409


def test_bound_pages_keep_one_snapshot_and_do_not_bind_page_size(source):
    _, gateway = source
    first = page(gateway)
    rest = runtime.read_operations(gateway, {"kind": "runtime_task", "offset": 1, "limit": 3,
                                            "expected_snapshot": first["snapshot"]})
    assert rest["snapshot"] == first["snapshot"]
    assert [item["resourceId"] for item in rest["operations"]] == ["B", "C"]
    assert rest["nextOffset"] is None
    RuntimeOperationsResponse.model_validate(rest)


@pytest.mark.parametrize("change", ["revision", "coverage", "filter"])
def test_snapshot_binds_metadata_coverage_and_query_semantics(source, change):
    state, gateway = source
    first = page(gateway)
    kwargs = {}
    if change == "revision":
        state.revision = "2"
    elif change == "coverage":
        state.complete = False
    else:
        kwargs["state"] = "all"
    with pytest.raises(ManagementError, match="RUNTIME_SNAPSHOT_CHANGED"):
        page(gateway, offset=1, expected_snapshot=first["snapshot"], **kwargs)


def test_partial_snapshot_stays_partial_even_with_valid_continuation(source):
    state, gateway = source
    state.complete = False
    first = page(gateway)
    second = page(gateway, offset=1, expected_snapshot=first["snapshot"])
    assert second["complete"] is False
    assert second["coverage"] == [{"source": "runtime_task", "state": "partial", "complete": False}]


def test_forged_well_formed_snapshot_fails_without_returning_a_page(source):
    _, gateway = source
    with pytest.raises(ManagementError, match="RUNTIME_SNAPSHOT_CHANGED"):
        page(gateway, expected_snapshot="0" * 64)


@pytest.mark.parametrize("invalid", ["", "A" * 64, "0" * 63, True, "../snapshot"])
def test_snapshot_is_a_closed_sha256_token(source, invalid):
    _, gateway = source
    with pytest.raises(ValidationError):
        RuntimeOperationsQuery(expected_snapshot=invalid)
    with pytest.raises(ManagementError, match="INVALID_INPUT"):
        page(gateway, expected_snapshot=invalid)


def test_progress_fingerprint_excludes_heartbeat_and_cas_revision():
    raw = {"id": "run-a", "teamId": "team-a", "flow": {"id": "flow-a"}, "status": "running",
           "revision": 1, "current": 0, "attempts": [{"nodeId": "step-a", "number": 1, "status": "running",
            "promptHash": "SECRET", "failureCode": "SECRET"}], "updatedAt": "yesterday"}
    before = runtime._project("team_run", raw)
    heartbeat = runtime._project("team_run", {**raw, "revision": 2, "updatedAt": "today"})
    progress = runtime._project("team_run", {**raw, "current": 1})
    assert before["progressFingerprint"] == heartbeat["progressFingerprint"]
    assert before["progressFingerprint"] != progress["progressFingerprint"]
    assert before["progressFingerprint"] is not None


@pytest.mark.parametrize("kind,raw", [("runtime_task", {"taskId": "task-a"}),
    ("external_task", {"taskId": "eat-a", "revision": 1}),
    ("session_turn", {"runId": "turn-a", "sessionId": "session-a"}),
    ("supervised_run", {"runId": "supervised-a"}), ("self_evolution_run", {"runId": "self-a"})])
def test_missing_progress_authority_is_explicitly_unknown(kind, raw):
    value = runtime._project(kind, {**raw, "status": "running", "updatedAt": "today",
                                  "eventSequence": 999, "progress": "SECRET forged generic field"})
    assert value["progressFingerprint"] is None


def test_research_progress_tracks_native_ledger_events_not_cas_version():
    raw = {"runId": "research-a", "teamId": "team-a", "flowId": "flow-a", "status": "running",
           "revision": 1, "lastEventSequence": 2, "activeNodeId": "node-a"}
    first = runtime._project("research_run", raw)["progressFingerprint"]
    assert first is not None
    assert runtime._project("research_run", {**raw, "revision": 3})["progressFingerprint"] == first
    assert runtime._project("research_run", {**raw, "lastEventSequence": 3})["progressFingerprint"] != first
