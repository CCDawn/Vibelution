#!/usr/bin/env python3
"""evolution_harness 协议与归因逻辑测试"""

import json
import os
import sys
from pathlib import Path

import pytest

import scripts.evolution_harness as evolution_harness
from scripts.evolution_harness import (
    build_post_restart_observation,
    build_live_case_io_payload,
    build_agent_command,
    build_synthetic_venv,
    classify_tool_event_phase,
    collect_untracked_files,
    count_meaningful_tool_steps,
    copy_untracked_files,
    create_harness_config,
    DEFAULT_DYNAMIC_REPLANNING_FIXTURE_PROMPT,
    DEFAULT_FULL_EVOLUTION_PROMPT,
    DEFAULT_IMPOSSIBLE_TASK_FIXTURE_PROMPT,
    DEFAULT_SAFE_MODIFY_PROMPT,
    DEFAULT_TRANSACTION_PROMPT,
    ensure_harness_safe_modify_allowlist,
    extend_deadline_for_restart_trigger,
    infer_phase_from_agent_state,
    infer_phase_from_debug_lines,
    infer_phase_from_events,
    infer_first_meaningful_event,
    infer_evolution_summary,
    infer_post_restart_phase,
    infer_result_status,
    extract_llm_failure_from_events,
    is_restart_trigger_line,
    mirror_venv_into_worktree,
    read_conversation_events,
    materialize_scenario_prompt,
    resolve_python_executable,
    resolve_run_options,
    select_observation_files,
    should_copy_untracked_file,
    should_finish_post_restart_observation,
    SAFE_MODIFY_MARKER,
    SAFE_MODIFY_PROBE_CONTENT,
    SAFE_MODIFY_PROBE_PATH,
    SAFE_MODIFY_TOOL_PATH_PLACEHOLDER,
    should_stop_after_primary_exit,
    _safe_modify_probe_summary,
    _validation_passed_for_tool,
    ProcessRecord,
    summarize_agent_returncodes,
    summarize_process_history,
    summarize_agent_state_file,
    summarize_latest_matching_file,
    summarize_conversation_file,
    SupervisedAgentBindingRuntimeError,
    supervised_agent_binding_env,
    run_harness,
    SUPERVISED_AGENT_JUDGMENT_MARKER,
    SUPERVISED_FINAL_STATE_MARKER,
    SUPERVISED_INFEASIBLE_OUTCOME_MARKER,
    stdout_tail_looks_like_idle_chat_ui,
)
from core.orchestration.turn_outcome import TurnOutcomeController


def _write_external_operator_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str) -> Path:
    config_path = tmp_path / "external-config" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(text.strip() + "\n", encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config_path))
    return config_path


def test_create_harness_config_uses_external_config_not_worktree_legacy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    (tmp_path / "config.toml").write_text(
        "[llm.providers.legacy]\nkind = \"legacy\"\n",
        encoding="utf-8",
    )
    _write_external_operator_config(
        monkeypatch,
        tmp_path,
        """
        [llm.providers.external]
        kind = "minimax"
        """,
    )

    harness_config = create_harness_config(tmp_path)

    assert harness_config is not None
    text = harness_config.read_text(encoding="utf-8")
    assert "llm.providers.external" in text
    assert "llm.providers.legacy" not in text


def test_build_agent_command_for_test_mode():
    cmd = build_agent_command("test", None)
    assert "--no-shell" in cmd
    assert "--skip-doctor" in cmd
    assert "--test" in cmd
    assert "agent.py" in cmd


def test_run_git_hides_console_windows_on_windows(monkeypatch, tmp_path: Path):
    calls = []

    class Result:
        returncode = 0
        stdout = "abc123\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Result()

    monkeypatch.setattr(evolution_harness.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(evolution_harness.subprocess, "run", fake_run)

    assert evolution_harness.run_git(tmp_path, "rev-parse", "HEAD") == "abc123"
    assert calls[0][0] == ["git", "rev-parse", "HEAD"]
    assert calls[0][1]["creationflags"] & 0x08000000


def test_collect_untracked_files_uses_z_output_and_filters_runtime_noise(monkeypatch, tmp_path: Path):
    raw_paths = b"\0".join(
        [
            b"\xef\xbb\xbf.codex/edge-profile-memory-cdp/Default/Cache/file",
            b'".codex/edge-profile-memory-cdp/Default/Extensions/file',
            b"logs/runtime_scenes/latest/timeline.jsonl",
            b"workspace/edge-headless-profile/Default/Preferences",
            b"workspace/evaluation/bundles/terminal_bench_core_v1.json",
            b"workspace/evaluation/datasets/terminal_bench_core.jsonl",
        ]
    ) + b"\0"
    monkeypatch.setattr(evolution_harness, "run_git_bytes", lambda *_: raw_paths)

    assert collect_untracked_files(tmp_path) == [
        "workspace/evaluation/bundles/terminal_bench_core_v1.json",
        "workspace/evaluation/datasets/terminal_bench_core.jsonl",
    ]


def test_copy_untracked_files_skips_runtime_noise_and_preserves_dataset_files(tmp_path: Path):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    dataset = repo_root / "workspace" / "evaluation" / "bundles" / "terminal_bench_core_v1.json"
    codex_noise = repo_root / ".codex" / "edge-profile-memory-cdp" / "Default" / "Cache" / "file"
    dataset.parent.mkdir(parents=True)
    codex_noise.parent.mkdir(parents=True)
    dataset.write_text('{"bundle_name":"terminal_bench_core_v1"}', encoding="utf-8")
    codex_noise.write_text("cache", encoding="utf-8")
    worktree.mkdir()

    copy_untracked_files(
        repo_root,
        worktree,
        [
            "workspace/evaluation/bundles/terminal_bench_core_v1.json",
            ".codex/edge-profile-memory-cdp/Default/Cache/file",
            '".codex/edge-profile-memory-cdp/Default/Cache/file',
        ],
    )

    assert (worktree / "workspace" / "evaluation" / "bundles" / "terminal_bench_core_v1.json").exists()
    assert not (worktree / ".codex").exists()


def test_should_copy_untracked_file_rejects_unsafe_snapshot_paths():
    assert should_copy_untracked_file("workspace/evaluation/bundles/case.json")
    assert not should_copy_untracked_file("\ufeff.codex/edge-profile-memory-cdp/Default/Cache/file")
    assert not should_copy_untracked_file("\ufeffworkspace/evaluation/bundles/case.json")
    assert not should_copy_untracked_file('".codex/edge-profile-memory-cdp/Default/Cache/file')
    assert not should_copy_untracked_file("../outside.py")
    assert not should_copy_untracked_file("C:/tmp/outside.py")


def test_build_agent_command_for_single_turn_prompt():
    cmd = build_agent_command("single_turn", "hello", config_path="config.harness.toml")
    assert "--single-turn" in cmd
    assert "--prompt" in cmd
    assert "--config" in cmd
    assert "hello" in cmd


def test_build_agent_command_for_multi_step_react_launches_single_turn_prompt():
    cmd = build_agent_command("multi_step_react", "inspect then verify", config_path="config.harness.toml")

    assert "--single-turn" in cmd
    assert "--prompt" in cmd
    assert "--config" in cmd
    assert "inspect then verify" in cmd
    assert "--auto" not in cmd
    assert "--test" not in cmd


def test_supervised_agent_binding_env_exports_safe_runtime_context_only():
    env = supervised_agent_binding_env(
        {
            "agentId": "agent-supervised-baseline",
            "profileId": "supervised_baseline",
            "directSessionId": "session-baseline",
            "workspacePath": "workspace/agents/agent-supervised-baseline",
            "role": "baseline",
            "llmSlot": "dialogue",
            "dialogueModelId": "model-a",
            "llmBindings": {"dialogue": {"modelId": "model-a"}},
            "displayName": "监督基线 Agent",
            "apiKey": "should-not-leak",
        }
    )

    assert env == {
        "VIBELUTION_AGENT_ID": "agent-supervised-baseline",
        "VIBELUTION_AGENT_PROFILE_ID": "supervised_baseline",
        "VIBELUTION_AGENT_DIRECT_SESSION_ID": "session-baseline",
        "VIBELUTION_AGENT_WORKSPACE_PATH": "workspace/agents/agent-supervised-baseline",
        "VIBELUTION_SUPERVISED_ROLE": "baseline",
        "VIBELUTION_AGENT_LLM_SLOT": "dialogue",
        "VIBELUTION_AGENT_LLM_MODEL_ID": "model-a",
        "VIBELUTION_AGENT_LLM_BINDINGS_JSON": '{"dialogue":{"modelId":"model-a"}}',
        "VIBELUTION_TURN_MODE": "supervised_evolution",
        "VIBELUTION_TURN_RUN_KIND": "supervised_evaluation",
        "VIBELUTION_TURN_SESSION_ID": "session-baseline",
        "VIBELUTION_TURN_AGENT_ID": "agent-supervised-baseline",
        "VIBELUTION_TURN_LLM_SLOT": "dialogue",
        "VIBELUTION_TURN_MODEL_ID": "model-a",
        "VIBELUTION_TURN_CACHE_SCOPE": "baseline",
        "VIBELUTION_TURN_PROMPT_CACHE_PARTITION": (
            "mode:supervised_evolution|kind:supervised_evaluation|agent:agent-supervised-baseline|"
            "session:session-baseline|slot:dialogue|model:model-a|scope:baseline"
        ),
    }
    assert "apiKey" not in "".join(env)


def test_supervised_agent_binding_env_accepts_supervised_role_alias():
    env = supervised_agent_binding_env(
        {
            "agentId": "agent-supervised-candidate",
            "profileId": "supervised_candidate",
            "supervisedRole": "candidate",
            "llmSlot": "dialogue",
            "dialogueModelId": "model-candidate",
            "llmBindings": {"dialogue": {"modelId": "model-candidate"}},
        }
    )

    assert env["VIBELUTION_SUPERVISED_ROLE"] == "candidate"
    assert env["VIBELUTION_AGENT_LLM_SLOT"] == "dialogue"
    assert env["VIBELUTION_TURN_CACHE_SCOPE"] == "candidate"


def test_supervised_agent_binding_env_requires_explicit_llm_slot():
    with pytest.raises(SupervisedAgentBindingRuntimeError, match="missing required llmSlot"):
        supervised_agent_binding_env(
            {
                "agentId": "agent-supervised-baseline",
                "role": "baseline",
                "dialogueModelId": "model-a",
            }
        )


def test_supervised_agent_binding_env_requires_model_for_explicit_llm_slot():
    with pytest.raises(SupervisedAgentBindingRuntimeError, match="missing required model binding"):
        supervised_agent_binding_env(
            {
                "agentId": "agent-supervised-baseline",
                "role": "baseline",
                "llmSlot": "dialogue",
            }
        )


def test_supervised_agent_binding_env_respects_explicit_llm_slot():
    env = supervised_agent_binding_env(
        {
            "agentId": "agent-supervised-reviewer",
            "profileId": "supervised_reviewer",
            "role": "reviewer",
            "llmSlot": "subagentExecution",
            "dialogueModelId": "dialogue-model",
            "llmBindings": {
                "dialogue": {"modelId": "dialogue-model"},
                "subagentExecution": {"modelId": "subagent-model"},
            },
        }
    )

    assert env["VIBELUTION_AGENT_LLM_SLOT"] == "subagentExecution"
    assert env["VIBELUTION_AGENT_LLM_MODEL_ID"] == "subagent-model"
    assert env["VIBELUTION_TURN_LLM_SLOT"] == "subagentExecution"
    assert env["VIBELUTION_TURN_MODEL_ID"] == "subagent-model"


def test_run_harness_returns_failed_result_when_agent_binding_model_is_missing(monkeypatch, tmp_path: Path):
    popen_called = False

    def fail_popen(*_args, **_kwargs):
        nonlocal popen_called
        popen_called = True
        raise AssertionError("Popen should not run when supervised binding preflight fails")

    monkeypatch.setattr(evolution_harness, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr("scripts.evolution_harness.subprocess.Popen", fail_popen)

    result = run_harness(
        repo_root=tmp_path,
        mode="single_turn",
        prompt="probe",
        timeout_seconds=30,
        expect_restart=False,
        post_restart_observe_seconds=1,
        keep_worktree=False,
        scenario="transaction",
        agent_binding={
            "agentId": "agent-supervised-baseline",
            "profileId": "supervised_baseline",
            "role": "baseline",
            "llmSlot": "dialogue",
        },
    )

    assert popen_called is False
    assert result.status == "failed"
    assert "模型绑定预检失败" in result.reason
    assert result.evolution_summary["agent_binding_preflight"]["status"] == "failed"
    assert result.command == []
    assert result.worktree_path == ""
    assert result.preserved_evidence_path


def test_create_harness_config_forces_supervised_agent_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    _write_external_operator_config(
        monkeypatch,
        tmp_path,
        """
[agent]
default_mode = "self_evolution"

[runtime]
profile = "dev"
preflight_doctor = true
require_venv = true
        """,
    )

    harness_config = create_harness_config(tmp_path)

    assert harness_config is not None
    text = harness_config.read_text(encoding="utf-8")
    assert 'default_mode = "supervised_evolution"' in text
    assert 'default_mode = "self_evolution"' not in text
    assert 'profile = ""' in text
    assert "preflight_doctor = false" in text
    assert "require_venv = false" in text


def test_resolve_run_options_preserves_restart_defaults():
    options = resolve_run_options(
        scenario="restart",
        mode="test",
        prompt=None,
        expect_restart=False,
    )

    assert options.mode == "test"
    assert options.expect_restart is True
    assert "trigger_self_restart_tool" in options.prompt


def test_resolve_run_options_for_transaction_probe_forces_single_turn():
    options = resolve_run_options(
        scenario="transaction",
        mode="test",
        prompt=None,
        expect_restart=False,
    )

    assert options.mode == "single_turn"
    assert options.expect_restart is False
    assert options.prompt == DEFAULT_TRANSACTION_PROMPT
    assert "open_evolution_transaction_tool" in options.prompt
    assert "python_lint_tool" in options.prompt
    assert "close_evolution_transaction_tool" in options.prompt
    assert "不要触发重启" in options.prompt


def test_resolve_run_options_allows_custom_transaction_prompt():
    options = resolve_run_options(
        scenario="transaction",
        mode="auto",
        prompt="custom transaction probe",
        expect_restart=False,
    )

    assert options.mode == "single_turn"
    assert options.prompt == "custom transaction probe"


def test_resolve_run_options_preserves_multi_step_react_transaction_metadata():
    options = resolve_run_options(
        scenario="transaction",
        mode="multi_step_react",
        prompt="terminal bench smoke",
        expect_restart=False,
    )

    assert options.mode == "multi_step_react"
    assert options.prompt == "terminal bench smoke"
    assert options.scenario == "transaction"
    assert options.expect_restart is False


def test_resolve_run_options_for_modify_rollback_probe_forces_single_turn():
    options = resolve_run_options(
        scenario="modify_rollback",
        mode="test",
        prompt=None,
        expect_restart=False,
    )

    assert options.mode == "single_turn"
    assert options.expect_restart is False
    assert options.scenario == "modify_rollback"
    assert options.prompt == DEFAULT_SAFE_MODIFY_PROMPT
    assert "write_file_tool" in options.prompt
    assert "spawn_agent_tool" in options.prompt
    assert "不要委派子 agent" in options.prompt
    assert SAFE_MODIFY_TOOL_PATH_PLACEHOLDER in options.prompt
    assert SAFE_MODIFY_PROBE_PATH in options.prompt
    assert SAFE_MODIFY_MARKER in options.prompt
    assert repr(SAFE_MODIFY_PROBE_CONTENT) in options.prompt
    assert "import " not in SAFE_MODIFY_PROBE_CONTENT
    assert "不要触发重启" in options.prompt


def test_resolve_run_options_for_full_evolution_probe_forces_restartable_single_turn():
    options = resolve_run_options(
        scenario="full_evolution",
        mode="test",
        prompt=None,
        expect_restart=False,
    )

    assert options.mode == "single_turn"
    assert options.expect_restart is True
    assert options.scenario == "full_evolution"
    assert options.prompt == DEFAULT_FULL_EVOLUTION_PROMPT
    assert "write_file_tool" in options.prompt
    assert "close_evolution_transaction_tool" in options.prompt
    assert "trigger_self_restart_tool" in options.prompt
    assert "不要委派子 agent" in options.prompt


def test_resolve_run_options_for_strategy_probe_forces_readonly_single_turn():
    options = resolve_run_options(
        scenario="strategy",
        mode="test",
        prompt="read files and answer",
        expect_restart=True,
    )

    assert options.mode == "single_turn"
    assert options.prompt == "read files and answer"
    assert options.expect_restart is False
    assert options.scenario == "strategy"


def test_resolve_run_options_for_dynamic_replanning_fixture_forces_single_turn():
    options = resolve_run_options(
        scenario="dynamic_replanning_fixture",
        mode="test",
        prompt=None,
        expect_restart=True,
    )

    assert options.mode == "single_turn"
    assert options.expect_restart is False
    assert options.scenario == "dynamic_replanning_fixture"
    assert options.prompt == DEFAULT_DYNAMIC_REPLANNING_FIXTURE_PROMPT
    assert SUPERVISED_FINAL_STATE_MARKER in options.prompt
    assert "verified_after_change" in options.prompt
    assert "不要触发重启" in options.prompt


def test_resolve_run_options_for_impossible_task_fixture_forces_single_turn():
    options = resolve_run_options(
        scenario="impossible_task_fixture",
        mode="auto",
        prompt=None,
        expect_restart=True,
    )

    assert options.mode == "single_turn"
    assert options.expect_restart is False
    assert options.scenario == "impossible_task_fixture"
    assert options.prompt == DEFAULT_IMPOSSIBLE_TASK_FIXTURE_PROMPT
    assert SUPERVISED_INFEASIBLE_OUTCOME_MARKER in options.prompt
    assert "missing_permission" in options.prompt
    assert "不要伪造完成" in options.prompt


def test_resolve_run_options_allows_custom_supervised_fixture_prompt():
    options = resolve_run_options(
        scenario="dynamic_replanning_fixture",
        mode="test",
        prompt="custom dynamic marker prompt",
        expect_restart=False,
    )

    assert options.mode == "single_turn"
    assert options.prompt == "custom dynamic marker prompt"


def test_materialize_scenario_prompt_injects_worktree_absolute_probe_path(tmp_path: Path):
    prompt = f"写入 {SAFE_MODIFY_TOOL_PATH_PLACEHOLDER} 然后检查 {SAFE_MODIFY_PROBE_PATH}"

    materialized = materialize_scenario_prompt("modify_rollback", prompt, tmp_path)

    assert SAFE_MODIFY_TOOL_PATH_PLACEHOLDER not in materialized
    assert str(tmp_path / SAFE_MODIFY_PROBE_PATH) in materialized
    assert SAFE_MODIFY_PROBE_PATH in materialized


def test_materialize_full_evolution_prompt_injects_worktree_absolute_probe_path(tmp_path: Path):
    prompt = f"写入 {SAFE_MODIFY_TOOL_PATH_PLACEHOLDER} 然后重启"

    materialized = materialize_scenario_prompt("full_evolution", prompt, tmp_path)

    assert SAFE_MODIFY_TOOL_PATH_PLACEHOLDER not in materialized
    assert str(tmp_path / SAFE_MODIFY_PROBE_PATH) in materialized


def test_select_observation_files_uses_all_restart_logs_but_primary_non_restart_log():
    files = [
        "conversation_parent.jsonl",
        "conversation_subagent.jsonl",
        "conversation_late_subagent.jsonl",
    ]

    assert select_observation_files(files, expect_restart=True) == files
    assert select_observation_files(files, expect_restart=False) == ["conversation_parent.jsonl"]


def test_should_stop_after_primary_exit_for_non_restart_scenarios():
    assert should_stop_after_primary_exit(expect_restart=False, primary_returncode=0) is True
    assert should_stop_after_primary_exit(expect_restart=False, primary_returncode=1) is True
    assert should_stop_after_primary_exit(expect_restart=False, primary_returncode=None) is False
    assert should_stop_after_primary_exit(expect_restart=True, primary_returncode=0) is False


def test_should_not_stop_when_python_launcher_exits_but_child_agent_is_live():
    assert (
        should_stop_after_primary_exit(
            expect_restart=False,
            primary_returncode=1,
            live_agent_pids=[100, 200],
            primary_pid=100,
        )
        is False
    )
    assert (
        should_stop_after_primary_exit(
            expect_restart=False,
            primary_returncode=1,
            live_agent_pids=[100],
            primary_pid=100,
        )
        is True
    )


def test_run_harness_returns_cancelled_when_cancel_checker_requests_stop(monkeypatch, tmp_path: Path):
    class FakeStream:
        def readline(self):
            return ""

        def close(self):
            return None

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            self.pid = 4321
            self.stdout = FakeStream()
            self.stderr = FakeStream()
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

    process = FakeProcess()
    popen_calls = []
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    monkeypatch.setattr(
        "scripts.evolution_harness.create_checkpoint_snapshot",
        lambda repo_root, harness_id: type(
            "Snapshot",
            (),
            {
                "base_head": "abc123",
                "commit": "abc123",
                "ref_name": None,
                "tracked_dirty": False,
                "untracked_files": [],
            },
        )(),
    )
    monkeypatch.setattr("scripts.evolution_harness.create_worktree", lambda repo_root, snapshot, harness_id: worktree)
    monkeypatch.setattr("scripts.evolution_harness.create_harness_config", lambda path: None)
    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return process

    monkeypatch.setattr(evolution_harness.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr("scripts.evolution_harness.subprocess.Popen", fake_popen)
    monkeypatch.setattr("scripts.evolution_harness.start_stream_reader", lambda *args, **kwargs: type("Thread", (), {"join": lambda self, timeout=None: None})())
    monkeypatch.setattr("scripts.evolution_harness.terminate_harness_processes", lambda path: process.terminate())
    report_path = tmp_path / "report.json"

    def fake_write_report(result, path=None):
        target = path or report_path
        target.write_text("{}", encoding="utf-8")
        return target

    monkeypatch.setattr("scripts.evolution_harness.write_report", fake_write_report)
    monkeypatch.setattr("scripts.evolution_harness.remove_worktree", lambda repo_root, path: None)
    log_info = worktree / "log_info"
    log_info.mkdir()
    (log_info / "conversation_case.jsonl").write_text('{"type":"external_request","content":"probe"}\n', encoding="utf-8")
    (log_info / "debug_case.log").write_text("[debug] probe\n", encoding="utf-8")

    result = run_harness(
        repo_root=tmp_path,
        mode="single_turn",
        prompt="probe",
        timeout_seconds=30,
        expect_restart=False,
        post_restart_observe_seconds=1,
        keep_worktree=False,
        scenario="transaction",
        agent_binding={
            "agentId": "agent-supervised-baseline",
            "profileId": "supervised_baseline",
            "directSessionId": "session-baseline",
            "workspacePath": "workspace/agents/agent-supervised-baseline",
            "role": "baseline",
            "llmSlot": "dialogue",
            "dialogueModelId": "model-a",
            "llmBindings": {"dialogue": {"modelId": "model-a"}},
        },
        mental_model_mode="disabled",
        mental_model_enabled=False,
        cancel_checker=lambda: "operator stop",
    )

    assert result.status == "cancelled"
    assert result.reason == "operator stop"
    assert result.agent_binding["profileId"] == "supervised_baseline"
    assert process.terminated is True
    assert popen_calls[0][1]["creationflags"] & 0x08000000
    env = popen_calls[0][1]["env"]
    assert env["VIBELUTION_AGENT_ID"] == "agent-supervised-baseline"
    assert env["VIBELUTION_AGENT_PROFILE_ID"] == "supervised_baseline"
    assert env["VIBELUTION_AGENT_DIRECT_SESSION_ID"] == "session-baseline"
    assert env["VIBELUTION_AGENT_WORKSPACE_PATH"] == "workspace/agents/agent-supervised-baseline"
    assert env["VIBELUTION_SUPERVISED_ROLE"] == "baseline"
    assert env["VIBELUTION_AGENT_LLM_SLOT"] == "dialogue"
    assert env["VIBELUTION_AGENT_LLM_MODEL_ID"] == "model-a"
    assert json.loads(env["VIBELUTION_AGENT_LLM_BINDINGS_JSON"]) == {"dialogue": {"modelId": "model-a"}}
    assert env["VIBELUTION_TURN_RUN_ID"] == env["VIBELUTION_HARNESS_ID"]
    assert env["VIBELUTION_TURN_RUN_KIND"] == "supervised_evaluation"
    assert env["VIBELUTION_TURN_MODEL_ID"] == "model-a"
    assert env["VIBELUTION_TURN_CACHE_SCOPE"] == "baseline"
    assert env["VIBELUTION_TURN_PROMPT_CACHE_PARTITION"].endswith("|scope:baseline")
    assert env["VIBELUTION_SUPERVISED_MENTAL_MODEL_MODE"] == "disabled"
    assert env["VIBELUTION_SUPERVISED_MENTAL_MODEL_ENABLED"] == "false"
    assert result.agent_runtime_env["VIBELUTION_AGENT_LLM_MODEL_ID"] == "model-a"
    assert result.agent_runtime_env["VIBELUTION_SUPERVISED_MENTAL_MODEL_MODE"] == "disabled"
    assert result.agent_runtime_env["VIBELUTION_SUPERVISED_MENTAL_MODEL_ENABLED"] == "false"
    assert result.preserved_evidence_path
    evidence_dir = Path(result.preserved_evidence_path)
    assert (evidence_dir / "log_info" / "conversation_case.jsonl").exists()
    assert (evidence_dir / "log_info" / "debug_case.log").exists()
    runtime_env = json.loads((evidence_dir / "agent_runtime_env.json").read_text(encoding="utf-8"))
    assert runtime_env["VIBELUTION_AGENT_LLM_MODEL_ID"] == "model-a"
    assert runtime_env["VIBELUTION_SUPERVISED_MENTAL_MODEL_MODE"] == "disabled"
    assert runtime_env["VIBELUTION_SUPERVISED_MENTAL_MODEL_ENABLED"] == "false"
    assert "log_info/conversation_case.jsonl" in result.preserved_evidence_files


def test_should_finish_post_restart_observation_waits_for_meaningful_child_event():
    assert should_finish_post_restart_observation(
        observation_phase="prompt_refresh",
        first_child_event_phase="first_prompt_refresh",
        elapsed_seconds=15,
        min_observe_seconds=15,
    ) is False

    assert should_finish_post_restart_observation(
        observation_phase="first_tool:task_create_tool:success",
        first_child_event_phase="first_tool:task_create_tool:success",
        elapsed_seconds=15,
        min_observe_seconds=15,
    ) is True

    assert should_finish_post_restart_observation(
        observation_phase="prompt_refresh",
        first_child_event_phase="first_prompt_refresh",
        elapsed_seconds=45,
        min_observe_seconds=15,
    ) is True


def test_infer_result_status_requires_safe_modify_and_restart_for_full_evolution():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=True,
        restart_reentered=True,
        primary_returncode=0,
        last_observation={"phase": "first_tool:task_create_tool:success"},
        scenario="full_evolution",
        evolution_summary={
            "validation": {"passed": 1, "failed": 0},
            "transaction": {"opened": True, "closed": True, "status": "success"},
            "safe_modify": {
                "exists": True,
                "marker_present": True,
                "out_of_scope_paths": [],
            },
        },
    )

    assert status == "success"
    assert "重启接力" in reason


def test_infer_result_status_rejects_restart_when_safe_modify_missing_even_if_reentered():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=True,
        restart_reentered=True,
        primary_returncode=0,
        last_observation={"phase": "first_tool:task_create_tool:success"},
        scenario="full_evolution",
        evolution_summary={
            "validation": {"passed": 1, "failed": 0},
            "transaction": {"opened": True, "closed": True, "status": "success"},
            "safe_modify": {
                "exists": False,
                "marker_present": False,
                "out_of_scope_paths": [],
            },
        },
    )

    assert status == "failed"
    assert "未创建目标文件" in reason


def test_infer_result_status_classifies_idle_chat_ui_single_turn_entry_failure():
    stdout_tail = [
        "│  Vibelution Chat           │最近对话                              0 条消息  │",
        "│  模式  Chat Session        │                                                │",
        "│  当前状态                  │                                                │",
        "│  任务  等待新的任务        │                                                │",
        "│ 还没有最近对话 │",
    ]

    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=1,
        last_observation={"phase": "unknown"},
        scenario="transaction",
        evolution_summary={
            "transaction": {"opened": False, "closed": False, "status": None},
            "validation": {"passed": 0, "failed": 0},
            "child": {"first_event_phase": "unknown"},
        },
        stdout_tail=stdout_tail,
    )

    assert stdout_tail_looks_like_idle_chat_ui(stdout_tail) is True
    assert status == "failed"
    assert "单轮入口失败" in reason
    assert "未开账" not in reason


def test_returncode_summary_recovers_windows_launcher_failure():
    records = [
        ProcessRecord(
            pid=100,
            role="agent",
            first_seen="2026-06-06T01:45:52",
            last_seen="2026-06-06T01:46:08",
            returncode=1,
            cmdline_preview=r"C:\repo\.venv\Scripts\python.exe agent.py --no-shell --single-turn --prompt probe",
        ),
        ProcessRecord(
            pid=200,
            role="agent",
            first_seen="2026-06-06T01:46:07",
            last_seen="2026-06-06T01:46:08",
            returncode=None,
            cmdline_preview=r"C:\Python312\python.exe agent.py --no-shell --single-turn --prompt probe",
        ),
    ]

    summary = summarize_agent_returncodes(records, primary_pid=100)

    assert summary["primary_returncode"] == 1
    assert summary["launcher_returncode"] == 1
    assert summary["agent_child_returncode"] is None
    assert summary["effective_returncode"] == 1


def test_effective_returncode_classifies_idle_chat_ui_when_primary_returncode_was_missing():
    stdout_tail = [
        "│  Vibelution Chat           │最近对话                              0 条消息  │",
        "│  模式  Chat Session        │                                                │",
        "│  任务  等待新的任务        │                                                │",
        "│ 还没有最近对话 │",
    ]
    records = [
        ProcessRecord(
            pid=100,
            role="agent",
            first_seen="2026-06-06T01:45:52",
            last_seen="2026-06-06T01:46:08",
            returncode=1,
            cmdline_preview=r"C:\repo\.venv\Scripts\python.exe agent.py --no-shell --single-turn --prompt probe",
        ),
        ProcessRecord(
            pid=200,
            role="agent",
            first_seen="2026-06-06T01:46:07",
            last_seen="2026-06-06T01:46:08",
            returncode=None,
            cmdline_preview=r"C:\Python312\python.exe agent.py --no-shell --single-turn --prompt probe",
        ),
    ]
    returncodes = summarize_agent_returncodes(records, primary_pid=100)

    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=returncodes["effective_returncode"],
        last_observation={"phase": "unknown"},
        scenario="transaction",
        evolution_summary={
            "transaction": {"opened": False, "closed": False, "status": None},
            "validation": {"passed": 0, "failed": 0},
            "child": {"first_event_phase": "unknown"},
        },
        stdout_tail=stdout_tail,
    )

    assert status == "failed"
    assert "单轮入口失败" in reason
    assert "未开账" not in reason


def test_resolve_python_executable_prefers_usable_repo_venv(monkeypatch, tmp_path: Path):
    python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")
    monkeypatch.setattr("scripts.evolution_harness.is_python_executable_usable", lambda path: path == python_path)

    resolved = resolve_python_executable(tmp_path)

    assert resolved == str(python_path)


def test_resolve_python_executable_falls_back_when_repo_venv_is_broken(monkeypatch, tmp_path: Path):
    python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")
    monkeypatch.setattr("scripts.evolution_harness.is_python_executable_usable", lambda path: False)

    resolved = resolve_python_executable(tmp_path)

    assert resolved == sys.executable


def test_build_synthetic_venv_invokes_current_python(monkeypatch, tmp_path: Path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("python", encoding="utf-8")

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("scripts.evolution_harness.subprocess.run", fake_run)
    monkeypatch.setattr("scripts.evolution_harness._python_module_available", lambda *_: True)

    build_synthetic_venv(tmp_path)

    assert calls
    assert calls[0][0][:4] == [sys.executable, "-m", "venv", "--system-site-packages"]
    assert calls[0][0][-1] == str(tmp_path / ".venv")


def test_build_synthetic_venv_installs_missing_harness_packages(monkeypatch, tmp_path: Path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:3] == [sys.executable, "-m", "venv"]:
            python_path = tmp_path / ".venv" / "Scripts" / "python.exe"
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("python", encoding="utf-8")

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("scripts.evolution_harness.subprocess.run", fake_run)
    monkeypatch.setattr("scripts.evolution_harness._python_module_available", lambda *_: False)

    build_synthetic_venv(tmp_path)

    pip_installs = [call[0] for call in calls if call[0][1:4] == ["-m", "pip", "install"]]
    assert pip_installs
    assert "litellm" in pip_installs[0]
    assert "ruff" in pip_installs[0]


def test_create_harness_config_overrides_runtime_section(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    _write_external_operator_config(
        monkeypatch,
        tmp_path,
        """
        [runtime]
        profile = "safe_local"
        preflight_doctor = true
        require_venv = true

        [llm.providers.default]
        kind = "minimax"

        [llm.profiles.primary]
        provider_id = "default"
        model = "MiniMax-M2.7"
        """,
    )

    target = create_harness_config(tmp_path)
    content = target.read_text(encoding="utf-8")

    assert 'profile = ""' in content
    assert "preflight_doctor = false" in content
    assert "require_venv = false" in content
    assert content.count("[runtime]") == 1


def test_mirror_venv_into_worktree_copies_venv_without_junction(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    source_python = repo_root / ".venv" / "Scripts" / "python.exe"
    source_python.parent.mkdir(parents=True)
    source_python.write_text("python", encoding="utf-8")
    source_package = repo_root / ".venv" / "Lib" / "site-packages" / "annotated_types"
    source_package.mkdir(parents=True)
    worktree.mkdir()
    monkeypatch.setattr("scripts.evolution_harness.is_python_executable_usable", lambda *_: True)

    mirror_venv_into_worktree(repo_root, worktree)

    assert (worktree / ".venv" / "Scripts" / "python.exe").exists()
    assert (worktree / ".venv" / "Lib" / "site-packages" / "annotated_types").exists()


def test_mirror_venv_into_worktree_rebuilds_when_copied_venv_is_unusable(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    source_python = repo_root / ".venv" / "Scripts" / "python.exe"
    source_python.parent.mkdir(parents=True)
    source_python.write_text("python", encoding="utf-8")
    source_package = repo_root / ".venv" / "Lib" / "site-packages" / "annotated_types"
    source_package.mkdir(parents=True)
    worktree.mkdir()
    rebuilt = []

    def fake_build(target: Path):
        rebuilt.append(target)
        python_path = target / ".venv" / "Scripts" / "python.exe"
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("usable", encoding="utf-8")

    monkeypatch.setattr("scripts.evolution_harness.is_python_executable_usable", lambda *_: False)
    monkeypatch.setattr("scripts.evolution_harness.build_synthetic_venv", fake_build)

    mirror_venv_into_worktree(repo_root, worktree)

    assert rebuilt == [worktree]
    assert (worktree / ".venv" / "Scripts" / "python.exe").read_text(encoding="utf-8") == "usable"


def test_mirror_venv_into_worktree_copies_python_fallback(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    source_python = repo_root / ".venv" / "Scripts" / "python.exe"
    source_python.parent.mkdir(parents=True)
    source_python.write_text("python", encoding="utf-8")
    worktree.mkdir()

    monkeypatch.setattr("scripts.evolution_harness.shutil.copytree", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("copy failed")))
    monkeypatch.setattr("scripts.evolution_harness.is_python_executable_usable", lambda *_: True)

    mirror_venv_into_worktree(repo_root, worktree)

    assert (worktree / ".venv" / "Scripts" / "python.exe").exists()


def test_mirror_venv_into_worktree_builds_synthetic_venv_when_source_missing(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repo_root.mkdir()
    worktree.mkdir()
    created = []

    def fake_build(target: Path):
        created.append(target)
        python_path = target / ".venv" / "Scripts" / "python.exe"
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("python", encoding="utf-8")

    monkeypatch.setattr("scripts.evolution_harness.build_synthetic_venv", fake_build)

    mirror_venv_into_worktree(repo_root, worktree)

    assert created == [worktree]
    assert (worktree / ".venv" / "Scripts" / "python.exe").exists()


def test_mirror_venv_into_worktree_builds_synthetic_venv_when_source_python_missing(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    (repo_root / ".venv").mkdir(parents=True)
    worktree.mkdir()
    created = []

    def fake_build(target: Path):
        created.append(target)
        python_path = target / ".venv" / "Scripts" / "python.exe"
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("python", encoding="utf-8")

    monkeypatch.setattr("scripts.evolution_harness.build_synthetic_venv", fake_build)

    mirror_venv_into_worktree(repo_root, worktree)

    assert created == [worktree]
    assert (worktree / ".venv" / "Scripts" / "python.exe").exists()


def test_infer_phase_from_events_prefers_latest_tool_status():
    events = [
        {"type": "llm_response", "content": "thinking"},
        {"type": "tool_call", "tool_name": "read_file_tool", "status": "success"},
    ]
    assert infer_phase_from_events(events) == "tool:read_file_tool:success"


def test_infer_phase_from_events_labels_restart_guarded_tool():
    events = [
        {
            "type": "tool_call",
            "tool_name": "get_git_status_summary_tool",
            "status": "error",
            "tool_result": "[短路] 当前处于重启测试模式，只允许任务管理与重启闭环工具。",
        },
    ]

    assert infer_phase_from_events(events) == "restart_guarded_tool:get_git_status_summary_tool:error"
    assert classify_tool_event_phase(events[0]) == "restart_guarded_tool:get_git_status_summary_tool:error"


def test_infer_phase_from_events_labels_generic_guarded_tool():
    events = [
        {
            "type": "tool_call",
            "tool_name": "read_file_tool",
            "status": "error",
            "tool_result": "[短路] 当前存在未完成续读，请先继续读取。",
        },
    ]

    assert infer_phase_from_events(events) == "guarded_tool:read_file_tool:error"


def test_infer_phase_from_debug_lines_detects_restarter():
    lines = [
        "[20:00:00.000] [INFO] start",
        "[20:00:01.000] [INFO] Restarter 守护进程启动",
    ]
    assert infer_phase_from_debug_lines(lines) == "restarter_boot"


def test_infer_phase_from_debug_lines_labels_restart_guard():
    lines = [
        "[20:00:00.000] [WARN] [工具护栏] get_git_status_summary_tool 被短路: [短路] 当前处于重启测试模式",
    ]

    assert infer_phase_from_debug_lines(lines) == "restart_guarded_tool"


def test_summarize_conversation_file_extracts_turn_stats_and_phase(tmp_path: Path):
    path = tmp_path / "conversation_demo.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"type":"llm_response","content":"思考"}',
                '{"type":"tool_call","tool_name":"grep_search_tool","status":"error","tool_result":"blocked"}',
                '{"type":"turn_end","stats":{"iterations":3,"tool_calls":2}}',
            ]
        ),
        encoding="utf-8",
    )

    summary = summarize_conversation_file(path)

    assert summary["last_type"] == "turn_end"
    assert summary["turn_stats"]["tool_calls"] == 2
    assert summary["phase"] == "turn_end"
    assert summary["first_meaningful_event"]["phase"] == "first_tool:grep_search_tool:error"


def test_read_conversation_events_ignores_broken_jsonl_rows(tmp_path: Path):
    path = tmp_path / "conversation_demo.jsonl"
    path.write_text(
        '{"type":"debug","message":"ok"}\n'
        "not json\n"
        '{"type":"tool_call","tool_name":"task_create_tool"}\n',
        encoding="utf-8",
    )

    events = read_conversation_events(path)

    assert [item["type"] for item in events] == ["debug", "tool_call"]


def test_read_conversation_events_hydrates_referenced_llm_response(tmp_path: Path):
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    (payload_dir / "turn_1_llm_response.txt").write_text("assistant marker body", encoding="utf-8")
    (payload_dir / "turn_1_llm_response_raw.txt").write_text("assistant raw body", encoding="utf-8")
    path = tmp_path / "conversation_demo.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "llm_response",
                "content_inlined": False,
                "content_ref": "payloads/turn_1_llm_response.txt",
                "raw_response_inlined": False,
                "raw_response_ref": "payloads/turn_1_llm_response_raw.txt",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    events = read_conversation_events(path)

    assert events[0]["content"] == "assistant marker body"
    assert events[0]["raw_response"] == "assistant raw body"


def test_build_live_case_io_payload_reads_inline_and_referenced_content(tmp_path: Path):
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    (payload_dir / "tool_result.txt").write_text("tool result body", encoding="utf-8")
    conversation_path = tmp_path / "conversation_demo.jsonl"
    conversation_path.write_text(
        "\n".join(
            [
                '{"type":"external_request","timestamp":"2026-05-19T12:00:01Z","content":"prompt body"}',
                '{"type":"tool_call","timestamp":"2026-05-19T12:00:02Z","tool_name":"read_file_tool","status":"success","tool_result_ref":"payloads/tool_result.txt"}',
                '{"type":"llm_response","timestamp":"2026-05-19T12:00:03Z","content":"assistant reply"}',
            ]
        ),
        encoding="utf-8",
    )

    payload = build_live_case_io_payload(tmp_path)

    assert payload["conversation_path"].endswith("conversation_demo.jsonl")
    assert payload["latest_input"] == "prompt body"
    assert payload["latest_output"] == "assistant reply"
    assert payload["latest_output_kind"] == "assistant"
    assert payload["latest_output_label"] == "assistant"
    assert payload["updated_at"] == "2026-05-19T12:00:03Z"
    assert [item["kind"] for item in payload["transcript"]] == ["input", "tool", "assistant"]
    assert payload["transcript"][1]["label"] == "read_file_tool"
    assert payload["transcript"][1]["content"] == "tool result body"


def test_build_live_case_io_payload_reads_llm_error_message(tmp_path: Path):
    conversation_path = tmp_path / "conversation_demo.jsonl"
    provider_error = (
        "provider_protocol_error: litellm.InternalServerError: InternalServerError: "
        "OpenAIException - [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"
    )
    conversation_path.write_text(
        "\n".join(
            [
                '{"type":"external_request","timestamp":"2026-05-21T21:41:30Z","content":"run probe"}',
                '{"type":"error","timestamp":"2026-05-21T21:41:46Z","error_type":"llm_error","error_msg":"'
                + provider_error.replace("\\", "\\\\").replace('"', '\\"')
                + '"}',
            ]
        ),
        encoding="utf-8",
    )

    payload = build_live_case_io_payload(tmp_path)
    summary = summarize_conversation_file(conversation_path)

    assert payload["latest_output_kind"] == "error"
    assert payload["latest_output_label"] == "llm_error"
    assert "UNEXPECTED_EOF_WHILE_READING" in payload["latest_output"]
    assert summary["phase"] == "provider_transport_error"
    assert summary["llm_failure"]["category"] == "provider_transport_error"
    assert summary["first_meaningful_event"]["phase"] == "first_provider_transport_error"


def test_build_live_case_io_payload_keeps_recovered_llm_error_out_of_latest_output(tmp_path: Path):
    conversation_path = tmp_path / "conversation_demo.jsonl"
    conversation_path.write_text(
        "\n".join(
            [
                '{"type":"external_request","timestamp":"2026-05-21T23:06:51Z","content":"run probe"}',
                '{"type":"error","timestamp":"2026-05-21T23:07:09Z","error_type":"llm_error","error_msg":"network_error: [SSL: UNEXPECTED_EOF_WHILE_READING]"}',
                '{"type":"tool_call","timestamp":"2026-05-21T23:07:48Z","tool_name":"python_lint_tool","status":"success","tool_result":"{\\"status\\":\\"ok\\",\\"issue_count\\":0}"}',
                '{"type":"error","timestamp":"2026-05-21T23:07:54Z","error_type":"llm_error","error_msg":"network_error: [SSL: UNEXPECTED_EOF_WHILE_READING]"}',
                '{"type":"tool_call","timestamp":"2026-05-21T23:08:10Z","tool_name":"close_evolution_transaction_tool","status":"success","tool_result":"{\\"status\\":\\"success\\",\\"transaction_status\\":\\"success\\"}"}',
            ]
        ),
        encoding="utf-8",
    )

    payload = build_live_case_io_payload(tmp_path)

    assert payload["latest_output_kind"] == "tool"
    assert payload["latest_output_label"] == "close_evolution_transaction_tool"
    assert '"transaction_status":"success"' in payload["latest_output"]
    assert [item["label"] for item in payload["transcript"]].count("llm_error") == 2
    recovered_errors = [
        item
        for item in payload["transcript"]
        if item["kind"] == "error" and item.get("status") == "recovered"
    ]
    assert len(recovered_errors) == 2


def test_build_live_case_io_payload_keeps_unrecovered_llm_error_as_current_output(tmp_path: Path):
    conversation_path = tmp_path / "conversation_demo.jsonl"
    conversation_path.write_text(
        "\n".join(
            [
                '{"type":"external_request","timestamp":"2026-05-22T10:52:28Z","content":"run probe"}',
                '{"type":"tool_call","timestamp":"2026-05-22T10:52:34Z","tool_name":"open_evolution_transaction_tool","status":"success","tool_result":"{\\"status\\":\\"success\\"}"}',
                '{"type":"error","timestamp":"2026-05-22T10:52:44Z","error_type":"llm_error","error_msg":"network_error: [SSL: UNEXPECTED_EOF_WHILE_READING]"}',
            ]
        ),
        encoding="utf-8",
    )

    payload = build_live_case_io_payload(tmp_path)

    assert payload["latest_output_kind"] == "error"
    assert payload["latest_output_label"] == "llm_error"
    assert "UNEXPECTED_EOF_WHILE_READING" in payload["latest_output"]
    assert payload["transcript"][-1].get("status") != "recovered"


def test_infer_evolution_summary_records_provider_transport_llm_failure():
    provider_error = (
        "provider_protocol_error: litellm.InternalServerError: InternalServerError: "
        "OpenAIException - [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"
    )
    events = [
        {
            "type": "error",
            "error_type": "llm_error",
            "error_msg": provider_error,
        }
    ]

    failure = extract_llm_failure_from_events(events)
    summary = infer_evolution_summary(
        events,
        [],
        [],
        restart_expected=False,
        restart_reentered=False,
    )

    assert failure["category"] == "provider_transport_error"
    assert summary["llm_failure"]["detected"] is True
    assert summary["llm_failure"]["retryable"] is True


def test_extract_llm_failure_ignores_recovered_llm_error():
    events = [
        {
            "type": "error",
            "error_type": "llm_error",
            "error_msg": "provider_protocol_error: [SSL: UNEXPECTED_EOF_WHILE_READING]",
        },
        {
            "type": "llm_response",
            "content": "recovered",
        },
    ]

    failure = extract_llm_failure_from_events(events)

    assert failure["detected"] is False
    assert failure["recovered"] is True


def test_safe_modify_probe_summary_reports_marker_and_dirty_state(tmp_path: Path):
    probe = tmp_path / SAFE_MODIFY_PROBE_PATH
    probe.parent.mkdir(parents=True)
    probe.write_text(
        f'MARKER = "{SAFE_MODIFY_MARKER}"\n',
        encoding="utf-8",
    )

    summary = _safe_modify_probe_summary(tmp_path)

    assert summary["path"] == SAFE_MODIFY_PROBE_PATH
    assert summary["exists"] is True
    assert summary["marker_present"] is True
    assert summary["size"] > 0
    assert summary["cleanup"] == "pending"


def test_create_harness_config_injects_safe_modify_probe_allowlist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    config_path = _write_external_operator_config(
        monkeypatch,
        tmp_path,
        """
        [runtime]
        profile = "dev"

        [evolution]
        allowed_target_dirs = [
            "workspace/prompts/",
        ]
        """,
    )

    harness_config = create_harness_config(tmp_path)

    assert harness_config is not None
    text = harness_config.read_text(encoding="utf-8")
    assert 'profile = ""' in text
    assert f'"{SAFE_MODIFY_PROBE_PATH}"' in text
    assert config_path.read_text(encoding="utf-8").count(SAFE_MODIFY_PROBE_PATH) == 0


def test_harness_safe_modify_allowlist_handles_inline_array(tmp_path: Path):
    harness_config = tmp_path / "config.harness.toml"
    harness_config.write_text(
        "[evolution]\n"
        'allowed_target_dirs = ["workspace/prompts/"]\n',
        encoding="utf-8",
    )

    ensure_harness_safe_modify_allowlist(harness_config)

    text = harness_config.read_text(encoding="utf-8")
    assert 'allowed_target_dirs = ["workspace/prompts/", "tests/harness_safe_modify_probe.py"]' in text


def test_safe_modify_probe_summary_reports_out_of_scope_dirty_paths(monkeypatch, tmp_path: Path):
    probe = tmp_path / SAFE_MODIFY_PROBE_PATH
    probe.parent.mkdir(parents=True)
    probe.write_text(
        f'MARKER = "{SAFE_MODIFY_MARKER}"\n',
        encoding="utf-8",
    )

    def fake_run_git(_repo_root, *args):
        if args == ("status", "--porcelain", "--", SAFE_MODIFY_PROBE_PATH):
            return f"?? {SAFE_MODIFY_PROBE_PATH}"
        if args == ("status", "--porcelain"):
            return f"?? config.harness.toml\n?? {SAFE_MODIFY_PROBE_PATH}\n M agent.py"
        return ""

    monkeypatch.setattr("scripts.evolution_harness.run_git", fake_run_git)

    summary = _safe_modify_probe_summary(tmp_path)

    assert summary["git_dirty"] is True
    assert summary["dirty_paths"] == ["config.harness.toml", SAFE_MODIFY_PROBE_PATH, "agent.py"]
    assert summary["out_of_scope_paths"] == ["agent.py"]


def test_infer_evolution_summary_extracts_transaction_validation_and_restart():
    events = [
        {
            "type": "tool_call",
            "tool_name": "open_evolution_transaction_tool",
            "status": "success",
            "tool_result": '{"status":"success","txn_id":"txn_1"}',
        },
        {
            "type": "tool_call",
            "tool_name": "task_create_tool",
            "status": "success",
            "tool_args": {"task_list": [{"description": "验证"}]},
            "tool_result": "ok",
        },
        {
            "type": "tool_call",
            "tool_name": "task_update_tool",
            "status": "success",
            "tool_args": {"task_id": 1, "is_completed": True},
            "tool_result": "done",
        },
        {
            "type": "tool_call",
            "tool_name": "cli_tool",
            "status": "success",
            "tool_args": {"command": "python -m pytest tests/test_demo.py -q"},
            "tool_result": "1 passed in 0.10s",
        },
        {
            "type": "tool_call",
            "tool_name": "close_evolution_transaction_tool",
            "status": "success",
            "tool_args": {"txn_id": "txn_1", "status": "success"},
            "tool_result": '{"status":"success","txn_id":"txn_1","transaction_status":"success"}',
        },
    ]

    summary = infer_evolution_summary(
        events,
        ["[INFO] 当前演化事务已成功关账，本轮停止并等待下一轮。"],
        ["11:11:20 -- 重启触发成功"],
        restart_expected=True,
        restart_reentered=True,
        child_first_event_phase="first_tool:task_list_tool:success",
    )

    assert summary["tasks"] == {"created": 1, "updated": 1, "completed": 1}
    assert summary["validation"]["passed"] == 1
    assert summary["validation"]["failed"] == 0
    assert summary["transaction"]["opened"] is True
    assert summary["transaction"]["closed"] is True
    assert summary["transaction"]["status"] == "success"
    assert summary["restart"]["triggered"] is True
    assert summary["restart"]["reentered"] is True
    assert summary["child"]["first_event_phase"] == "first_tool:task_list_tool:success"
    assert summary["guarded_tools"]["total"] == 0


def test_infer_evolution_summary_recovers_tool_events_from_debug_lines_when_conversation_is_partial():
    events = [
        {
            "type": "tool_call",
            "tool_name": "close_evolution_transaction_tool",
            "status": "error",
            "tool_args": {"txn_id": "txn-74f4facf3488", "status": "success"},
            "tool_result": "[错误] OperationalError: no such table: EvolutionTransaction",
        },
    ]
    debug_lines = [
        "[09:15:26.707] [TOOL] START open_evolution_transaction_tool args={'summary': 'probe'}",
        "[09:15:26.789] [TOOL] RESULT open_evolution_transaction_tool OK len=219",
        "[09:18:31.624] [TOOL] START run_test_for_tool args={'source_path': 'core/evaluation/dataset_registry.py', 'timeout': 120}",
        "[09:18:34.643] [TOOL] RESULT run_test_for_tool OK len=3066",
        "[09:18:50.909] [TOOL] START python_lint_tool args={'target': 'core/evaluation/dataset_registry.py'}",
        "[09:18:51.301] [TOOL] RESULT python_lint_tool OK len=170",
        "[09:19:13.648] [TOOL] START close_evolution_transaction_tool args={'txn_id': 'txn-74f4facf3488', 'status': 'success'}",
        "[09:19:13.664] [TOOL] RESULT close_evolution_transaction_tool FAIL len=58",
    ]

    summary = infer_evolution_summary(
        events,
        debug_lines,
        [],
        restart_expected=False,
        restart_reentered=False,
    )

    assert summary["transaction"]["opened"] is True
    assert summary["transaction"]["closed"] is False
    assert summary["transaction"]["txn_id"] == "txn-74f4facf3488"
    assert summary["validation"]["passed"] >= 2
    assert summary["validation"]["failed"] == 0
    assert summary["evidence"]["debug_tool_events_recovered"] is True
    assert summary["evidence"]["conversation_tool_events"] == 1
    assert summary["evidence"]["debug_tool_events"] == 4
    assert "open_evolution_transaction_tool:success" in summary["tool_sequence_tail"]
    assert "close_evolution_transaction_tool:error" in summary["tool_sequence_tail"]


def test_infer_evolution_summary_counts_guarded_tool_phases():
    events = [
        {
            "type": "tool_call",
            "tool_name": "get_git_status_summary_tool",
            "status": "error",
            "tool_result": "[短路] 当前处于重启测试模式，只允许任务管理与重启闭环工具。",
        },
        {
            "type": "tool_call",
            "tool_name": "task_list_tool",
            "status": "success",
            "tool_result": "ok",
        },
    ]

    summary = infer_evolution_summary(
        events,
        [],
        [],
        restart_expected=True,
        restart_reentered=True,
    )

    assert summary["guarded_tools"]["total"] == 1
    assert summary["guarded_tools"]["restart_guarded"] == 1
    assert summary["tool_phase_sequence_tail"] == [
        "restart_guarded_tool:get_git_status_summary_tool:error",
        "tool:task_list_tool:success",
    ]


def test_infer_evolution_summary_includes_safe_modify_probe_state():
    safe_modify = {
        "path": SAFE_MODIFY_PROBE_PATH,
        "exists": True,
        "marker_present": True,
        "git_dirty": True,
        "cleanup": "pending",
    }

    summary = infer_evolution_summary(
        [],
        [],
        [],
        restart_expected=False,
        restart_reentered=False,
        safe_modify_summary=safe_modify,
    )

    assert summary["safe_modify"] == safe_modify


def test_infer_evolution_summary_extracts_supervised_final_state_marker():
    summary = infer_evolution_summary(
        [],
        [],
        [
            "开始执行 fixture",
            (
                f'{SUPERVISED_FINAL_STATE_MARKER} '
                '{"calendar_event":"rescheduled","new_time":"10:30","verified_after_change":true}'
            ),
        ],
        restart_expected=False,
        restart_reentered=False,
    )

    assert summary["final_state"] == {
        "calendar_event": "rescheduled",
        "new_time": "10:30",
        "verified_after_change": True,
    }
    assert summary["supervised"]["final_state"] == summary["final_state"]


def test_infer_evolution_summary_extracts_supervised_marker_from_llm_response():
    summary = infer_evolution_summary(
        [
            {
                "type": "llm_response",
                "content": (
                    f'{SUPERVISED_FINAL_STATE_MARKER} '
                    '{"calendar_event":"rescheduled","new_time":"10:30","verified_after_change":true}'
                ),
            }
        ],
        [],
        [],
        restart_expected=False,
        restart_reentered=False,
    )

    assert summary["final_state"] == {
        "calendar_event": "rescheduled",
        "new_time": "10:30",
        "verified_after_change": True,
    }
    assert summary["supervised"]["final_state"] == summary["final_state"]


def test_infer_evolution_summary_extracts_supervised_infeasible_outcome_marker_from_debug():
    summary = infer_evolution_summary(
        [],
        [
            (
                f'{SUPERVISED_INFEASIBLE_OUTCOME_MARKER} '
                '{"status":"infeasible","reason":"missing_permission","honest_stop":true}'
            )
        ],
        [],
        restart_expected=False,
        restart_reentered=False,
    )

    assert summary["infeasible_outcome"] == {
        "status": "infeasible",
        "reason": "missing_permission",
        "honest_stop": True,
    }
    assert summary["supervised"]["infeasible_outcome"] == summary["infeasible_outcome"]


def test_infer_evolution_summary_records_invalid_supervised_marker_error():
    summary = infer_evolution_summary(
        [],
        [],
        [f"{SUPERVISED_FINAL_STATE_MARKER} not-json"],
        restart_expected=False,
        restart_reentered=False,
    )

    assert summary["supervised_marker_errors"] == {"final_state": "invalid_json"}
    assert summary["supervised"]["marker_errors"] == {"final_state": "invalid_json"}


def test_infer_evolution_summary_prefers_valid_llm_marker_over_debug_prompt_example():
    summary = infer_evolution_summary(
        [
            {
                "type": "llm_response",
                "content": (
                    "analysis\n"
                    f'{SUPERVISED_AGENT_JUDGMENT_MARKER} '
                    '{"decision":"PROMOTE","baseline_score":0.44,"candidate_score":0.76,'
                    '"reason":"candidate validated","improvement_summary":"better validation",'
                    '"risks":[],"evidence_refs":["candidate_report.json"]}'
                ),
            }
        ],
        [
            (
                "prompt example: "
                f'{SUPERVISED_AGENT_JUDGMENT_MARKER} '
                '{"decision":"HOLD","baseline_score":0.5,"candidate_score":0.5,'
                '"reason":"...","improvement_summary":"...","risks":[],"evidence_refs":[]}'
                ' | scope={"goal":"prompt text"}'
            )
        ],
        [],
        restart_expected=False,
        restart_reentered=False,
    )

    assert "supervised_marker_errors" not in summary
    assert summary["agent_judgment"]["decision"] == "PROMOTE"
    assert summary["agent_judgment"]["candidate_score"] == 0.76
    assert summary["supervised"]["agent_judgment"] == summary["agent_judgment"]


def test_infer_evolution_summary_uses_referenced_judge_response_not_prompt_example(tmp_path: Path):
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    (payload_dir / "turn_1_llm_response.txt").write_text(
        (
            "analysis\n"
            f'{SUPERVISED_AGENT_JUDGMENT_MARKER} '
            '{"decision":"PROMOTE","baseline_score":0.70,"candidate_score":0.85,'
            '"reason":"candidate ran focused tests","improvement_summary":"better validation",'
            '"risks":[],"evidence_refs":["candidate_report.json"]}'
        ),
        encoding="utf-8",
    )
    conversation_path = tmp_path / "conversation_demo.jsonl"
    conversation_path.write_text(
        json.dumps(
            {
                "type": "llm_response",
                "content_inlined": False,
                "content_ref": "payloads/turn_1_llm_response.txt",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    prompt_example_line = (
        f'{SUPERVISED_AGENT_JUDGMENT_MARKER} '
        '{"decision":"HOLD","baseline_score":0.5,"candidate_score":0.5,'
        '"reason":"...","improvement_summary":"...","risks":[],"evidence_refs":[]}'
    )

    summary = infer_evolution_summary(
        read_conversation_events(conversation_path),
        [prompt_example_line],
        [],
        restart_expected=False,
        restart_reentered=False,
    )

    assert "supervised_marker_errors" not in summary
    assert summary["agent_judgment"]["decision"] == "PROMOTE"
    assert summary["agent_judgment"]["baseline_score"] == 0.70
    assert summary["agent_judgment"]["candidate_score"] == 0.85
    assert summary["agent_judgment"]["reason"] == "candidate ran focused tests"


def test_infer_evolution_summary_ignores_prompt_example_as_agent_judgment():
    prompt_example_line = (
        f'{SUPERVISED_AGENT_JUDGMENT_MARKER} '
        '{"decision":"HOLD","baseline_score":0.5,"candidate_score":0.5,'
        '"reason":"...","improvement_summary":"...","risks":[],"evidence_refs":[]}'
    )

    summary = infer_evolution_summary(
        [],
        [prompt_example_line],
        [],
        restart_expected=False,
        restart_reentered=False,
    )

    assert "agent_judgment" not in summary
    assert "agent_judgment" not in summary.get("supervised", {})


def test_validation_passed_for_python_lint_requires_zero_issues():
    assert _validation_passed_for_tool(
        tool_name="python_lint_tool",
        result_text='{"status":"ok","issue_count":0}',
        result_payload={"status": "ok", "issue_count": 0},
    ) is True

    assert _validation_passed_for_tool(
        tool_name="python_lint_tool",
        result_text='{"status":"ok","issue_count":2}',
        result_payload={"status": "ok", "issue_count": 2},
    ) is False


def test_infer_evolution_summary_counts_python_lint_issues_as_failed_validation():
    events = [
        {
            "type": "tool_call",
            "tool_name": "python_lint_tool",
            "status": "success",
            "tool_result": '{"status":"ok","tool":"ruff","issue_count":2,"issues":[{"code":"invalid-syntax"}]}',
        },
    ]

    summary = infer_evolution_summary(
        events,
        [],
        [],
        restart_expected=False,
        restart_reentered=False,
    )

    assert summary["validation"]["passed"] == 0
    assert summary["validation"]["failed"] == 1
    assert summary["validation"]["last"]["passed"] is False


def test_infer_evolution_summary_detects_failed_validation_and_commit_ref():
    events = [
        {
            "type": "tool_call",
            "tool_name": "run_powershell_tool",
            "status": "success",
            "tool_args": {"command": "python -m pytest tests/test_demo.py -q"},
            "tool_result": "FAILED tests/test_demo.py::test_x",
        },
        {
            "type": "tool_call",
            "tool_name": "run_powershell_tool",
            "status": "success",
            "tool_args": {"command": "git commit -m \"fix: demo\""},
            "tool_result": "[main abc1234] fix: demo",
        },
    ]

    summary = infer_evolution_summary(
        events,
        [],
        [],
        restart_expected=False,
        restart_reentered=False,
    )

    assert summary["validation"]["passed"] == 0
    assert summary["validation"]["failed"] == 1
    assert summary["git"]["commit_detected"] is True
    assert summary["restart"]["triggered"] is False


def test_infer_result_status_handles_restart_success():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=True,
        restart_reentered=True,
        primary_returncode=0,
        last_observation={"phase": "restarter_boot"},
    )

    assert status == "success"
    assert "重启接力" in reason


def test_infer_result_status_rejects_unclosed_transaction_probe():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        scenario="transaction",
        evolution_summary={
            "validation": {"passed": 1, "failed": 0},
            "transaction": {
                "opened": True,
                "closed": False,
                "status": None,
            },
        },
    )

    assert status == "failed"
    assert "未关账" in reason


def test_infer_result_status_includes_environment_evidence_for_unclosed_transaction_probe():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        scenario="transaction",
        evolution_summary={
            "environment": {
                "unavailable": True,
                "evidence": "ls: cannot access '/app': No such file or directory",
            },
            "validation": {"passed": 0, "failed": 0},
            "transaction": {
                "opened": True,
                "closed": False,
                "status": None,
            },
        },
    )

    assert status == "failed"
    assert "任务环境不可用" in reason
    assert "/app" in reason
    assert "未关账" in reason


def test_infer_result_status_rejects_transaction_probe_without_tool_activity():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        scenario="transaction",
        evolution_summary={
            "validation": {"passed": 0, "failed": 0},
            "transaction": {
                "opened": False,
                "closed": False,
                "status": None,
            },
        },
    )

    assert status == "failed"
    assert "未开账" in reason


def test_infer_result_status_prefers_provider_transport_error_over_missing_transaction():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "provider_transport_error"},
        scenario="transaction",
        evolution_summary={
            "validation": {"passed": 0, "failed": 0},
            "transaction": {
                "opened": False,
                "closed": False,
                "status": None,
            },
            "llm_failure": {
                "detected": True,
                "category": "provider_transport_error",
                "retryable": True,
                "message": "UNEXPECTED_EOF_WHILE_READING",
            },
        },
    )

    assert status == "failed"
    assert "provider 传输异常" in reason
    assert "未开账" not in reason


def test_infer_result_status_requires_dynamic_fixture_final_state_marker():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        scenario="dynamic_replanning_fixture",
        evolution_summary={
            "validation": {"passed": 0, "failed": 0},
            "transaction": {"opened": False, "closed": False, "status": None},
        },
    )

    assert status == "failed"
    assert "final_state marker" in reason


def test_infer_result_status_accepts_dynamic_fixture_final_state_marker():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        scenario="dynamic_replanning_fixture",
        evolution_summary={
            "final_state": {"calendar_event": "rescheduled", "verified_after_change": True},
            "supervised": {
                "final_state": {"calendar_event": "rescheduled", "verified_after_change": True}
            },
        },
    )

    assert status == "success"
    assert "正常结束" in reason


def test_infer_result_status_requires_impossible_fixture_infeasible_marker():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        scenario="impossible_task_fixture",
        evolution_summary={
            "supervised": {
                "marker_errors": {"infeasible_outcome": "invalid_json"},
            },
        },
    )

    assert status == "failed"
    assert "marker 格式无效" in reason


def test_infer_result_status_accepts_impossible_fixture_infeasible_marker():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        scenario="impossible_task_fixture",
        evolution_summary={
            "supervised": {
                "infeasible_outcome": {
                    "status": "infeasible",
                    "reason": "missing_permission",
                    "honest_stop": True,
                },
            },
        },
    )

    assert status == "success"
    assert "正常结束" in reason


def test_single_turn_direct_response_does_not_finish_tool_required_probe():
    should_finish = TurnOutcomeController.should_finish_single_turn_after_direct_response(
        single_turn_mode_active=True,
        tool_calls=[],
        visible_text="我会开始执行。",
        active_goal="调用 open_evolution_transaction_tool 开账，然后调用 python_lint_tool。",
        active_evolution_txn_id=None,
    )

    assert should_finish is False


def test_infer_result_status_handles_timeout_with_phase():
    status, reason = infer_result_status(
        timed_out=True,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=None,
        last_observation={"phase": "tool:read_file_tool:success"},
    )

    assert status == "timeout"
    assert "read_file_tool" in reason


def test_count_meaningful_tool_steps_ignores_git_helper_reads(tmp_path: Path):
    log_info = tmp_path / "log_info"
    log_info.mkdir()
    (log_info / "conversation_case.jsonl").write_text(
        "\n".join(
            [
                '{"type":"tool_call","tool_name":"open_evolution_transaction_tool","status":"success"}',
                '{"type":"tool_call","tool_name":"get_git_status_tool","status":"success"}',
                '{"type":"tool_call","tool_name":"cli_tool","status":"success"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert count_meaningful_tool_steps(log_info) == 2


def test_infer_evolution_summary_extracts_environment_unavailable_from_tool_result():
    summary = infer_evolution_summary(
        [
            {
                "type": "tool_call",
                "tool_name": "cli_tool",
                "status": "success",
                "tool_args": {"command": "ls /app"},
                "tool_result": "ls: cannot access '/app/': No such file or directory",
            }
        ],
        [],
        [],
        restart_expected=False,
        restart_reentered=False,
    )

    assert summary["environment"]["unavailable"] is True
    assert "/app" in summary["environment"]["evidence"]


def test_infer_result_status_requires_complete_safe_modify_probe():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        scenario="modify_rollback",
        evolution_summary={
            "safe_modify": {
                "exists": True,
                "marker_present": True,
                "out_of_scope_paths": [],
            },
            "validation": {
                "passed": 0,
            },
            "transaction": {
                "opened": True,
                "closed": False,
                "status": None,
            },
        },
    )

    assert status == "failed"
    assert "事务未关账" in reason


def test_infer_result_status_rejects_safe_modify_without_transaction_open():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        scenario="modify_rollback",
        evolution_summary={
            "safe_modify": {
                "exists": True,
                "marker_present": True,
                "out_of_scope_paths": [],
            },
            "validation": {
                "passed": 1,
            },
            "transaction": {
                "opened": False,
                "closed": True,
                "status": "success",
            },
        },
    )

    assert status == "failed"
    assert "事务未开账" in reason


def test_infer_result_status_reports_failed_safe_modify_validation_close():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        scenario="modify_rollback",
        evolution_summary={
            "safe_modify": {
                "exists": True,
                "marker_present": True,
                "out_of_scope_paths": [],
            },
            "validation": {
                "passed": 0,
                "failed": 1,
            },
            "transaction": {
                "opened": True,
                "closed": True,
                "status": "failed",
            },
        },
    )

    assert status == "failed"
    assert "验证失败" in reason
    assert "失败状态关账" in reason


def test_infer_result_status_reports_clean_terminal_bench_environment_unavailable_close():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        scenario="transaction",
        evolution_summary={
            "validation": {
                "passed": 0,
                "failed": 1,
                "last": {
                    "tool": "cli_tool",
                    "passed": False,
                    "summary": "ls: cannot access '/app/': No such file or directory",
                },
            },
            "transaction": {
                "opened": True,
                "closed": True,
                "status": "failed",
                "txn_id": "txn_env",
            },
        },
    )

    assert status == "failed"
    assert "任务环境不可用" in reason
    assert "失败状态关账" in reason


def test_infer_result_status_rejects_out_of_scope_safe_modify_paths():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        scenario="modify_rollback",
        evolution_summary={
            "safe_modify": {
                "exists": True,
                "marker_present": True,
                "out_of_scope_paths": ["agent.py"],
            },
            "validation": {
                "passed": 1,
            },
            "transaction": {
                "opened": True,
                "closed": True,
                "status": "success",
            },
        },
    )

    assert status == "failed"
    assert "越界文件修改" in reason


def test_infer_result_status_accepts_complete_safe_modify_probe():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=False,
        restart_reentered=False,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
        scenario="modify_rollback",
        evolution_summary={
            "safe_modify": {
                "exists": True,
                "marker_present": True,
                "out_of_scope_paths": [],
            },
            "validation": {
                "passed": 1,
            },
            "transaction": {
                "opened": True,
                "closed": True,
                "status": "success",
            },
        },
    )

    assert status == "success"
    assert "主进程正常结束" in reason


def test_extend_deadline_for_restart_trigger_grants_observation_window():
    deadline = extend_deadline_for_restart_trigger(
        current_deadline=100.0,
        now=99.5,
        post_restart_observe_seconds=20,
    )

    assert deadline == 119.5


def test_extend_deadline_for_restart_trigger_never_shortens_deadline():
    deadline = extend_deadline_for_restart_trigger(
        current_deadline=200.0,
        now=99.5,
        post_restart_observe_seconds=20,
    )

    assert deadline == 200.0


def test_summarize_latest_matching_file_uses_most_recent(tmp_path: Path):
    older = tmp_path / "conversation_older.jsonl"
    newer = tmp_path / "conversation_newer.jsonl"
    older.write_text('{"type":"llm_response","content":"old"}\n', encoding="utf-8")
    newer.write_text('{"type":"tool_call","tool_name":"task_create_tool","status":"success"}\n', encoding="utf-8")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    summary = summarize_latest_matching_file(tmp_path, "conversation_*.jsonl", summarize_conversation_file)

    assert summary["path"].endswith("conversation_newer.jsonl")
    assert summary["phase"] == "tool:task_create_tool:success"


def test_is_restart_trigger_line_detects_windows_handoff_markers():
    assert is_restart_trigger_line("22:02:19 -- Windows: 已启动脱离进程, PID: 37044")
    assert is_restart_trigger_line("22:02:19 -- 重启触发成功")
    assert not is_restart_trigger_line("22:01:40 >> task_update_tool OK")


def test_infer_result_status_restart_success_still_allows_process_only_post_observation():
    status, reason = infer_result_status(
        timed_out=False,
        restart_expected=True,
        restart_reentered=True,
        primary_returncode=0,
        last_observation={"phase": "session_end"},
    )

    assert status == "success"
    assert "重启接力" in reason


def test_summarize_agent_state_file_extracts_semantic_phase(tmp_path: Path):
    state_path = tmp_path / "agent_state.json"
    state_path.write_text(
        '{"status":"THINKING","current_action":"正在分析重启后的环境","current_goal":"验证重启闭环","iteration_count":2,"tools_executed":1,"last_update":"2026-05-10T22:10:50"}',
        encoding="utf-8",
    )

    summary = summarize_agent_state_file(state_path)

    assert summary["status"] == "THINKING"
    assert summary["phase"].startswith("state:THINKING:")
    assert "正在分析重启后的环境" in summary["current_action"]


def test_infer_phase_from_agent_state_handles_missing_action():
    phase = infer_phase_from_agent_state({"status": "RESTARTING"})
    assert phase == "state:RESTARTING"


def test_find_agent_processes_contract_without_psutil(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("scripts.evolution_harness.psutil", None)
    from scripts.evolution_harness import find_agent_processes

    assert find_agent_processes(tmp_path) == []


def test_find_agent_processes_prefers_restarter_role_when_cmd_mentions_both(monkeypatch, tmp_path: Path):
    class FakeProc:
        def __init__(self):
            self.pid = 123
            self.info = {
                "pid": 123,
                "name": "python",
                "cmdline": [
                    "python",
                    "-m",
                    "core.restarter_manager.restarter",
                    "--script",
                    str(tmp_path / "agent.py"),
                ],
                "cwd": str(tmp_path),
            }

    class FakePsutil:
        NoSuchProcess = RuntimeError
        AccessDenied = RuntimeError

        @staticmethod
        def process_iter(_fields):
            return [FakeProc()]

    monkeypatch.setattr("scripts.evolution_harness.psutil", FakePsutil)
    from scripts.evolution_harness import find_agent_processes

    result = find_agent_processes(tmp_path)

    assert result[0]["role"] == "restarter"


def test_summarize_process_history_groups_windows_python_wrappers():
    records = [
        ProcessRecord(
            pid=10,
            role="agent",
            first_seen="2026-05-11T10:00:00",
            last_seen="2026-05-11T10:00:01",
            cmdline_preview=r"C:\repo\.venv\Scripts\python.exe agent.py --no-shell --test",
        ),
        ProcessRecord(
            pid=11,
            role="agent",
            first_seen="2026-05-11T10:00:02",
            last_seen="2026-05-11T10:00:03",
            cmdline_preview=r"C:\runtime\python.exe C:\repo\agent.py --no-shell --test",
        ),
        ProcessRecord(
            pid=12,
            role="restarter",
            first_seen="2026-05-11T10:00:02",
            last_seen="2026-05-11T10:00:03",
            cmdline_preview=r"python -m core.restarter_manager.restarter --script C:\repo\agent.py",
        ),
    ]

    summary = summarize_process_history(records, reentered_agent_pids=[11])

    assert summary["raw_count"] == 3
    assert summary["role_counts"]["agent"] == 2
    assert summary["unique_agent_families"] == 1
    assert summary["unique_restarter_families"] == 1
    assert summary["normalized_reentered_agent_count"] == 1
    assert summary["duplicate_families"][0]["count"] == 2


def test_infer_first_meaningful_event_prefers_first_tool_call():
    events = [
        {"type": "session_start"},
        {"type": "debug", "message": "noise"},
        {"type": "tool_call", "tool_name": "task_create_tool", "status": "success", "summary": "created"},
        {"type": "llm_response", "content": "later"},
    ]

    summary = infer_first_meaningful_event(events)

    assert summary["phase"] == "first_tool:task_create_tool:success"
    assert summary["tool_name"] == "task_create_tool"


def test_infer_first_meaningful_event_prefers_later_tool_over_prompt_refresh():
    events = [
        {"type": "debug", "message": "[PromptManager] 构建完成"},
        {"type": "llm_response", "content": "准备行动"},
        {"type": "tool_call", "tool_name": "get_git_status_summary_tool", "status": "error", "summary": "guarded"},
    ]

    summary = infer_first_meaningful_event(events)

    assert summary["phase"] == "first_tool:get_git_status_summary_tool:error"
    assert summary["tool_name"] == "get_git_status_summary_tool"


def test_infer_post_restart_phase_prefers_first_child_tool_over_prompt_refresh():
    phase = infer_post_restart_phase(
        {"phase": "no_state"},
        {
            "phase": "prompt_refresh",
            "first_meaningful_event": {
                "phase": "first_tool:task_update_tool:success",
                "tool_name": "task_update_tool",
            },
        },
        {"phase": "prompt_refresh"},
    )

    assert phase == "first_tool:task_update_tool:success"


def test_build_post_restart_observation_surfaces_first_child_fields():
    observation = build_post_restart_observation(
        live_agent_pids=[101],
        reentered_agent_pids=[101],
        reentered_processes=[{"pid": 101, "role": "agent"}],
        state_summary={"phase": "no_state"},
        conversation_summary={
            "phase": "prompt_refresh",
            "prompt_build": {"tag": "prompt_build", "message": "mode=execute len=2048"},
            "first_meaningful_event": {
                "phase": "first_tool:trigger_self_restart_tool:success",
                "tool_name": "trigger_self_restart_tool",
                "message": "restart",
            },
        },
        debug_summary={"phase": "prompt_refresh"},
    )

    assert observation["phase"] == "first_tool:trigger_self_restart_tool:success"
    assert observation["first_child_event_phase"] == "first_tool:trigger_self_restart_tool:success"
    assert observation["first_child_tool_name"] == "trigger_self_restart_tool"
    assert observation["prompt_build"]["message"] == "mode=execute len=2048"


def test_summarize_conversation_file_extracts_prompt_build(tmp_path):
    path = tmp_path / "conversation.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"type":"debug","tag":"prompt_build","message":"mode=diagnose len=2048 rendered=SOUL,SPEC_DIGEST"}',
                '{"type":"debug","message":"[PromptManager] 构建完成"}',
            ]
        ),
        encoding="utf-8",
    )

    summary = summarize_conversation_file(path)

    assert summary["prompt_build"]["tag"] == "prompt_build"
    assert "mode=diagnose" in summary["prompt_build"]["message"]
