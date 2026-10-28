import json
import os
import subprocess
import threading
from pathlib import Path
from queue import Queue

import pytest

from core.agent_plugins.personal_affairs.service import PersonalAffairsError, PersonalAffairsService
from core.assistant_runtime.reminder_source_identity import observe_reminder_source
from core.infrastructure.reminder_source_mutex import trusted_reminder_source_mutex_key
from tests.test_assistant_history_preview import setup_preview  # noqa: F401


@pytest.mark.skipif(os.name != "nt", reason="Windows source mutex")
def test_real_source_write_refuses_busy_ledger_and_recovers(setup_preview, monkeypatch):
    from core.web.services import personal_affairs_service, personal_assistant_service
    from tools import personal_affairs_tools
    addon = os.environ.get("VIBELUTION_MUTEX_TEST_ADDON", "")
    if not addon or not Path(addon).is_file():
        pytest.skip("requires an isolated test addon")
    dispatch, workspace, _ = setup_preview
    registry = workspace / "agents/agents.json"
    rows = json.loads(registry.read_text(encoding="utf-8"))
    rows["agents"][0]["primaryMode"] = "general"
    registry.write_text(json.dumps(rows), encoding="utf-8")
    root = dispatch._admitted_projects()["registered:1"]
    agents = {"agent-pa": {"agentId": "agent-pa", "status": "active", "roleKey": "personal_assistant",
                            "primaryMode": "general", "metadata": {"personalAssistantProfile": "personal_assistant_v1"}},
              "other": {"agentId": "other"}}
    monkeypatch.setattr(personal_affairs_service, "is_launcher_assistant_process", lambda: False)
    monkeypatch.setattr(personal_assistant_service, "profile_agent", lambda: agents["agent-pa"])
    service = PersonalAffairsService(root, agent_loader=lambda agent_id, **_: agents.get(agent_id),
                                    source_mutex_guard=personal_affairs_service._is_trusted_legacy_assistant)
    monkeypatch.setattr(personal_affairs_tools, "_service", lambda: service)
    monkeypatch.setattr(personal_affairs_tools, "_runtime_context", lambda: {"agentId": "agent-pa"})
    first = service.add_item("agent-pa", kind="todo", title="initial")
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as source:
        key = trusted_reminder_source_mutex_key(source)
        env = {**os.environ, "MUTEX_TEST_ADDON": addon, "MUTEX_TEST_KEY": key}
        script = "const a=require(process.env.MUTEX_TEST_ADDON),h=a.tryAcquireReminderMutex(process.env.MUTEX_TEST_KEY); if(!h)process.exit(2); console.log('held'); process.stdin.once('data',()=>{a.releaseReminderMutex(h.handle);process.exit(0)})"
        child = subprocess.Popen(["node", "-e", script], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            ready = Queue()
            threading.Thread(target=lambda: ready.put(child.stdout.readline()), daemon=True).start()
            assert ready.get(timeout=10).strip() == "held"
            before = service.list_items("agent-pa")["items"]
            with pytest.raises(PersonalAffairsError, match="同步占用"):
                service.add_item("agent-pa", kind="todo", title="blocked")
            tool_result = json.loads(personal_affairs_tools.personal_affairs_tool(action="add", title="blocked"))
            assert tool_result["ok"] is False and "同步占用" in tool_result["message"]
            for action in (lambda: service.complete_item("agent-pa", item_id=first["itemId"]),
                           lambda: service.cancel_item("agent-pa", item_id=first["itemId"]),
                           lambda: service.reopen_item("agent-pa", item_id=first["itemId"]),
                           lambda: service.set_due("agent-pa", item_id=first["itemId"], due_at="2026-10-29")):
                with pytest.raises(PersonalAffairsError, match="同步占用"):
                    action()
            assert service.list_items("agent-pa")["items"] == before
            assert service.add_item("other", kind="todo", title="unrelated")["title"] == "unrelated"
            child.stdin.write("release\n"); child.stdin.flush()
            assert child.wait(timeout=10) == 0
            assert service.add_item("agent-pa", kind="todo", title="after")["title"] == "after"
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=10)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream:
                    stream.close()


def test_only_the_verified_workbench_assistant_receives_mutex(monkeypatch):
    from types import SimpleNamespace
    from core.web.services import personal_affairs_service, personal_assistant_service
    agent = {"agentId": "pa", "status": "active", "roleKey": "personal_assistant", "primaryMode": "general",
             "metadata": {"personalAssistantProfile": "personal_assistant_v1"}}
    monkeypatch.setattr(personal_affairs_service, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(personal_affairs_service, "is_launcher_assistant_process", lambda: False)
    monkeypatch.setattr(personal_assistant_service, "profile_agent", lambda: agent)
    assert personal_affairs_service._is_trusted_legacy_assistant(agent)
    assert not personal_affairs_service._is_trusted_legacy_assistant({"agentId": "ordinary"})
    with pytest.raises(PersonalAffairsError):
        personal_affairs_service._is_trusted_legacy_assistant({**agent, "agentId": "forged"})
    monkeypatch.setattr(personal_affairs_service, "is_launcher_assistant_process", lambda: True)
    assert not personal_affairs_service._is_trusted_legacy_assistant(agent)
