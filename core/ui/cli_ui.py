# -*- coding: utf-8 -*-
"""
CLI UI 渲染引擎 - 龙虾宝宝主题版

基于 rich 库实现的动态终端界面，支持：
- 龙虾宝宝可爱主题
- 原地刷新的动态面板
- 加载动画 (Spinner)
- 带颜色的日志输出
- 任务清单树形渲染
- 进度条和状态显示
"""

import sys
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

# rich 组件
from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich.markdown import Markdown
from rich.status import Status
from rich.syntax import Syntax
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn
from rich.box import Box, ROUNDED, DOUBLE, ASCII2
from rich.align import Align
from rich.text import Text


# 预创建全局 Console 实例用于 Banner
_banner_console = Console(force_terminal=True)

# 龙虾主题
from core.ui.ascii_art import get_avatar_manager
from core.ui.theme import LobsterTheme, get_theme, get_style
from core.pet_system import get_pet_system as get_pet

# 全局 Console 实例
_console = Console(stderr=False, force_terminal=True)
_stderr_console = Console(stderr=True, force_terminal=True)  # 专用 stderr 控制台


class UIManager:
    """
    终端 UI 管理器 - 龙虾宝宝主题版

    提供可爱的终端渲染能力：
    - 龙虾宝宝 ASCII Art
    - 动态面板 (Live refresh)
    - 加载动画
    - 日志输出
    - 任务清单
    """

    _instance = None
    _lock = threading.Lock()
    # Test 模式：跳过 Live UI，直接打印到 stdout
    _test_mode = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self.console = _console
        self._stderr_console = _stderr_console  # 专用 stderr 控制台
        self._live: Optional[Live] = None
        self._current_renderable = None
        self._logs: List[str] = []
        self._log_buffer: List[str] = []  # 启动前的日志缓冲
        self._max_logs = self._load_max_logs()
        self._generation = 1
        self._current_goal = ""
        self._task_board = ""
        self._status = "IDLE"
        self._thinking = False
        self._tool_count = 0
        self._iterations = 0

        # ========== Claude Code 风格三段式布局 ==========
        self._content_lines: List[str] = []  # 中间可滚动内容区
        self._max_content = 16  # 最大保留行数
        self._header_height = 7  # 顶部状态栏高度（Art 5行 + 状态4行 + 边框2行 = 11）
        self.content_height=18
        self._footer_height = 7  # 底部日志栏高度（10条日志 + 边框2行 = 12）
        self._max_visible_logs = 10  # 日志面板最多显示多少条日志

        # 龙虾主题
        self.theme = get_theme()
        self.style = get_style()
        self.avatar = get_avatar_manager()

        # 龙虾宝宝宠物
        self.pet = get_pet()

    def _load_max_logs(self) -> int:
        """从配置加载最大日志条目数"""
        try:
            from config import get_config
            return get_config().ui.max_log_entries
        except Exception:
            return 100

    def _create_header(self) -> Panel:
        """创建状态头面板 - 龙虾宝宝主题"""
        status_color = self.theme.get_status_color(self._status)
        status_icon = self.theme.get_status_icon(self._status)

        # 龙虾 ASCII Art
        lobster_art = self.avatar.get_art(self._status.lower())

        # 宠物属性（安全获取，防止宠物系统未初始化时崩溃）
        try:
            pet_attrs = self.pet.data.attributes
        except Exception:
            pet_attrs = None

        pet_age = pet_attrs.level - 1 if pet_attrs else 0
        pet_level = pet_attrs.level if pet_attrs else 1
        pet_mood = pet_attrs.mood if pet_attrs else 100
        pet_hunger = pet_attrs.hunger if pet_attrs else 100
        pet_energy = int(pet_attrs.energy) if pet_attrs else 100
        pet_health = pet_attrs.health if pet_attrs else 100
        pet_love = pet_attrs.love if pet_attrs else 50
        pet_exp = pet_attrs.exp if pet_attrs else 0
        pet_exp_to_next = pet_attrs.exp_to_next if pet_attrs else 100

        # Emoji 映射
        mood_emoji = "😊" if pet_mood > 70 else "😐" if pet_mood > 40 else "😢"
        hunger_emoji = "🍖" if pet_hunger > 70 else "🍽️" if pet_hunger > 40 else "😫"
        energy_emoji = "⚡" if pet_energy > 70 else "💤" if pet_energy > 40 else "🥱"
        health_emoji = "❤️" if pet_health > 70 else "💔" if pet_health > 40 else "🏥"
        love_emoji = "💕" if pet_love > 70 else "💗" if pet_love > 40 else "💔"

        # 经验条
        exp_percent = pet_exp / pet_exp_to_next if pet_exp_to_next > 0 else 0
        exp_bar = "█" * int(exp_percent * 5) + "░" * (5 - int(exp_percent * 5))

        # 状态信息（文本格式，包含所有属性）
        status_text = (
            f"[{self.theme.LOBSTER_CYAN} bold]Lv.{pet_level}[/] ({pet_age}岁)\n"
            f"[{status_color}]{status_icon}[/] {self._status}  "
            f"[{self.theme.LOBSTER_ORANGE} bold]TURN[/] #{self._iterations}\n"
            f"{mood_emoji}心情: {pet_mood}/100  "
            f"{hunger_emoji}饱食: {pet_hunger}/100  "
            f"{energy_emoji}活力: {pet_energy}/100\n"
            f"{health_emoji}健康: {pet_health}/100  "
            f"{love_emoji}爱心: {pet_love}/100  "
            f"⭐经验 [{exp_bar}] {pet_exp}/{pet_exp_to_next}"
        )

        # Art 和状态组合（左右布局）
        art_lines = lobster_art.strip().split('\n')
        status_lines = status_text.split('\n')

        # Art 宽度（保持对齐）
        art_width = 12
        combined = []
        for i in range(max(len(art_lines), len(status_lines))):
            left = art_lines[i] if i < len(art_lines) else " " * art_width
            right = status_lines[i] if i < len(status_lines) else ""
            combined.append(left + "  " + right)

        content = '\n'.join(combined)

        return Panel(
            content,
            title=self.style.status_title,
            border_style=self.theme.LOBSTER_CYAN,
            box=ASCII2,
        )

    def _create_task_board(self) -> Optional[Panel]:
        """创建任务清单面板"""
        if not self._task_board:
            return None

        return Panel(
            self._task_board,
            title=f"[bold {self.theme.LOBSTER_ORANGE}]📋 任务清单[/bold {self.theme.LOBSTER_ORANGE}]",
            border_style=self.theme.LOBSTER_ORANGE,
            box=ASCII2,
            width=60,
        )

    def _create_log_panel(self) -> Panel:
        """创建底部日志面板 - 固定显示最近日志"""
        if not self._logs:
            return Panel(
                f"[dim]等待日志...[/dim]",
                title=f"[bold {self.theme.LOBSTER_GREEN}]📝 日志[/bold {self.theme.LOBSTER_GREEN}]",
                border_style=self.theme.LOBSTER_GREEN,
                box=ASCII2,
                height=self._footer_height,
            )

        # 只显示最近的 _max_visible_logs 条日志
        recent_logs = self._logs[-self._max_visible_logs:] if len(self._logs) > self._max_visible_logs else self._logs
        log_text = "\n".join(recent_logs)

        return Panel(
            log_text,
            title=f"[bold {self.theme.LOBSTER_GREEN}]📝 日志 ({len(self._logs)})[/]",
            border_style=self.theme.LOBSTER_GREEN,
            box=ASCII2,
            height=self._footer_height,
        )

    def _create_full_renderable(self) -> Layout:
        """创建完整的渲染布局 - Claude Code 风格三段式

        布局结构:
        ┌──────────────────────────────────────────────┐
        │  [顶部状态栏: Baby Claw 状态 - 固定高度]      │
        ├──────────────────────────────────────────────┤
        │  [中间可滚动内容区: 工具输出、思考过程]        │  ← flex 填充剩余空间
        ├──────────────────────────────────────────────┤
        │  [底部日志栏: 最近日志 - 固定高度]             │
        └──────────────────────────────────────────────┘
        """
        layout = Layout()

        # 顶部: 固定高度（根据状态行数自动计算）
        layout.split_column(
            Layout(name="header", size=self._header_height),
            Layout(name="content", size=self.content_height),
            Layout(name="log", size=self._footer_height, minimum_size=10),
        )

        # 填充各区域
        layout["header"].update(self._create_header())
        layout["content"].update(self._create_content_area())
        layout["log"].update(self._create_log_panel())

        return layout

    def _create_content_area(self) -> Panel:
        """创建中间可滚动内容区"""
        if not self._content_lines:
            content = "[dim]等待任务...[/dim]"
        else:
            recent = self._content_lines[-self._max_content:] if len(self._content_lines) > self._max_content else self._content_lines
            content = "\n".join(recent)

        return Panel(
            content,
            title=f"[bold cyan]📤 内容输出[/bold cyan] ({len(self._content_lines)} 条)",
            border_style="cyan",
            box=ASCII2,
            padding=0,
        )

    # ========== 内容区操作 ==========

    def add_content(self, text: str):
        """添加内容到中间可滚动区"""
        self._content_lines.append(text)
        if UIManager._test_mode:
            import sys
            sys.__stdout__.write(str(text) + "\n")
            sys.__stdout__.flush()
            return
        if len(self._content_lines) > self._max_content * 2:  # 超过2倍上限时清理
            self._content_lines = self._content_lines[-self._max_content:]
        self.refresh()

    def add_content_block(self, lines: List[str]):
        """添加多行内容块"""
        for line in lines:
            self.add_content(line)

    def clear_content(self):
        """清空内容区"""
        self._content_lines = []
        self.refresh()

    @contextmanager
    def live_display(self, refresh_per_second: int = 4):
        """
        启动 Live 刷新上下文
        """
        self.start_live()
        try:
            yield self
        finally:
            self.stop_live()

    def start_live(self):
        """启动 Live 刷新"""
        if UIManager._test_mode:
            return
        if self._live is None:
            # 刷新 logger 的函数引用，确保在 Live 启动时使用最新的 UI 实例
            try:
                from core.logging.logger import _refresh_ui_fns
                _refresh_ui_fns()
                from core.logging.logger import reset_token_console
                reset_token_console()
            except ImportError:
                pass

            refresh_rate = self._load_refresh_rate()
            self._live = Live(
                self._create_full_renderable(),
                console=self.console,
                refresh_per_second=refresh_rate,
                transient=False,
                auto_refresh=False,
                redirect_stdout=True,
                redirect_stderr=True,
            )
            self._live.start()

            # 将启动前缓冲的日志一次性刷新到面板
            if self._log_buffer:
                self._logs.extend(self._log_buffer)
                self._log_buffer.clear()
                if len(self._logs) > self._max_logs:
                    self._logs = self._logs[-self._max_logs:]
                self.refresh()

    def _load_refresh_rate(self) -> int:
        """从配置加载刷新频率"""
        try:
            from config import get_config
            return get_config().ui.refresh_rate
        except Exception:
            return 4

    def stop_live(self):
        """停止 Live 刷新"""
        if UIManager._test_mode:
            return
        if self._live:
            self._live.stop()
            self._live = None
            # 清除控制台缓冲，防止后续输出与 Live 显示残留混合
            self.console.print("\n", end="")

    def refresh(self):
        """刷新显示"""
        if UIManager._test_mode:
            return
        if self._live:
            try:
                self._live.update(self._create_full_renderable(), refresh=True)
            except Exception:
                pass  # 静默忽略刷新错误，避免日志刷屏
        # 启动前不打印，等待 Live 启动后一次性刷新

    # ==================== 状态更新 ====================

    def update_status(
        self,
        status: str,
        generation: int = None,
        goal: str = None,
        iterations: int = None,
        tool_count: int = None,
    ):
        """
        更新状态
        """
        self._status = status.upper()
        if generation is not None:
            self._generation = generation
        if goal is not None:
            self._current_goal = goal
        if iterations is not None:
            self._iterations = iterations
        if tool_count is not None:
            self._tool_count = tool_count

        self.refresh()

    def set_task_board(self, markdown: str):
        """设置任务清单 (Markdown 格式)"""
        self._task_board = markdown
        self.refresh()

    def increment_tool_count(self):
        """工具调用次数 +1"""
        self._tool_count += 1
        self.refresh()

    # ==================== 日志记录 - 龙虾主题 ====================

    def add_log(self, message: str, level: str = "INFO"):
        """
        添加日志条目 - 龙虾宝宝主题版
        """
        timestamp = datetime.now().strftime("%H:%M:%S")

        # 安全获取 theme（可能在某些边界情况下为 None）
        try:
            icon = self.theme.get_log_icon(level.upper()) if self.theme else "📋"
            color = self.theme.get_log_color(level.upper()) if self.theme else "white"
        except Exception:
            icon = "📋"
            color = "white"

        log_entry = f"[dim]{timestamp}[/dim] {icon} [{color}]{level}[/{color}] {message}"

        if UIManager._test_mode:
            import re, sys
            plain = re.sub(r'\[/?\w+\]', '', log_entry)
            sys.__stdout__.write(plain + "\n")
            sys.__stdout__.flush()
            return

        # 启动前：缓冲日志，不直接打印
        if self._live is None:
            self._log_buffer.append(log_entry)
            return

        self._logs.append(log_entry)
        if len(self._logs) > self._max_logs:
            self._logs.pop(0)

        self.refresh()

    # ==================== 思考动画 ====================

    @contextmanager
    def thinking(self, message: str = "Thinking..."):
        """
        思考动画上下文
        """
        self._thinking = True
        self.add_log(message, "LLM")

        original_status = self._status
        self._status = "THINKING"
        self.refresh()

        if UIManager._test_mode:
            import sys
            sys.__stdout__.write(f"[THINKING] {message}\n")
            sys.__stdout__.flush()
            try:
                yield
            finally:
                self._thinking = False
                self._status = original_status
            return

        try:
            yield
        finally:
            self._thinking = False
            self._status = original_status
            self.refresh()

    # ==================== 独立输出方法 - 龙虾主题 ====================

    def print_header(self, model: str, generation: int = None):
        """打印会话头 - 龙虾宝宝版"""
        if generation is not None:
            self._generation = generation

        pet = get_pet()
        pet_level = pet.data.attributes.level
        pet_age = pet_level - 1

        # 获取 ASCII Art 宠物形象
        lobster_art = self.avatar.get_art('happy')
        banner = self.avatar.get_banner("Baby Claw", "v1.0", pet.data.attributes.model_dump())

        header = f"""
{lobster_art}
{banner}

[cyan]模型:[/cyan] {model}
[green]时间:[/green] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        self.console.print(header)

    def print_thinking(self, message: str):
        """打印思考过程"""
        with self.console.status(f"[bold magenta]🤔 思考中...[/bold magenta] {message}") as status:
            yield status

    def print_tool_start(self, tool_name: str, args: Dict[str, Any] = None):
        """打印工具调用开始 - 仅输出到内容区"""
        self.increment_tool_count()
        tool_icon = self.theme.get_tool_icon(tool_name)
        self.add_content("")
        self.add_content(f"[bold magenta]🔧 {tool_icon} {tool_name}[/bold magenta]" + (f"({', '.join([f'{k}={str(v)[:30]}' for k, v in args.items()][:3])})" if args else ""))

    def print_tool_start_log(self, tool_name: str, args: Dict[str, Any] = None):
        """打印工具调用开始 - 仅写入日志面板"""
        if args:
            args_preview = ", ".join([f"{k}={str(v)[:20]}" for k, v in list(args.items())[:3]])
            self.add_log(f"{self.theme.get_tool_icon(tool_name)} {tool_name}({args_preview})", "TOOL")
        else:
            self.add_log(f"{self.theme.get_tool_icon(tool_name)} {tool_name}", "TOOL")

    def print_tool_result(self, tool_name: str, result: str, success: bool = True):
        """打印工具执行结果 - 仅输出到内容区"""
        status_icon = "✅" if success else "❌"
        color = self.theme.LOBSTER_GREEN if success else self.theme.LOBSTER_RED

        # 安全转换 result 为字符串
        if not isinstance(result, str):
            try:
                result = str(result)
            except Exception:
                result = f"<非字符串类型: {type(result).__name__}>"

        self.add_content(f"  {status_icon} [{color}]{tool_name}[/{color}]")
        if result:
            preview = result[:300] + "..." if len(result) > 300 else result
            self.add_content(f"     {preview}")
        self.add_content("")

    def print_tool_result_log(self, tool_name: str, success: bool = True):
        """打印工具执行结果 - 仅写入日志面板"""
        if success:
            self.add_log(f"✅ {tool_name} 完成", "TOOL")
        else:
            self.add_log(f"❌ {tool_name} 失败", "ERROR")

    def print_warning(self, message: str):
        """打印警告 - 龙虾主题"""
        self.console.print(f"[bold yellow]⚠️ 警告[/bold yellow] {message}")
        self.add_log(message, "WARN")

    def print_error(self, message: str, exc_info: str = None):
        """打印错误 - 龙虾主题"""
        _stderr_console.print(f"[bold red]❌ 错误[/bold red] {message}")
        self.add_log(message, "ERROR")

        if exc_info:
            _stderr_console.print(exc_info, style="red dim")

    def print_success(self, message: str):
        """打印成功消息 - 龙虾主题（仅添加到日志，不直接打印）"""
        self.add_log(message, "SUCCESS")

    def print_section(self, title: str):
        """打印分节标题 - 输出到内容区"""
        self.add_content("")
        self.add_content(f"[bold cyan]--- {title} ---[/bold cyan]")

    def print_markdown(self, markdown_text: str):
        """打印 Markdown 内容 - 输出到内容区"""
        md = Markdown(markdown_text)
        self.add_content(str(md))

    def print_code(self, code: str, language: str = "python"):
        """打印代码块"""
        syntax = Syntax(code, language, theme="monokai", line_numbers=True)
        self.console.print(syntax)

    def print_table(self, data: List[Dict[str, Any]], columns: List[str] = None):
        """打印表格"""
        if not data:
            return

        if columns is None:
            columns = list(data[0].keys())

        table = Table(box=ROUNDED)
        for col in columns:
            table.add_column(col, style="cyan")

        for row in data:
            table.add_row(*[str(row.get(col, "")) for col in columns])

        self.console.print(table)

    def print_task_checklist(self, tasks: List[Dict[str, Any]]):
        """
        打印任务清单 - 龙虾主题
        """
        tree = Tree(f"[bold yellow]📋 任务清单[/bold yellow]")

        for task in tasks:
            title = task.get("title", "")
            done = task.get("done", False)
            priority = task.get("priority", "medium")

            icon = "[bold green]✓[/bold green]" if done else "[ ]"
            priority_color = self.theme.LOBSTER_RED if priority == "high" else (self.theme.LOBSTER_ORANGE if priority == "medium" else "cyan")

            tree.add(f"{icon} [bold {priority_color}]{title}[/{priority_color}]")

        self.console.print(tree)

    def print_progress(self, description: str, completed: int, total: int):
        """打印进度条"""
        bar_length = 30
        percent = completed / total if total > 0 else 0
        filled = int(bar_length * percent)
        bar = f"[{self.theme.LOBSTER_GREEN}]" + "=" * filled + "[/]" + "-" * (bar_length - filled)

        self.console.print(f"  {description}")
        self.console.print(f"  [{bar}] {int(percent * 100)}%")

    def print_lobster_status(self, status: str = "happy", message: str = ""):
        """
        打印龙虾宝宝状态面板

        Args:
            status: 状态 (happy, thinking, working, sleeping, sad)
            message: 状态消息
        """
        lobster_art = self.avatar.get_art(status)
        status_icon = self.theme.get_status_icon(status.upper())

        content = f"[cyan]{lobster_art}[/cyan]\n"
        content += f"[bold cyan]状态:[/bold cyan] {status_icon} {status.upper()}\n"
        if message:
            content += f"[cyan]消息:[/cyan] {message}"

        panel = Panel(
            content,
            title=self.style.status_title,
            border_style=self.theme.LOBSTER_CYAN,
            box=ASCII2,
        )
        self.console.print(panel)

    def print_pet_status(self):
        """打印龙虾宝宝宠物状态"""
        pet_text = self.pet.get_full_status()
        panel = Panel(
            pet_text,
            title="[bold magenta]🦞 龙虾宝宝[/bold magenta]",
            border_style="bright_magenta",
            box=ASCII2,
        )
        self.console.print(panel)

    def print_welcome_panel(self):
        """打印欢迎面板"""
        art = self.avatar.get_art('happy')
        pet = get_pet()
        pet_age = pet.data.attributes.level - 1
        pet_level = pet.data.attributes.level

        welcome = Panel(
            f"""{art}

[bold bright_red]🦞 欢迎回来，龙虾爸爸！🦞[/bold bright_red]

[green]我是你的小虾宝，已经准备好为你服务啦~[/green]

[cyan]📊 当前状态:[/cyan]
  • 年龄: {pet_age}岁 (Lv.{pet_level})
  • 目标: {self._current_goal[:30] if self._current_goal else '等待任务...'}
  • 状态: {self.theme.get_status_icon(self._status)} {self._status}

[yellow]🎯 快速开始:[/yellow]
  1. 直接输入任务，虾宝会帮你完成
  2. 输入 /help 查看所有命令
  3. 输入 /status 查看我的状态

[dim]💡 提示: 按 Ctrl+C 可以随时中断[/dim]
            """,
            title="[bold bright_red]🦞 虾宝已就绪[/bold bright_red]",
            border_style="bright_cyan",
            box=ASCII2,
        )
        self.console.print(welcome)

    def clear(self):
        """清屏"""
        self.console.clear()


# ==================== 全局实例 ====================

_ui: Optional[UIManager] = None


def get_ui() -> UIManager:
    """获取全局 UI 管理器实例"""
    global _ui
    if _ui is None:
        _ui = UIManager()
    return _ui


# 当 cli_ui 模块加载完成后，立即刷新 logger 的函数引用
# 这样 logger.py 在模块级别持有 noop 函数后，一旦 cli_ui 加载完成，
# logger 的所有输出就会正确路由到 Live 界面
try:
    from core.logging.logger import _refresh_ui_fns
    _refresh_ui_fns()
except ImportError:
    pass


# 便捷函数
def ui_print_header(model: str, generation: int = None):
    """打印会话头"""
    get_ui().print_header(model, generation)


def ui_thinking(message: str = "Thinking..."):
    """获取思考动画上下文"""
    return get_ui().thinking(message)


def ui_print_tool(tool_name: str, args: Dict = None, result: str = None, success: bool = True):
    """打印工具执行"""
    if result is None:
        get_ui().print_tool_start(tool_name, args)
    else:
        get_ui().print_tool_result(tool_name, result, success)


def ui_warning(message: str):
    """打印警告"""
    get_ui().print_warning(message)


def ui_error(message: str, exc_info: str = None):
    """打印错误"""
    get_ui().print_error(message, exc_info)


def ui_success(message: str):
    """打印成功"""
    get_ui().print_success(message)


def ui_log(message: str, level: str = "INFO"):
    """添加日志"""
    get_ui().add_log(message, level)


def ui_update_status(
    status: str,
    generation: int = None,
    goal: str = None,
    iterations: int = None,
    tool_count: int = None,
):
    """更新状态"""
    get_ui().update_status(status, generation, goal, iterations, tool_count)


def ui_task_board(markdown: str):
    """设置任务清单"""
    get_ui().set_task_board(markdown)


def ui_lobster_status(status: str = "happy", message: str = ""):
    """打印龙虾状态"""
    get_ui().print_lobster_status(status, message)


def ui_welcome():
    """打印欢迎面板"""
    get_ui().print_welcome_panel()


def ui_print_welcome():
    """打印欢迎面板（别名）"""
    get_ui().print_welcome_panel()


def run_interactive_mode(agent) -> bool:
    """
    运行交互模式

    Args:
        agent: SelfEvolvingAgent 实例

    Returns:
        True: 正常退出, False: 中断退出
    """
    ui = get_ui()

    while True:
        try:
            user_input = input("[bold cyan]Agent[/bold cyan] > ").strip()

            if not user_input:
                print("[dim]进入自动模式...[/dim]")
                ui.start_live()
                agent.run_loop()
                ui.stop_live()
                break
            elif user_input.lower() in ['/quit', '/exit', '/q']:
                print("[yellow]再见![/yellow]")
                return True
            elif user_input.lower() in ['/auto', '/a']:
                print("[dim]进入自动模式...[/dim]")
                ui.start_live()
                agent.run_loop()
                ui.stop_live()
                break
            elif user_input.lower() in ['/help', '/h', '/?']:
                print("""
[bold cyan]可用命令:[/bold cyan]
  /auto, /a     - 进入自动模式
  /quit, /q     - 退出程序
  /help, /h     - 显示此帮助
  <任意文本>     - 将文本作为任务发送给 Agent
""")
                continue
            else:
                ui.start_live()
                agent.run_loop(initial_prompt=user_input)
                ui.stop_live()
                print("[dim]" + "─" * 60 + "[/dim]")
                print("[yellow]返回交互模式[/yellow]")
                print()

        except KeyboardInterrupt:
            print("\n[yellow]中断，退出...[/yellow]")
            return False
        except EOFError:
            return False

    return True
