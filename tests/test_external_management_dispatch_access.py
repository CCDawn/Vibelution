"""Real temporary config commits, native qualification and original receipts."""
from copy import deepcopy
from contextlib import contextmanager
import json
from threading import RLock
import tomllib
from types import SimpleNamespace

import pytest

from core.web.services.external_management import dispatch_access as access
from core.web.services.external_management.service import ManagementError, ManagementService, TargetIdentity
from core.web.services.external_management.store import digest
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests.test_external_management_agent_directory import env as metadata_env
from tests.test_operator_config_transaction import _valid_v2_text


@pytest.fixture
def env(metadata_env, monkeypatch):
    from config import settings
    from core.web.services import agent_directory_service as directory, team_service, session_service as sessions
    from core.web.services.session import admission_lock
    import vibelution_storage
    env = metadata_env
    monkeypatch.setattr(settings, "_settings", None)
    monkeypatch.setattr(settings, "_config_path", None)
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(env.config))
    monkeypatch.setattr(team_service, "PROJECT_ROOT", env.root)
    env.directory._STATE_LOCK = RLock()
    env.life_lock = RLock()
    env.directory.agent_session_lifecycle_transaction = lambda **_kwargs: env.life_lock
    monkeypatch.setattr(directory, "PROJECT_ROOT", env.root)
    monkeypatch.setattr(directory, "_active_project_root", lambda: env.root)
    monkeypatch.setattr(directory, "agent_session_lifecycle_transaction", env.directory.agent_session_lifecycle_transaction)
    monkeypatch.setattr(sessions, "PROJECT_ROOT", env.root)
    monkeypatch.setattr(vibelution_storage, "resolve_project_runtime_home", lambda _root: env.root / ".runtime")
    env.session_rows = [{"conversation_id": "session-" + row["agentId"], "agent_id": row["agentId"],
                         "last_turn_status": "ready"} for row in env.agents]
    env.suspicious_work_index = False
    @contextmanager
    def admission(agent_id, **_kwargs):
        with env.life_lock:
            yield {row["conversation_id"] for row in env.session_rows if row["agent_id"] == agent_id}
    monkeypatch.setattr(sessions, "agent_archive_transaction", admission)
    monkeypatch.setattr(sessions, "load_chat_state", lambda _root: {"conversations": env.session_rows})
    from core.chat.session_activity import session_activity_policy
    monkeypatch.setattr(sessions, "_is_session_busy_for_delete", lambda _sid, row:
        session_activity_policy({"status": row["last_turn_status"]})["blocksMutation"])
    monkeypatch.setattr(admission_lock, "session_has_active_work_run", lambda *_args: env.suspicious_work_index)
    env.directory._agent_archive_protected = directory._agent_archive_protected
    env.native = SimpleNamespace(project_root=env.root, _owners=lambda: env.directory)
    env.control = access.DispatchAccessControl(env.native)
    env.config.write_text(_valid_v2_text() + '\n[launcher.developer_mode]\nenabled=false\n'
        + '[external_agent_gateway]\nenabled=true\nallowed_agent_ids=["a","b","c","d","e","f","g"]\n'
          'denied_agent_ids=["ordinary","blocked"]\npermission_ceiling="read_only"\nruntime_permission_ceiling="workspace_write"\n', encoding="utf-8")
    return env


def parameters(env, enabled=True, **changes):
    view = env.control.read("ordinary")
    return {"agent_id": "ordinary", "enabled": enabled,
        "expected_public_config_hash": view["publicConfigHash"],
        "expected_eligibility_fingerprint": view["eligibilityFingerprint"], **changes}


def marker(params, key="a" * 64):
    return {"subjectType": "operator", "subjectId": "ops-" + "b" * 32,
            "requestKey": key, "requestFingerprint": digest(params)}


def authorized(env):
    binding = {"projectId": "project-a", "instanceId": "main-a"}
    service = ManagementService(env.root / "management", identity=lambda: TargetIdentity(binding, "authority-a"), native=env.native)
    grant = service.bind({"client_id": "original", "expected_binding": binding, "scopes": ["agents:read"]})
    credentials = grant["subject_id"], grant["subject_capability"]
    service.invoke(*credentials, "authorization_upgrade", {"request_id": "grant-dispatch", "expected_binding": binding,
        "parameters": {"expected_scopes": ["agents:read"],
            "add_scopes": ["agents:dispatch-access:read", "agents:dispatch-access:write"]}})
    return service, credentials, binding


def test_enable_changes_only_target_membership_and_reloads_native_gateway(env):
    from config.settings import get_config
    with server_operator_scope("test-operator", roles=("operator",)):
        before = tomllib.loads(env.config.read_text(encoding="utf-8"))
        params = parameters(env)
        result = env.control.set(params, marker(params))
        after = tomllib.loads(env.config.read_text(encoding="utf-8"))
        expected = deepcopy(before)
        expected["external_agent_gateway"]["allowed_agent_ids"].append("ordinary")
        expected["external_agent_gateway"]["denied_agent_ids"].remove("ordinary")
        assert after == expected
        view = env.control.read("ordinary")
        assert view["dispatchable"] and view["operatorEnabled"] and view["gatewayEnabled"]
        assert result["fingerprint"] == view["publicConfigHash"] and result["verified"]
        assert get_config().external_agent_gateway.allowed_agent_ids == ["a", "b", "c", "d", "e", "f", "g", "ordinary"]
        assert "SECRET" not in json.dumps(view) and "allowed_agent_ids" not in json.dumps(view)
        assert env.control.receipt(params, marker(params)) == result
        assert len(list(env.config.parent.glob("backups/*.json"))) == 1
        assert not list(env.root.rglob("*acknowledgements*"))


def test_disable_keeps_last_allowlist_entry_and_cannot_open_other_agents(env):
    env.config.write_text(env.config.read_text().replace('["a","b","c","d","e","f","g"]', '["ordinary"]'))
    with server_operator_scope("test-operator", roles=("operator",)):
        params = parameters(env, False)
        env.control.set(params, marker(params))
        gateway = tomllib.loads(env.config.read_text())["external_agent_gateway"]
        assert gateway["allowed_agent_ids"] == ["ordinary"]
        assert gateway["denied_agent_ids"] == ["ordinary", "blocked"]
        assert env.control.read("ordinary")["dispatchable"] is False


def test_enable_empty_allowlist_preserves_existing_open_class_semantics(env):
    env.config.write_text(env.config.read_text().replace('["a","b","c","d","e","f","g"]', '[]'))
    with server_operator_scope("test-operator", roles=("operator",)):
        params = parameters(env)
        env.control.set(params, marker(params))
        assert tomllib.loads(env.config.read_text())["external_agent_gateway"]["allowed_agent_ids"] == []


@pytest.mark.parametrize("agent_id", ["team", "rostered", "system", "companion", "hidden", "invalid", "missing", "archived"])
def test_private_team_invalid_and_inactive_agents_cannot_be_enabled(env, agent_id):
    with server_operator_scope("test-operator", roles=("operator",)):
        view = env.control.read(agent_id)
        params = {"agent_id": agent_id, "enabled": True, "expected_public_config_hash": view["publicConfigHash"],
            "expected_eligibility_fingerprint": view["eligibilityFingerprint"]}
        original = env.config.read_bytes()
        with pytest.raises(ManagementError) as failure:
            env.control.set(params, marker(params))
        assert failure.value.code == "AGENT_DISPATCH_ACCESS_DENIED" and env.config.read_bytes() == original
        assert not (env.config.parent / "backups").exists()


def test_personal_classification_does_not_override_protected_native_marker(env):
    env.agents[0]["metadata"]["protected"] = True
    env.write()
    with server_operator_scope("test-operator", roles=("operator",)):
        assert env.control.read("ordinary")["dispatchReason"] == "agent_protected"
        params = parameters(env)
        with pytest.raises(ManagementError, match="AGENT_DISPATCH_ACCESS_DENIED"):
            env.control.set(params, marker(params))


@pytest.mark.parametrize("change", ["public_hash", "qualification", "roster", "gateway_disabled"])
def test_cas_and_gateway_guard_precede_config_write(env, change):
    with server_operator_scope("test-operator", roles=("operator",)):
        params = parameters(env)
        if change == "public_hash": params["expected_public_config_hash"] = "0" * 64
        elif change == "qualification": params["expected_eligibility_fingerprint"] = "0" * 64
        elif change == "roster":
            env.teams[0]["members"].append({"agentId": "ordinary"})
            env.write()
        else:
            env.config.write_text(env.config.read_text().replace("enabled=true", "enabled=false"))
            params = parameters(env)
        original = env.config.read_bytes()
        with pytest.raises(ManagementError) as failure:
            env.control.set(params, marker(params))
        assert failure.value.code == ("GATEWAY_NOT_READY" if change == "gateway_disabled" else "STATE_CONFLICT")
        assert env.config.read_bytes() == original and not (env.config.parent / "backups").exists()


def test_operator_control_and_explicit_scope_upgrade_are_independent(env):
    with pytest.raises(ManagementError, match="OPERATOR_CONTROL_REQUIRED"):
        env.control.read("ordinary")
    with server_operator_scope("reader", roles=("reader",)):
        with pytest.raises(ManagementError, match="OPERATOR_CONTROL_REQUIRED"):
            env.control.read("ordinary")
    service = ManagementService(env.root / "management", identity=lambda: TargetIdentity({"projectId": "p", "instanceId": "i"}, "authority"), native=env.native)
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        service.bind({"client_id": "cannot-auto-upgrade", "expected_binding": {"projectId": "p", "instanceId": "i"},
            "scopes": ["agents:dispatch-access:write"]})
    assert "agents:dispatch-access:write" not in service.binding()["scopes"]


def test_lost_outer_ack_recovers_original_manifest_after_restart_without_second_commit(env, monkeypatch):
    from core.web.services.external_management import service as management
    with server_operator_scope("test-operator", roles=("operator",)):
        service, credentials, binding = authorized(env)
        params = parameters(env)
        execute = management.execute_platform_action
        calls = []
        def lose_ack(*args):
            calls.append("commit")
            execute(*args)
            raise OSError("lost outer response")
        monkeypatch.setattr(management, "execute_platform_action", lose_ack)
        envelope = {"request_id": "original-set", "expected_binding": binding, "parameters": params}
        assert service.invoke(*credentials, access._ACTION, envelope)["status"] == "unknown"
        restarted = ManagementService(service.root, identity=service.identity, native=env.native)
        proof = restarted.reconcile_request(*credentials, access._ACTION, "original-set")
        assert (proof["state"], proof["evidence"]) == ("confirmed", "native_outcome")
        receipt = restarted.receipt(*credentials, access._ACTION, "original-set")
        assert receipt["status"] == "completed" and receipt["asset"]["resourceId"] == "ordinary"
        assert restarted.invoke(*credentials, access._ACTION, envelope) == receipt
        assert calls == ["commit"]
        assert len(list(env.config.parent.glob("backups/*.json"))) == 1


def test_reload_failure_restores_exact_bytes_and_never_proves_success(env, monkeypatch):
    import config.operator_config_transaction as transaction
    original = env.config.read_bytes()
    reload = transaction.reload_config
    calls = []
    def fail_once(path):
        calls.append(path)
        if len(calls) == 1: raise RuntimeError("reload failed")
        return reload(path)
    monkeypatch.setattr(transaction, "reload_config", fail_once)
    with server_operator_scope("test-operator", roles=("operator",)):
        params = parameters(env)
        with pytest.raises(ManagementError, match="OPERATION_UNCONFIRMED"):
            env.control.set(params, marker(params))
        assert env.config.read_bytes() == original and len(calls) == 2
        assert env.control.receipt(params, marker(params)) is None
        with pytest.raises(ManagementError, match="OPERATION_UNCONFIRMED"):
            env.control.set(params, marker(params))
        assert len(calls) == 2


def test_native_target_and_roster_locks_cover_the_actual_config_commit(env, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from core.web.services import team_service
    entered, release, attempting, acquired = Event(), Event(), Event(), Event()
    apply = access.apply_operator_config_transaction
    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return apply(*args, **kwargs)
    monkeypatch.setattr(access, "apply_operator_config_transaction", paused)
    with server_operator_scope("test-operator", roles=("operator",)):
        params = parameters(env)
    def commit():
        with server_operator_scope("test-operator", roles=("operator",)):
            return env.control.set(params, marker(params))
    def roster_change():
        attempting.set()
        with team_service._TEAM_LOCK, env.directory._STATE_LOCK:
            acquired.set()
            env.teams[0]["members"].append({"agentId": "ordinary"})
            env.write()
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(commit)
        assert entered.wait(3)
        mutate = pool.submit(roster_change)
        assert attempting.wait(3) and not acquired.wait(0.05)
        release.set()
        assert pending.result(timeout=3)["verified"] is True
        mutate.result(timeout=3)
    with server_operator_scope("test-operator", roles=("operator",)):
        current = env.control.read("ordinary")
        assert current["dispatchable"] is False and current["dispatchReason"] == "active_team_member"
        assert env.control.receipt(params, marker(params))["verified"] is True


@pytest.mark.parametrize("change", ["revoke", "authority"])
def test_original_receipt_cannot_escape_current_subject_authority(env, change):
    with server_operator_scope("test-operator", roles=("operator",)):
        service, credentials, binding = authorized(env)
        params = parameters(env)
        service.invoke(*credentials, access._ACTION,
            {"request_id": "original", "expected_binding": binding, "parameters": params})
        if change == "revoke":
            path = service.store.path("subjects", credentials[0])
            grant = service.store.read(path)
            grant["revoked"] = True
            service.store.write(path, grant)
        else:
            service.identity = lambda: TargetIdentity(binding, "different-authority")
        with pytest.raises(ManagementError) as failure:
            service.receipt(*credentials, access._ACTION, "original")
        assert failure.value.code == ("SUBJECT_REVOKED" if change == "revoke" else "TARGET_BINDING_CHANGED")


def test_incomplete_manifest_is_unknown_even_when_current_policy_matches(env, monkeypatch):
    import config.operator_config_transaction as transaction
    class AbruptExit(BaseException): pass
    update = transaction._update_transaction_manifest
    def crash_before_complete(artifacts, **kwargs):
        if kwargs["status"] == "completed": raise AbruptExit()
        update(artifacts, **kwargs)
    with server_operator_scope("test-operator", roles=("operator",)):
        params = parameters(env)
        monkeypatch.setattr(transaction, "_update_transaction_manifest", crash_before_complete)
        with pytest.raises(AbruptExit): env.control.set(params, marker(params))
        assert env.control.read("ordinary")["operatorEnabled"] is True
        assert env.control.receipt(params, marker(params)) is None
        with pytest.raises(ManagementError, match="OPERATION_UNCONFIRMED"):
            env.control.set(params, marker(params))


@pytest.mark.parametrize("raw", ['"bad"', '[1]', '[" "]'])
def test_malformed_native_lists_fail_closed_without_empty_list_coercion(env, raw):
    env.config.write_text(env.config.read_text().replace('["a","b","c","d","e","f","g"]', raw))
    original = env.config.read_bytes()
    with server_operator_scope("test-operator", roles=("operator",)):
        with pytest.raises(ManagementError, match="DISPATCH_ACCESS_UNAVAILABLE"):
            env.control.read("ordinary")
    assert env.config.read_bytes() == original
