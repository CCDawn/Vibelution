"""Shadow-approval evaluator: four-hypothesis end states, stable ruleIds,
pure-boundary (no storage reads), env switch, bounded telemetry, and a
parity matrix against the real auto-approval chain (drift alarm).

判定/落账走真代码：本文件只桩模型侧不涉及的任何东西——免批链复刻与真实
``tool_approvals._can_auto_approve`` 在同一输入矩阵上逐位对账；workspace 根
与 agent 目录等 I/O 点按影子纯化边界注入/monkeypatch，证明影子侧不重读。
"""

from __future__ import annotations

import pytest

from core.authorization import shadow_approval_evaluator as ev
from core.web.services.session import tool_approvals


@pytest.fixture(autouse=True)
def _reset_shadow_state(monkeypatch):
    monkeypatch.delenv(ev.SHADOW_APPROVALS_ENV, raising=False)
    ev.reset_shadow_telemetry()
    ev.set_shadow_approval_telemetry_sink(None)
    yield
    ev.reset_shadow_telemetry()
    ev.set_shadow_approval_telemetry_sink(None)
    monkeypatch.delenv(ev.SHADOW_APPROVALS_ENV, raising=False)


def _snapshot(**changes):
    base = dict(
        tool_name="web_search_tool",
        risk="network",
        decision_arguments={"query": "q"},
        permission_preset="request_approval",
        reminder_recovery=False,
        policy_id="tool-agent-a",
        approval_baseline="on_request",
        approval_descriptor="on_request",
    )
    base.update(changes)
    return ev.ShadowApprovalSnapshot(**base)


# ---------------------------------------------------------------------------
# Four-hypothesis end states with ruleId evidence
# ---------------------------------------------------------------------------


def test_pa_message_override_off_turns_free_dispatch_into_human_pending():
    snapshot = _snapshot(
        tool_name="agent_message_tool",
        risk="write",
        approval_baseline="never",
        approval_descriptor="on_request",
        permission_preset="request_approval",
    )
    evaluation = ev.evaluate_shadow_approvals(snapshot, real_outcome_code="approval_not_required")

    assert evaluation.baseline.outcome == "approved_auto"
    assert evaluation.baseline.rule_gate == "shadow.approval.never"
    assert evaluation.baseline.rule_id == "tool-agent-a:shadow.approval.never:approved_auto"
    # 关闭 PA 派发豁免：on_request + request_approval 预设下落到人工 pending。
    assert evaluation.no_pa_message_override.outcome == "needs_human"
    assert evaluation.no_pa_message_override.rule_gate == "shadow.approval.pending"
    assert evaluation.no_pa_message_override.rule_id == "tool-agent-a:shadow.approval.pending:needs_human"
    # 无区分度的假设退化为基线克隆。
    assert evaluation.no_external_write_override == evaluation.baseline
    assert evaluation.no_action_window == evaluation.baseline
    # 复刻基线与权威基线一致（outcome 揭示 never 短路）。
    assert evaluation.replica_baseline_agrees


def test_external_write_override_off_auto_approves_contained_workspace_write(monkeypatch, tmp_path):
    (tmp_path / "workspace").mkdir()
    monkeypatch.setattr("tools.shell_tools._get_workspace_root", lambda: tmp_path / "workspace")
    snapshot = _snapshot(
        tool_name="write_file_tool",
        risk="write",
        decision_arguments={"file_path": "workspace/report.md"},
        permission_preset="auto_review",
        approval_baseline="always",
        approval_descriptor="on_request",
    )
    evaluation = ev.evaluate_shadow_approvals(snapshot, real_outcome_code="approval_timeout")

    # 基线：always 覆盖下等待人工、超时 fail-closed。
    assert evaluation.baseline.outcome == "needs_human"
    assert evaluation.baseline.rule_gate == "shadow.approval.pending"
    # 关闭外部代理写 always 覆盖：auto_review 预设下工作区内路径自动批准。
    assert evaluation.no_external_write_override.outcome == "approved_auto"
    assert evaluation.no_external_write_override.rule_gate == "shadow.approval.auto_review"
    assert evaluation.no_external_write_override.rule_id == (
        "tool-agent-a:shadow.approval.auto_review:approved_auto"
    )
    assert evaluation.no_pa_message_override == evaluation.baseline
    assert evaluation.no_action_window == evaluation.baseline


def test_external_write_override_kept_for_absolute_out_of_workspace_path(monkeypatch, tmp_path):
    (tmp_path / "workspace").mkdir()
    monkeypatch.setattr("tools.shell_tools._get_workspace_root", lambda: tmp_path / "workspace")
    snapshot = _snapshot(
        tool_name="write_file_tool",
        risk="write",
        decision_arguments={"file_path": "C:/outside/evil.md"},
        permission_preset="auto_review",
        approval_baseline="always",
        approval_descriptor="on_request",
    )
    evaluation = ev.evaluate_shadow_approvals(snapshot, real_outcome_code="approval_timeout")

    assert evaluation.baseline.outcome == "needs_human"
    # 逃逸出 workspace 的路径即使在假设下也仍需人工。
    assert evaluation.no_external_write_override.outcome == "needs_human"
    assert evaluation.no_external_write_override.rule_gate == "shadow.approval.pending"


def test_action_window_off_returns_windowed_auto_call_to_human():
    snapshot = _snapshot(
        tool_name="personal_assistant_manage_tool",
        risk="write",
        decision_arguments={"action": "session_create"},
        permission_preset="request_approval",
        approval_baseline="on_request",
        approval_descriptor="on_request",
    )
    evaluation = ev.evaluate_shadow_approvals(snapshot, real_outcome_code="approved_for_action_window")

    assert evaluation.baseline.outcome == "approved_auto"
    assert evaluation.baseline.rule_gate == "shadow.approval.action_window"
    assert evaluation.baseline.rule_id == "tool-agent-a:shadow.approval.action_window:approved_auto"
    # 关闭窗口：request_approval 预设下 manage 工具回到人工 pending。
    assert evaluation.no_action_window.outcome == "needs_human"
    assert evaluation.no_action_window.rule_gate == "shadow.approval.pending"
    assert evaluation.no_pa_message_override == evaluation.baseline
    assert evaluation.no_external_write_override == evaluation.baseline


def test_action_window_hypothesis_is_baseline_clone_when_window_did_not_fire():
    snapshot = _snapshot()
    evaluation = ev.evaluate_shadow_approvals(snapshot, real_outcome_code="approval_declined")
    assert evaluation.no_action_window == evaluation.baseline


def test_session_grant_baseline_reveals_grant_gate_and_replica_agrees():
    evaluation = ev.evaluate_shadow_approvals(_snapshot(), real_outcome_code="approved_for_session")
    assert evaluation.baseline.outcome == "approved_for_session"
    assert evaluation.baseline.rule_gate == "shadow.approval.session_grant"
    assert evaluation.baseline.rule_id == "tool-agent-a:shadow.approval.session_grant:approved_for_session"
    assert evaluation.replica_baseline_agrees


def test_human_accepted_baseline_is_pending_gate():
    evaluation = ev.evaluate_shadow_approvals(_snapshot(), real_outcome_code="approved")
    assert evaluation.baseline.outcome == "needs_human"
    assert evaluation.baseline.rule_gate == "shadow.approval.pending"
    assert evaluation.replica_baseline_agrees


def test_full_access_auto_approval_baseline_gate():
    snapshot = _snapshot(permission_preset="full_access")
    evaluation = ev.evaluate_shadow_approvals(snapshot, real_outcome_code="full_access_auto_approved")
    assert evaluation.baseline.outcome == "approved_auto"
    assert evaluation.baseline.rule_gate == "shadow.approval.full_access"
    assert evaluation.replica_baseline_agrees
    # full_access 预设下，关闭 PA 豁免也照样自动批准（预设先于 approval）。
    pa_snapshot = _snapshot(
        permission_preset="full_access",
        tool_name="agent_message_tool",
        approval_baseline="never",
        approval_descriptor="on_request",
    )
    pa_evaluation = ev.evaluate_shadow_approvals(pa_snapshot, real_outcome_code="approval_not_required")
    assert pa_evaluation.no_pa_message_override.outcome == "approved_auto"


def test_unknown_outcome_code_degrades_to_pending_baseline():
    evaluation = ev.evaluate_shadow_approvals(_snapshot(), real_outcome_code="")
    assert evaluation.baseline.outcome == "needs_human"
    assert evaluation.baseline.rule_gate == "shadow.approval.pending"


def test_unknown_descriptor_falls_back_to_baseline_clone():
    snapshot = _snapshot(
        tool_name="agent_message_tool",
        approval_baseline="never",
        approval_descriptor="",
    )
    evaluation = ev.evaluate_shadow_approvals(snapshot, real_outcome_code="approval_not_required")
    assert evaluation.no_pa_message_override == evaluation.baseline


def test_reminder_recovery_pins_hypotheses_to_baseline():
    snapshot = _snapshot(
        tool_name="agent_message_tool",
        approval_baseline="never",
        approval_descriptor="on_request",
        reminder_recovery=True,
    )
    evaluation = ev.evaluate_shadow_approvals(snapshot, real_outcome_code="approval_timeout")
    assert evaluation.no_pa_message_override == evaluation.baseline


# ---------------------------------------------------------------------------
# Parity matrix against the real chain predicate (drift alarm)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_name,args",
    [
        ("cli_tool", {"cmd": "git status"}),
        ("cli_tool", {"cmd": "git push origin main"}),
        ("cli_tool", {"command": "git -c core.pager=cat log --oneline"}),
        ("cli_tool", {"cmd": "git status && rm -rf /"}),
        ("cli_tool", {"cmd": "ls -la"}),
        ("exec_command", {"cmd": "git diff"}),
        ("write_stdin", {"session_id": "term-a", "chars": "y"}),
        ("apply_diff_edit_tool", {"file_path": "workspace/inner/file.md"}),
        ("apply_diff_edit_tool", {"file_path": "C:/outside/file.md"}),
        ("apply_patch_tool", {"patch_text": "*** Update File: workspace/a.md\n+++ content"}),
        ("apply_patch_tool", {"patch_text": "*** Update File: C:/outside/a.md\n+++ content"}),
        ("write_file_tool", {"file_path": "workspace/a.md"}),
        ("web_search_tool", {"query": "q"}),
    ],
)
@pytest.mark.parametrize("permission_preset", ["request_approval", "auto_review", "full_access"])
@pytest.mark.parametrize("approval", ["on_request", "always"])
@pytest.mark.parametrize("risk", ["read", "write", "network", "destructive"])
def test_replica_auto_approve_matches_real_chain_on_matrix(
    monkeypatch, tmp_path, tool_name, args, permission_preset, approval, risk
):
    (tmp_path / "workspace").mkdir()
    monkeypatch.setattr("tools.shell_tools._get_workspace_root", lambda: tmp_path / "workspace")
    real = tool_approvals._can_auto_approve(
        permission_preset=permission_preset,
        tool_name=tool_name,
        tool_args=args,
        approval=approval,
        risk=risk,
    )
    replica = ev._can_auto_approve(
        permission_preset=permission_preset,
        tool_name=tool_name,
        tool_args=args,
        approval=approval,
        risk=risk,
    )
    assert replica == real


def test_replica_constants_match_real_chain_tables():
    """复刻常量与真实链表逐字对账，防止静默漂移。"""

    assert ev._SANDBOX_CONTAINED_TOOLS == tool_approvals._SANDBOX_CONTAINED_TOOLS
    assert ev._WORKSPACE_PATH_TOOLS == tool_approvals._WORKSPACE_PATH_TOOLS
    assert ev._CLI_SHELL_TOOLS == {"cli_tool", "exec_command"}
    assert ev._SAFE_READONLY_GIT_SUBCOMMANDS == tool_approvals._SAFE_READONLY_GIT_SUBCOMMANDS
    assert ev._SAFE_READONLY_GIT_STASH_ACTIONS == tool_approvals._SAFE_READONLY_GIT_STASH_ACTIONS
    assert ev._SAFE_READONLY_GIT_REMOTE_ACTIONS == tool_approvals._SAFE_READONLY_GIT_REMOTE_ACTIONS
    assert ev._SAFE_READONLY_GIT_CONFIG_ACTIONS == tool_approvals._SAFE_READONLY_GIT_CONFIG_ACTIONS
    assert ev._UNSAFE_GIT_FLAG_TOKENS == tool_approvals._UNSAFE_GIT_FLAG_TOKENS


def test_hypothesis_objects_match_declared_sources():
    """高价值假设对象与真实策略源对账（contracts / PA policy）。"""

    from core.web.services.external_management import contracts
    from core.web.services import personal_assistant_service

    preset = contracts.agent_create_tool_policy("project_files_v1")
    overrides = preset["approvalOverrides"]
    assert ev.EXTERNAL_WRITE_OVERRIDE_TOOLS == {"apply_diff_edit_tool", "write_file_tool"}
    assert set(overrides) == ev.EXTERNAL_WRITE_OVERRIDE_TOOLS
    assert all(mode == "always" for mode in overrides.values())
    pa_overrides = personal_assistant_service.current_policy()["approvalOverrides"]
    assert pa_overrides == {ev.PA_MESSAGE_OVERRIDE_TOOL: "never"}


# ---------------------------------------------------------------------------
# Purity: the shadow side never re-reads storage
# ---------------------------------------------------------------------------


def test_evaluator_does_not_reach_into_agent_storage(monkeypatch):
    """durable grant 的读 I/O 点被注入替代：即便目录存储炸掉，评估也不受影响。"""

    from core.web.services.session import tool_approvals

    def _explode(*_args, **_kwargs):
        raise RuntimeError("shadow must not read agent storage")

    monkeypatch.setattr(tool_approvals, "_canonical_agent_configs", _explode)
    monkeypatch.setattr(
        "core.web.services.session.assistant_manage_policy.assistant_action_window_remaining",
        _explode,
    )
    snapshot = _snapshot()
    evaluation = ev.evaluate_shadow_approvals(snapshot, real_outcome_code="approved_for_session")
    assert evaluation.baseline.outcome == "approved_for_session"
    assert evaluation.replica_baseline_agrees


# ---------------------------------------------------------------------------
# Outcome revelation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,expected",
    [
        ("approval_not_required", (True, False, False, False, False, False, "")),
        ("full_access_auto_approved", (False, True, False, False, False, False, "")),
        ("approved_for_action_window", (False, False, True, False, False, False, "")),
        ("approved_for_session", (False, False, False, True, False, False, "")),
        ("approved_for_agent", (False, False, False, False, True, False, "")),
        ("auto_approved", (False, False, False, False, False, True, "")),
        ("approved", (False, False, False, False, False, False, "approved")),
        ("approval_declined", (False, False, False, False, False, False, "declined")),
        ("approval_timeout", (False, False, False, False, False, False, "timeout")),
        ("approval_cancelled", (False, False, False, False, False, False, "cancelled")),
    ],
)
def test_reveal_chain_facts_mapping(code, expected):
    facts = ev.reveal_chain_facts(code)
    assert (
        facts.approval_not_required,
        facts.full_access_hit,
        facts.action_window_hit,
        facts.session_grant_hit,
        facts.durable_grant_hit,
        facts.auto_approve_hit,
        facts.human_resolution,
    ) == expected


# ---------------------------------------------------------------------------
# Env switch (default shadow; off only; no enforce tier)
# ---------------------------------------------------------------------------


def test_shadow_enabled_by_default(monkeypatch):
    monkeypatch.delenv(ev.SHADOW_APPROVALS_ENV, raising=False)
    assert ev.shadow_approvals_enabled() is True


@pytest.mark.parametrize("raw", ["off", "0", "false", "no", "disabled", "OFF", " False "])
def test_shadow_disabled_by_explicit_off_values(monkeypatch, raw):
    monkeypatch.setenv(ev.SHADOW_APPROVALS_ENV, raw)
    assert ev.shadow_approvals_enabled() is False


@pytest.mark.parametrize("raw", ["enforce", "on", "1", "true", "yes", "observe", "shadow"])
def test_no_enforce_tier_everything_else_stays_shadow(monkeypatch, raw):
    """一期纯观察：任何非 off 值（含 enforce）都停留在观察档，绝不升级行为。"""

    monkeypatch.setenv(ev.SHADOW_APPROVALS_ENV, raw)
    assert ev.shadow_approvals_enabled() is True


# ---------------------------------------------------------------------------
# Bounded telemetry (turn_journal hook form)
# ---------------------------------------------------------------------------


def test_telemetry_counters_and_sink_receive_bounded_records():
    records: list[dict] = []
    ev.set_shadow_approval_telemetry_sink(records.append)
    ev.bump_shadow_telemetry(engaged=1)
    ev.bump_shadow_telemetry(engaged=1, recorded=1)
    ev.bump_shadow_telemetry(unknown_key=5)  # 有界固定键：未知键被丢弃

    snapshot = ev.shadow_approval_telemetry()
    assert snapshot["engaged"] == 2
    assert snapshot["recorded"] == 1
    assert "unknown_key" not in snapshot
    assert records == [{"engaged": 1}, {"engaged": 2, "recorded": 1}]


def test_telemetry_sink_must_never_break_the_caller():
    def _boom(_record):
        raise RuntimeError("sink exploded")

    ev.set_shadow_approval_telemetry_sink(_boom)
    ev.bump_shadow_telemetry(engaged=1)
    assert ev.shadow_approval_telemetry()["engaged"] == 1


def test_rule_id_is_policy_scoped_and_bounded():
    long_policy = "p" * 200
    rule_id = ev.compose_shadow_rule_id(long_policy, "shadow.approval.pending", "needs_human")
    assert rule_id == ev.compose_shadow_rule_id(long_policy, "shadow.approval.pending", "needs_human")
    assert len(rule_id) <= ev.MAX_RULE_ID_LENGTH
    assert ev.compose_shadow_rule_id("", "", "needs_human").startswith("policy-unresolved:")
