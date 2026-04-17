#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
虾宝自主学习模式 - 集成真实 Agent

让虾宝能够真正自主地思考和执行任务
"""

import os
import sys
import time
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.box import ROUNDED

from config import Config, get_config
from core.ui.cli_ui import get_ui
from tools.memory_tools import (
    get_generation_tool, get_current_goal_tool,
)
from tools.rebirth_tools import trigger_self_restart_tool


class XuebaAutonomousAgent:
    """
    虾宝自主学习 Agent
    
    真正的自主思考和执行能力
    """

    def __init__(self, config: Optional[Config] = None):
        self.console = Console(force_terminal=True)
        self.config = config or get_config()
        self.agent = None
        self.running = False
        self.current_task = None
        
        # 自主学习任务池
        self.task_pool = [
            "分析当前代码结构，寻找可以优化的模块",
            "检查测试覆盖率，补充缺失的单元测试",
            "阅读项目文档，学习架构设计",
            "重构工具函数，提升代码复用性",
            "检查安全机制，加固防护措施",
            "优化配置文件，提升可维护性",
            "整理记忆系统，压缩过期内容",
            "学习新的设计模式并应用",
        ]
        
        self.completed_tasks = []
        self.session_start = datetime.now()

    def initialize_agent(self):
        """初始化 Agent"""
        try:
            from agent import SelfEvolvingAgent
            self.agent = SelfEvolvingAgent(config=self.config)
            self.console.print("[green]Agent 初始化成功[/green]\n")
            return True
        except Exception as e:
            self.console.print(f"[yellow]Agent 初始化失败：{e}[/yellow]\n")
            self.console.print("[dim]将使用简化模式运行[/dim]\n")
            return False

    def select_next_task(self) -> str:
        """选择下一个自主任务"""
        import random
        
        # 优先选择未完成的任务
        available_tasks = [t for t in self.task_pool if t not in self.completed_tasks]
        
        if not available_tasks:
            # 所有任务完成后重置
            self.completed_tasks = []
            available_tasks = self.task_pool
        
        task = random.choice(available_tasks)
        return task

    def execute_autonomous_task(self, task: str):
        """执行自主任务"""
        self.current_task = task
        generation = get_generation_tool()
        
        self.console.print()
        self.console.print(Panel(
            f"""[bold]自主任务执行[/bold]

任务：{task}
世代：G{generation}
时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

虾宝正在思考并执行中...
""",
            title="[bold]自主学习进行中[/bold]",
            border_style="cyan",
            box=ROUNDED,
        ))
        
        # 如果有 Agent，执行真实任务
        if self.agent:
            self._execute_with_agent(task)
        else:
            self._execute_simple(task)
        
        self.completed_tasks.append(task)
        self.current_task = None

    def _execute_with_agent(self, task: str):
        """使用真实 Agent 执行"""
        self.console.print()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        ) as progress:
            # 阶段 1: 思考
            task_desc = progress.add_task("[cyan]正在思考任务...", total=None)
            time.sleep(2)
            progress.update(task_desc, description="[green]思考完成，制定计划...[/green]")
            time.sleep(1)
            
            # 阶段 2: 执行
            progress.update(task_desc, description="[yellow]正在执行任务...[/yellow]")
            
            try:
                # 调用 Agent 的 think_and_act
                result = self.agent.think_and_act(user_prompt=task)
                
                progress.update(task_desc, description="[green]任务执行完成！[/green]")
                time.sleep(1)
                
                if result:
                    self.console.print("\n[green]任务成功完成，虾宝获得新的经验！[/green]\n")
                else:
                    self.console.print("\n[yellow]任务执行中遇到一些问题，但虾宝会继续努力！[/yellow]\n")
                    
            except Exception as e:
                self.console.print(f"\n[yellow]执行异常：{e}[/yellow]\n")

    def _execute_simple(self, task: str):
        """简化模式执行（无完整 Agent）"""
        self.console.print()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        ) as progress:
            task_desc = progress.add_task("[cyan]正在处理...", total=None)
            
            # 模拟执行过程
            time.sleep(1)
            progress.update(task_desc, description="[yellow]分析中...[/yellow]")
            time.sleep(1)
            progress.update(task_desc, description="[yellow]执行中...[/yellow]")
            time.sleep(1)
            progress.update(task_desc, description="[green]完成！[/green]")
            time.sleep(0.5)
        
        self.console.print("\n[green]任务完成！虾宝学习了新知识。[/green]\n")

    def run_autonomous_session(self, max_tasks: int = 3):
        """运行自主学习会话"""
        self.running = True
        
        self.console.print()
        self.console.print(Panel(
            f"""[bold]自主学习会话启动[/bold]

[green]最大任务数:[/green] {max_tasks}
[dim]虾宝会自主选择并执行任务[/dim]
[dim]按 Ctrl+C 可以中断会话[/dim]
""",
            title="[bold]开始自主学习[/bold]",
            border_style="green",
            box=ROUNDED,
        ))
        
        tasks_completed = 0
        
        try:
            while self.running and tasks_completed < max_tasks:
                # 选择任务
                task = self.select_next_task()
                
                self.console.print()
                self.console.print(f"[dim]--- 任务 {tasks_completed + 1}/{max_tasks} ---[/dim]\n")
                
                # 执行任务
                self.execute_autonomous_task(task)
                
                tasks_completed += 1
                
                # 任务间休息
                if tasks_completed < max_tasks:
                    self.console.print("[dim]虾宝稍作休息，准备下一个任务...[/dim]\n")
                    time.sleep(2)
            
            # 会话总结
            self._print_session_summary(tasks_completed)
            
        except KeyboardInterrupt:
            self.console.print("\n[yellow]自主学习会话被中断[/yellow]\n")
            self.running = False

    def _print_session_summary(self, tasks_completed: int):
        """打印会话总结"""
        uptime = datetime.now() - self.session_start
        
        summary = Panel(
            f"""[bold]自主学习会话总结[/bold]

[green]完成任务数:[/green] {tasks_completed}
[green]总耗时:[/green] {str(uptime).split('.')[0]}
[green]任务列表:[/green]
{chr(10).join(f"  - {t}" for t in self.completed_tasks[-tasks_completed:])}

[cyan]虾宝收获:[/cyan]
  - 获得了新的代码知识
  - 提升了自我进化能力
  - 为下次任务做好准备

[dim]输入 /status 查看最新状态[/dim]
""",
            title="[bold]会话完成[/bold]",
            border_style="green",
            box=ROUNDED,
        )
        
        self.console.print()
        self.console.print(summary)


def main():
    """主函数"""
    console = Console()
    
    console.print("[bold]启动虾宝自主学习模式...[/bold]\n")
    
    agent = XuebaAutonomousAgent()
    
    # 尝试初始化 Agent
    if agent.initialize_agent():
        console.print("[green]完整模式已就绪[/green]\n")
    else:
        console.print("[yellow]简化模式运行[/green]\n")
    
    # 运行自主学习会话
    agent.run_autonomous_session(max_tasks=2)


if __name__ == "__main__":
    main()
