# Core 目录结构重组方案 - SPEC 规范

**版本：** v1.0
**日期：** 2026-04-17
**类型：** 技术重构 - 目录结构优化

---

## S - Self-Evolving-Baby (Core 目录重组)

### 当前问题诊断

| 问题 | 现状 | 影响 |
|------|------|------|
| 目录扁平化 | core/ 下 47 个文件堆叠 | 难以定位和维护 |
| 功能不分组 | 按 Phase 而非功能分组 | 相关功能分散 |
| 宠物系统独立 | pet_system/ 已独立 | 但仍在 core 下根目录 |
| 导入路径复杂 | `from core.xxx import` 层级不清 | - |

---

## P - Purpose (目标)

### 核心目标

```
┌─────────────────────────────────────────────────────────────────┐
│                   Core 目录结构重组目标                            │
├─────────────────────────────────────────────────────────────────┤
│  1. 按功能分类组织文件                                            │
│  2. 保持向后兼容 - 所有导入路径继续有效                           │
│  3. 简化长路径导入 - 使用 __init__.py 重导出                    │
│  4. 提升可维护性 - 相关功能放在一起                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## E - Evolution (进化路径)

### 当前结构

```
core/
├── __init__.py
├── 47 个 .py 文件 (全部堆叠在一起)
└── pet_system/  (子目录)
```

### 目标结构

```
core/
├── __init__.py                      # 统一导出入口
│
├── ━━━ Phase 1-2: 基础设施 ━━━
├── infrastructure/                   # 基础设施
│   ├── __init__.py
│   ├── tool_executor.py
│   ├── tool_registry.py
│   ├── state.py
│   ├── event_bus.py
│   ├── security.py
│   ├── model_discovery.py
│   └── workspace_manager.py
│
├── ━━━ Phase 3: 进化能力 ━━━
├── evolution/                        # 进化引擎
│   ├── __init__.py
│   ├── evolution_engine.py
│   ├── self_analyzer.py
│   ├── refactoring_planner.py
│   ├── code_generator.py
│   └── self_refactoror.py
│
├── ━━━ Phase 4: 知识系统 ━━━
├── knowledge/                        # 知识系统
│   ├── __init__.py
│   ├── knowledge_graph.py
│   ├── codebase_analyzer.py
│   ├── semantic_search.py
│   └── message_bus.py
│
├── ━━━ Phase 5: 持续学习 ━━━
├── learning/                         # 持续学习
│   ├── __init__.py
│   ├── learning_engine.py
│   ├── feedback_loop.py
│   ├── insight_tracker.py
│   ├── strategy_learner.py
│   └── agent_core.py                 # Agent 抽象基类
│
├── ━━━ Phase 6: 自主决策 ━━━
├── decision/                         # 自主决策
│   ├── __init__.py
│   ├── decision_tree.py
│   ├── priority_optimizer.py
│   └── strategy_selector.py
│
├── ━━━ Phase 7: 模块化重构 ━━━
├── orchestration/                    # 模块化重构
│   ├── __init__.py
│   ├── llm_orchestrator.py
│   ├── memory_manager.py
│   ├── task_planner.py
│   ├── compression_persister.py      # Phase 5 记忆增强
│   ├── semantic_retriever.py         # Phase 5 记忆增强
│   └── forgetting_engine.py           # Phase 5 记忆增强
│
├── ━━━ Phase 8: 自主探索 ━━━
├── autonomous/                        # 自主探索
│   ├── __init__.py
│   ├── autonomous_mode.py
│   ├── autonomous_explorer.py
│   ├── opportunity_finder.py
│   └── goal_generator.py
│
├── ━━━ 工具与UI ━━━
├── ui/                               # 用户界面
│   ├── __init__.py
│   ├── ascii_art.py
│   ├── cli_ui.py
│   ├── interactive_cli.py
│   └── theme.py
│
├── ━━━ 日志与追踪 ━━━
├── logging/                          # 日志系统
│   ├── __init__.py
│   ├── logger.py
│   ├── unified_logger.py
│   ├── transcript_logger.py
│   └── tool_tracker.py
│
├── ━━━ 能力与任务 ━━━
├── capabilities/                      # 能力系统
│   ├── __init__.py
│   ├── skills_profiler.py
│   ├── task_analyzer.py
│   ├── task_manager.py
│   ├── prompt_builder.py
│   └── pattern_library.py
│
├── ━━━ 工具生态系统 ━━━
├── ecosystem/                         # 工具生态
│   ├── __init__.py
│   ├── tool_ecosystem.py
│   └── restarter.py
│
├── ━━━ 宠物系统 ━━━
├── pet_system/                        # 宠物系统 (已独立)
│   └── [保持不变]
│
└── backup/                            # 备份文件
    └── agent_core_backup.py
```

---

## 一、功能分组详情

### 1.1 infrastructure/ - 基础设施

| 文件 | 功能 | 导入来源 |
|------|------|---------|
| tool_executor.py | 工具执行器 | tools/ |
| tool_registry.py | 工具注册表 | tools/ |
| state.py | 状态管理 | core/ |
| event_bus.py | 事件总线 | core/ |
| security.py | 安全模块 | core/ |
| model_discovery.py | 模型发现 | core/ |
| workspace_manager.py | 工作区管理 | core/ |

### 1.2 evolution/ - 进化引擎

| 文件 | 功能 | 导入来源 |
|------|------|---------|
| evolution_engine.py | 8阶段进化 | core/ |
| self_analyzer.py | 自我分析 | core/ |
| refactoring_planner.py | 重构规划 | core/ |
| code_generator.py | 代码生成 | core/ |
| self_refactoror.py | 自我重构 | core/ |

### 1.3 knowledge/ - 知识系统

| 文件 | 功能 | 导入来源 |
|------|------|---------|
| knowledge_graph.py | 知识图谱 | core/ |
| codebase_analyzer.py | 代码分析 | core/ |
| semantic_search.py | 语义搜索 | core/ |
| message_bus.py | 消息总线 | core/ |

### 1.4 learning/ - 持续学习

| 文件 | 功能 | 导入来源 |
|------|------|---------|
| learning_engine.py | 学习引擎 | core/ |
| feedback_loop.py | 反馈循环 | core/ |
| insight_tracker.py | 洞察追踪 | core/ |
| strategy_learner.py | 策略学习 | core/ |
| agent_core.py | Agent 基类 | core/ |

### 1.5 decision/ - 自主决策

| 文件 | 功能 | 导入来源 |
|------|------|---------|
| decision_tree.py | 决策树 | core/ |
| priority_optimizer.py | 优先级优化 | core/ |
| strategy_selector.py | 策略选择 | core/ |

### 1.6 orchestration/ - 模块化重构

| 文件 | 功能 | 导入来源 |
|------|------|---------|
| llm_orchestrator.py | LLM 协调 | core/ |
| memory_manager.py | 记忆管理 | core/ |
| task_planner.py | 任务规划 | core/ |
| compression_persister.py | 压缩持久化 | core/ |
| semantic_retriever.py | 语义检索 | core/ |
| forgetting_engine.py | 遗忘引擎 | core/ |

### 1.7 autonomous/ - 自主探索

| 文件 | 功能 | 导入来源 |
|------|------|---------|
| autonomous_mode.py | 自主模式 | core/ |
| autonomous_explorer.py | 探索引擎 | core/ |
| opportunity_finder.py | 机会发现 | core/ |
| goal_generator.py | 目标生成 | core/ |

### 1.8 ui/ - 用户界面

| 文件 | 功能 | 导入来源 |
|------|------|---------|
| ascii_art.py | ASCII 艺术 | core/ |
| cli_ui.py | CLI UI | core/ |
| interactive_cli.py | 交互式 CLI | core/ |
| theme.py | 主题系统 | core/ |

### 1.9 logging/ - 日志系统

| 文件 | 功能 | 导入来源 |
|------|------|---------|
| logger.py | 调试日志 | core/ |
| unified_logger.py | 统一日志 | core/ |
| transcript_logger.py | 转录日志 | core/ |
| tool_tracker.py | 工具追踪 | core/ |

### 1.10 capabilities/ - 能力系统

| 文件 | 功能 | 导入来源 |
|------|------|---------|
| skills_profiler.py | 能力画像 | core/ |
| task_analyzer.py | 任务分析 | core/ |
| task_manager.py | 任务管理 | core/ |
| prompt_builder.py | 提示词构建 | core/ |
| pattern_library.py | 模式库 | core/ |

### 1.11 ecosystem/ - 工具生态

| 文件 | 功能 | 导入来源 |
|------|------|---------|
| tool_ecosystem.py | 工具生态 | core/ |
| restarter.py | 重启管理 | core/ |

---

## 二、向后兼容策略

### 2.1 核心原则

**保持所有原有导入路径有效**

```python
# 原有导入（继续有效）
from core.tool_executor import get_tool_executor
from core.memory_manager import get_memory_manager

# 新增导入（同时有效）
from core.infrastructure.tool_executor import get_tool_executor
from core.orchestration.memory_manager import get_memory_manager
```

### 2.2 实现方式

在 `core/__init__.py` 中重导出所有符号：

```python
# core/__init__.py

# 从新位置重导出，保持向后兼容
from core.infrastructure.tool_executor import (
    ToolExecutor, get_tool_executor, reset_tool_executor
)
from core.infrastructure.tool_registry import (
    ToolRegistry, ToolMetadata, get_tool_registry, reset_tool_registry
)
# ... 其他所有模块

# 标记为已重组
CORE_REORGANIZED = True
CORE_REORGANIZE_DATE = "2026-04-17"
```

---

## 三、执行步骤

### Phase 1: 创建目录结构 (0.5天)

```bash
cd core/
mkdir -p infrastructure evolution knowledge learning decision orchestration
mkdir -p autonomous ui logging capabilities ecosystem backup
```

### Phase 2: 移动文件 (1天)

按依赖顺序移动（先移动无依赖的）：

| 顺序 | 目录 | 文件 |
|------|------|------|
| 1 | infrastructure/ | tool_executor, tool_registry, state, event_bus, security, model_discovery, workspace_manager |
| 2 | ui/ | ascii_art, cli_ui, interactive_cli, theme |
| 3 | logging/ | logger, unified_logger, transcript_logger, tool_tracker |
| 4 | capabilities/ | skills_profiler, task_analyzer, task_manager, prompt_builder, pattern_library |
| 5 | ecosystem/ | tool_ecosystem, restarter |
| 6 | knowledge/ | knowledge_graph, codebase_analyzer, semantic_search, message_bus |
| 7 | evolution/ | evolution_engine, self_analyzer, refactoring_planner, code_generator, self_refactoror |
| 8 | learning/ | learning_engine, feedback_loop, insight_tracker, strategy_learner, agent_core |
| 9 | decision/ | decision_tree, priority_optimizer, strategy_selector |
| 10 | orchestration/ | llm_orchestrator, memory_manager, task_planner, compression_persister, semantic_retriever, forgetting_engine |
| 11 | autonomous/ | autonomous_mode, autonomous_explorer, opportunity_finder, goal_generator |

### Phase 3: 创建 __init__.py (0.5天)

每个目录创建 `__init__.py`，重导出所有公开 API。

### Phase 4: 更新 core/__init__.py (0.5天)

重导出所有模块，保持向后兼容。

### Phase 5: 验证导入 (0.5天)

```bash
# 测试所有导入路径
python -c "from core import *"
python -c "from core.infrastructure import *"
python -c "from core.orchestration import *"
# ... 测试所有分组
```

### Phase 6: 更新 agent.py 和其他导入 (1天)

检查并更新所有使用旧导入路径的文件。

---

## 四、风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 导入路径失效 | 代码无法运行 | 使用 __init__.py 重导出 |
| 循环依赖 | 模块无法导入 | 按依赖顺序移动 |
| 第三方工具失效 | IDE 无法找到定义 | 更新 IDE 配置 |
| 测试失败 | 回归问题 | 完整测试套件运行 |

---

## 五、验证清单

```
✅ 所有目录创建完成
✅ 所有文件移动到正确位置
✅ 每个目录有 __init__.py
✅ core/__init__.py 重导出所有符号
✅ 原有导入路径继续有效
✅ 新导入路径可用
✅ agent.py 导入正常
✅ tools/ 导入正常
✅ tests/ 导入正常
✅ 完整测试通过
```

---

## 六、文件清单

### 新目录结构

```
core/
├── __init__.py                      # 统一导出入口 (更新)
├── infrastructure/                   # [新建]
│   ├── __init__.py                   # [新建]
│   ├── tool_executor.py              # [移动]
│   ├── tool_registry.py              # [移动]
│   ├── state.py                      # [移动]
│   ├── event_bus.py                  # [移动]
│   ├── security.py                   # [移动]
│   ├── model_discovery.py            # [移动]
│   └── workspace_manager.py          # [移动]
├── evolution/                        # [新建]
│   ├── __init__.py                   # [新建]
│   ├── evolution_engine.py          # [移动]
│   ├── self_analyzer.py              # [移动]
│   ├── refactoring_planner.py       # [移动]
│   ├── code_generator.py            # [移动]
│   └── self_refactoror.py            # [移动]
├── knowledge/                        # [新建]
│   ├── __init__.py                   # [新建]
│   ├── knowledge_graph.py           # [移动]
│   ├── codebase_analyzer.py         # [移动]
│   ├── semantic_search.py           # [移动]
│   └── message_bus.py                 # [移动]
├── learning/                         # [新建]
│   ├── __init__.py                   # [新建]
│   ├── learning_engine.py            # [移动]
│   ├── feedback_loop.py             # [移动]
│   ├── insight_tracker.py           # [移动]
│   ├── strategy_learner.py          # [移动]
│   └── agent_core.py                 # [移动]
├── decision/                         # [新建]
│   ├── __init__.py                   # [新建]
│   ├── decision_tree.py             # [移动]
│   ├── priority_optimizer.py        # [移动]
│   └── strategy_selector.py         # [移动]
├── orchestration/                    # [新建]
│   ├── __init__.py                   # [新建]
│   ├── llm_orchestrator.py          # [移动]
│   ├── memory_manager.py            # [移动]
│   ├── task_planner.py              # [移动]
│   ├── compression_persister.py    # [移动]
│   ├── semantic_retriever.py        # [移动]
│   └── forgetting_engine.py         # [移动]
├── autonomous/                        # [新建]
│   ├── __init__.py                   # [新建]
│   ├── autonomous_mode.py          # [移动]
│   ├── autonomous_explorer.py      # [移动]
│   ├── opportunity_finder.py       # [移动]
│   └── goal_generator.py            # [移动]
├── ui/                               # [新建]
│   ├── __init__.py                   # [新建]
│   ├── ascii_art.py                 # [移动]
│   ├── cli_ui.py                    # [移动]
│   ├── interactive_cli.py           # [移动]
│   └── theme.py                      # [移动]
├── logging/                          # [新建]
│   ├── __init__.py                   # [新建]
│   ├── logger.py                    # [移动]
│   ├── unified_logger.py            # [移动]
│   ├── transcript_logger.py         # [移动]
│   └── tool_tracker.py               # [移动]
├── capabilities/                      # [新建]
│   ├── __init__.py                   # [新建]
│   ├── skills_profiler.py           # [移动]
│   ├── task_analyzer.py             # [移动]
│   ├── task_manager.py              # [移动]
│   ├── prompt_builder.py           # [移动]
│   └── pattern_library.py           # [移动]
├── ecosystem/                         # [新建]
│   ├── __init__.py                   # [新建]
│   ├── tool_ecosystem.py            # [移动]
│   └── restarter.py                 # [移动]
├── pet_system/                        # [保持不变]
│   └── [现有文件]
└── backup/                            # [新建]
    └── agent_core_backup.py          # [移动]
```

---

## 七、里程碑

| 阶段 | 完成标准 | 预计时间 |
|------|----------|----------|
| Phase 1 | 创建目录结构 | 0.5天 |
| Phase 2 | 移动文件 | 1天 |
| Phase 3 | 创建 __init__.py | 0.5天 |
| Phase 4 | 更新 core/__init__.py | 0.5天 |
| Phase 5 | 验证导入 | 0.5天 |
| Phase 6 | 更新其他文件导入 | 1天 |
| **Total** | **重组完成** | **5天** |

---

**下一步行动：**
1. 创建目录结构
2. 移动文件（按依赖顺序）
3. 创建各目录 __init__.py
4. 更新 core/__init__.py
5. 验证所有导入
6. 更新 INDEX.md
7. 生成任务报告
