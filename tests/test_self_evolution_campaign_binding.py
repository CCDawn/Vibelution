"""Campaign role authority remains tied to the existing live flow binding."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
from contextlib import contextmanager

import pytest

from core.web.services.self_evolution_local_integration import LocalIntegrationError


def module():
    return importlib.import_module("core.web.services.self_evolution_campaign_binding")


def test_legacy_context_does_not_resolve_a_flow(monkeypatch):
    from core.web.services.team_workflow.generic import store

    monkeypatch.setattr(store, "path", lambda *args: pytest.fail("Legacy context resolved a flow"))
    context = {"request": {"localIntegration": {"teamId": "team-a"}}}
    grant = {"expiresAt": "2030-01-01T00:00:00+00:00"}
    assert module().campaign_bindings(context) is None
    assert module().bind_campaign_authority(context, grant) == grant
    with module().binding_guard(context):
        pass


@pytest.fixture
def bound(monkeypatch, tmp_path):
    helper = module()
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
    policy = {"bindingId": "binding-1", "expiresAt": expiry,
              "assistantAgentId": "assistant", "directorAgentId": "director",
              "developerAgentId": "developer", "reviewerAgentId": "reviewer"}
    flow = {"id": "diagnosis", "failureRecovery": policy}
    status = {"teamId": "team-a", "flowId": "diagnosis", "status": "ready", **policy}
    roles = {"observer": {"agentId": "director"}, "executor": {"agentId": "developer"},
             "reviewer": {"agentId": "reviewer"}}
    monkeypatch.setattr(helper.store, "path", lambda team, kind, fid: tmp_path / team / (fid + ".json"))
    monkeypatch.setattr(helper.store, "read", lambda path: deepcopy(flow))
    monkeypatch.setattr(helper.binding, "get_recovery_binding", lambda *args: deepcopy(status))
    monkeypatch.setattr(helper.code_repair, "bound_role_bindings", lambda source: deepcopy(roles))
    context = {"runId": "campaign-1", "request": {"roleBindingFlowId": "diagnosis",
               "localIntegration": {"teamId": "team-a"}}}
    grant = {"teamId": "team-a", "principals": deepcopy(roles),
             "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    return helper, context, grant, flow, status, roles


def test_existing_flow_roles_are_frozen_and_expiry_cannot_expand(bound):
    helper, context, grant, flow, _, roles = bound
    assert helper.campaign_bindings(context) == roles
    issued = helper.bind_campaign_authority(context, grant)
    assert issued["roleBindingSource"] == "campaign_role_binding_v1"
    assert issued["campaignRoleBinding"]["bindingId"] == "binding-1"
    assert issued["expiresAt"] == flow["failureRecovery"]["expiresAt"]
    context["localIntegrationAuthorization"] = issued
    assert helper.campaign_bindings(context) == roles
    assert "campaignRoleBinding" not in grant


def test_child_uses_canonical_parent_binding_not_global_or_caller_ids(bound, monkeypatch):
    from core.web.services import self_evolution_campaign_service as campaigns

    helper, parent, grant, _, _, roles = bound
    parent["localIntegrationAuthorization"] = helper.bind_campaign_authority(parent, grant)
    monkeypatch.setattr(campaigns, "_load", lambda store, campaign_id: deepcopy(parent))
    child = {"_campaignSource": {"storeRoot": ".", "campaignId": "campaign-1"},
             "request": {"localIntegration": {"teamId": "team-a"}},
             "localIntegrationAuthorization": deepcopy(parent["localIntegrationAuthorization"])}
    child["request"]["directorAgentId"] = "forged"
    assert helper.campaign_bindings(child) == roles
    child["request"]["localIntegration"]["teamId"] = "other"
    with pytest.raises(LocalIntegrationError):
        helper.campaign_bindings(child)


@pytest.mark.parametrize("mutation", ["rebind", "unbound", "expired", "unavailable", "missing_request", "tampered_ref"])
def test_authority_changes_block_instead_of_falling_back_to_global(bound, mutation):
    helper, context, grant, flow, status, _ = bound
    context["localIntegrationAuthorization"] = helper.bind_campaign_authority(context, grant)
    if mutation == "rebind":
        status["bindingId"] = flow["failureRecovery"]["bindingId"] = "binding-2"
    elif mutation in {"unbound", "unavailable"}:
        status["status"] = mutation
    elif mutation == "expired":
        status["expiresAt"] = flow["failureRecovery"]["expiresAt"] = "2000-01-01T00:00:00+00:00"
    elif mutation == "missing_request":
        context["request"].pop("roleBindingFlowId")
    else:
        context["localIntegrationAuthorization"]["campaignRoleBinding"]["teamId"] = "other"
    with pytest.raises(LocalIntegrationError):
        helper.campaign_bindings(context)


def test_first_issuance_rejects_changed_principals(bound):
    helper, context, grant, *_ = bound
    grant["principals"]["executor"]["agentId"] = "old-global-executor"
    with pytest.raises(LocalIntegrationError):
        helper.bind_campaign_authority(context, grant)


def test_binding_flow_lock_remains_held_through_merge(bound, monkeypatch):
    helper, context, grant, *_ = bound
    context["localIntegrationAuthorization"] = helper.bind_campaign_authority(context, grant)
    events = []

    @contextmanager
    def locked(path):
        events.append("locked")
        yield
        events.append("unlocked")

    monkeypatch.setattr(helper.store, "locked", locked)
    original = helper.binding.get_recovery_binding

    def read_status(*args):
        assert events == ["locked"]
        return original(*args)

    monkeypatch.setattr(helper.binding, "get_recovery_binding", read_status)
    with helper.binding_guard(context):
        assert events == ["locked"]
    assert events == ["locked", "unlocked"]
