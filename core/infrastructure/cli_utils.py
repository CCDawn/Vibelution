# -*- coding: utf-8 -*-
"""
core/infrastructure/cli_utils.py — CLI 辅助工具

职责：
- 命令行参数解析

从 agent.py 下沉，遵循 Core First 原则。
"""

from __future__ import annotations

import argparse


def parse_args():
    """解析命令行参数。

    Returns:
        argparse.Namespace: 解析后的参数
    """
    parser = argparse.ArgumentParser(description="自我进化 Agent")
    parser.add_argument('-c', '--config', dest='config_path', help='配置文件路径')
    parser.add_argument('--awake-interval', type=int, dest='awake_interval', help='苏醒间隔（秒）')
    parser.add_argument('--model', dest='model_name', help='模型名称')
    parser.add_argument('--temperature', type=float, help='温度参数')
    parser.add_argument('--log-level', dest='log_level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='日志级别')
    parser.add_argument('--name', help='Agent 名称')
    parser.add_argument('--test', action='store_true', help='运行首次进化测试')
    parser.add_argument('--prompt', type=str, default=None, help='初始任务提示')
    parser.add_argument('--auto', action='store_true', help='自动模式（无交互）')
    return parser.parse_args()
