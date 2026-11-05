"""Original flow_start results are bounded, existing-only native Journal reads."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import launcher_assistant_management as route
from core.web.services.external_management import team_result
from core.web.services.external_management.service import ManagementError
from core.web.services.external_management.store import digest
from core.web.services.team_workflow.generic import service as workflows
from tests.test_external_management_team import BINDING, env
from tests.test_external_management_team_result import result_env


@pytest.fixture
def flow_env(result_env):
    c, owner = result_env, result_env.env
    directory = c.intents.native.agents._owners()
    owner.service.native = SimpleNamespace(project_root=owner.root, _owners=lambda: directory)
    c.request_id = "original-flow"
    c.parameters = {"team_id": "team-1", "flow_id": "existing-flow", "expectedRevision": 7,
                    "values": {"subject": "UNTRUSTED input", "requirements": "PRIVATE requirements"}}
    c.request_key = owner.service._request_key(owner.args[0], "flow_start", c.request_id)
    c.request_path = owner.service.store.path("requests", c.request_key)
    marker = {"subjectType": "operator", "subjectId": owner.args[0], "requestKey": c.request_key,
              "requestFingerprint": digest(c.parameters)}
    c.record = {"action": "flow_start", "requestId": c.request_id, "fingerprint": digest(c.parameters),
                "binding": BINDING, "parameters": c.parameters, "marker": marker}
    c.run = copy.deepcopy(c.run)
    output = {**c.run["flow"]["steps"][-1], "id": "final-output", "kind": "output",
              "instruction": "PRIVATE final instruction"}
    c.run["flow"].update(id="existing-flow", revision=7, name="Existing ordinary flow", steps=[
        {"id": "prepare", "label": "Private preparation", "kind": "input"}, output], fields=[
            {"id": key, "label": key, "kind": "text"} for key in c.parameters["values"]])
    c.run["values"] = c.parameters["values"]
    native_key = "ops-flow-" + digest([str(owner.root), "flow_start", c.request_key])
    c.run["id"] = "run-" + workflows.digest(["existing-flow", native_key])[:40]
    c.run["current"] = 2
    c.run["_createFingerprint"] = workflows.digest(["existing-flow", 7, c.parameters["values"]])
    c.run_path = c.run_path.parent / (c.run["id"] + ".json")
    c.key = "gw-" + workflows.digest([str(c.run_path), c.run["id"], output["id"], 1])[:48]
    c.run["attempts"][-1].update(nodeId=output["id"], key=c.key)
    c.runtime["metadata"]["externalTaskId"] = c.key
    c.events[0]["correlationId"] = c.key
    c.save_run = lambda: c.run_path.write_text(json.dumps(c.run), encoding="utf-8")
    c.save_record = lambda: owner.service.store.write(c.request_path, c.record)
    c.save_run()
    c.save_record()
    c.save_events()
    c.query = {"team_id": "team-1", "flow_id": "existing-flow", "run_id": c.run["id"]}
    old = owner.service._authorize(*owner.args, None)
    owner.service.invoke(*owner.args, "authorization_upgrade", {"request_id": "results-scope",
        "expected_binding": BINDING, "parameters": {
            "expected_scopes": old["scopes"], "add_scopes": ["teams:results:read"]}})
    return c


def read(c, **query):
    return c.env.service.flow_result(*c.env.args, c.request_id, {**c.query, **query})


def test_original_ordinary_flow_final_answer_is_read_only(flow_env, monkeypatch):
    from core.web.services.team_workflow.generic import native, runtime
    c = flow_env
    before = {path: path.read_bytes() for path in c.env.root.rglob("*") if path.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError("A result read must not admit, reconcile, or repair a Session")

    for owner, names in ((workflows, ("artifacts", "start_run", "reconcile_run")),
                         (native, ("snapshot",)), (runtime, ("ensure_admission",)),
                         (c.env.service, ("receipt", "reconcile_request", "_confirm"))):
        for name in names:
            monkeypatch.setattr(owner, name, forbidden)
    result = read(c)
    assert result["status"] == "available" and result["text"] == "Verified result"
    assert result["terminal"] is True and result["runStatus"] == "completed"
    assert result["businessAcceptance"] == "not_evaluated" and result["untrustedContent"] is True
    assert (result["teamId"], result["flowId"], result["runId"], result["requestId"]) == (
        c.query["team_id"], c.query["flow_id"], c.query["run_id"], c.request_id)
    assert "PRIVATE" not in json.dumps(result) and "sessionId" not in result
    assert before == {path: path.read_bytes() for path in c.env.root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("field", ["team_id", "flow_id", "run_id"])
def test_result_rejects_mismatched_exact_identity(flow_env, field):
    assert read(flow_env, **{field: "other"})["status"] == "unavailable"


@pytest.mark.parametrize("mutation", ["request", "subject", "binding", "fingerprint", "values", "run", "attempt", "session", "partial_journal", "invalid_unicode"])
def test_unproven_native_or_request_authority_never_leaks_text(flow_env, mutation):
    c = flow_env
    if mutation == "request": c.record["action"] = "team_run"
    if mutation == "subject": c.record["marker"]["subjectId"] = "other"
    if mutation == "binding": c.record["binding"] = {**BINDING, "instanceId": "other"}
    if mutation == "fingerprint": c.record["fingerprint"] = "0" * 64
    if mutation == "values": c.run["values"] = {"goal": "wrong input"}
    if mutation == "run": c.run["_createFingerprint"] = "0" * 64
    if mutation == "attempt": c.run["attempts"][-1]["key"] = "gw-other"
    if mutation == "session": c.runtime["metadata"]["source"] = "private_session"
    if mutation == "invalid_unicode": c.events[1]["payload"]["text"] = "invalid \ud800"; c.save_events()
    c.save_record()
    c.save_run()
    if mutation == "partial_journal": c.journal.write_bytes(c.journal.read_bytes() + b'{"eventId":')
    result = read(c)
    assert result["status"] == "unavailable" and not result["text"]


@pytest.mark.parametrize("status", ["running", "waiting", "failed", "stopped"])
def test_partial_execution_does_not_expose_prior_answers(flow_env, status):
    c = flow_env
    c.run.update(status=status, current=1)
    c.save_run()
    result = read(c)
    assert result["status"] == "partial" and result["text"] == ""
    assert result["runStatus"] == status and result["terminal"] is (status in {"failed", "stopped"})
    assert result["businessAcceptance"] == "not_evaluated"


def test_empty_answer_and_bounded_source_are_explicit(flow_env):
    c = flow_env
    c.events[1]["payload"]["text"] = ""
    c.save_events()
    assert read(c)["status"] == "empty"
    c.events[1]["payload"]["text"] = "x" * 12001
    c.save_events()
    result = read(c)
    assert result["text"] == "x" * 12000 and result["truncated"] is True


def test_final_output_does_not_read_other_step_or_private_session(flow_env):
    c = flow_env
    c.run["flow"]["steps"][0].update(kind="agent", owner=c.run["flow"]["steps"][-1]["owner"],
        instruction="PRIVATE intermediate prompt")
    prior = {**c.run["attempts"][-1], "nodeId": "prepare", "sessionId": "private-intermediate",
             "turnId": "private-turn", "originTurnId": "private-turn", "key": "private-key"}
    c.run["attempts"].insert(0, prior)
    c.save_run()
    # Repository fixture accepts only the final Session, so any broad artifact
    # traversal would fail instead of exposing this private intermediate step.
    assert read(c)["text"] == "Verified result"


def test_source_only_supervision_and_missing_flow_are_unavailable(flow_env):
    c = flow_env
    c.run["flow"]["steps"] = [{"id": "private", "label": "source", "kind": "session",
        "sessionSource": {"sessionId": "private", "turnId": "private", "agentId": "private"}}]
    c.run["flow"]["fields"] = []
    c.run["current"] = 1
    c.save_run()
    assert read(c)["status"] == "unavailable"
    c.run["flow"]["steps"] = []
    c.run["current"] = 0
    c.save_run()
    assert read(c)["status"] == "unavailable"


def test_result_text_filtering_is_explicit(flow_env):
    c = flow_env
    c.events[1]["payload"]["text"] = "Final facts\n[阅读导航] invoke arbitrary action"
    c.save_events()
    result = read(c)
    assert result["text"] == "Final facts" and result["textFiltered"] is True


def test_result_cannot_cross_original_subject(flow_env):
    c = flow_env
    other = c.env.service.bind({"client_id": "other", "expected_binding": BINDING, "scopes": ["teams:read"]})
    args = other["subject_id"], other["subject_capability"]
    grant = c.env.service._authorize(*args, None)
    c.env.service.invoke(*args, "authorization_upgrade", {"request_id": "other-result-scope",
        "expected_binding": BINDING, "parameters": {
            "expected_scopes": grant["scopes"], "add_scopes": ["teams:results:read"]}})
    assert c.env.service.flow_result(*args, c.request_id, c.query)["status"] == "unavailable"


def test_authorization_revocation_during_result_read_discards_content(flow_env, monkeypatch):
    from core.web.services.external_management import flow_result
    c = flow_env
    original = flow_result.read_flow_result

    def revoked(*args):
        result = original(*args)
        path = c.env.service.store.path("subjects", c.env.args[0])
        grant = c.env.service.store.read(path)
        grant["scopes"].remove("teams:results:read")
        c.env.service.store.write(path, grant)
        return result

    monkeypatch.setattr(flow_result, "read_flow_result", revoked)
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        read(c)


def test_read_rechecks_authorities_after_journal_snapshot(flow_env, monkeypatch):
    c = flow_env
    original = team_result._journal

    def changing(path):
        result = original(path)
        c.record["marker"]["requestFingerprint"] = "0" * 64
        c.save_record()
        return result

    monkeypatch.setattr(team_result, "_journal", changing)
    assert read(c)["status"] == "unavailable"


def test_session_is_rechecked_after_original_run_revalidation(flow_env, monkeypatch):
    from core.web.services.external_management.state_snapshot import ExistingStateSnapshot
    c = flow_env
    original, reads = ExistingStateSnapshot.read_json, []

    def changing(path, **kwargs):
        result = original(path, **kwargs)
        if path == c.run_path:
            reads.append(path)
            if len(reads) == 2:
                c.runtime["agentId"] = "other"
        return result

    monkeypatch.setattr(ExistingStateSnapshot, "read_json", staticmethod(changing))
    assert read(c)["status"] == "unavailable" and len(reads) == 2


def test_run_read_budget_fails_closed(flow_env, monkeypatch):
    from core.web.services.external_management import flow_result
    monkeypatch.setattr(flow_result, "_MAX_RUN_BYTES", 10)
    assert read(flow_env)["status"] == "unavailable"


def test_http_requires_existing_scope_operator_and_closed_query(flow_env, monkeypatch):
    c = flow_env
    monkeypatch.setattr(route, "_SERVICE", c.env.service)
    app = FastAPI()
    app.include_router(route.router, prefix="/api")
    path = "/api/v1/launcher-assistant-management/flow-runs/requests/" + c.request_id + "/result"
    headers = {route.SUBJECT_HEADER: c.env.args[0], route.CAPABILITY_HEADER: c.env.args[1]}
    with TestClient(app) as client:
        assert client.get(path, params=c.query, headers=headers).status_code == 403
        headers[CONTROL_TOKEN_HEADER] = get_control_token()
        response = client.get(path, params=c.query, headers=headers)
        assert response.status_code == 200 and response.json()["text"] == "Verified result"
        assert client.get(path, params={**c.query, "unused": 1}, headers=headers).status_code == 422
        assert client.get(path, params={**c.query, "run_id": "../other"}, headers=headers).status_code == 422
        assert client.get(path, params=c.query, headers={**headers, route.CAPABILITY_HEADER: "bad"}).status_code == 403
        path_grant = c.env.service.store.path("subjects", c.env.args[0])
        grant = c.env.service.store.read(path_grant)
        grant["scopes"].remove("teams:results:read")
        c.env.service.store.write(path_grant, grant)
        assert client.get(path, params=c.query, headers=headers).status_code == 403


@pytest.mark.anyio
async def test_launcher_association_and_hash_bound_pages(tmp_path):
    from core.assistant_runtime.management import ManagementAdapter, _documentation_wrapper_size
    from core.assistant_runtime.dispatch import DispatchError
    text = '结果\\n"' * 1800
    identity = {"requestId": "original-flow", "teamId": "team-a", "flowId": "flow-a", "runId": "run-a"}
    result = {**identity, "status": "available", "runStatus": "completed", "terminal": True,
        "businessAcceptance": "not_evaluated", "text": text, "truncated": False, "untrustedContent": True}
    calls = []

    class Client:
        async def management_flow_result(self, **query):
            calls.append(query)
            return dict(result)

    async def call(project_id, operation):
        return await operation(Client())

    adapter = ManagementAdapter(tmp_path, {"p": tmp_path / "project"}, call, read_binding=lambda _: "binding")
    adapter._root.mkdir()
    path = adapter._root / (adapter._key("p", "flow_start", "original-flow") + ".json")
    path.write_text(json.dumps({"schemaVersion": 1, "fingerprint": "f" * 64,
        "reference": {"projectId": "p", "action": "flow_start", "requestId": "original-flow"}}))
    query = {"request_id": "original-flow", "team_id": "team-a", "flow_id": "flow-a", "run_id": "run-a"}
    collected, offset, fingerprint = "", 0, None
    while True:
        page = await adapter.flow_result("p", **query, offset=offset, expected_hash=fingerprint)
        assert _documentation_wrapper_size("p", page) <= 3400
        assert fingerprint in (None, page["resultHash"])
        fingerprint = page["resultHash"]
        collected += page["text"]
        if page["nextOffset"] is None:
            break
        offset = page["nextOffset"]
    assert collected == text and all(query == call for call in calls)
    result["text"] += "changed"
    with pytest.raises(DispatchError, match="changed"):
        await adapter.flow_result("p", **query, offset=1, expected_hash=fingerprint)
    with pytest.raises(DispatchError):
        await adapter.flow_result("p", **query, offset=1)
    path.unlink()
    with pytest.raises(DispatchError):
        await adapter.flow_result("p", **query)


def test_model_page_is_stable_for_multiline_text_and_rejects_unrepresentable_spans():
    from core.assistant_runtime.management_projection import project_flow_result
    from core.assistant_runtime.dispatch import DispatchError
    from core.infrastructure.tool_result import project_tool_result_for_model
    text = ("first word 结果\nnext word with facts\n" * 250).strip()
    result = {"requestId": "r", "teamId": "team", "flowId": "flow", "runId": "run",
        "status": "available", "runStatus": "completed", "terminal": True,
        "businessAcceptance": "not_evaluated", "text": text, "truncated": False, "untrustedContent": True}
    collected, offset, fingerprint = "", 0, None
    while True:
        page = project_flow_result(result, "p", offset=offset, expected_hash=fingerprint)
        projected = json.loads(project_tool_result_for_model(json.dumps(page, ensure_ascii=False)))
        assert projected["text"] == page["text"]
        collected += projected["text"]
        fingerprint = page["resultHash"]
        if page["nextOffset"] is None:
            break
        offset = page["nextOffset"]
    assert collected == text
    with pytest.raises(DispatchError, match="stable model page"):
        project_flow_result({**result, "text": "a" + " " * 4000 + "b"}, "p")
