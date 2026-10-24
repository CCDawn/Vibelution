"""Self-observation status vocabulary; distinct from worktree evolution runs."""

SELF_OBSERVATION_OPERATOR_TERMINAL_STATUSES = frozenset({"terminated", "cancelled", "stopped"})
SELF_OBSERVATION_FINAL_STATUSES = SELF_OBSERVATION_OPERATOR_TERMINAL_STATUSES | frozenset({
    "done", "failed", "boundary_violation",
})

SELF_OBSERVATION_CONTRACT = {
    "activeStatuses": ["queued", "running"],
    "terminalStatuses": sorted(SELF_OBSERVATION_FINAL_STATUSES),
    "labels": {
        "queued": "排队中", "running": "运行中", "done": "已完成", "failed": "运行失败",
        "terminated": "已终止", "cancelled": "已取消", "stopped": "已停止",
        "boundary_violation": "越界异常", "unknown": "未知状态",
    },
    "labelsEn": {
        "queued": "Queued", "running": "Running", "done": "Completed", "failed": "Run failed",
        "terminated": "Terminated", "cancelled": "Cancelled", "stopped": "Stopped",
        "boundary_violation": "Boundary violation", "unknown": "Unknown state",
    },
}
