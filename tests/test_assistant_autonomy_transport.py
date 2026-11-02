"""Real ASGI + SDK transport for additive inventory and autonomy contracts."""
from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from core.external_agent.backend_client import BackendClientError, ManagedAgentBackendClient
from core.web.services.external_management import research_control, runtime_operations
from core.web.services.external_management.service import ManagementError
from tests.test_external_agent_runtime_operations import api as management_api, adapter as launcher_adapter, PREFIX
from tests.test_launcher_assistant_runtime_operations import env, research as native_research


HASH = "a" * 64
RUN = {"kind": "research_run", "resourceId": "run-a", "status": "running", "revision": "1", "agentId": "",
       "sessionId": "", "teamId": "team-a", "flowId": "flow-a", "commands": ["stop", "pause"], "progressFingerprint": HASH}
RUN_QUERY = {"kind": "research_run", "resource_id": "run-a", "team_id": "team-a", "flow_id": "flow-a"}
CONTROL = {**RUN_QUERY, "command": "stop", "expected_revision": "1"}


@pytest.fixture
def api(management_api, env, native_research, monkeypatch):
    """Reuse the real HTTP/service bridge, with isolated native Research Ledger."""
    api = management_api
    api.native.project_root = env.project
    api.native._owners = env.gateway._owners
    api.state.operation_rows = [deepcopy(RUN)]

    def snapshot(gateway, kind):
        return [deepcopy(row) for row in api.state.operation_rows if row["kind"] == kind], {
            "source": kind, "state": "available", "complete": True}

    def read_runtime(query):
        api.state.reads.append(("runtime_list", query.model_dump()))
        return runtime_operations.read_operations(api.native, query)

    def read_operation(query):
        api.state.reads.append(("runtime_get", query.model_dump()))
        row = next((row for row in api.state.operation_rows if row["kind"] == query.kind and row["resourceId"] == query.resource_id), None)
        if row is None:
            raise ManagementError("OPERATION_UNAVAILABLE", 404)
        return {"operation": deepcopy(row), "untrustedContent": True}

    def knowledge(query):
        api.state.reads.append(("knowledge_list", query.model_dump()))
        return {"knowledgeBases": [{"knowledgeBaseId": "kb-a", "scopedKnowledgeBaseId": "team:team-a:kb-a",
            "ownerType": "team", "ownerId": "team-a", "name": "Public metadata", "status": "active", "fingerprint": HASH}],
            "status": "available", "total": 1, "offset": query.offset, "nextOffset": None, "digest": HASH,
            "unavailableOwnerCount": 0, "issues": [], "requiredScopes": ["knowledge:catalog:read"],
            "coverage": "Existing owner metadata only", "untrustedContent": True}

    real_research = research_control.read

    def read_research(gateway, query):
        api.state.reads.append(("research_get", deepcopy(query)))
        return real_research(gateway, query)

    monkeypatch.setattr(runtime_operations, "_snapshot", snapshot)
    monkeypatch.setattr(api.native, "read_runtime_operations", read_runtime)
    monkeypatch.setattr(api.native, "read_runtime_operation", read_operation)
    monkeypatch.setattr(api.native, "read_knowledge_catalog", knowledge, raising=False)
    monkeypatch.setattr(research_control, "read", read_research)
    api.research = native_research
    yield api


async def authorize(api, scopes, request_id="upgrade-autonomy"):
    status = await api.sdk.management_authorization_status()
    missing = sorted(set(scopes) - set(status["scopes"]))
    if missing:
        return await api.sdk.management_action(action="authorization_upgrade", request_id=request_id,
            parameters={"expected_scopes": status["scopes"], "add_scopes": missing})


def server_scopes(api):
    return api.client.get(PREFIX + "/authorization", headers=api.headers).json()["scopes"]


@pytest.mark.anyio
@pytest.mark.parametrize("method,args", [("runtime", ["list"]), ("knowledge_catalog", []),
                                       ("research", []), ("reconciliation", [])])
@pytest.mark.parametrize("change", ["revoked", "rebound", "revision"])
async def test_metadata_read_drops_results_if_native_authorization_changes(tmp_path, method, args, change):
    from core.assistant_runtime.management import ManagementAdapter
    from core.assistant_runtime.dispatch import DispatchError
    projects, binding = {"p": str(tmp_path / "project")}, {"revision": 1}

    async def call(project_id, _reader):
        if change == "revoked":
            projects.clear()
        elif change == "rebound":
            projects[project_id] = str(tmp_path / "other-project")
        else:
            binding["revision"] += 1
        return {"privateMetadata": "must not escape"}

    owner = ManagementAdapter(tmp_path, lambda: projects, call,
        read_binding=lambda key: (projects.get(key), binding["revision"]))
    with pytest.raises(DispatchError) as error:
        await getattr(owner, method)("p", *args)
    assert error.value.code == "PROJECT_BINDING_CHANGED"


@pytest.mark.anyio
async def test_new_inventory_and_item_are_explicit_scoped_additions_with_legacy_closed_shapes(api):
    denied = api.client.get(PREFIX + "/runtime/inventory", headers=api.headers)
    assert denied.status_code == 403 and not api.state.reads
    await authorize(api, ["operations:read"])
    legacy = api.client.get(PREFIX + "/runtime/operations?kind=research_run", headers=api.headers)
    item = api.client.get(PREFIX + "/runtime/operation", params=RUN_QUERY, headers=api.headers)
    assert legacy.status_code == item.status_code == 200
    assert "snapshot" not in legacy.json() and "progressFingerprint" not in legacy.json()["operations"][0]
    assert "progressFingerprint" not in item.json()["operation"]
    inventory = await api.sdk.management_runtime("list", kind="research_run")
    current = await api.sdk.management_runtime("get", **RUN_QUERY)
    assert len(inventory["snapshot"]) == 64 and inventory["operations"][0]["progressFingerprint"] == HASH
    assert current["operation"]["progressFingerprint"] == HASH
    paths = [path.split("?")[0] for method, path, _ in api.state.transport if method == "GET"]
    assert any(path.endswith("/runtime/inventory") for path in paths)
    assert any(path.endswith("/runtime/item") for path in paths)
    assert not any(path.endswith(("/runtime/operations", "/runtime/operation")) for path in paths)
    assert api.client.get(PREFIX + "/runtime/operations?expected_snapshot=" + inventory["snapshot"], headers=api.headers).status_code == 422


@pytest.mark.anyio
async def test_runtime_snapshot_409_detects_equal_total_page_omission_through_sdk(api):
    await authorize(api, ["operations:read"])
    api.state.operation_rows = [{**RUN, "resourceId": rid} for rid in ["A", "B", "C"]]
    first = await api.sdk.management_runtime("list", kind="research_run", limit=1)
    api.state.operation_rows = [{**RUN, "resourceId": rid} for rid in ["B", "C", "D"]]
    with pytest.raises(BackendClientError) as failure:
        await api.sdk.management_runtime("list", kind="research_run", offset=1, limit=1, expected_snapshot=first["snapshot"])
    assert failure.value.code == "RUNTIME_SNAPSHOT_CHANGED"
    response = api.client.get(PREFIX + "/runtime/inventory", headers=api.headers,
        params={"kind": "research_run", "offset": 1, "limit": 1, "expected_snapshot": first["snapshot"]})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "RUNTIME_SNAPSHOT_CHANGED"
    with pytest.raises(BackendClientError) as forged:
        await api.sdk.management_runtime("list", expected_snapshot="0" * 64)
    assert forged.value.code == "RUNTIME_SNAPSHOT_CHANGED"


@pytest.mark.anyio
async def test_invalid_snapshot_is_rejected_locally_and_by_http_before_native_read(api):
    await authorize(api, ["operations:read"])
    before = len(api.state.reads), len(api.state.transport)
    with pytest.raises(BackendClientError) as failure:
        await api.sdk.management_runtime("list", expected_snapshot="forged")
    assert failure.value.code == "INVALID_MANAGEMENT_REQUEST"
    assert (len(api.state.reads), len(api.state.transport)) == before
    response = api.client.get(PREFIX + "/runtime/inventory?expected_snapshot=forged", headers=api.headers)
    assert response.status_code == 422 and len(api.state.reads) == before[0]


@pytest.mark.anyio
async def test_knowledge_and_real_research_owner_references_survive_sdk_service_transport_without_scope_expansion(api):
    await authorize(api, ["operations:read", "knowledge:catalog:read"])
    before = server_scopes(api)
    catalog = await api.sdk.management_knowledge_catalog(owner_type="team", owner_id="team-a", query="Public", limit=1)
    assert catalog["knowledgeBases"][0]["scopedKnowledgeBaseId"] == "team:team-a:kb-a"
    query = {"run_id": "run-test", **api.research.refs, "node_offset": 0, "human_task_offset": 0, "limit": 1}
    result = await api.sdk.management_research(**query)
    assert (result["operation"]["resourceId"], result["operation"]["teamId"], result["operation"]["flowId"]) == (
        "run-test", query["team_id"], query["flow_id"])
    assert result["nodes"][0]["nodeId"] == "problem_understanding"
    assert ("research_get", {**query, "expected_revision": "", "expected_snapshot": None}) in api.state.reads
    assert next(value for name, value in api.state.reads if name == "knowledge_list")["owner_id"] == "team-a"
    assert server_scopes(api) == before and not api.state.writes
    assert api.client.get(PREFIX + "/assets/knowledge-acl?knowledge_base_id=team:team-a:kb-a", headers=api.headers).status_code == 403
    payload = json.dumps([catalog, result]).lower()
    for forbidden in ["prompt", "transcript", "summary", "private/path"]:
        assert forbidden not in payload
    with pytest.raises(BackendClientError) as denied:
        await api.sdk.management_research(**{**query, "team_id": "foreign-team"})
    assert denied.value.code == "run_not_found"


@pytest.mark.anyio
async def test_sdk_rejects_wrong_knowledge_or_research_owner_even_in_a_closed_native_response(api):
    await authorize(api, ["operations:read", "knowledge:catalog:read"])
    with pytest.raises(BackendClientError) as failure:
        await api.sdk.management_knowledge_catalog(owner_type="agent", owner_id="agent-a")
    assert failure.value.code == "BACKEND_PROTOCOL_ERROR"
    def change_owner(payload):
        payload["operation"]["teamId"] = "foreign-team"
        return payload
    api.state.transform = change_owner
    with pytest.raises(BackendClientError) as failure:
        await api.sdk.management_research(run_id="run-test", **api.research.refs)
    assert failure.value.code == "BACKEND_PROTOCOL_ERROR"


@pytest.mark.anyio
@pytest.mark.parametrize("changed_field", ["revision", "snapshot"])
async def test_sdk_research_continuation_verifies_the_requested_native_revision(api, changed_field):
    await authorize(api, ["operations:read"])
    query = {"run_id": "run-test", **api.research.refs}
    page = await api.sdk.management_research(**query)
    revision = page["operation"]["revision"]

    def change_revision(payload):
        if changed_field == "revision":
            payload["operation"]["revision"] = str(int(revision) + 1)
        else:
            payload["snapshot"] = "e" * 64 if page["snapshot"] != "e" * 64 else "f" * 64
        return payload

    api.state.transform = change_revision
    with pytest.raises(BackendClientError) as failure:
        await api.sdk.management_research(**query, expected_revision=revision, expected_snapshot=page["snapshot"])
    assert failure.value.code == "BACKEND_PROTOCOL_ERROR"


@pytest.mark.parametrize("suffix", [
    "/runtime/inventory?kind=research_run&kind=runtime_task", "/runtime/item?kind=research_run&resource_id=run-a&team_id=team-a&flow_id=flow-a&extra=1",
    "/knowledge-bases?owner_type=team&owner_type=agent", "/knowledge-bases?owner_type=team&owner_id=team-a&body=SECRET",
    "/research/operation?run_id=run-test&run_id=other", "/research/operation?run_id=run-test&team_id=research-team&flow_id=flow&force=true",
])
@pytest.mark.anyio
async def test_duplicate_and_extra_queries_never_reach_native_owners(api, suffix):
    await authorize(api, ["operations:read", "knowledge:catalog:read"])
    before = len(api.state.reads), len(api.state.writes)
    response = api.client.get(PREFIX + suffix, headers=api.headers)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_INPUT"
    assert (len(api.state.reads), len(api.state.writes)) == before


@pytest.mark.anyio
async def test_reduce_and_revoke_sync_sdk_scopes_without_historical_upgrade_restoration(api, monkeypatch):
    await authorize(api, ["operations:read", "knowledge:catalog:read"], request_id="original-upgrade")
    current = await api.sdk.management_authorization_status()
    reduced = await api.sdk.management_action(action="authorization_reduce", request_id="reduce-once", parameters={
        "expected_scopes": current["scopes"], "remove_scopes": ["operations:read"], "expected_grant_revision": current["grantRevision"]})
    assert reduced["authorization"]["scopes"] == api.sdk._state["management"]["scopes"]
    remaining = list(api.sdk._state["management"]["scopes"])
    assert "operations:read" not in remaining and remaining == server_scopes(api)
    old = await api.sdk.management_receipt(action="authorization_upgrade", request_id="original-upgrade")
    assert old["verified"] is True and api.sdk._state["management"]["scopes"] == remaining
    with pytest.raises(BackendClientError) as denied:
        await api.sdk.management_runtime("list")
    assert denied.value.code == "SCOPE_DENIED"
    current = await api.sdk.management_authorization_status()
    revoked = await api.sdk.management_action(action="authorization_revoke", request_id="revoke-once", parameters={
        "expected_scopes": current["scopes"], "expected_grant_revision": current["grantRevision"]})
    assert revoked["authorization"]["revoked"] is True and revoked["authorization"]["scopes"] == []
    assert api.sdk._state["management"]["revoked"] is True
    assert api.sdk._state["management"]["scopes"] == []
    monkeypatch.setattr(api.sdk, "_management_grant", ManagedAgentBackendClient._management_grant.__get__(api.sdk))
    before = len(api.state.transport)
    with pytest.raises(BackendClientError) as locally_denied:
        await api.sdk.management_runtime("list")
    assert locally_denied.value.code == "SUBJECT_REVOKED" and len(api.state.transport) == before
    receipt = await api.sdk.management_receipt(action="authorization_revoke", request_id="revoke-once")
    assert receipt["verified"] is True and receipt["authorization"]["revoked"] is True


@pytest.mark.anyio
async def test_sdk_and_launcher_reconciliation_report_requires_review_without_post_or_replay(api, monkeypatch):
    await authorize(api, ["operations:control"])
    def unknown(parameters, marker):
        api.state.writes.append(("runtime_command", deepcopy(parameters)))
        raise ManagementError("OPERATION_UNCONFIRMED", 503)
    monkeypatch.setattr(api.native, "runtime_command", unknown)
    first = await api.sdk.management_action(action="runtime_command", request_id="original-control", parameters=CONTROL)
    assert first["status"] == "unknown" and first["verified"] is False
    before = len(api.state.transport), len(api.state.writes)
    result = await api.sdk.management_reconciliation(action="runtime_command", request_id="original-control")
    assert result["state"] == "requires_review" and result["requiresReview"] is True and result["verified"] is False
    assert result["target"]["resource_id"] == "run-a" and "result" not in result
    through_adapter = await launcher_adapter(api).reconciliation("project-a", action="runtime_command", request_id="original-control")
    assert through_adapter["state"] == "requires_review" and through_adapter["projectId"] == "project-a"
    assert len(api.state.writes) == before[1] == 1
    assert all(method == "GET" for method, _, _ in api.state.transport[before[0]:])
    assert api.client.get(PREFIX + "/actions/runtime_command/requests/original-control/reconciliation?force=true", headers=api.headers).status_code == 422
