"""Launcher dispatch-access reads stay target-only and bound to current authority."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from core.assistant_runtime.actions import _management_contracts, _project_read_contracts
from core.assistant_runtime.dispatch import DispatchError
from core.assistant_runtime.management import ManagementAdapter
from core.assistant_runtime.platform_approval import platform_management_approval_summary


READ = {"project_id": "project-a", "agent_id": "agent-a"}
WRITE = {**READ, "request_id": "access-a", "enabled": True,
    "expected_public_config_hash": "a" * 64, "expected_eligibility_fingerprint": "b" * 64}


def test_launcher_dispatch_access_contract_is_target_only_and_explicitly_governed():
    read = _project_read_contracts()["agent_dispatch_access_get"]
    assert read.model_validate(READ).model_dump() == READ
    with pytest.raises(ValidationError):
        read.model_validate({**READ, "document_pointer": "/config"})
    write, contract = _management_contracts()["agent_dispatch_access_set"]
    assert write.model_validate(WRITE).model_dump() == WRITE
    assert contract["governed"] is True
    assert contract["scope"] == "agents:dispatch-access:write"
    for patch in ({"enabled": "true"}, {"allowed_agent_ids": []}, {"force": True},
                  {"config_path": "private.toml"}, {"expected_public_config_hash": "stale"}):
        with pytest.raises(ValidationError):
            write.model_validate({**WRITE, **patch})


@pytest.mark.parametrize("enabled", [True, False])
def test_dispatch_access_preview_binds_exact_membership_and_both_cas(enabled):
    values = {**WRITE, "enabled": enabled}
    summary = platform_management_approval_summary("agent_dispatch_access_set", values)
    assert summary["assistantTargets"] == {key: value for key, value in values.items() if key != "enabled"}
    assert summary["assistantDelta"] == {"enabled": enabled}
    assert summary["assistantChangedFields"] == ["enabled"]
    assert summary["assistantDetailsOmitted"] is False
    assert summary["assistantContentOmitted"] is False


@pytest.mark.anyio
@pytest.mark.parametrize("authority_changes", [False, True])
async def test_dispatch_access_read_uses_original_native_target_and_drops_rebound_results(tmp_path, authority_changes):
    projects = {"project-a": tmp_path / "project"}
    calls = []

    async def native_read(operation, **parameters):
        calls.append((operation, parameters))
        if authority_changes:
            projects["project-a"] = tmp_path / "another-project"
        return {"agentId": "agent-a", "gatewayEnabled": True, "operatorEnabled": False,
            "dispatchable": False, "dispatchReason": "operator_disabled", "publicConfigHash": "a" * 64,
            "eligibilityFingerprint": "b" * 64, "untrustedContent": True}

    async def call(project_id, reader):
        assert project_id == "project-a"
        return await reader(SimpleNamespace(management_asset=native_read))

    adapter = ManagementAdapter(tmp_path, projects, call)
    if authority_changes:
        with pytest.raises(DispatchError) as error:
            await adapter.asset("project-a", "dispatch-access", agent_id="agent-a")
        assert error.value.code == "PROJECT_BINDING_CHANGED"
    else:
        result = await adapter.asset("project-a", "dispatch-access", agent_id="agent-a")
        assert result["agentId"] == "agent-a" and result["projectId"] == "project-a"
        assert result["operatorEnabled"] is False
    assert calls == [("dispatch-access", {"agent_id": "agent-a"})]
