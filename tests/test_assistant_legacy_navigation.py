"""Model navigation reuses receipt-only SDK reads without authorizing controls."""
import asyncio
import json

import pytest

from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
from core.assistant_runtime.dispatch import DispatchError, DispatchService
from tests.test_assistant_runtime_actions import _through_native_model_budget


@pytest.mark.anyio
async def test_legacy_model_navigation_pages_losslessly_without_replaying_or_leaking(tmp_path):
    project_id = "p" * 160
    observers = [{"observerId": "lob-" + f"{i:064x}", "status": "created",
        "sourceAgentId": "a" * 160, "sourceSessionId": "s" * 160,
        "legacyMessageIds": ["dispatch"], "sourceAuthority": "PRIVATE_PATH"} for i in range(8)]
    dispatches = [{"legacyMessageId": "d" * 159 + str(i), "targetAgentId": "t" * 160,
        "targetSessionId": "s" * 160, "businessTaskStatus": "running",
        "nativeCorrelation": "correlated", "nativeTurnId": "n" * 160,
        "nativeRunId": None, "nativeTaskId": None, "nativeTurnStatus": "completed",
        "nativeRunReason": "runtime_unavailable", "reason": "correlated",
        "receiptCount": 1, "receiptsTruncated": False,
        "receipts": [{"legacyMessageId": "receipt", "taskStatus": "running", "evidenceCount": 2}]} for i in range(8)]
    calls = []
    def factory(root, **kwargs):
        class Client:
            async def diagnostics(self): return {"status": "healthy"}
            async def management_legacy_observers(self):
                calls.append("list")
                return {"observers": observers}
            async def management_legacy_receipts(self, observer_id):
                calls.append(observer_id)
                return {"dispatches": dispatches}
        return Client()
    service = DispatchService(tmp_path / "profile", {project_id: tmp_path / "project"}, client_factory=factory)
    bind_actions(service, asyncio.get_running_loop())
    try:
        for action, field, params, expected in (
            ("legacy_observers", "observers", {}, [x["observerId"] for x in observers]),
            ("legacy_receipts", "dispatches", {"observer_id": observers[0]["observerId"]}, [x["legacyMessageId"] for x in dispatches]),
        ):
            offset, observed = 0, []
            while offset is not None:
                page = await asyncio.to_thread(execute_action, action,
                    {"project_id": project_id, "offset": offset, "limit": 4, **params})
                raw, outcome, facts, rendered = _through_native_model_budget(page)
                assert outcome is None and not facts.truncated
                assert json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
                assert "PRIVATE_" not in raw and str(tmp_path) not in raw
                assert page["readOnly"] and not page["readyForCutover"]
                for row in page[field]:
                    if field == "observers":
                        assert row["actions"] == ["read_receipt"] and row["whitelistedMessageCount"] == 1
                        observed.append(row["observerId"])
                    else:
                        assert "receipts" not in row and row["receiptCount"] == 1
                        assert row["businessTaskStatus"] == "running" and row["nativeTurnStatus"] == "completed"
                        assert row["nativeRunReason"] == "runtime_unavailable"
                        observed.append(row["legacyMessageId"])
                offset = page["nextOffset"]
            assert observed == expected
        before = len(calls)
        for params in ({"project_id": "foreign"}, {"project_id": project_id, "offset": True},
                       {"project_id": project_id, "limit": 5}, {"project_id": project_id, "force": True}):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, "legacy_observers", params)
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "legacy_receipts", {"project_id": project_id, "observer_id": "../private"})
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "legacy_observer_create", {"project_id": project_id})
        assert len(calls) == before
        with pytest.raises(DispatchError):
            await service.management.legacy_observers("foreign")
        assert not (tmp_path / "profile/assistant_management").exists()
    finally:
        unbind_actions(service)
