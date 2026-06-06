from core.runtime_manager import agent_run_store, work_run_store


def test_agent_run_store_persists_public_agent_and_subagent_snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    agent = {
        "agentId": "agent-main",
        "agentCode": "A001",
        "displayName": "Main Agent",
        "primaryMode": "chat",
        "roleKey": "primary",
        "profileId": "primary",
        "promptTemplateId": "prompt-chat-default",
        "toolPolicyId": "tool-default",
        "memoryPolicyId": "memory-default",
        "workspacePath": "workspace/agents/agent-main",
    }
    summary = agent_run_store.result_summary(
        {
            "summary": "Authorization: Bearer sk-sensitive-token\nline2\nline3\nline4\nline5",
            "raw_output": "ignored",
        }
    )

    agent_snapshot = agent_run_store.persist_agent_run_snapshot(
        agent,
        source_run_id="session-turn-1",
        session_id="session-main",
        status="completed",
        summary=summary,
        tool_call_count=2,
        timestamp="2026-05-29T00:00:00Z",
        result={"metadata": {"apiKey": "secret"}, "finishedAt": "2026-05-29T00:00:01Z"},
    )
    sub_snapshot = agent_run_store.persist_sub_agent_run_snapshot(
        parent_run_id="session-turn-1",
        sub_run_id="sub-1",
        status="completed",
        summary="sub result",
        tool_call_count=0,
        timestamp="2026-05-29T00:00:02Z",
        result={"parentAgentId": "agent-main", "parentSessionId": "session-main", "metadata": {"secret": "x"}},
    )

    payload = agent_run_store.list_agent_runs_for_agent("agent-main", limit=5)

    assert agent_snapshot["runKind"] == "agent_run"
    assert agent_snapshot["summary"] == "Authorization: Bearer ***\nline2\nline3\nline4"
    assert "metadata" not in payload["runs"][0]
    assert payload["runs"][0]["summary"] == "Authorization: Bearer ***\nline2\nline3\nline4"
    assert payload["subAgentRuns"][0]["runKind"] == "sub_agent_run"
    assert payload["subAgentRuns"][0]["parentAgentId"] == "agent-main"
    assert "metadata" not in payload["subAgentRuns"][0]
    assert sub_snapshot["runId"].startswith("subagentrun-")


def test_agent_run_store_lists_many_agents_with_one_snapshot_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    alpha = {"agentId": "agent-alpha", "displayName": "Alpha"}
    beta = {"agentId": "agent-beta", "displayName": "Beta"}

    agent_run_store.persist_agent_run_snapshot(
        alpha,
        source_run_id="turn-alpha",
        session_id="session-alpha",
        status="running",
        summary="alpha running",
        tool_call_count=1,
        timestamp="2026-06-06T01:00:00Z",
        result={"updatedAt": "2026-06-06T01:00:00Z"},
    )
    agent_run_store.persist_agent_run_snapshot(
        beta,
        source_run_id="turn-beta",
        session_id="session-beta",
        status="failed",
        summary="beta failed",
        tool_call_count=2,
        timestamp="2026-06-06T01:01:00Z",
        result={"updatedAt": "2026-06-06T01:01:00Z"},
    )
    agent_run_store.persist_sub_agent_run_snapshot(
        parent_run_id="turn-alpha",
        sub_run_id="sub-alpha",
        status="completed",
        summary="sub alpha",
        tool_call_count=0,
        timestamp="2026-06-06T01:02:00Z",
        result={"parentAgentId": "agent-alpha", "parentSessionId": "session-alpha"},
    )

    payload = agent_run_store.list_agent_runs_for_agents(["agent-alpha", "agent-beta"], limit=5)

    assert payload["agentIds"] == ["agent-alpha", "agent-beta"]
    assert payload["agents"]["agent-alpha"]["runs"][0]["status"] == "running"
    assert payload["agents"]["agent-alpha"]["subAgentRuns"][0]["parentAgentId"] == "agent-alpha"
    assert payload["agents"]["agent-beta"]["runs"][0]["status"] == "failed"
    assert payload["agents"]["agent-beta"]["subAgentRuns"] == []
