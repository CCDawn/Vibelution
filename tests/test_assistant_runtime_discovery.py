"""Reference navigation stays complete beyond its former offset ceiling."""
import json
import threading

import pytest

from core.assistant_runtime import actions, discovery_actions, native
from core.web.services import virtual_human_life_service as dialogue


@pytest.fixture
def current(monkeypatch):
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_OFFLINE_MIGRATION", False)
    monkeypatch.setattr(native, "_STOP_REQUESTED", threading.Event())
    monkeypatch.setattr(native, "_AGENT_ID", "assistant")
    monkeypatch.setattr(native, "_SESSION_ID", "session")
    return {"agentId": "assistant", "sessionId": "session"}


def _rows(monkeypatch, action, count, *, long_refs=False):
    suffix = "x" * 100 if long_refs else ""
    if action == "dispatch_list":
        rows = [{"dispatchId": f"d{index}{suffix}", "projectId": "p" + suffix,
                 "nativeTaskId": "task" + suffix, "receipt": {"status": "running"}}
                for index in range(count)]
        class Service:
            def list_dispatches(self):
                return rows
        monkeypatch.setattr(actions, "_binding", (Service(), object(), None))
        return "dispatches", "dispatchId", [row["dispatchId"] for row in rows]
    rows = [{"proposalId": f"p{index}{suffix}", "agentId": "assistant", "status": "pending",
             "preferenceType": "humor", "candidateValue": "off", "sourceTurnId": "turn" + suffix}
            for index in range(count)]
    monkeypatch.setattr(dialogue, "virtual_human_preference_proposals", lambda *_a, **_kw: {"proposals": rows})
    return "proposals", "proposalId", [row["proposalId"] for row in rows]


@pytest.mark.parametrize("action", ["dispatch_list", "preference_proposals"])
def test_next_offset_reaches_every_record_past_4096(monkeypatch, current, action):
    field, reference, expected = _rows(monkeypatch, action, 4120)
    seen, offset = [], 0
    while True:
        page = discovery_actions.execute(action, {"offset": offset, "limit": 20}, current)
        assert 0 < len(page[field]) <= 20
        seen.extend(row[reference] for row in page[field])
        if page["nextOffset"] is None:
            break
        assert page["nextOffset"] == offset + len(page[field])
        offset = page["nextOffset"]
    assert seen == expected
    assert page["total"] == len(expected)
    tail = discovery_actions.execute(action, {"offset": 4116, "limit": 20}, current)
    assert [row[reference] for row in tail[field]] == expected[4116:]
    assert tail["nextOffset"] is None


@pytest.mark.parametrize("action", ["dispatch_list", "preference_proposals"])
def test_reference_pages_survive_native_model_budget(monkeypatch, current, action):
    from tests.test_assistant_runtime_actions import _through_native_model_budget

    field, reference, expected = _rows(monkeypatch, action, 23, long_refs=True)
    seen, offset = [], 0
    while True:
        page = discovery_actions.execute(action, {"offset": offset, "limit": 20}, current)
        raw, outcome, facts, rendered = _through_native_model_budget(page)
        assert outcome is None and not facts.truncated
        assert json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
        seen.extend(row[reference] for row in page[field])
        if page["nextOffset"] is None:
            break
        offset = page["nextOffset"]
    assert seen == expected


def test_management_request_discovery_is_scoped_read_only_and_strict(monkeypatch, current):
    from types import SimpleNamespace

    calls = []
    def listing(**query):
        calls.append(query)
        return {"requests": [{"projectId": "p", "action": "team_run", "requestId": "original"}],
                "nextOffset": None, "total": 1}
    monkeypatch.setattr(actions, "_binding", (SimpleNamespace(management=SimpleNamespace(list_requests=listing)), object(), None))
    contract = discovery_actions.contracts()["management_requests"]
    assert contract["governed"] is False
    assert contract["parameters"]["additionalProperties"] is False
    result = discovery_actions.execute("management_requests", {"action": "team_run", "offset": 4116}, current)
    assert result["requests"][0]["requestId"] == "original"
    assert calls == [{"project_id": None, "action": "team_run", "offset": 4116, "limit": 10}]
    for query in ({"limit": 21}, {"offset": True}, {"action": "arbitrary"}, {"project_root": "/private"}):
        with pytest.raises(ValueError):
            discovery_actions.execute("management_requests", query, current)
    with pytest.raises(ValueError):
        discovery_actions.execute("management_requests", {}, {**current, "agentId": "foreign"})
    assert len(calls) == 1


def test_management_request_directory_is_reachable_through_canonical_action(monkeypatch, current):
    from types import SimpleNamespace

    calls = []
    def listing(**query):
        calls.append(query)
        return {"requests": [], "nextOffset": None, "total": 0}
    service = SimpleNamespace(management=SimpleNamespace(list_requests=listing))
    monkeypatch.setattr(actions, "_binding", (service, object(), None))
    index = actions.execute_action("index", {"query": "management_requests"})
    assert [row["action"] for row in index["actions"]] == ["management_requests"]
    detail = actions.execute_action("describe", {"action": "management_requests"})
    assert detail["governed"] is False
    assert detail["parameters"]["additionalProperties"] is False
    result = actions.execute_action("management_requests", {"project_id": "p", "action": "team_run"}, runtime=current)
    assert result["requests"] == []
    assert calls == [{"project_id": "p", "action": "team_run", "offset": 0, "limit": 10}]
