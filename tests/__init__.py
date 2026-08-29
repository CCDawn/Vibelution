#!/usr/bin/env python3
"""
自我进化 Agent - 核心测试套件

包含以下测试模块：
1. test_memory.py - 记忆系统读写测试
2. test_tools.py - 工具模块可用性测试
3. test_compression.py - Token 压缩逻辑测试
4. conftest.py - pytest 配置和共享 fixtures

运行方式：
    pytest tests/ -v --maxfail=0
    pytest tests/ -v --tb=short --maxfail=0

只有在所有测试通过后，Agent 才能执行 trigger_self_restart 进行自我进化。
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
