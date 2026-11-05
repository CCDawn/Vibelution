from core.runtime_manager.work_run_leases import (
    WorkRunLeaseRequest,
    check_lease_conflicts,
    infer_chat_turn_leases,
)

def test_readonly_chat_can_overlap_with_supervised_run():
    active = [
        {
            "runId": "supervised_1",
            "runKind": "supervised_evolution_run",
            "leases": ["evaluation"],
            "status": "running",
        }
    ]
    request = WorkRunLeaseRequest(run_kind="chat_turn", leases=["readonly_chat"])

    result = check_lease_conflicts(request, active)

    assert result.allowed is True
    assert result.conflicts == []


def test_coding_chat_conflicts_with_self_evolution_write_run():
    active = [
        {
            "runId": "self_1",
            "runKind": "self_evolution_run",
            "leases": ["evolution_transaction", "worktree_write", "memory_write"],
            "status": "running",
        }
    ]
    request = WorkRunLeaseRequest(run_kind="chat_turn", leases=["worktree_write"])

    result = check_lease_conflicts(request, active)

    assert result.allowed is False
    assert "worktree_write" in result.reason
    assert result.conflicts[0]["runId"] == "self_1"


def test_supervised_evaluation_conflicts_with_self_evolution_transaction():
    active = [
        {
            "runId": "self_1",
            "runKind": "self_evolution_run",
            "status": "running",
        }
    ]
    request = WorkRunLeaseRequest(run_kind="supervised_evolution_run", leases=["evaluation"])

    result = check_lease_conflicts(request, active)

    assert result.allowed is False
    assert "evaluation" in result.reason


def test_final_runs_and_unknown_leases_do_not_block_requests():
    active = [
        {
            "runId": "old_self",
            "runKind": "self_evolution_run",
            "leases": ["worktree_write"],
            "status": "done",
        },
        {
            "runId": "legacy",
            "runKind": "legacy",
            "leases": ["future_observer"],
            "status": "running",
        },
    ]
    request = WorkRunLeaseRequest(run_kind="chat_turn", leases=["worktree_write"])

    result = check_lease_conflicts(request, active)

    assert result.allowed is True


def test_infer_chat_turn_leases_defaults_to_readonly_and_marks_write_intent():
    assert infer_chat_turn_leases({"content": "解释当前状态"}) == ["readonly_chat"]
    assert infer_chat_turn_leases({"mode": "coding", "content": "修改这个 bug"}) == ["worktree_write", "memory_write"]
    assert infer_chat_turn_leases({"writeIntent": True}) == ["worktree_write", "memory_write"]
    assert infer_chat_turn_leases({"content": "继续", "activeTask": {"status": "editing"}}) == [
        "worktree_write",
        "memory_write",
    ]


def test_keyword_only_message_without_target_stays_readonly():
    # Regression: a read-only question that merely mentions a write keyword
    # ("上次修复了什么") must not be inferred as write intent; keyword-only
    # inference used to hand out worktree_write and 409 against active runs.
    assert infer_chat_turn_leases({"content": "上次修复了什么"}) == ["readonly_chat"]
    assert infer_chat_turn_leases({"content": "继续修复这个 bug"}) == ["readonly_chat"]
    assert infer_chat_turn_leases({"content": "help me fix this later, thanks"}) == ["readonly_chat"]
    assert infer_chat_turn_leases({"content": "这个 commit 是谁提交的？"}) == ["readonly_chat"]
    # Date-like fragments are not concrete write targets.
    assert infer_chat_turn_leases({"content": "2026/05/21 之前的修复改了什么"}) == ["readonly_chat"]


def test_keyword_with_concrete_target_falls_back_to_write_leases():
    # Legacy clients send no explicit signal; a write keyword naming a
    # concrete target path is double evidence of declared write intent.
    assert infer_chat_turn_leases({"content": "修复 core/runtime_manager/work_run_leases.py 的 bug"}) == [
        "worktree_write",
        "memory_write",
    ]
    assert infer_chat_turn_leases({"content": "fix the failing test in web/src/App.tsx"}) == [
        "worktree_write",
        "memory_write",
    ]
    assert infer_chat_turn_leases({"content": "重构 web/src/components 下面的组件"}) == [
        "worktree_write",
        "memory_write",
    ]


def test_explicit_write_signals_keep_lease_protection():
    # Explicit declarations win regardless of message text, so turns that
    # truly declare write intent still conflict with active write runs.
    assert infer_chat_turn_leases({"content": "上次修复了什么", "writeIntent": True}) == [
        "worktree_write",
        "memory_write",
    ]
    assert infer_chat_turn_leases({"content": "上次修复了什么", "toolMode": "write"}) == [
        "worktree_write",
        "memory_write",
    ]
    assert infer_chat_turn_leases({"content": "继续", "activeTask": {"changedFiles": ["a.py"]}}) == [
        "worktree_write",
        "memory_write",
    ]
    assert infer_chat_turn_leases({"content": "上次修复了什么"}) == ["readonly_chat"]
