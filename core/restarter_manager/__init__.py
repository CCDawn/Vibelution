# -*- coding: utf-8 -*-
"""
core/restarter_manager/ - Agent 生命周期重启管理器

专门负责 Agent 的进程重启与生命周期管理。
"""

from core.restarter_manager.restarter import (
    run_restarter,
    main as restarter_main,
)

__all__ = [
    "run_restarter",
    "restarter_main",
]
