# -*- coding: utf-8 -*-
"""
龙虾宝宝主题配置

提供统一的颜色、图标、样式配置。
"""

from __future__ import annotations

from typing import Dict, Optional
from dataclasses import dataclass


class LobsterTheme:
    """
    龙虾宝宝终端主题配置

    统一管理所有终端显示的样式、颜色和图标。
    """

    # 主色调
    LOBSTER_RED = "bright_red"
    LOBSTER_ORANGE = "bright_yellow"
    LOBSTER_PINK = "bright_magenta"
    LOBSTER_CYAN = "bright_cyan"
    LOBSTER_GREEN = "bright_green"
    LOBSTER_BLUE = "bright_blue"

    # 基础色
    WHITE = "white"
    DIM = "dim"
    BOLD = "bold"

    # 状态颜色映射
    STATUS_COLORS: Dict[str, str] = {
        "IDLE": "cyan",
        "THINKING": "bright_magenta",
        "SEARCHING": "bright_blue",
        "CODING": "bright_green",
        "TESTING": "bright_yellow",
        "COMPRESSING": "bright_magenta",
        "RESTARTING": "bright_red",
        "HIBERNATING": "bright_black",
        "SUCCESS": "bright_green",
        "ERROR": "bright_red",
        "WARNING": "bright_yellow",
    }

    # 日志级别颜色
    LOG_COLORS: Dict[str, str] = {
        "INFO": "bright_cyan",
        "WARN": "bright_yellow",
        "WARNING": "bright_yellow",
        "ERROR": "bright_red",
        "CRITICAL": "bright_red",
        "SUCCESS": "bright_green",
        "TOOL": "bright_magenta",
        "LLM": "bright_magenta",
        "DEBUG": "dim",
    }

    # 状态图标（带备选）
    STATUS_ICONS: Dict[str, str] = {
        "IDLE": "🦞",
        "THINKING": "🤔",
        "SEARCHING": "🔍",
        "CODING": "💻",
        "TESTING": "🧪",
        "COMPRESSING": "📦",
        "RESTARTING": "🔄",
        "HIBERNATING": "😴",
        "SUCCESS": "✅",
        "ERROR": "❌",
        "WARNING": "⚠️",
        "DONE": "🏁",
        "RUNNING": "🔧",
    }

    # 日志图标
    LOG_ICONS: Dict[str, str] = {
        "INFO": "💡",
        "WARN": "⚠️",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "CRITICAL": "💥",
        "SUCCESS": "✅",
        "TOOL": "🔧",
        "LLM": "🧠",
        "DEBUG": "🔍",
        "SEARCH": "🔍",
        "CODING": "💻",
        "TESTING": "🧪",
    }

    # 工具图标
    TOOL_ICONS: Dict[str, str] = {
        "grep_search": "🔍",
        "read_file": "📖",
        "write_file": "✏️",
        "edit_file": "📝",
        "execute_shell": "💻",
        "apply_diff_edit": "🔧",
        "trigger_self_restart": "🔄",
        "search_and_replace": "🔄",
        "list_directory": "📁",
        "create_file": "🆕",
        "delete_file": "🗑️",
        "web_search": "🌐",
        "browser_automation": "🌐",
    }

    # 面板边框样式
    PANEL_BORDER_COLORS: Dict[str, str] = {
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "red",
        "thinking": "magenta",
        "tool": "magenta",
        "default": "cyan",
    }

    @classmethod
    def get_status_color(cls, status: str) -> str:
        """获取状态对应的颜色"""
        return cls.STATUS_COLORS.get(status.upper(), "white")

    @classmethod
    def get_status_icon(cls, status: str) -> str:
        """获取状态对应的图标（带备选）"""
        return cls.STATUS_ICONS.get(status.upper(), "🦞")

    @classmethod
    def get_log_color(cls, level: str) -> str:
        """获取日志级别对应的颜色"""
        return cls.LOG_COLORS.get(level.upper(), "white")

    @classmethod
    def get_log_icon(cls, level: str) -> str:
        """获取日志级别对应的图标"""
        return cls.LOG_ICONS.get(level.upper(), "💬")

    @classmethod
    def get_tool_icon(cls, tool_name: str) -> str:
        """获取工具对应的图标"""
        return cls.TOOL_ICONS.get(tool_name, "🔧")

    @classmethod
    def get_panel_border(cls, style: str = "default") -> str:
        """获取面板边框颜色"""
        return cls.PANEL_BORDER_COLORS.get(style.lower(), "cyan")


@dataclass
class LobsterStyle:
    """龙虾宝宝样式预设"""

    # 欢迎面板
    welcome_title: str = "[bold bright_red]🦞 虾宝已就绪[/bold bright_red]"
    welcome_border: str = "bright_cyan"

    # 状态面板
    status_title: str = "[bold bright_red]🦞 虾宝状态[/bold bright_red]"
    status_border: str = "cyan"

    # 成功面板
    success_title: str = "[bold bright_green]✅ 成功[/bold bright_green]"
    success_border: str = "green"

    # 错误面板
    error_title: str = "[bold bright_red]❌ 错误[/bold bright_red]"
    error_border: str = "red"

    # 警告面板
    warning_title: str = "[bold bright_yellow]⚠️ 警告[/bold bright_yellow]"
    warning_border: str = "yellow"

    # 思考面板
    thinking_title: str = "[bold bright_magenta]🤔 思考中[/bold bright_magenta]"
    thinking_border: str = "magenta"

    # 工具面板
    tool_title: str = "[bold bright_magenta]🔧 执行工具[/bold bright_magenta]"
    tool_border: str = "magenta"


# 全局实例
DEFAULT_THEME = LobsterTheme()
DEFAULT_STYLE = LobsterStyle()


def get_theme() -> LobsterTheme:
    """获取主题配置"""
    return DEFAULT_THEME


def get_style() -> LobsterStyle:
    """获取样式预设"""
    return DEFAULT_STYLE
