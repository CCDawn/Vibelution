"""Shared session scheduling limits.

单一权威：同一 Agent 的会话并发上限、启动恢复留位和恢复 turn 的队列优先级
都在这里定义，避免调度器、启动恢复和提交通路各写一份数字而悄悄漂移。

背景（2026-11 排队事故）：``SessionTurnScheduler`` 把同一 Agent 的并行会话
限制在 ``SESSION_AGENT_MAX_ACTIVE_TURNS`` 个，而启动恢复原本用同样大小的
线程池一次性拉起全部中断会话，两者相等时第 9 个 turn 必然排队，用户正在用
的会话被后台补偿任务挤到后面。
"""

from __future__ import annotations

# 同一 Agent 下最多同时运行的会话数（SessionTurnScheduler 的 max_active_per_agent）。
SESSION_AGENT_MAX_ACTIVE_TURNS = 8

# 启动恢复永远为交互式用户 turn 预留的槽位数。
# 恢复是后台补偿：它可以排队，用户打字后干等不行。
RECOVERY_SLOT_RESERVE = 2

# 恢复 turn 在调度队列里的优先级。数值越大越靠后（越低优先级）：
# 用户 turn 默认 0，恢复 turn 90，proactive 主动消息 100。
RECOVERY_TURN_SCHEDULER_PRIORITY = 90

# 恢复 turn 的 turn_mode 标记；只有这个模式享受低优先级与留位语义。
RECOVERY_TURN_MODE = "hot_restart_resume"


def recovery_worker_limit(total_workers: int) -> int:
    """Bound the startup-recovery pool so it never consumes every scheduler slot.

    参数 ``total_workers`` 是恢复扫描原本打算用的线程数；返回值同时不超过它
    和“调度上限减预留”，且至少为 1。这样无论恢复候选有多少，交互式 turn
    始终至少还有 ``RECOVERY_SLOT_RESERVE`` 个槽位可用。
    """

    usable = max(1, SESSION_AGENT_MAX_ACTIVE_TURNS - RECOVERY_SLOT_RESERVE)
    return max(1, min(max(1, int(total_workers or 1)), usable))
