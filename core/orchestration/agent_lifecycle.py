#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent 生命周期管理模块

职责：
- 状态转换管理
- 自动备份调度
- 自主模式提示词注入
- Awake interval 睡眠控制

使用方式：
    from core.orchestration.agent_lifecycle import AgentLifecycle

    lifecycle = AgentLifecycle(agent, config)
    lifecycle.run()
"""

from __future__ import annotations

import time
from typing import Optional, Callable, Any

from core.infrastructure.state import get_state_manager, AgentState
from core.capabilities.prompt_manager import get_prompt_manager
from core.logging.logger import debug as _debug_logger
from core.logging.unified_logger import logger


# 自主进化模式提示词
AUTONOMOUS_USER_PROMPT = (
    "【自主进化】你是完全自主的进化体，请根据 SOUL.md 的使命指示，"
    "**要求**：每次仅生成一个主要任务。\n\n"
    "首先调用 set_generation_task(task=\"...\") 设定你的任务\n"
    "然后调用 set_plan(task=\"...\") 制定计划并执行\n"
    "每完成一个计划调用 tick_subtask(task=\"...\") 打勾并记录结论摘要\n"
    "所有计划完成后调用 commit_compressed_memory(task=\"...\") 保存记忆\n"
    "最后调用 trigger_self_restart_tool(task=\"...\") 结束本轮\n"
)


class AgentLifecycle:
    """Agent 生命周期管理器"""

    def __init__(
        self,
        agent: Any,
        config: Any,
    ):
        """
        初始化生命周期管理器

        Args:
            agent: SelfEvolvingAgent 实例
            config: 配置对象
        """
        self.agent = agent
        self.config = config
        self.state_manager = get_state_manager()
        self.last_backup_time = time.time()

    def transition_state(self, state: AgentState, action: str = ""):
        """状态转换"""
        from tools.memory_tools import get_generation_tool, get_current_goal
        self.state_manager.set_state(
            state,
            action=action,
            generation=get_generation_tool(),
            current_goal=get_current_goal()
        )

    def check_auto_backup(self):
        """检查并执行自动备份"""
        if not getattr(self.config.agent, 'auto_backup', False):
            return

        current_time = time.time()
        backup_interval = getattr(self.config.agent, 'backup_interval', 300)

        if current_time - self.last_backup_time >= backup_interval:
            from tools.shell_tools import backup_project
            from datetime import datetime

            backup_project(f"自动备份 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            self.last_backup_time = current_time

    def get_autonomous_prompt(self) -> str:
        """获取自主进化模式提示词"""
        return AUTONOMOUS_USER_PROMPT

    def should_continue(self, result: Any) -> bool:
        """
        判断是否继续运行

        Args:
            result: think_and_act 返回值

        Returns:
            True: 继续运行, False: 退出
        """
        if result is False:
            _debug_logger.warning("重启已触发", tag="AGENT")
            return False
        if result == "hibernated":
            _debug_logger.debug("Agent 已主动休眠完毕，继续执行", tag="WAKE")
            return True
        return True

    def get_next_prompt(self, user_input: Optional[str]) -> Optional[str]:
        """
        获取下一轮提示词

        Args:
            user_input: 外部输入（可选）

        Returns:
            下一轮提示词或None
        """
        if user_input:
            _debug_logger.system("首次任务已加载，开始执行...", tag="START")
            return user_input

        _debug_logger.system(
            f"自主进化模式，awake_interval={self.config.agent.awake_interval}s",
            tag="AUTO"
        )
        return self.get_autonomous_prompt()

    def run_loop(self, initial_prompt: str = None) -> None:
        """
        运行主循环

        Args:
            initial_prompt: 初始提示词（可选）
        """
        self.transition_state(AgentState.AWAKENING, action="系统初始化中...")

        from tools.memory_tools import get_generation_tool
        generation = get_generation_tool()
        pm = get_prompt_manager()
        system_prompt, _ = pm.build()
        logger.start_generation(generation, system_prompt)
        logger.log_action("会话开始", f"世代: G{generation}, 模型: {self.agent.model_name}")

        user_input = self.get_next_prompt(initial_prompt)

        try:
            while True:
                self.transition_state(AgentState.THINKING, action="思考并执行任务...")

                # 计算系统提示词
                system_prompt, _ = pm.build()

                # 自动备份检查
                self.check_auto_backup()

                # 执行思考-行动循环
                result = self.agent.think_and_act(
                    user_prompt=user_input,
                    system_prompt=system_prompt
                )
                user_input = None  # 首次之后为None

                # 判断是否继续
                if not self.should_continue(result):
                    break

                # 自主模式：自动注入下一轮任务
                _debug_logger.system(
                    "执行完成，模型自主决策下一轮进化...",
                    tag="EVOLVE"
                )
                user_input = self.get_autonomous_prompt()
                time.sleep(2)

        except KeyboardInterrupt:
            _debug_logger.info("收到中断，退出", tag="AGENT")
            logger.end_session({"reason": "keyboard_interrupt"})
        except Exception as e:
            _debug_logger.error(
                f"主循环异常: {type(e).__name__}: {e}",
                exc_info=True
            )
            logger.log_error("main_loop_exception", str(e))
        finally:
            uptime = time.time() - time.mktime(self.agent.start_time.timetuple())
            _debug_logger.info(f"运行结束 (运行时长: {uptime}s)", tag=self.agent.name)
            self.transition_state(AgentState.IDLE, action="系统已关闭")
            logger.end_session({"uptime_seconds": uptime})


__all__ = [
    "AgentLifecycle",
    "AUTONOMOUS_USER_PROMPT",
]
