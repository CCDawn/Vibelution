# Core 模块审查与修复规划

**日期：** 2026-04-18
**审查人：** Claude
**版本：** v1.0

---

## 一、审查概述

根据 INDEX.md (v4.8) 对项目进行了系统性审查，重点关注 core 各模块的**导入完整性**、**语法正确性**和**逻辑正确性**。

### 审查范围

| 模块目录 | 文件数 | 状态 |
|----------|--------|------|
| core/infrastructure/ | 7 | 可用 |
| core/evolution/ | 5 | 可用 |
| core/knowledge/ | 4 | 可用 |
| core/learning/ | 5 | 可用 |
| core/decision/ | 3 | 可用 |
| core/orchestration/ | 7 | ⚠️ 有问题 |
| core/autonomous/ | 4 | 可用 |
| core/capabilities/ | 6 | 可用 |
| core/ecosystem/ | 5 | 可用 |
| core/logging/ | 4 | 可用 |
| core/ui/ | 4 | 可用 |
| core/pet_system/ | 10+ | 可用 |

---

## 二、发现的问题

### 问题 1: MemoryManager 语法错误 [严重]

**文件：** `core/orchestration/memory_manager.py`
**位置：** 第 129 行
**严重程度：** 🔴 严重 - 导致模块无法使用

**问题代码：**
```python
124→        # 统计
125→        self._stats = {
126→            "tool_calls_recorded": 0,
127→            "insights_recorded": 0,
128→            "memory_saves": 0,
129→        }._load_long_term()  # ← 无效代码
130→
131→        # 统计
132→        self._stats = {
133→            "tool_calls_recorded": 0,
134→            "insights_recorded": 0,
135→            "memory_saves": 0,
136→        }
```

**错误分析：**
- 第 125-129 行是一个字典字面量，后面跟着 `._load_long_term()` 方法调用
- 这是无效的 Python 语法，字典对象没有 `_load_long_term` 方法
- 第 131-136 行有重复的 `_stats` 初始化代码

**错误验证：**
```bash
$ python -c "from core.orchestration.memory_manager import MemoryManager; mm = MemoryManager()"
AttributeError: 'dict' object has no attribute '_load_long_term'
```

**修复方案：**
删除第 129 行的 `}._load_long_term()`，保留第 131-136 行的正确代码。

---

### 问题 2: Task 导出名称不一致 [低]

**文件：** `core/orchestration/__init__.py`
**严重程度：** 🟡 低 - 功能可用但不匹配文档

**现象：**
- `from core.orchestration import Task` 失败
- `from core.orchestration import PlannerTask` 成功

**INDEX.md 描述：**
```python
from core.orchestration.task_planner import (
    TaskPlanner, Task as PlannerTask, TaskStatus, TaskPriority,
    get_task_planner, reset_task_planner
)
```

**建议：** 在 `__init__.py` 中添加 `Task` 作为 `PlannerTask` 的别名导出。

---

### 问题 3: ResponseParser 导出路径不一致 [低]

**文件：** `core/orchestration/__init__.py`
**严重程度：** 🟡 低

**现象：**
- `from core.orchestration import ResponseParser` 失败
- `from core.capabilities import ResponseParser` 成功

**原因：** `capabilities/__init__.py` 从 `orchestration.response_parser` 导入了 `ResponseParser`，但 `orchestration/__init__.py` 本身没有直接导出它。

**建议：** 在 `orchestration/__init__.py` 中添加 ResponseParser 导出。

---

### 问题 4: workspace_manager.py 已修复 [已解决]

**文件：** `core/infrastructure/workspace_manager.py`
**状态：** ✅ 已修复

之前报告的第 82-89 行缩进错误已修复，`WorkspaceManager` 可以正常导入和使用。

---

## 三、提示词系统审查

### 双轨加载架构

根据 INDEX.md 和实际代码审查，提示词系统采用**双轨加载架构**：

```
core/core_prompt/              ← 静态核心提示词（内置只读模板）
├── __init__.py               CorePromptManager 双轨加载引擎
├── SOUL.md                   禁止修改
└── AGENTS.md                 禁止修改

workspace/prompts/            ← 动态提示词（用户可编辑，覆盖优先）
├── SOUL.md                   ✅ 可覆盖
├── AGENTS.md                 ✅ 可覆盖
├── IDENTITY.md               ✅ 可修改
├── USER.md                   ✅ 可修改
├── DYNAMIC.md                ✅ 必须修改
└── COMPRESS_SUMMARY.md       ✅ 可修改
```

### PromptManager 实现状态

| 功能 | 状态 | 说明 |
|------|------|------|
| 双轨加载 | ✅ 完整 | workspace 优先，回退 static |
| 参数驱动拼接 | ✅ 完整 | `build(include, exclude)` API |
| 组件注册表 | ✅ 完整 | 10+ 组件 |
| 规则注册表 | ✅ 完整 | base/code_review/creative/debug/planning/refactor |
| 状态记忆持久化 | ✅ 完整 | STATE_MEMORY.md |
| 向后兼容 | ✅ 完整 | `build_system_prompt()` 兼容函数 |

### memory_tools.py 实现状态

| 功能 | 状态 | 说明 |
|------|------|------|
| 世代索引读写 | ✅ 完整 | `read_memory_tool()`, `commit_compressed_memory_tool()` |
| 世代归档 | ✅ 完整 | `archive_generation_history()` |
| 动态提示词 | ✅ 完整 | `read_dynamic_prompt_tool()`, `update_generation_task_tool()` |
| 任务管理 | ✅ 完整 | `set_plan_tool()`, `tick_subtask_tool()` |
| 代码库认知 | ✅ 完整 | `record_codebase_insight_tool()`, `get_global_codebase_map_tool()` |
| 重启拦截 | ✅ 完整 | `check_restart_block_tool()` |

---

## 四、记忆管理系统审查

### 三层记忆架构

根据 `memory_manager.py` 和 `memory_tools.py`，系统采用**三层记忆架构**：

```
┌─────────────────────────────────────────────────────────────┐
│                    三层记忆架构                               │
├─────────────────────────────────────────────────────────────┤
│  短期记忆 (ShortTermMemory)                                  │
│  ├── session_id: 会话标识                                    │
│  ├── task_list: 任务列表                                     │
│  ├── tool_calls: 工具调用记录                                │
│  ├── thoughts: 思考过程                                      │
│  └── user_inputs: 用户输入                                   │
├─────────────────────────────────────────────────────────────┤
│  中期记忆 (MidTermMemory)                                    │
│  ├── generation: 世代号                                      │
│  ├── current_task: 当前任务                                  │
│  ├── task_plan: 任务计划                                     │
│  ├── completed_tasks: 已完成任务                             │
│  ├── insights: 洞察                                          │
│  ├── code_insights: 代码洞察                                 │
│  └── tool_stats: 工具统计                                    │
├─────────────────────────────────────────────────────────────┤
│  长期记忆 (LongTermMemory)                                    │
│  ├── current_generation: 当前世代                             │
│  ├── total_generations: 总世代数                             │
│  ├── core_wisdom: 核心智慧                                   │
│  ├── skills_profile: 能力画像                                │
│  ├── evolution_history: 进化历史                              │
│  └── archive_index: 归档索引                                 │
└─────────────────────────────────────────────────────────────┘
```

### 组件集成状态

| 组件 | 状态 | 说明 |
|------|------|------|
| SemanticRetriever | ✅ 可用 | 语义检索 |
| CompressionPersister | ✅ 可用 | 压缩快照持久化 |
| ForgettingEngine | ✅ 可用 | 选择性遗忘 |
| WorkspaceManager | ✅ 可用 | SQLite 工作区 |

### ⚠️ MemoryManager 实例化问题

由于第 129 行的语法错误，`MemoryManager` 类**无法实例化**，导致以下功能暂时不可用：
- `get_memory_manager()` 单例获取失败
- 三层记忆的统一管理功能中断
- 语义检索、压缩持久化、遗忘引擎的集成功能受影响

---

## 五、修复计划

### 优先级排序

| 优先级 | 问题 | 预计工时 | 影响范围 |
|--------|------|----------|----------|
| P0 | MemoryManager 语法错误 | 5 分钟 | 整个记忆系统 |
| P1 | Task 导出别名 | 5 分钟 | API 一致性 |
| P2 | ResponseParser 导出 | 5 分钟 | API 一致性 |

### 修复步骤

#### P0: MemoryManager 语法错误

1. 编辑 `core/orchestration/memory_manager.py`
2. 删除第 129 行 `}._load_long_term()`
3. 保留第 131-136 行的正确初始化代码
4. 运行测试验证：
   ```bash
   python -c "from core.orchestration.memory_manager import MemoryManager; mm = MemoryManager(); print('OK')"
   ```

#### P1: Task 导出别名

1. 编辑 `core/orchestration/__init__.py`
2. 在 `task_planner` 导入处添加 `Task` 别名

#### P2: ResponseParser 导出

1. 编辑 `core/orchestration/__init__.py`
2. 添加 `from core.orchestration.response_parser import ResponseParser`

---

## 六、验证清单

修复完成后需要验证：

- [ ] `python -c "from core.orchestration.memory_manager import MemoryManager; mm = MemoryManager()"` 成功
- [ ] `python -c "from core.orchestration import Task"` 成功
- [ ] `python -c "from core.orchestration import ResponseParser"` 成功
- [ ] `python -c "from core.orchestration import get_memory_manager; mm = get_memory_manager()"` 成功
- [ ] `pytest tests/test_memory_manager.py -v` 通过

---

## 七、后续建议

### 短期 (1-2 天)
1. 修复上述 3 个问题
2. 运行 Phase 7 模块测试 (`pytest tests/test_memory_manager.py tests/test_llm_orchestrator.py -v`)
3. 验证 MemoryManager 与 agent.py 的集成

### 中期 (1 周)
1. 完善 Phase 8 自主探索模块的实现
2. 补充 MemoryManager 的单元测试
3. 优化提示词系统的组件管理

### 长期 (1 个月)
1. 实现 agent.py 的完全模块化拆分（目标 <500 行）
2. 建立完整的端到端测试覆盖
3. 优化记忆系统的检索效率

---

## 八、附录

### A. 相关文件路径

| 文件 | 路径 |
|------|------|
| MemoryManager | `core/orchestration/memory_manager.py` |
| PromptManager | `core/capabilities/prompt_manager.py` |
| memory_tools | `tools/memory_tools.py` |
| workspace_manager | `core/infrastructure/workspace_manager.py` |
| 测试套件 | `tests/test_memory_manager.py` |

### B. 参考文档

- `INDEX.md` - 项目全局索引 (v4.8)
- `requirement/claude第一次规划/记忆力机制优化方案.md`
- `requirement/claude第一次规划/core目录结构重组方案.md`
