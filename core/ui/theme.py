# -*- coding: utf-8 -*-
"""
Vibelution 终端主题配置

精简颜色方案：5 种语义色，最小化 emoji 依赖。
保持向后兼容：所有 classmethod 签名不变。
"""

from __future__ import annotations

from typing import Dict
from dataclasses import dataclass


class LobsterTheme:
    """终端主题配置"""

    # 语义色（5 种）
    SUCCESS = "green"
    ERROR = "red"
    WARN = "yellow"
    INFO = "cyan"
    DIM = "dim"

    # 兼容旧代码的颜色别名
    LOBSTER_RED = "red"
    LOBSTER_ORANGE = "yellow"
    LOBSTER_PINK = "magenta"
    LOBSTER_CYAN = "cyan"
    LOBSTER_GREEN = "green"
    LOBSTER_BLUE = "blue"
    WHITE = "white"
    DIM_CONST = "dim"
    BOLD = "bold"

    # 状态颜色
    STATUS_COLORS: Dict[str, str] = {
        "IDLE": "dim",
        "THINKING": "magenta",
        "ACTING": "cyan",
        "SUCCESS": "green",
        "ERROR": "red",
        "WARNING": "yellow",
    }

    # 日志级别颜色
    LOG_COLORS: Dict[str, str] = {
        "INFO": "cyan",
        "WARN": "yellow",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "red",
        "SUCCESS": "green",
        "TOOL": "cyan",
        "LLM": "magenta",
        "DEBUG": "dim",
    }

    # 状态标记（简洁文本）
    STATUS_ICONS: Dict[str, str] = {
        "IDLE": "-",
        "THINKING": "...",
        "ACTING": ">",
        "SUCCESS": "+",
        "ERROR": "!",
        "WARNING": "~",
    }

    # 日志前缀标记
    LOG_ICONS: Dict[str, str] = {
        "INFO": "--",
        "WARN": "!!",
        "WARNING": "!!",
        "ERROR": "!!",
        "CRITICAL": "!!",
        "SUCCESS": "++",
        "TOOL": ">>",
        "LLM": "##",
        "DEBUG": "..",
    }

    # 工具图标（文本前缀，非 emoji）
    TOOL_ICONS: Dict[str, str] = {
        "grep_search": "[grep]",
        "read_file": "[read]",
        "write_file": "[write]",
        "edit_file": "[edit]",
        "execute_shell": "[exec]",
        "apply_diff_edit": "[diff]",
        "trigger_self_restart": "[restart]",
        "search_and_replace": "[s/r]",
        "list_directory": "[ls]",
        "create_file": "[new]",
        "delete_file": "[del]",
        "web_search": "[web]",
        "browser_automation": "[browser]",
    }

    # 面板边框颜色
    PANEL_BORDER_COLORS: Dict[str, str] = {
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "red",
        "thinking": "magenta",
        "tool": "cyan",
        "default": "dim",
    }

    @classmethod
    def get_status_color(cls, status: str) -> str:
        return cls.STATUS_COLORS.get(status.upper(), "white")

    @classmethod
    def get_status_icon(cls, status: str) -> str:
        return cls.STATUS_ICONS.get(status.upper(), "-")

    @classmethod
    def get_log_color(cls, level: str) -> str:
        return cls.LOG_COLORS.get(level.upper(), "white")

    @classmethod
    def get_log_icon(cls, level: str) -> str:
        return cls.LOG_ICONS.get(level.upper(), "--")

    @classmethod
    def get_tool_icon(cls, tool_name: str) -> str:
        return cls.TOOL_ICONS.get(tool_name, ">>")

    @classmethod
    def get_panel_border(cls, style: str = "default") -> str:
        return cls.PANEL_BORDER_COLORS.get(style.lower(), "dim")


@dataclass
class LobsterStyle:
    """样式预设 — 简洁文本版本"""

    welcome_title: str = "Vibelution"
    welcome_border: str = "cyan"

    status_title: str = "Status"
    status_border: str = "dim"

    success_title: str = "+ OK"
    success_border: str = "green"

    error_title: str = "! Error"
    error_border: str = "red"

    warning_title: str = "~ Warning"
    warning_border: str = "yellow"

    thinking_title: str = "... Thinking"
    thinking_border: str = "magenta"

    tool_title: str = ">> Tool"
    tool_border: str = "cyan"


# 全局实例
DEFAULT_THEME = LobsterTheme()
DEFAULT_STYLE = LobsterStyle()


def get_theme() -> LobsterTheme:
    return DEFAULT_THEME


def get_style() -> LobsterStyle:
    return DEFAULT_STYLE
