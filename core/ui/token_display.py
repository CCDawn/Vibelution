#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Token 显示模块

职责：
- 统一格式化输出 Token 使用信息
- 支持 Rich Console 和纯文本 fallback

使用方式：
    from core.ui.token_display import print_tokens, print_input_tokens, print_output_tokens
"""

from __future__ import annotations

from typing import Optional


_token_console = None


def _get_token_console():
    """获取共享的 Token 显示 Console（延迟初始化）"""
    global _token_console
    if _token_console is None:
        from rich.console import Console
        _token_console = Console(force_terminal=True, stderr=False)
    return _token_console


def print_tokens(
    input_tokens: int,
    output_tokens: Optional[int] = None,
    iteration: Optional[int] = None,
    max_iterations: Optional[int] = None,
) -> None:
    """
    打印 Token 使用信息（路由到 Live 日志面板）

    Args:
        input_tokens: 输入 Token 数
        output_tokens: 输出 Token 数（可选）
        iteration: 当前迭代数（可选）
        max_iterations: 最大迭代数（可选）
    """
    # 通过 UI 日志系统路由，Token 信息显示在日志面板中
    try:
        from core.ui.cli_ui import UIManager
        if UIManager._test_mode:
            import sys
            if output_tokens is not None:
                sys.__stdout__.write(f"[TOKEN] 输出: {output_tokens} | 输入: {input_tokens}\n")
            elif iteration is not None and max_iterations is not None:
                sys.__stdout__.write(f"[TOKEN] 输入: {input_tokens} | 迭代: {iteration}/{max_iterations}\n")
            else:
                sys.__stdout__.write(f"[TOKEN] 输入: {input_tokens}\n")
            sys.__stdout__.flush()
            return
    except ImportError:
        pass
    try:
        from core.ui.cli_ui import ui_log
        if output_tokens is not None:
            ui_log(f"TOKEN 输出: {output_tokens} | 输入: {input_tokens}", "TOKEN")
        elif iteration is not None and max_iterations is not None:
            ui_log(f"TOKEN 输入: {input_tokens} | 迭代: {iteration}/{max_iterations}", "TOKEN")
        else:
            ui_log(f"TOKEN 输入: {input_tokens}", "TOKEN")
    except ImportError:
        # UI 模块未加载时直接打印
        console = _get_token_console()
        if output_tokens is not None:
            console.print(
                "[dim]\\[TOKEN] 输出: {} | 输入: {}[/dim]".format(output_tokens, input_tokens)
            )
        elif iteration is not None and max_iterations is not None:
            console.print(
                "[dim]\\[TOKEN] 输入: {} | 迭代: {}/{}[/dim]".format(
                    input_tokens, iteration, max_iterations
                )
            )
        else:
            console.print(f"[dim]\\[TOKEN] 输入: {input_tokens}[/dim]")


def print_input_tokens(input_tokens: int, iteration: int, max_iterations: int) -> None:
    """打印输入 Token 和迭代信息"""
    print_tokens(
        input_tokens=input_tokens,
        iteration=iteration,
        max_iterations=max_iterations
    )


def print_output_tokens(input_tokens: int, output_tokens: int) -> None:
    """打印输出 Token 信息"""
    print_tokens(input_tokens=input_tokens, output_tokens=output_tokens)


def format_token_report(
    input_tokens: int,
    output_tokens: int,
    compression_ratio: Optional[float] = None,
) -> str:
    """
    格式化 Token 报告

    Args:
        input_tokens: 输入 Token 数
        output_tokens: 输出 Token 数
        compression_ratio: 压缩率（可选）

    Returns:
        格式化的报告字符串
    """
    total = input_tokens + output_tokens
    report = f"Token: {input_tokens} + {output_tokens} = {total}"
    if compression_ratio is not None:
        report += f" (压缩率: {compression_ratio:.1%})"
    return report


__all__ = [
    "print_tokens",
    "print_input_tokens",
    "print_output_tokens",
    "format_token_report",
]
