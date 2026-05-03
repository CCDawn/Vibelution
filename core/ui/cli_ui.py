# -*- coding: utf-8 -*-
"""
Vibelution CLI UI — 流式输出引擎

基于 rich 库的简洁终端界面：
- 流式内联输出（无固定面板布局）
- 工具调用分组显示
- 状态行 Live 刷新
- 代码/Markdown/表格直接渲染
"""

import sys
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich.box import ROUNDED, ASCII2
from rich.align import Align

# 全局 Console 实例
_console = Console(stderr=False, force_terminal=True)
_stderr_console = Console(stderr=True, force_terminal=True)

from core.ui.ascii_art import get_avatar_manager
from core.ui.theme import LobsterTheme, get_theme, get_style
from core.pet_system import get_pet_system as get_pet


class UIManager:
    """终端 UI 管理器 — 流式输出"""

    _instance = None
    _lock = threading.Lock()
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
        self._stderr_console = _stderr_console
        self._live: Optional[Live] = None
        self._status_line = ""
        self._current_goal = ""
        self._status = "IDLE"
        self._thinking = False
        self._tool_count = 0
        self._iterations = 0
        self._input_tokens = 0
        self._output_tokens = 0

        self._content_buffer: List[str] = []
        self._buffer_max_lines = 200

        self.theme = get_theme()
        self.style = get_style()
        self.avatar = get_avatar_manager()
        self.pet = get_pet()

    # ======================== 全屏渲染 ========================

    def _build_pet_panel(self):
        """构建宠物状态面板 — 固定在 Live 区域底部常驻"""
        bar_w = 10

        # 宠物数据
        pet_name = "Baby Claw"
        pet_level = 1
        pet_age = 0
        mood = hunger = energy = health = love = 100
        exp = 0
        exp_max = 100
        try:
            p = get_pet()
            a = p.data.attributes
            pet_name = a.name or pet_name
            pet_level = a.level
            pet_age = pet_level - 1
            mood = a.mood
            hunger = a.hunger
            energy = int(a.energy)
            health = a.health
            love = a.love
            exp = a.exp
            exp_max = a.exp_to_next
        except Exception:
            pass

        def _bar(val, color):
            b = self._make_bar(val, 100, bar_w)
            return f"[{color}]{b}[/{color}]"

        def _attr(label, value, color, icon):
            bar = _bar(value, color)
            return f"  {icon} {label} {bar} {value:>3}/100"

        exp_pct = exp / exp_max if exp_max > 0 else 0
        exp_bar = f"[dim]{self._make_bar(exp, exp_max, bar_w)}[/dim]"

        art = self.avatar.get_art("happy")

        # Agent 状态行
        agent_line = f"{self._status}"
        if self._current_goal:
            goal_preview = self._current_goal[:40].replace("\n", " ")
            agent_line += f" | {goal_preview}"
        agent_line += f" | Turn {self._iterations}"
        if self._input_tokens or self._output_tokens:
            agent_line += f" | Tok {self._input_tokens}+{self._output_tokens}"

        content = (
            f"[cyan]{art}[/cyan]\n"
            f"  [bold]{pet_name}[/bold]  [dim]Lv.{pet_level} ({pet_age}岁)[/dim]\n\n"
            f"{_attr('Mood  ', mood, 'yellow', 'M')}    "
            f"{_attr('Hunger', hunger, 'green', 'H')}\n"
            f"{_attr('Energy', energy, 'cyan', 'E')}    "
            f"{_attr('Health', health, 'red', '❤ ')}\n"
            f"{_attr('Love  ', love, 'magenta', '♥ ')}    "
            f"  ⭐ EXP     {exp_bar} {int(exp_pct * 100):>3}%\n\n"
            f"  [dim]{agent_line}[/dim]"
        )

        return Panel(
            content,
            title="[bold]Vibelution[/bold]",
            border_style="dim",
            box=ROUNDED,
            padding=(0, 1),
        )

    def _full_screen_renderable(self):
        """宠物面板(上) + 内容缓冲(下) — 全屏重绘"""
        pet_panel = self._build_pet_panel()

        # 取 buffer 最后 40 行
        visible = self._content_buffer[-40:] if self._content_buffer else []
        if visible:
            content_text = Text("\n".join(visible), style="dim")
            from rich.table import Table
            grid = Table.grid(padding=0)
            grid.add_row(pet_panel)
            grid.add_row(Text(""))  # spacer
            grid.add_row(content_text)
            return grid
        return pet_panel

    def _status_renderable(self):
        return self._full_screen_renderable()

    def _append_to_buffer(self, text: str):
        """写入内容缓冲区并触发刷新；Live 未激活时直接 console.print"""
        if not self._live or UIManager._test_mode:
            self.console.print(text)
            return
        self._content_buffer.append(text)
        if len(self._content_buffer) > self._buffer_max_lines:
            self._content_buffer = self._content_buffer[-self._buffer_max_lines:]
        self._update_status_line()

    # ======================== Live 管理 ========================

    def start_live(self):
        if UIManager._test_mode:
            return
        if self._live is None:
            try:
                from core.logging.logger import reset_token_console
                reset_token_console()
            except ImportError:
                pass

            from rich.live import Live
            self._live = Live(
                self._status_renderable(),
                console=self.console,
                refresh_per_second=4,
                transient=False,
                auto_refresh=False,
                redirect_stdout=False,
                redirect_stderr=False,
            )
            self._live.start()

    def stop_live(self):
        if UIManager._test_mode:
            return
        if self._live:
            self._live.stop()
            self._live = None

    def _update_status_line(self):
        if self._live and not UIManager._test_mode:
            try:
                self._live.update(self._status_renderable(), refresh=True)
            except Exception:
                pass

    # ======================== 状态更新 ========================

    def update_status(self, status: str, generation: int = None, goal: str = None,
                      iterations: int = None, tool_count: int = None,
                      input_tokens: int = None, output_tokens: int = None):
        self._status = status.upper()
        if goal is not None:
            self._current_goal = goal
        if iterations is not None:
            self._iterations = iterations
        if tool_count is not None:
            self._tool_count = tool_count
        if input_tokens is not None:
            self._input_tokens = input_tokens
        if output_tokens is not None:
            self._output_tokens = output_tokens
        self._update_status_line()

    def refresh_pet_display(self):
        """刷新状态行中的宠物数据（主循环每次迭代后调用）"""
        self._update_status_line()

    def set_task_board(self, markdown: str):
        self.console.print(f"[dim]--- 任务清单 ---[/dim]")
        if markdown:
            self.console.print(Markdown(markdown))

    def increment_tool_count(self):
        self._tool_count += 1
        self._update_status_line()

    # ======================== 流式输出 ========================

    def add_content(self, text: str):
        """输出一行到内容缓冲区"""
        if UIManager._test_mode:
            sys.__stdout__.write(str(text) + "\n")
            sys.__stdout__.flush()
            return
        self._append_to_buffer(text)

    def add_content_block(self, lines: List[str]):
        for line in lines:
            self.add_content(line)

    def clear_content(self):
        self._content_buffer.clear()

    def add_log(self, message: str, level: str = "INFO"):
        """内联日志输出 — 前缀时间戳"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        try:
            icon = self.theme.get_log_icon(level.upper()) if self.theme else "--"
            color = self.theme.get_log_color(level.upper()) if self.theme else "white"
        except Exception:
            icon, color = "--", "white"

        entry = f"[dim]{timestamp}[/dim] [{color}]{icon}[/{color}] {message}"

        if UIManager._test_mode:
            import re
            plain = re.sub(r'\[/?\w+\]', '', entry)
            sys.__stdout__.write(plain + "\n")
            sys.__stdout__.flush()
            return

        self._append_to_buffer(entry)

    # ======================== 思考动画 ========================

    @contextmanager
    def thinking(self, message: str = "Thinking..."):
        self._thinking = True
        original_status = self._status
        self._status = "THINKING"
        self._update_status_line()
        self.add_log(message, "LLM")

        if UIManager._test_mode:
            sys.__stdout__.write(f"[{message}]\n")
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
            self._update_status_line()

    # ======================== 工具输出 ========================

    def print_tool_start(self, tool_name: str, args: Dict[str, Any] = None):
        self.increment_tool_count()
        self._append_to_buffer("")
        if args:
            args_str = " ".join(f"{k}={str(v)[:40]}" for k, v in list(args.items())[:3])
            self._append_to_buffer(f"[bold cyan]>>[/bold cyan] [bold]{tool_name}[/bold] [dim]({args_str})[/dim]")
        else:
            self._append_to_buffer(f"[bold cyan]>>[/bold cyan] [bold]{tool_name}[/bold]")

    def print_tool_start_log(self, tool_name: str, args: Dict[str, Any] = None):
        """工具调用日志（向后兼容）"""
        if args:
            preview = " ".join(f"{k}={str(v)[:20]}" for k, v in list(args.items())[:2])
            self.add_log(f"{tool_name}({preview})", "TOOL")
        else:
            self.add_log(tool_name, "TOOL")

    def print_tool_result(self, tool_name: str, result: str, success: bool = True):
        icon = "+" if success else "!"
        color = "green" if success else "red"
        if not isinstance(result, str):
            try:
                result = str(result)
            except Exception:
                result = f"<{type(result).__name__}>"

        self._append_to_buffer(f"  [{color}]{icon}[/{color}] [{color}]{tool_name}[/{color}]")

        if result:
            preview = result[:400] + "..." if len(result) > 400 else result
            for line in preview.split("\n")[:10]:
                self._append_to_buffer(f"  [dim]│[/dim] {line}")
        self._append_to_buffer("")

    def print_tool_result_log(self, tool_name: str, success: bool = True):
        if success:
            self.add_log(f"{tool_name} OK", "TOOL")
        else:
            self.add_log(f"{tool_name} FAILED", "ERROR")

    # ======================== 独立输出方法 ========================

    @staticmethod
    def _make_bar(value: int, max_val: int = 100, width: int = 10) -> str:
        """创建文本进度条"""
        pct = max(0, min(value, max_val)) / max(max_val, 1)
        filled = int(pct * width)
        return "█" * filled + "░" * (width - filled)

    def print_header(self, model: str, generation: int = None, tools_count: int = 0):
        """打印会话头 — 宠物面板版"""
        pet_name = "Baby Claw"
        pet_level = 1
        pet_age = 0
        mood = hunger = energy = health = love = 100
        exp = 0
        exp_max = 100
        try:
            p = get_pet()
            a = p.data.attributes
            pet_name = a.name or pet_name
            pet_level = a.level
            pet_age = pet_level - 1
            mood = a.mood
            hunger = a.hunger
            energy = int(a.energy)
            health = a.health
            love = a.love
            exp = a.exp
            exp_max = a.exp_to_next
        except Exception:
            pass

        art = self.avatar.get_art("happy")
        self._append_to_buffer(f"[cyan]{art}[/cyan]")

        self._append_to_buffer(
            f"[bold]Vibelution[/bold] [dim]v7.0[/dim]  —  "
            f"[cyan]{pet_name}[/cyan]  "
            f"[dim]Lv.{pet_level} ({pet_age}岁)[/dim]"
        )
        self._append_to_buffer("")

        bar_w = 10

        def _attr(label, value, color, icon):
            bar = self._make_bar(value, 100, bar_w)
            return f"  {icon} {label} [{color}]{bar}[/{color}] {value:>3}/100"

        self._append_to_buffer(
            _attr("Mood  ", mood, "yellow", "M") + "    " +
            _attr("Hunger", hunger, "green", "H")
        )
        self._append_to_buffer(
            _attr("Energy", energy, "cyan", "E") + "    " +
            _attr("Health", health, "red", "❤ ")
        )
        exp_pct = exp / exp_max if exp_max > 0 else 0
        exp_bar = f"[dim]{self._make_bar(exp, exp_max, bar_w)}[/dim]"
        self._append_to_buffer(
            _attr("Love  ", love, "magenta", "♥ ") + "    " +
            f"  ⭐ EXP     {exp_bar} {int(exp_pct * 100):>3}%"
        )
        self._append_to_buffer("")

        parts = [f"[dim]Model:[/dim] {model}"]
        if tools_count:
            parts.append(f"[dim]Tools:[/dim] {tools_count} loaded")
        parts.append(f"[dim]Time:[/dim] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._append_to_buffer("  |  ".join(parts))
        self._append_to_buffer("")

    def print_thinking(self, message: str):
        with self.console.status(f"[magenta]...[/magenta] {message}") as status:
            yield status

    def print_warning(self, message: str):
        self._append_to_buffer(f"[yellow]![/yellow] {message}")
        self.add_log(message, "WARN")

    def print_error(self, message: str, exc_info: str = None):
        self._append_to_buffer(f"[red]!! {message}[/red]")
        self.add_log(message, "ERROR")
        if exc_info:
            self._append_to_buffer(f"[red dim]{exc_info}[/red dim]")

    def print_success(self, message: str):
        self.add_log(message, "SUCCESS")

    def print_section(self, title: str):
        self._append_to_buffer(f"\n[bold cyan]--- {title} ---[/bold cyan]")

    def print_markdown(self, markdown_text: str):
        self.console.print(Markdown(markdown_text))

    def print_code(self, code: str, language: str = "python"):
        self.console.print(Syntax(code, language, theme="monokai", line_numbers=True))

    def print_table(self, data: List[Dict[str, Any]], columns: List[str] = None):
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
        tree = Tree(f"[bold yellow]Tasks[/bold yellow]")
        for task in tasks:
            title = task.get("title", "")
            done = task.get("done", False)
            priority = task.get("priority", "medium")
            pcolor = "red" if priority == "high" else ("yellow" if priority == "medium" else "cyan")
            icon = "[green]+[/green]" if done else "[dim]o[/dim]"
            tree.add(f"{icon} [{pcolor}]{title}[/{pcolor}]")
        self.console.print(tree)

    def print_progress(self, description: str, completed: int, total: int):
        bar_len = 30
        pct = completed / total if total > 0 else 0
        filled = int(bar_len * pct)
        bar = "[green]" + "=" * filled + "[/]" + "-" * (bar_len - filled)
        self.console.print(f"  {description}")
        self.console.print(f"  [{bar}] {int(pct * 100)}%")

    def print_lobster_status(self, status: str = "happy", message: str = ""):
        art = self.avatar.get_art(status)
        self.console.print(f"[cyan]{art}[/cyan]")
        self.console.print(f"[bold]Status:[/bold] {status.upper()}")
        if message:
            self.console.print(f"[dim]{message}[/dim]")

    def print_pet_status(self):
        try:
            text = self.pet.get_full_status_text()
            self.console.print(Panel(text, title="Pet", border_style="magenta", box=ASCII2))
        except Exception:
            self.console.print("[dim]Pet system not available[/dim]")

    def print_welcome_panel(self):
        """打印欢迎面板"""
        try:
            from config import get_config
            model = get_config().llm.model_name
        except Exception:
            model = "?"
        self.print_header(model)
        self._append_to_buffer("[dim]Type /help for commands, or enter a task to begin[/dim]")
        self._append_to_buffer("")

    def clear(self):
        self.console.clear()


# ======================== 全局实例 ========================

_ui: Optional[UIManager] = None


def get_ui() -> UIManager:
    global _ui
    if _ui is None:
        _ui = UIManager()
    return _ui




# ======================== 便捷函数 ========================

def ui_print_header(model: str, generation: int = None):
    get_ui().print_header(model, generation)


def ui_thinking(message: str = "Thinking..."):
    return get_ui().thinking(message)


def ui_print_tool(tool_name: str, args: Dict = None, result: str = None, success: bool = True):
    if result is None:
        get_ui().print_tool_start(tool_name, args)
    else:
        get_ui().print_tool_result(tool_name, result, success)


def ui_warning(message: str):
    get_ui().print_warning(message)


def ui_error(message: str, exc_info: str = None):
    get_ui().print_error(message, exc_info)


def ui_success(message: str):
    get_ui().print_success(message)


def ui_log(message: str, level: str = "INFO"):
    get_ui().add_log(message, level)


def ui_update_status(status: str, generation: int = None, goal: str = None,
                     iterations: int = None, tool_count: int = None,
                     input_tokens: int = None, output_tokens: int = None):
    get_ui().update_status(status, generation, goal, iterations, tool_count,
                           input_tokens=input_tokens, output_tokens=output_tokens)


def ui_task_board(markdown: str):
    get_ui().set_task_board(markdown)


def ui_lobster_status(status: str = "happy", message: str = ""):
    get_ui().print_lobster_status(status, message)


def ui_welcome():
    get_ui().print_welcome_panel()


def ui_print_welcome():
    get_ui().print_welcome_panel()


def run_interactive_mode(agent) -> bool:
    """交互模式 REPL — 支持宠物互动命令"""
    ui = get_ui()

    while True:
        try:
            user_input = input("Agent > ").strip()

            if not user_input:
                ui.start_live()
                agent.run_loop()
                ui.stop_live()
                break

            lower = user_input.lower()
            parts = user_input.split()
            cmd = parts[0].lower() if parts else ""
            args = parts[1:] if len(parts) > 1 else []

            if lower in ("/quit", "/exit", "/q"):
                print("Goodbye.")
                return True

            elif lower in ("/auto", "/a"):
                ui.start_live()
                agent.run_loop()
                ui.stop_live()
                break

            elif cmd == "/pet":
                ui.print_pet_status()

            elif cmd == "/feed":
                try:
                    pet = get_pet()
                    pet.feed(20)
                    ui.console.print("[green]Pet fed! Hunger +20, Mood +5[/green]")
                except Exception as e:
                    ui.console.print(f"[yellow]Feed failed: {e}[/yellow]")
                ui.print_pet_status()

            elif cmd == "/play":
                try:
                    pet = get_pet()
                    pet.play()
                    ui.console.print("[magenta]Played with pet! Love +10, Mood +15, Energy -10[/magenta]")
                except Exception as e:
                    ui.console.print(f"[yellow]Play failed: {e}[/yellow]")
                ui.print_pet_status()

            elif cmd == "/avatar":
                if args:
                    preset = args[0].lower()
                    from core.ui.ascii_art import get_avatar_manager
                    avatar = get_avatar_manager()
                    if avatar.switch(preset):
                        info = avatar.list_presets().get(preset, {})
                        ui.console.print(
                            f"[green]Avatar switched to:[/green] "
                            f"{info.get('icon', '?')} {info.get('name', preset)}"
                        )
                    else:
                        ui.console.print(f"[yellow]Unknown avatar: {preset}[/yellow]")
                        ui.console.print("[dim]Available: lobster, shrimp, crab, cat, chick[/dim]")
                else:
                    from core.ui.ascii_art import get_avatar_manager
                    avatar = get_avatar_manager()
                    ui.console.print("\n[bold]Available avatars:[/bold]")
                    for key, info in avatar.list_presets().items():
                        current = " [green](current)[/green]" if key == avatar.preset_name else ""
                        ui.console.print(
                            f"  {info['icon']} [cyan]{key}[/cyan] - "
                            f"{info['name']} - {info['desc']}{current}"
                        )
                    ui.console.print("[dim]Usage: /avatar <name>[/dim]\n")

            elif cmd == "/status":
                ui.print_header("?", tools_count=len(agent.key_tools) if hasattr(agent, 'key_tools') else 0)

            elif lower in ("/help", "/h", "/?"):
                ui.console.print("""
[yellow]Commands:[/yellow]
  /auto, /a     — Enter auto mode
  /quit, /q     — Exit
  /help, /h     — Show help
  /pet          — Show pet status
  /feed         — Feed pet (+20 hunger)
  /play         — Play with pet
  /avatar [name] — Switch avatar (lobster/shrimp/crab/cat/chick)
  /status       — Show full agent + pet status
  <text>        — Send task to Agent
""")

            else:
                ui.start_live()
                agent.run_loop(initial_prompt=user_input)
                ui.stop_live()
                print(f"[dim]{'─' * 50}[/dim]")
                print("[dim]Back to interactive mode[/dim]")
                print()

        except KeyboardInterrupt:
            print("\n[yellow]Interrupted.[/yellow]")
            return False
        except EOFError:
            return False

    return True
