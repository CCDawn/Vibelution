from types import SimpleNamespace

from core.orchestration.delegation_governor import DelegationGovernor


def _governor(snapshot=None, *, session=None):
    return DelegationGovernor(
        spawn_execute=lambda *_args, **_kwargs: ("{}", None),
        sync_runtime_state_memory=lambda: None,
        ui_getter=lambda: None,
        session_getter=lambda: session
        or SimpleNamespace(
            get_attention_snapshot=lambda: snapshot or {},
            has_recent_delegation=lambda *_args, **_kwargs: False,
            _normalize_scope_signature=lambda scope: str(scope),
        ),
    )


def test_contains_any_treats_string_keywords_as_one_phrase():
    assert DelegationGovernor.contains_any("hello", "log") is False
    assert DelegationGovernor.contains_any("read the log", "log") is True


def test_string_modified_path_counts_as_one_file():
    assert DelegationGovernor.has_delegation_reading_load(
        {
            "modified_paths": "core/orchestration/delegation_governor.py",
            "recent_blockers": [],
        }
    ) is False


def test_string_blockers_and_history_do_not_crash():
    assert DelegationGovernor.has_delegation_reading_load(
        {"modified_paths": [], "recent_blockers": "not-a-list"}
    ) is False
    assert DelegationGovernor.should_cooldown_delegation({"delegation_history": "oops"}, "diagnose") is False
    assert DelegationGovernor.is_unhelpful_terminal_delegation("failed") is False


def test_string_false_validation_flag_is_not_success():
    assert DelegationGovernor.is_success_validation_summary("", "false") is False
    assert DelegationGovernor.is_success_validation_summary("ruff lint 通过", "false") is True
    assert DelegationGovernor.is_success_validation_summary("anything", True) is True


def test_infer_role_need_coerces_string_counters():
    governor = _governor()
    need = governor.infer_role_need(
        goal="检查当前配置 config.toml",
        snapshot={
            "modified_paths": ["core/orchestration/delegation_governor.py", "agent.py"],
            "recent_blockers": [],
        },
        iteration="2",
        total_tool_calls="0",
        readonly_diagnostic_goal=False,
        readonly_summary_goal=False,
        explicit_inspect_goal=True,
        summary_goal_requested=False,
        summary_evidence_ready=False,
        reading_load_ready=True,
        last_validation_summary="",
    )
    assert need is not None
    assert need.task_type == "inspect"


def test_build_request_survives_string_snapshot_lists():
    governor = _governor(
        {
            "last_validation_summary": "",
            "last_validation_passed": "false",
            "recent_blockers": "not-a-list",
            "modified_paths": "core/orchestration/delegation_governor.py",
            "delegation_history": "oops",
            "delegation_failures": "oops",
            "delegation_evidence_digest": "",
        }
    )
    request = governor.build_request(
        goal="只做诊断 core/orchestration/delegation_governor.py，不要修改代码",
        iteration="1",
        total_tool_calls="0",
    )
    assert request is not None
    assert request["task_type"] == "diagnose"
