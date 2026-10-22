# -*- coding: utf-8 -*-
"""Subagent orphan governance regression tests.

K-1: spawn timeout budget is clamped to the executor budget, and the
executor timeout path physically terminates the spawned child process tree
instead of only cancelling an un-cancellable future.

K-3: address records left ``running`` by a crashed parent are failed by the
startup sweep, and an orphan child pid is only terminated when its cmdline
provably matches this project's agent.py subagent signature.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

import tools.agent_tools as agent_tools
from core.orchestration import subagent_address
from core.orchestration.subagent_address import (
    open_subagent_address,
    sweep_stale_subagent_addresses,
)
from tools.agent_tools import (
    SPAWN_AGENT_EXECUTOR_BUDGET_SECONDS,
    clamp_spawn_timeout,
)


# ── 测试替身 ────────────────────────────────────────────────────────────────


class _FakePipe:
    def readline(self) -> str:
        return ""

    def close(self) -> None:
        return None


class _FakeProcess:
    def __init__(self, pid: int = 424242):
        self.pid = pid
        self.stdout = _FakePipe()
        self.stderr = _FakePipe()
        self.returncode = 0
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.terminated = True


def _write_running_record(
    tmp_path,
    monkeypatch,
    *,
    agent_id: str = "subagent-inspect-d1-orphan",
    pid: int | None = 12345,
    opened_at: str | None = None,
) -> dict:
    monkeypatch.setenv("VIBELUTION_SUBAGENT_ADDRESS_ROOT", str(tmp_path / "addresses"))
    record = {
        "agentId": agent_id,
        "subRunId": agent_id,
        "parentSessionId": "parent-1",
        "parentTurnId": "turn-parent",
        "childSessionId": "child-1",
        "projectRoot": str(tmp_path),
        "status": "running",
        "previousStatus": "",
        "resumeClaimed": False,
        "pending": [],
        "activeMessages": [],
        "taskType": "inspect",
        "summary": "",
        "pid": pid,
        "openedAt": opened_at or datetime.now(timezone.utc).isoformat(),
    }
    subagent_address._save_record(record)
    return record


# ── K-1: spawn 超时预算 clamp ───────────────────────────────────────────────


class TestSpawnTimeoutClamp:
    def test_clamp_bounds_model_timeout_to_executor_budget(self):
        assert clamp_spawn_timeout(99999) == SPAWN_AGENT_EXECUTOR_BUDGET_SECONDS == 150
        assert clamp_spawn_timeout(120) == 120
        assert clamp_spawn_timeout(10) == 10
        assert clamp_spawn_timeout(150) == 150

    def test_clamp_falls_back_to_default_on_invalid_values(self):
        assert clamp_spawn_timeout(0) == 120
        assert clamp_spawn_timeout(-5) == 120
        assert clamp_spawn_timeout("abc") == 120
        assert clamp_spawn_timeout(None) == 120

    def test_executor_budget_is_shared_constant(self):
        from core.infrastructure.tool_executor import ToolExecutor

        executor = ToolExecutor()
        assert executor._timeout_map["spawn_agent_tool"] == SPAWN_AGENT_EXECUTOR_BUDGET_SECONDS

    def test_resolve_timeout_no_longer_stretches_unbounded(self):
        from core.infrastructure.tool_executor import ToolExecutor

        executor = ToolExecutor()
        assert executor._resolve_timeout("spawn_agent_tool", {}) == 150
        assert executor._resolve_timeout("spawn_agent_tool", {"timeout": 120}) == 150
        assert executor._resolve_timeout("spawn_agent_tool", {"timeout": 600}) == 165
        assert executor._resolve_timeout("spawn_agent_tool", {"timeout": 999999}) == 165

    def test_spawn_agent_reports_clamped_timeout_in_started_event(self, monkeypatch):
        events = []
        monkeypatch.setattr(agent_tools, "_record_subagent_scene_event", lambda **kw: events.append(kw))
        monkeypatch.setattr(agent_tools.subprocess, "Popen", lambda *a, **k: _FakeProcess())

        result = json.loads(agent_tools.spawn_agent(task="分析日志", timeout=99999))

        started = [e for e in events if e.get("event_code") == "subagent.run.started"]
        assert started, "spawn 应发布 started 场景事件"
        assert started[0]["fields"]["timeoutSeconds"] == 150
        assert result["subRunId"]


# ── K-1: 执行器超时物理终止子进程树 ─────────────────────────────────────────


class TestExecutorTimeoutTermination:
    @pytest.fixture
    def executor(self):
        from core.infrastructure.tool_executor import ToolExecutor

        return ToolExecutor()

    def test_executor_timeout_terminates_registered_spawn_process(self, executor, monkeypatch):
        terminated: list[int] = []
        release = threading.Event()
        monkeypatch.setattr(agent_tools, "_terminate_process_tree", lambda p: terminated.append(p.pid))

        class _HangingProcess:
            pid = 515151

            def poll(self):
                return None

            def terminate(self):
                terminated.append(self.pid)

            def kill(self):
                terminated.append(self.pid)

            def wait(self, timeout=None):
                return 0

        captured: dict = {}

        def fake_spawn(task: str = "", timeout: int = 120, _cancel_checker=None) -> str:
            captured["checker"] = _cancel_checker
            agent_tools._register_active_spawn_process(
                "subagent-test-hang", _HangingProcess(), cancel_checker=_cancel_checker
            )
            release.wait(timeout=15)
            return "{}"

        monkeypatch.setitem(executor._tool_map, "spawn_agent_tool", fake_spawn)
        monkeypatch.setitem(executor._timeout_map, "spawn_agent_tool", 1)
        try:
            result, _action = executor.execute(
                "spawn_agent_tool", {"task": "hang", "_internal_delegate": True}
            )
        finally:
            release.set()

        assert "[超时]" in result
        assert 515151 in terminated, "executor 超时必须物理终止注册的子进程树"
        assert captured["checker"] is not None, "超时归属过滤依赖工具收到的 cancel checker"
        assert "subagent-test-hang" not in agent_tools._ACTIVE_SPAWN_PROCESSES

    def test_timeout_hook_spares_other_turns_spawn(self, executor, monkeypatch):
        terminated: list[int] = []
        release = threading.Event()
        monkeypatch.setattr(agent_tools, "_terminate_process_tree", lambda p: terminated.append(p.pid))

        class _OtherTurnProcess:
            pid = 616161

            def poll(self):
                return None

            def terminate(self):
                terminated.append(self.pid)

            def kill(self):
                terminated.append(self.pid)

            def wait(self, timeout=None):
                return 0

        def fake_spawn(task: str = "", timeout: int = 120, _cancel_checker=None) -> str:
            agent_tools._register_active_spawn_process(
                "subagent-test-other-turn",
                _OtherTurnProcess(),
                cancel_checker=lambda: "other_turn",
            )
            release.wait(timeout=15)
            return "{}"

        monkeypatch.setitem(executor._tool_map, "spawn_agent_tool", fake_spawn)
        monkeypatch.setitem(executor._timeout_map, "spawn_agent_tool", 1)
        try:
            result, _action = executor.execute(
                "spawn_agent_tool", {"task": "hang", "_internal_delegate": True}
            )
        finally:
            release.set()
            agent_tools._unregister_active_spawn_process("subagent-test-other-turn")

        assert "[超时]" in result
        assert terminated == [], "其他归属的子进程不允许被本次超时误杀"

    def test_terminate_active_subagent_processes_without_owner_kills_all(self, monkeypatch):
        terminated: list[int] = []
        monkeypatch.setattr(agent_tools, "_terminate_process_tree", lambda p: terminated.append(p.pid))
        process = _FakeProcess()
        process.returncode = None  # 模拟仍在运行
        agent_tools._register_active_spawn_process("subagent-test-all", process)
        try:
            count = agent_tools.terminate_active_subagent_processes("unit_test")
        finally:
            agent_tools._unregister_active_spawn_process("subagent-test-all")

        assert count == 1
        assert terminated == [424242]
        assert "subagent-test-all" not in agent_tools._ACTIVE_SPAWN_PROCESSES

    def test_send_message_tool_threads_cancel_checker_into_resume(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VIBELUTION_SUBAGENT_ADDRESS_ROOT", str(tmp_path / "addresses"))
        record = {
            "agentId": "subagent-inspect-d1-abc",
            "subRunId": "subagent-inspect-d1-abc",
            "parentSessionId": "parent-1",
            "parentTurnId": "turn-parent",
            "childSessionId": "child-1",
            "projectRoot": str(tmp_path),
            "status": "completed",
            "previousStatus": "",
            "resumeClaimed": False,
            "pending": [],
            "activeMessages": [],
            "taskType": "inspect",
            "summary": "",
        }
        subagent_address._save_record(record)

        captured: dict = {}
        original_spawn = agent_tools.spawn_agent

        def spy_spawn(*args, **kwargs):
            captured["cancel_checker"] = kwargs.get("_cancel_checker")
            captured["resume_agent_id"] = kwargs.get("resume_agent_id")
            return original_spawn(*args, **kwargs)

        monkeypatch.setattr(agent_tools, "spawn_agent", spy_spawn)
        monkeypatch.setattr(agent_tools.subprocess, "Popen", lambda *a, **k: _FakeProcess())

        payload = json.loads(
            agent_tools.continue_subagent(
                to="subagent-inspect-d1-abc",
                message="接着做",
                _cancel_checker=lambda: "",
            )
        )

        assert payload.get("status") not in {"error"}, payload
        assert captured["cancel_checker"] is not None, "续聊路径必须透传 cancel checker"
        assert captured["resume_agent_id"] == "subagent-inspect-d1-abc"

    def test_send_message_tool_is_visible_and_accepts_cancel_checker(self):
        from core.infrastructure.tool_executor import _tool_accepts_cancel_checker
        from tools.Key_Tools import create_key_tools

        tools = {tool.name: tool.func for tool in create_key_tools()}
        assert "send_message_tool" in tools
        assert _tool_accepts_cancel_checker(tools["send_message_tool"]) is True


# ── K-3: 启动清扫 running 孤儿记录 ──────────────────────────────────────────


class TestStartupSweep:
    def test_sweep_fails_running_record_with_dead_pid(self, tmp_path, monkeypatch):
        record = _write_running_record(tmp_path, monkeypatch, pid=12345)
        monkeypatch.setattr(subagent_address, "is_pid_alive", lambda pid: False)

        swept = sweep_stale_subagent_addresses()

        assert len(swept) == 1
        assert swept[0]["agentId"] == record["agentId"]
        assert swept[0]["reason"] == "process_dead"
        updated = subagent_address.get_subagent_address(record["agentId"])
        assert updated["status"] == "failed"
        assert updated["failReason"] == "process_dead"
        assert updated["resumeClaimed"] is False

    def test_sweep_leaves_live_recent_running_record_alone(self, tmp_path, monkeypatch):
        record = _write_running_record(tmp_path, monkeypatch, pid=12345)
        monkeypatch.setattr(subagent_address, "is_pid_alive", lambda pid: True)

        swept = sweep_stale_subagent_addresses()

        assert swept == []
        assert subagent_address.get_subagent_address(record["agentId"])["status"] == "running"

    def test_sweep_fails_overaged_running_record_even_with_live_pid(
        self, tmp_path, monkeypatch
    ):
        opened_at = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        record = _write_running_record(tmp_path, monkeypatch, pid=12345, opened_at=opened_at)
        monkeypatch.setattr(subagent_address, "is_pid_alive", lambda pid: True)
        # cmdline 不匹配项目子代理签名：记录判 failed，但进程绝不被终止。
        monkeypatch.setattr(
            subagent_address,
            "_cmdline_matches_project_subagent",
            lambda pid, root: False,
        )

        swept = sweep_stale_subagent_addresses()

        assert len(swept) == 1
        assert swept[0]["reason"] == "stale_running_timeout"
        assert swept[0]["terminatedPid"] is None
        assert subagent_address.get_subagent_address(record["agentId"])["status"] == "failed"

    def test_sweep_fails_legacy_record_without_pid_via_age(self, tmp_path, monkeypatch):
        record = _write_running_record(tmp_path, monkeypatch, pid=None)
        # 无 pid 且未超龄：不动。
        assert sweep_stale_subagent_addresses() == []
        # 无 pid 但超龄：判 failed（150s 预算下 running 超时只可能是孤儿）。
        swept = sweep_stale_subagent_addresses(max_age_seconds=1, now_epoch=time.time() + 3600)

        assert len(swept) == 1
        assert swept[0]["reason"] == "stale_running_timeout"
        assert subagent_address.get_subagent_address(record["agentId"])["status"] == "failed"

    def test_sweep_terminates_orphan_child_with_matching_cmdline(
        self, tmp_path, monkeypatch
    ):
        opened_at = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        record = _write_running_record(
            tmp_path, monkeypatch, pid=777, opened_at=opened_at
        )
        monkeypatch.setattr(subagent_address, "is_pid_alive", lambda pid: True)

        terminated: list[int] = []

        class _FakePsutilProcess:
            def __init__(self, pid: int):
                self.pid = pid

            def cmdline(self):
                return [
                    sys.executable,
                    "C:/proj/agent.py",
                    "--prompt",
                    "p",
                    "--single-turn",
                    "--subagent-json",
                ]

            def children(self, recursive=False):
                return []

            def terminate(self):
                terminated.append(self.pid)

            def wait(self, timeout=None):
                return 0

            def kill(self):
                terminated.append(self.pid)

        class _FakePsutilModule:
            Process = _FakePsutilProcess
            NoSuchProcess = Exception

        monkeypatch.setitem(sys.modules, "psutil", _FakePsutilModule)
        monkeypatch.setattr(
            subagent_address,
            "_cmdline_matches_project_subagent",
            lambda pid, root: True,
        )
        # 后代终止走共享 inventory：打桩避免 fake pid 触碰真实进程。
        descendant_targets: list[int] = []
        monkeypatch.setattr(
            "core.runtime_manager.process_inventory.terminate_process_descendants",
            lambda pid, **k: descendant_targets.append(pid),
        )

        swept = sweep_stale_subagent_addresses()

        assert len(swept) == 1
        assert swept[0]["terminatedPid"] == 777
        assert terminated == [777]
        assert subagent_address.get_subagent_address(record["agentId"])["status"] == "failed"

    def test_sweep_preserves_pending_and_drains_active_messages(
        self, tmp_path, monkeypatch
    ):
        record = _write_running_record(tmp_path, monkeypatch, pid=12345)
        with subagent_address._LOCK:
            fresh = subagent_address.get_subagent_address(record["agentId"])
            fresh["resumeClaimed"] = True
            fresh["activeMessages"] = ["被中断的续聊正文"]
            subagent_address._save_record(fresh)
        monkeypatch.setattr(subagent_address, "is_pid_alive", lambda pid: False)

        sweep_stale_subagent_addresses()

        updated = subagent_address.get_subagent_address(record["agentId"])
        assert updated["status"] == "failed"
        assert updated["resumeClaimed"] is False
        assert updated["activeMessages"] == []
        assert [item.get("message") for item in updated["pending"]] == ["被中断的续聊正文"]

    def test_recover_on_startup_respects_should_stop(self):
        summary = subagent_address.recover_stale_subagent_addresses_on_startup(
            should_stop=lambda: True
        )
        assert summary.get("stopped") is True
        assert summary.get("sweptCount") == 0

    def test_cmdline_match_requires_project_agent_signature(self, monkeypatch):
        class _CmdlineProcess:
            def __init__(self, pid: int):
                self.pid = pid
                self._cmdline: list[str] = []

            def cmdline(self):
                return self._cmdline

        fake_process = _CmdlineProcess(1)
        monkeypatch.setattr(
            subagent_address, "_psutil_process_for_pid", lambda pid: fake_process
        )

        # 空 projectRoot：一律不匹配。
        assert subagent_address._cmdline_matches_project_subagent(1, "") is False

        fake_process._cmdline = [
            sys.executable,
            "C:/proj/agent.py",
            "--prompt",
            "p",
            "--single-turn",
            "--subagent-json",
        ]
        assert subagent_address._cmdline_matches_project_subagent(1, "C:/proj") is True

        # 缺少子代理签名 flag：不匹配。
        fake_process._cmdline = [sys.executable, "C:/proj/agent.py", "--single-turn"]
        assert subagent_address._cmdline_matches_project_subagent(1, "C:/proj") is False

        # agent.py 不在项目根下：不匹配。
        fake_process._cmdline = [
            sys.executable,
            "C:/other/agent.py",
            "--single-turn",
            "--subagent-json",
        ]
        assert subagent_address._cmdline_matches_project_subagent(1, "C:/proj") is False

    def test_open_subagent_address_records_pid_and_timestamps(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VIBELUTION_SUBAGENT_ADDRESS_ROOT", str(tmp_path / "addresses"))

        identity = (tmp_path, "parent-1", "turn-1")
        monkeypatch.setattr(subagent_address, "parent_chat_identity", lambda: identity)
        monkeypatch.setattr(
            subagent_address, "_ensure_child_session", lambda *a, **k: "child-1"
        )
        events = []
        monkeypatch.setattr(subagent_address, "note_subagent_progress", lambda *a, **k: events.append(k))

        opened = open_subagent_address(
            agent_id="subagent-inspect-d1-pidtest",
            task="任务",
            task_type="inspect",
            status="running",
            pid=9876,
        )

        assert opened["pid"] == 9876
        assert opened["openedAt"]
        reread = subagent_address.get_subagent_address("subagent-inspect-d1-pidtest")
        assert reread["pid"] == 9876
        assert reread["openedAt"] == opened["openedAt"]
        assert reread["updatedAt"]


# ── 回归护栏：正常路径不受影响 ───────────────────────────────────────────────


class TestNormalPathsUnchanged:
    def test_healthy_spawn_registers_and_unregisters_process(self, monkeypatch):
        events = []
        monkeypatch.setattr(agent_tools, "_record_subagent_scene_event", lambda **kw: events.append(kw))
        fake = _FakeProcess()
        monkeypatch.setattr(agent_tools.subprocess, "Popen", lambda *a, **k: fake)

        result = json.loads(agent_tools.spawn_agent(task="正常分析", timeout=60))

        assert result["status"] in {"no_result", "failed", "partial", "completed"}
        started = [e for e in events if e.get("event_code") == "subagent.run.started"]
        assert started[0]["fields"]["timeoutSeconds"] == 60
        # finally 注销：注册表不残留。
        assert all(
            entry.get("process") is not fake
            for entry in agent_tools._ACTIVE_SPAWN_PROCESSES.values()
        )

    def test_clamp_keeps_default_timeout_behaviour(self):
        assert clamp_spawn_timeout(120) == 120
        assert clamp_spawn_timeout("120") == 120
