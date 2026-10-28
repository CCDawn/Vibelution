"""Temporary real legacy files through durable target grants, HTTP and SDK."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from core.web.services.external_management.contracts import SCOPES
from core.web.services.external_management.legacy_native import LegacyNativeGateway
from core.web.services.external_management.service import ManagementError, ManagementService, TargetIdentity
from tests.test_assistant_legacy_correlation import source, read_rows, write_rows, write_json, disk

PREFIX = "/v1/launcher-assistant-management"
BINDING = {"projectId": "project", "instanceId": "instance"}
SCOPE = "legacy:receipts:read"
OLD = sorted(["agents:avatar", "agents:create", "agents:read", "agents:update", "platform:describe",
              "sessions:read", "teams:read", "teams:run"])


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.infrastructure import developer_sandbox
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes import launcher_assistant_management as route
    fixture = source(tmp_path)
    config = tmp_path / "source-config.toml"
    config.write_text("[launcher.developer_mode]\nenabled = false\n", encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "formal_workspace_path", lambda project, *parts: fixture["args"]["workspace"].joinpath(*parts))
    gateway = LegacyNativeGateway(fixture["args"]["project_root"], SimpleNamespace(CONFIG_PATH=config), runtime_root=fixture["runtime"])
    calls = []
    class Native:
        project_root = fixture["args"]["project_root"]
        def legacy_observation_snapshot(self, *args):
            calls.append(args)
            return gateway.snapshot(*args)
        def __getattr__(self, name):
            raise AssertionError("No native execution/repair call is authorized: " + name)
    identity = [TargetIdentity(deepcopy(BINDING), "authority")]
    native = Native()
    def restarted():
        return ManagementService(tmp_path / "management", identity=lambda: identity[0], native=native)
    service = restarted()
    grant = service.bind({"client_id": "observer-client", "expected_binding": BINDING, "scopes": [SCOPE]})
    headers = {CONTROL_TOKEN_HEADER: get_control_token(), route.SUBJECT_HEADER: grant["subject_id"],
               route.CAPABILITY_HEADER: grant["subject_capability"]}
    monkeypatch.setattr(route, "_SERVICE", service)
    app = FastAPI()
    app.include_router(route.router)
    with TestClient(app) as client:
        yield SimpleNamespace(**fixture, config=config, service=service, restart=restarted, native=native,
            gateway=gateway, calls=calls, identity=identity, grant=grant, subject=grant["subject_id"],
            cap=grant["subject_capability"], headers=headers, client=client, route=route, tmp=tmp_path)


def request(env, **changes):
    return {"request_id": "observe-1", "expected_binding": BINDING, "source_agent_id": "pa",
            "legacy_message_ids": ["dispatch"], "expected_registry_sha256": hashlib.sha256(env.registry.read_bytes()).hexdigest(),
            "expected_source_authority": env.gateway.snapshot(BINDING, "pa", ["dispatch"]).data["sourceAuthority"], **changes}


def create(env, **changes):
    return env.service.create_legacy_observer(env.subject, env.cap, request(env, **changes))


def read(env, observer_id):
    return env.service.read_legacy_receipts(env.subject, env.cap, observer_id)


def append_receipt(env):
    receipt = {"messageId": "late-reply", "eventId": "late-reply", "sourceAgentId": "target", "targetAgentId": "pa",
        "sourceSessionId": "target-session", "targetSessionId": "pa-session", "kind": "agent_inbox_reply", "status": "pending",
        "content": "PRIVATE_LATE_REPLY", "metadata": {"replyToMessageId": "dispatch", "sourceTurnId": "turn-real",
            "personalAssistantTask": {"schemaVersion": 1, "dispatchMessageId": "dispatch", "status": "completed", "evidenceRefs": ["PRIVATE_EVIDENCE"]}}}
    write_rows(env.pa_inbox, read_rows(env.pa_inbox) + [receipt])


def source_hashes(env):
    return {"project": disk(env.args["project_root"]), "workspace": disk(env.args["workspace"]), "runtime": disk(env.runtime)}


def test_real_source_grant_late_receipt_and_restart_are_read_only(env):
    before = source_hashes(env)
    first = create(env)
    assert first["status"] == "created" and first["actions"] == ["read_receipt"] and first["ownerEpoch"] == 1
    assert not first["sourceQuiesced"] and not first["readyForCutover"]
    current = read(env, first["observerId"])
    assert current["dispatches"][0]["nativeTurnId"] == "turn-real"
    assert current["dispatches"][0]["nativeTaskId"] is None
    assert source_hashes(env) == before
    append_receipt(env)
    late_before = source_hashes(env)
    env.service = env.restart()
    result = read(env, first["observerId"])
    assert result["dispatches"][0]["businessTaskStatus"] == "completed"
    assert result["dispatches"][0]["receipts"] == [{"legacyMessageId": "late-reply", "taskStatus": "completed", "evidenceCount": 1}]
    assert source_hashes(env) == late_before
    assert all(value not in json.dumps(result) for value in ("PRIVATE_", str(env.tmp), env.cap, "subject_capability"))


def test_retry_reads_original_proof_without_native_reprepare_or_new_write(env, monkeypatch):
    payload = request(env)
    first = env.service.create_legacy_observer(env.subject, env.cap, payload)
    count = len(env.calls)
    env.service = env.restart()
    def writing(*args):
        raise AssertionError("No proof replay write")
    monkeypatch.setattr(env.service.store, "write", writing)
    result = env.service.create_legacy_observer(env.subject, env.cap, payload)
    assert result == {**first, "reused": True} and len(env.calls) == count


@pytest.mark.parametrize("point", ["before-proof", "after-proof", "after-intent"])
def test_lost_ack_durable_intent_recovers_only_original_proof(env, monkeypatch, point):
    payload = request(env)
    original = env.service.store.write
    hits = []
    def writing(path, value):
        if path.parent.name == "subjects" and "legacyObservers" in value:
            hits.append("proof")
            if point == "before-proof": raise OSError("PRIVATE_PATH")
            original(path, value)
            if point == "after-proof": raise OSError("PRIVATE_PATH")
            return
        original(path, value)
        if point == "after-intent" and value.get("action") == "legacy_observer":
            raise OSError("PRIVATE_PATH")
    monkeypatch.setattr(env.service.store, "write", writing)
    result = env.service.create_legacy_observer(env.subject, env.cap, payload)
    assert result["status"] == "unknown" and "PRIVATE_PATH" not in str(result)
    native_calls = len(env.calls)
    env.service = env.restart()
    recovered = env.service.create_legacy_observer(env.subject, env.cap, payload)
    assert recovered["reused"] and len(env.calls) == native_calls
    assert recovered["status"] == ("created" if point == "after-proof" else "unknown")
    assert len(hits) <= 1


@pytest.mark.parametrize("changes", [{"legacy_message_ids": ["another"]}, {"source_agent_id": "target"},
                                      {"expected_registry_sha256": "0" * 64}, {"expected_source_authority": "0" * 64}])
def test_admitted_request_parameters_and_fingerprints_are_immutable(env, changes):
    create(env)
    calls = len(env.calls)
    with pytest.raises(ManagementError, match="IDEMPOTENCY_CONFLICT"):
        create(env, **changes)
    assert len(env.calls) == calls


@pytest.mark.parametrize("changes", [{"actions": ["cancel"]}, {"actions": ["read_receipt"]}, {"force": True},
    {"path": "C:/private"}, {"legacy_message_ids": []}, {"legacy_message_ids": ["dispatch", "dispatch"]},
    {"legacy_message_ids": ["z", "a"]}, {"source_agent_id": "../pa"},
    {"expected_source_authority": None}, {"expected_source_authority": ""},
    {"expected_source_authority": "A" * 64}, {"expected_source_authority": "g" * 64},
    {"expected_source_authority": "a" * 63}])
def test_closed_creation_rejects_extra_actions_paths_and_implicit_refs(env, changes):
    with pytest.raises(ManagementError, match="INVALID_INPUT"):
        create(env, **changes)
    assert env.calls == []


def test_creation_requires_explicit_source_authority(env):
    payload = request(env)
    del payload["expected_source_authority"]
    with pytest.raises(ManagementError, match="INVALID_INPUT"):
        env.service.create_legacy_observer(env.subject, env.cap, payload)
    assert env.calls == []
    assert not list(env.service.store.root.glob("requests/*.json"))


def test_source_authority_mismatch_cannot_persist_intent_or_proof(env, monkeypatch):
    def writing(*args):
        raise AssertionError("Source mismatch must be rejected before any durable write")
    monkeypatch.setattr(env.service.store, "write", writing)
    with pytest.raises(ManagementError, match="LEGACY_SOURCE_CHANGED"):
        create(env, expected_source_authority="0" * 64)
    assert len(env.calls) == 1
    assert not list(env.service.store.root.glob("requests/*.json"))
    assert not env.service.store.read(env.service.store.path("subjects", env.subject)).get("legacyObservers")


def test_stale_registry_unknown_ref_or_foreign_source_cannot_mint_observer(env):
    for changes, code in (({"expected_registry_sha256": "0" * 64}, "LEGACY_REGISTRY_CHANGED"),
                          ({"legacy_message_ids": ["unknown"]}, "LEGACY_REFERENCE_UNAVAILABLE"),
                          ({"source_agent_id": "target"}, "LEGACY_SOURCE_CHANGED")):
        with pytest.raises(ManagementError, match=code):
            create(env, **changes)
    assert "legacyObservers" not in env.service.store.read(env.service.store.path("subjects", env.subject))


@pytest.mark.parametrize("extra", [[], ["sessions:pin"], ["agents:archive", "sessions:pin"],
                                  ["agents:archive", "sessions:pin", "teams:directory:read", "rooms:read", "sessions:parameters:read"]])
def test_old_eight_nine_ten_thirteen_scopes_do_not_auto_upgrade(env, extra):
    scopes = sorted(OLD + extra)
    grant = env.service.bind({"client_id": "old-" + str(len(scopes)), "expected_binding": BINDING, "scopes": scopes})
    for action in (lambda: env.service.create_legacy_observer(grant["subject_id"], grant["subject_capability"], request(env)),
                   lambda: env.service.list_legacy_observers(grant["subject_id"], grant["subject_capability"])):
        with pytest.raises(ManagementError, match="SCOPE_DENIED"):
            action()
    assert env.service.store.read(env.service.store.path("subjects", grant["subject_id"]))["scopes"] == scopes


def test_current_subject_capability_scope_and_binding_are_rechecked(env):
    observer = create(env)["observerId"]
    with pytest.raises(ManagementError, match="SUBJECT_DENIED"):
        env.service.read_legacy_receipts(env.subject, "x" * 48, observer)
    other = env.service.bind({"client_id": "other", "expected_binding": BINDING, "scopes": [SCOPE]})
    with pytest.raises(ManagementError, match="LEGACY_OBSERVER_UNAVAILABLE"):
        env.service.read_legacy_receipts(other["subject_id"], other["subject_capability"], observer)
    path = env.service.store.path("subjects", env.subject)
    grant = env.service.store.read(path)
    grant["scopes"] = ["agents:read"]
    env.service.store.write(path, grant)
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        read(env, observer)
    grant["scopes"] = [SCOPE]
    env.service.store.write(path, grant)
    env.identity[0] = TargetIdentity({**BINDING, "instanceId": "changed"}, "authority")
    with pytest.raises(ManagementError, match="TARGET_BINDING_CHANGED"):
        read(env, observer)


def test_identity_pins_survive_display_status_change_but_deny_source_or_target_session_change(env):
    observer = create(env)["observerId"]
    registry = json.loads(env.registry.read_text(encoding="utf-8"))
    registry["agents"][0].update(displayName="New display", status="archived")
    write_json(env.registry, registry)
    assert read(env, observer)["observer"]["sourceAgentId"] == "pa"
    rows = read_rows(env.inbox)
    rows[0]["targetSessionId"] = "different"
    write_rows(env.inbox, rows)
    with pytest.raises(ManagementError):
        read(env, observer)


def test_new_source_dispatch_is_not_accepted_into_existing_grant(env):
    observer = create(env)["observerId"]
    extra = dict(read_rows(env.inbox)[0])
    extra.update(messageId="new-message", eventId="new-message", targetSessionId="new-private-session")
    write_rows(env.inbox, read_rows(env.inbox) + [extra])
    result = read(env, observer)
    assert [row["legacyMessageId"] for row in result["dispatches"]] == ["dispatch"]
    assert not (env.args["workspace"] / "sessions/new-private-session").exists()


def test_post_requires_control_token_subject_capability_and_closed_body(env):
    response = env.client.post(PREFIX + "/legacy-observers", json=request(env))
    assert response.status_code == 403
    for changes in ({"actions": ["continue"]}, {"approvals": True}, {"root": str(env.tmp)}):
        response = env.client.post(PREFIX + "/legacy-observers", headers=env.headers, json=request(env, **changes))
        assert response.status_code == 422
    response = env.client.post(PREFIX + "/legacy-observers", headers=env.headers, json=request(env))
    assert response.status_code == 200, response.text
    observer = response.json()["observerId"]
    assert env.client.get(PREFIX + "/legacy-observers", headers=env.headers).json()["observers"][0]["observerId"] == observer
    assert env.client.get(PREFIX + f"/legacy-observers/{observer}/receipts", headers=env.headers).status_code == 200
    for path in ("/legacy-observers", f"/legacy-observers/{observer}/receipts"):
        assert env.client.get(PREFIX + path + "?cancel=true", headers=env.headers).status_code == 422
    for action in ("legacy_observer", "legacy_observer_create", "legacy_cancel", "legacy_continue"):
        response = env.client.post(PREFIX + "/actions/" + action, headers=env.headers, json={})
        assert response.status_code == 404


def sdk_http(env, sdk, monkeypatch):
    from core.external_agent.backend_client import BackendClientError
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    async def transport(method, path, **kwargs):
        headers = {CONTROL_TOKEN_HEADER: get_control_token()}
        if kwargs.get("management_auth"):
            subject, capability = kwargs["management_auth"]
            headers.update({env.route.SUBJECT_HEADER: subject, env.route.CAPABILITY_HEADER: capability})
        response = env.client.request(method, path.removeprefix("/api"), headers=headers, json=kwargs.get("json_payload"))
        if response.status_code >= 400:
            code = response.json()["detail"]["code"]
            raise BackendClientError("Synthetic denied: " + code, code=code)
        return response.json()
    monkeypatch.setattr(sdk, "_request_json", transport)
    return transport


@pytest.mark.anyio
async def test_sdk_requires_explicit_valid_source_authority(env, monkeypatch):
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    sdk = ManagedAgentBackendClient(env.tmp, state_path=env.tmp / "sdk-required-source.json")
    transport = sdk_http(env, sdk, monkeypatch)
    posts = []
    async def recording(method, path, **kwargs):
        if method == "POST" and path.endswith("/legacy-observers"):
            posts.append(kwargs["json_payload"])
        return await transport(method, path, **kwargs)
    monkeypatch.setattr(sdk, "_request_json", recording)
    parameters = {key: value for key, value in request(env).items() if key != "expected_binding"}
    expected = parameters.pop("expected_source_authority")
    with pytest.raises(TypeError, match="expected_source_authority"):
        await sdk.management_legacy_observer_create(**parameters)
    for invalid in (None, "", "A" * 64, "g" * 64, "a" * 63):
        with pytest.raises(BackendClientError) as denied:
            await sdk.management_legacy_observer_create(**parameters, expected_source_authority=invalid)
        assert denied.value.code == "INVALID_MANAGEMENT_REQUEST"
    assert posts == [] and env.calls == []
    result = await sdk.management_legacy_observer_create(**parameters, expected_source_authority=expected)
    assert result["status"] == "created" and posts[0]["expected_source_authority"] == expected


@pytest.mark.anyio
@pytest.mark.parametrize("random_prefix", ["-", "_"])
async def test_sdk_closed_http_lost_ack_restart_and_late_receipt(env, monkeypatch, random_prefix):
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    from core.external_agent import backend_client
    token_urlsafe = backend_client.secrets.token_urlsafe
    monkeypatch.setattr(backend_client.secrets, "token_urlsafe",
                        lambda n: random_prefix + "a" * 42 if n == 32 else token_urlsafe(n))
    sdk_path = env.tmp / "sdk-state.json"
    sdk = ManagedAgentBackendClient(env.tmp, state_path=sdk_path)
    transport = sdk_http(env, sdk, monkeypatch)
    async def lost(method, path, **kwargs):
        result = await transport(method, path, **kwargs)
        if method == "POST" and path.endswith("/legacy-observers"):
            raise BackendClientError("Synthetic lost ACK", code="BACKEND_UNAVAILABLE")
        return result
    monkeypatch.setattr(sdk, "_request_json", lost)
    parameters = {key: value for key, value in request(env).items() if key != "expected_binding"}
    with pytest.raises(BackendClientError, match="Synthetic lost"):
        await sdk.management_legacy_observer_create(**parameters)
    saved = deepcopy(sdk._state["management"])
    assert saved["clientId"].endswith(random_prefix + "a" * 42)
    assert saved["scopes"] == sorted(SCOPES[:14]) and len(saved["scopes"]) == 14
    env.service = env.restart()
    monkeypatch.setattr(env.route, "_SERVICE", env.service)
    restarted = ManagedAgentBackendClient(env.tmp, state_path=sdk_path)
    sdk_http(env, restarted, monkeypatch)
    count = len(env.calls)
    result = await restarted.management_legacy_observer_create(**parameters)
    assert result["status"] == "created" and result["reused"] and len(env.calls) == count
    assert restarted._state["management"] == saved
    append_receipt(env)
    listed = await restarted.management_legacy_observers()
    assert listed["observers"][0]["observerId"] == result["observerId"]
    receipts = await restarted.management_legacy_receipts(result["observerId"])
    assert receipts["dispatches"][0]["businessTaskStatus"] == "completed"
    assert all(value not in json.dumps(receipts) for value in ("PRIVATE_", str(env.tmp), saved["capability"]))


def test_explicit_native_authorization_upgrade_adds_only_new_read_scope(env):
    old = env.service.bind({"client_id": "old-explicit-upgrade", "expected_binding": BINDING, "scopes": OLD})
    path = env.service.store.path("subjects", old["subject_id"])
    before = deepcopy(env.service.store.read(path))
    upgraded = env.service.invoke(old["subject_id"], old["subject_capability"], "authorization_upgrade", {
        "request_id": "upgrade-observation", "expected_binding": BINDING,
        "parameters": {"expected_scopes": OLD, "add_scopes": [SCOPE]}})
    assert upgraded["status"] == "completed" and upgraded["authorization"]["addedScopes"] == [SCOPE]
    after = env.service.store.read(path)
    assert after["subject_id"] == before["subject_id"] and after["subject_capability"] == before["subject_capability"]
    assert after["scopes"] == sorted(OLD + [SCOPE])
    result = env.service.create_legacy_observer(old["subject_id"], old["subject_capability"], request(env))
    assert result["status"] == "created" and result["actions"] == ["read_receipt"]


def test_source_change_after_durable_intent_cannot_publish_a_false_created_result(env, monkeypatch):
    original = env.service.store.write
    payload = request(env)
    def writing(path, value):
        original(path, value)
        if value.get("action") == "legacy_observer":
            append_receipt(env)
    monkeypatch.setattr(env.service.store, "write", writing)
    result = env.service.create_legacy_observer(env.subject, env.cap, payload)
    assert result["status"] == "unknown"
    grant = env.service.store.read(env.service.store.path("subjects", env.subject))
    assert not grant.get("legacyObservers")
    count = len(env.calls)
    env.service = env.restart()
    retry = env.service.create_legacy_observer(env.subject, env.cap, payload)
    assert retry["status"] == "unknown" and len(env.calls) == count


def test_unresolved_native_turn_is_explicit_and_does_not_grant_task_control(env):
    env.journal.unlink()
    result = create(env)
    assert result["status"] == "created"
    receipt = read(env, result["observerId"])["dispatches"][0]
    assert receipt["nativeCorrelation"] == "unresolved" and receipt["nativeTaskId"] is None
    assert receipt["nativeTurnId"] is None and receipt["reason"] == "source_unavailable"
    assert result["actions"] == ["read_receipt"]


@pytest.mark.anyio
async def test_sdk_rejects_private_fields_control_actions_and_wrong_observer_binding(env, monkeypatch):
    from core.external_agent.backend_client import ManagedAgentBackendClient, BackendClientError
    sdk = ManagedAgentBackendClient(env.tmp, state_path=env.tmp / "sdk-closed.json")
    transport = sdk_http(env, sdk, monkeypatch)
    parameters = {key: value for key, value in request(env).items() if key != "expected_binding"}
    original = await sdk.management_legacy_observer_create(**parameters)
    for change in ({"private_grant": {"secret": "never"}}, {"actions": ["cancel"]}, {"ownerEpoch": True},
                   {"sourceQuiesced": 0}, {"observerId": "lob-" + "0" * 64}):
        async def tampered(method, path, **kwargs):
            value = await transport(method, path, **kwargs)
            return {**value, **change} if path.endswith("/legacy-observers") else value
        monkeypatch.setattr(sdk, "_request_json", tampered)
        with pytest.raises(BackendClientError) as denied:
            await sdk.management_legacy_observer_create(**parameters)
        assert denied.value.code == "BACKEND_PROTOCOL_ERROR"
    assert original["status"] == "created"


def test_default_target_runtime_resolver_uses_existing_native_run(env, monkeypatch):
    import vibelution_storage
    env.gateway.runtime_root = None
    calls = []
    def runtime(project):
        assert project == env.args["project_root"]
        calls.append(project)
        return env.runtime
    monkeypatch.setattr(vibelution_storage, "resolve_project_runtime_home", runtime)
    observer = create(env)["observerId"]
    result = read(env, observer)
    assert calls and result["dispatches"][0]["nativeRunId"] == "turn-real"
    assert result["dispatches"][0]["nativeRunReason"] == "matched"


def test_missing_target_runtime_is_explicit_and_does_not_guess_run(env, monkeypatch):
    import vibelution_storage
    env.gateway.runtime_root = None
    monkeypatch.setattr(vibelution_storage, "resolve_project_runtime_home", lambda project: env.tmp / "not-initialized-runtime")
    result = read(env, create(env)["observerId"])["dispatches"][0]
    assert result["nativeRunId"] is None and result["nativeRunReason"] == "runtime_root_unavailable"


def test_workspace_route_switch_with_copied_ids_denies_original_grant(env, monkeypatch):
    import shutil
    from core.infrastructure import developer_sandbox
    observer = create(env)["observerId"]
    replacement = env.tmp / "other-source/workspace"
    shutil.copytree(env.args["workspace"], replacement)
    monkeypatch.setattr(developer_sandbox, "formal_workspace_path", lambda project, *parts: replacement.joinpath(*parts))
    with pytest.raises(ManagementError, match="LEGACY_SOURCE_CHANGED"):
        read(env, observer)


def test_copied_registry_and_ids_in_other_workspace_cannot_mint_observer(env, monkeypatch):
    import shutil
    from core.infrastructure import developer_sandbox
    payload = request(env)
    replacement = env.tmp / "other-source/workspace"
    shutil.copytree(env.args["workspace"], replacement)
    assert hashlib.sha256((replacement / "agents/agents.json").read_bytes()).hexdigest() == payload["expected_registry_sha256"]
    monkeypatch.setattr(developer_sandbox, "formal_workspace_path", lambda project, *parts: replacement.joinpath(*parts))
    current = env.gateway.snapshot(BINDING, "pa", ["dispatch"]).data
    assert current["sourceAuthority"] != payload["expected_source_authority"]
    before = source_hashes(env), disk(replacement)
    with pytest.raises(ManagementError, match="LEGACY_SOURCE_CHANGED"):
        env.service.create_legacy_observer(env.subject, env.cap, payload)
    assert len(env.calls) == 1
    assert not list(env.service.store.root.glob("requests/*.json"))
    assert not env.service.store.read(env.service.store.path("subjects", env.subject)).get("legacyObservers")
    assert (source_hashes(env), disk(replacement)) == before


def unrelated_agent(env, *, workspace_path=""):
    registry = json.loads(env.registry.read_text(encoding="utf-8"))
    registry["agents"].append({"agentId": "unrelated", "directSessionId": "unrelated-session", "status": "active",
                               "metadata": {}, "workspacePath": workspace_path})
    write_json(env.registry, registry)
    return env.args["workspace"] / "agents/unrelated/events/agent_inbox_messages.jsonl"


def observation_preview(env):
    from core.assistant_runtime.legacy_handoff import preview_legacy_observation
    return preview_legacy_observation(**env.args, legacy_message_ids=["dispatch"])


def test_absent_unrelated_inbox_uses_typed_negative_proof_without_changing_old_preview(env):
    from core.assistant_runtime.legacy_handoff import preview_legacy_handoff
    from core.assistant_runtime.legacy_correlation import correlate_legacy_dispatches
    absent = unrelated_agent(env)
    before = source_hashes(env)
    old = preview_legacy_handoff(**env.args)
    assert old["previewComplete"] is False and any(issue["code"] == "source_missing" for issue in old["issues"])
    evidence = observation_preview(env)
    assert evidence.report["observationComplete"] is True
    assert evidence.report["previewComplete"] is False
    assert len(evidence.absences) == evidence.report["absentSourceCount"] == 1
    assert evidence.absences[0].path == absent
    correlated = correlate_legacy_dispatches(evidence, workspace=env.args["workspace"], runtime_root=env.runtime)
    assert correlated["correlationComplete"] and correlated["dispatches"][0]["nativeTurnId"] == "turn-real"
    observer = create(env)
    assert observer["status"] == "created"
    assert read(env, observer["observerId"])["dispatches"][0]["nativeRunId"] == "turn-real"
    assert not absent.exists() and source_hashes(env) == before


def test_negative_proof_rejects_inbox_appearance_before_correlation(env):
    from core.assistant_runtime.legacy_correlation import correlate_legacy_dispatches
    absent = unrelated_agent(env)
    evidence = observation_preview(env)
    write_rows(absent, [])
    result = correlate_legacy_dispatches(evidence, workspace=env.args["workspace"], runtime_root=env.runtime)
    assert not result["correlationComplete"]
    assert result["issues"] == [{"code": "absent_inbox_appeared"}]
    assert result["dispatches"][0]["nativeTurnId"] is None


def test_negative_proof_detects_absent_parent_create_remove_aba(env):
    from core.assistant_runtime.legacy_correlation import correlate_legacy_dispatches
    import os
    absent = unrelated_agent(env)
    evidence = observation_preview(env)
    ancestor = absent.parents[1]
    ancestor.mkdir()
    ancestor.rmdir()
    nearest = evidence.absences[0].parents[-1][0]
    value = nearest.stat()
    os.utime(nearest, ns=(value.st_atime_ns, value.st_mtime_ns + 10_000_000))
    result = correlate_legacy_dispatches(evidence, workspace=env.args["workspace"], runtime_root=env.runtime)
    assert not result["correlationComplete"]
    assert result["issues"] == [{"code": "absent_inbox_changed"}]


@pytest.mark.parametrize("missing", ["pa_inbox", "inbox"])
def test_selected_pa_or_target_inbox_missing_never_gets_negative_permission(env, missing):
    getattr(env, missing).unlink()
    evidence = observation_preview(env)
    assert evidence.report["observationComplete"] is False
    with pytest.raises(ManagementError):
        create(env)
    assert not env.service.store.read(env.service.store.path("subjects", env.subject)).get("legacyObservers")


def test_absent_custom_unrelated_inbox_is_not_authorized_by_negative_mode(env):
    unrelated_agent(env, workspace_path=str(env.tmp / "outside-agent"))
    evidence = observation_preview(env)
    assert not evidence.report["observationComplete"] and not evidence.absences
    assert any(issue["code"] == "custom_workspace_unsupported" for issue in evidence.report["issues"])
    with pytest.raises(ManagementError):
        create(env)


def test_all_present_inboxes_still_participate_in_duplicate_detection(env):
    path = unrelated_agent(env)
    duplicate = dict(read_rows(env.inbox)[0])
    duplicate["targetAgentId"] = "unrelated"
    duplicate["targetSessionId"] = "unrelated-session"
    write_rows(path, [duplicate])
    evidence = observation_preview(env)
    assert not evidence.report["observationComplete"]
    assert any(issue["code"] == "duplicate_message_id" for issue in evidence.report["issues"])
    with pytest.raises(ManagementError):
        create(env)


def test_negative_proof_is_rechecked_after_intent_before_private_grant(env, monkeypatch):
    absent = unrelated_agent(env)
    original = env.service.store.write
    payload = request(env)
    def writing(path, value):
        original(path, value)
        if value.get("action") == "legacy_observer":
            write_rows(absent, [])
    monkeypatch.setattr(env.service.store, "write", writing)
    result = env.service.create_legacy_observer(env.subject, env.cap, payload)
    assert result["status"] == "unknown"
    assert not env.service.store.read(env.service.store.path("subjects", env.subject)).get("legacyObservers")


def test_existing_observer_survives_new_unrelated_agent_without_inbox(env):
    observer = create(env)["observerId"]
    absent = unrelated_agent(env)
    result = read(env, observer)
    assert result["observer"]["status"] == "created" and not absent.exists()
    assert [row["legacyMessageId"] for row in result["dispatches"]] == ["dispatch"]


def test_only_migrated_observer_gets_are_documented_as_native_actions():
    from core.web.services.external_management.contracts import DOCUMENTATION_ACTIONS, ACTION_MODELS
    prefix = "/api/v1/launcher-assistant-management/legacy-observers"
    assert DOCUMENTATION_ACTIONS[("GET", prefix)] == "legacy_observers"
    assert DOCUMENTATION_ACTIONS[("GET", prefix + "/{observer_id}/receipts")] == "legacy_receipts"
    assert ("POST", prefix) not in DOCUMENTATION_ACTIONS
    assert "legacy_observer" not in ACTION_MODELS and "legacy_observer_create" not in ACTION_MODELS
