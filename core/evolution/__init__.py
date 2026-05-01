"""
Core Evolution Module - 自进化引擎
基于5.4.2 Phase 3进化引擎规范实现

功能模块：
- SelfEvolution: 基于反馈的行为模式自动调整
- SelfMonitor: 实时性能和状态监控
- SelfRepair: 错误检测与自动修复

Author: Vibelution Agent
Version: 5.4.3-phase3
"""

from .evolution_engine import EvolutionEngine
from .self_monitor import SelfMonitor
from .self_repair import SelfRepair
from .self_evolution import SelfEvolution

__all__ = [
    "EvolutionEngine",
    "SelfMonitor", 
    "SelfRepair",
    "SelfEvolution",
]

__version__ = "5.4.3-phase3"
