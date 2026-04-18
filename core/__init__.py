"""
core - 核心模块包

目录结构重组 (2026-04-17):
- infrastructure/ : 基础设施 (工具执行、状态、事件、安全、模型发现，工作区)
- evolution/       : 进化引擎 (进化流程、自我分析、重构规划、代码生成)
- knowledge/       : 知识系统 (知识图谱、代码分析、语义搜索、消息总线)
- learning/        : 持续学习 (学习引擎、反馈循环、洞察追踪、策略学习)
- decision/        : 自主决策 (决策树、优先级优化、策略选择)
- orchestration/   : 模块化重构 (LLM协调、记忆管理、任务规划、压缩持久化、语义检索、遗忘引擎)
- autonomous/      : 自主探索 (自主模式、探索引擎、机会发现、目标生成)
- ui/             : 用户界面 (ASCII艺术、CLI UI、交互式CLI、主题)
- logging/         : 日志系统 (调试日志、统一日志、转录日志、工具追踪)
- capabilities/    : 能力系统 (能力画像、任务分析、任务管理、提示词构建、模式库)
- ecosystem/       : 工具生态 (工具生态系统、重启管理)
- pet_system/      : 宠物系统 (保持不变)
- core_prompt/     : 核心提示词 (双轨加载：静态SOUL/AGENTS + 动态workspace覆盖)

向后兼容：
- 所有模块现在位于子目录中，但通过各子目录的 __init__.py 重新导出
- 旧的导入路径如 `from core.tool_executor import` 已不再有效
- 请使用新的导入路径如 `from core.infrastructure.tool_executor import`

提示词双轨加载说明：
- core/core_prompt/: 内置只读模板（SOUL.md, AGENTS.md）
- workspace/prompts/: 用户可编辑覆盖层（优先加载）
- 加载器：CorePromptManager (core/core_prompt/__init__.py)
"""

# 标记重组版本
__version__ = "4.4"
CORE_REORGANIZED = True
CORE_REORGANIZE_DATE = "2026-04-18"
