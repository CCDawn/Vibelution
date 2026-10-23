from core.runtime_manager import agent_run_store, work_run_store


def test_result_status_normalizes_aliases_and_keeps_activity_separate():
    assert agent_run_store.result_status({"status": "succeeded"}) == "completed"
    assert agent_run_store.result_status({"status": "stopped_by_user"}) == "stopped"
    assert agent_run_store.result_status({"currentPhase": "reading"}) == "running"
    assert agent_run_store.result_status({"status": "future_state"}) == "unknown"


def test_agent_run_snapshot_separates_status_phase_and_terminal_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    fields = {"agent": {"agentId": "agent"}, "source_run_id": "turn", "session_id": "session", "summary": "",
              "tool_call_count": 0, "timestamp": "2026-10-23T00:00:00Z"}
    running = agent_run_store.persist_agent_run_snapshot(**fields, status="running", result={"currentPhase": "reading"})
    assert running["status"] == "running"
    assert running["currentPhase"] == "reading"
    stopped = agent_run_store.persist_agent_run_snapshot(**fields, status="stopped_by_user", result={"currentPhase": "reading"})
    assert stopped["status"] == "stopped"
    assert stopped["currentPhase"] == ""
    assert stopped["terminalReason"] == "stopped_by_user"
    assert stopped["finishedAt"]


def test_unknown_agent_run_is_not_finished_or_successful(tmp_path, monkeypatch):
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    snapshot = agent_run_store.persist_sub_agent_run_snapshot(
        parent_run_id="parent", sub_run_id="child", status="future_state", summary="", tool_call_count=0,
        timestamp="2026-10-23T00:00:00Z", result={},
    )
    assert snapshot["status"] == "unknown"
    assert snapshot["rawStatus"] == "future_state"
    assert not snapshot["endedAt"]
    assert snapshot["runId"] in work_run_store.WorkRunStore(root=work_run_store.WORK_RUNS_DIR).load_active_run_ids("sub_agent_run")


def test_public_run_activity_adds_canonical_fields_without_changing_legacy_wire():
    snapshot = {"runId": "legacy", "status": "stopped_by_user", "currentPhase": "stopped_by_user"}
    projected = agent_run_store._public_snapshot(snapshot, agent_run_store._PUBLIC_AGENT_RUN_KEYS)
    assert projected["status"] == projected["currentPhase"] == "stopped_by_user"
    assert projected["executionStatus"] == "stopped"
    assert projected["activityPhase"] == ""
    assert projected["terminalReason"] == "stopped_by_user"
    assert snapshot == {"runId": "legacy", "status": "stopped_by_user", "currentPhase": "stopped_by_user"}


def test_normalized_result_keeps_original_stop_cause_and_clears_stale_end(tmp_path, monkeypatch):
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    result = {"status": "stopped_by_user"}
    fields = {"agent": {"agentId": "agent"}, "source_run_id": "turn", "session_id": "session", "summary": "",
              "tool_call_count": 0, "timestamp": "2026-10-23T00:00:00Z"}
    stopped = agent_run_store.persist_agent_run_snapshot(**fields, status=agent_run_store.result_status(result), result=result)
    assert stopped["terminalReason"] == "stopped_by_user"
    public = agent_run_store.list_agent_runs_for_agent("agent")["runs"][0]
    assert public["status"] == "stopped_by_user"
    assert public["executionStatus"] == "stopped"
    running = agent_run_store.persist_agent_run_snapshot(**fields, status="running", result={"finishedAt": "old", "currentPhase": "reading"})
    assert not running["finishedAt"]
    assert not running["terminalReason"]


def test_legacy_force_stop_writer_cannot_reactivate_stale_alias_or_terminal_cause():
    snapshot = {
        "status": "stopped", "currentPhase": "stopped", "rawStatus": "running",
        "runtimeStatus": "force_stopped", "terminalReason": "success",
    }
    public = agent_run_store._public_snapshot(snapshot, agent_run_store._PUBLIC_AGENT_RUN_KEYS)
    assert public["status"] == public["executionStatus"] == "stopped"
    assert public["activityPhase"] == ""
    assert public["terminalReason"] == "force_stopped"

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


def test_agent_run_store_uses_bounded_recent_work_run_reads(monkeypatch):
    calls = []

    class FakeStore:
        def list_snapshots(self, run_kind, *, limit=None):
            calls.append((run_kind, limit))
            if run_kind == agent_run_store.AGENT_RUN_KIND:
                return [
                    {
                        "runId": "agentrun-alpha",
                        "runKind": agent_run_store.AGENT_RUN_KIND,
                        "agentId": "agent-alpha",
                        "status": "completed",
                        "updatedAt": "2026-06-08T00:00:00Z",
                    }
                ]
            return []

    monkeypatch.setattr(agent_run_store, "_store", lambda: FakeStore())

    payload = agent_run_store.list_agent_runs_for_agents(["agent-alpha", "agent-beta"], limit=6)

    assert payload["agents"]["agent-alpha"]["runs"][0]["runId"] == "agentrun-alpha"
    assert calls == [
        (agent_run_store.AGENT_RUN_KIND, 48),
        (agent_run_store.SUB_AGENT_RUN_KIND, 48),
    ]
