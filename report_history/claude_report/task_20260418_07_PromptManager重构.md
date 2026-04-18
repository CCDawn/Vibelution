# PromptManager 重构 - 提示词系统动态管理

**任务编号**：19
**完成时间**：2026-04-18
**Phase**：核心模块重构
**状态**：✅ 完整

---

## 任务概述

将现有的 `CorePromptManager` + `build_system_prompt()` 重构为一个统一的 `PromptManager` 类，实现参数驱动的提示词组件拼接。

**背景**：原架构中提示词拼接逻辑硬编码在 `build_system_prompt()` 函数中，组件顺序和包含条件无法灵活配置。重构后通过组件注册表和 `build(include, exclude, ...)` API 实现动态拼接。

**目标**：
1. 建立组件注册表，支持核心硬编码 + 扩展可配
2. 实现参数驱动的 `build()` 拼接 API
3. 保持单例全局访问模式
4. 兼容旧接口，平滑迁移

---

## 完成情况

### 核心功能

| 功能 | 状态 | 说明 |
|------|------|------|
| PromptComponent 组件定义 | ✅ 完整 | dataclass 封装 name/priority/required/load_fn |
| PromptManager 核心类 | ✅ 完整 | 组件注册表 + 参数驱动拼接 |
| build() API | ✅ 完整 | include/exclude 参数过滤，priority 排序 |
| 单例模式 | ✅ 完整 | `get_prompt_manager()` 全局访问 |
| 双轨加载逻辑 | ✅ 完整 | workspace 优先，回退 static |
| 缓存失效机制 | ✅ 完整 | `invalidate_cache(name)` |
| 兼容函数 | ✅ 完整 | `build_system_prompt()` / `build_simple_system_prompt()` |
| 测试覆盖 | ✅ 完整 | 28 测试全部通过 |

### build() API 效果

```python
# 全量拼接（默认行为，与现有逻辑一致）
pm = get_prompt_manager()
prompt = pm.build(generation=1, total_generations=1, core_context="...")

# 只拼接核心部分（用于测试/快速启动）
prompt = pm.build(include=["SOUL", "AGENTS"])

# 排除记忆部分（用于不需要上下文的场景）
prompt = pm.build(exclude=["MEMORY", "CODEBASE_MAP"])

# 特定场景
prompt = pm.build(
    include=["SOUL", "TASK_CHECKLIST", "DYNAMIC", "AGENTS"],
    exclude=["MEMORY"],
    generation=2,
    total_generations=5,
)
```

### 组件注册表

| name | priority | required | 说明 |
|------|----------|----------|------|
| SOUL | 10 | True | SOUL.md，双轨加载 |
| TASK_CHECKLIST | 20 | False | 任务清单 |
| CODEBASE_MAP | 30 | False | 代码库认知地图 |
| DYNAMIC | 40 | False | DYNAMIC.md |
| IDENTITY | 50 | False | IDENTITY.md |
| AGENTS | 60 | True | AGENTS.md，双轨加载 |
| USER | 70 | False | USER.md |
| MEMORY | 80 | False | 记忆上下文 |
| TOOLS_INDEX | 90 | False | 工具手册索引 |
| ENV_INFO | 100 | False | 环境信息 |

---

## 代码变更

### 新增文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `core/capabilities/prompt_manager.py` | ~370 | PromptManager 核心类 |
| `tests/test_prompt_manager.py` | ~260 | 28 个测试用例 |

### 修改文件

| 文件 | 变更 | 说明 |
|------|------|------|
| `core/capabilities/__init__.py` | +2 行 | 导出 PromptComponent / PromptManager / get_prompt_manager |
| `agent.py` | -5 行 | `_build_system_prompt()` 改用 `get_prompt_manager().build()` |
| `core/capabilities/prompt_builder.py` | 重写 | 改为兼容层，重新导出新模块 |
| `core/core_prompt/__init__.py` | 重写 | 改为兼容层，别名 CorePromptManager = PromptManager |
| `core/backup/agent_core_backup.py` | -1 行 | 导入路径更新 |

---

## 测试结果

### test_prompt_manager.py

```
============================= test session starts =============================
28 passed in 0.16s
```

| 测试类 | 测试数 | 状态 |
|--------|--------|------|
| TestPromptComponent | 3 | ✅ 全部通过 |
| TestPromptManager | 8 | ✅ 全部通过 |
| TestBuildAPI | 6 | ✅ 全部通过 |
| TestCompatibilityFunctions | 3 | ✅ 全部通过 |
| TestCache | 3 | ✅ 全部通过 |
| TestLoadFunctions | 5 | ✅ 全部通过 |
| TestComponentPriority | 2 | ✅ 全部通过 |

---

## 技术细节

### 设计决策

1. **Plugin Registry 模式**：每个组件封装为 `PromptComponent`，包含加载函数和元数据，支持动态注册/注销
2. **参数驱动拼接**：`include` 和 `exclude` 规则清晰，`required=True` 组件无法被 exclude 移除
3. **优先级排序**：组件按 `priority` 升序拼接，确保 SOUL (10) 始终在 AGENTS (60) 之前
4. **平滑迁移**：旧接口 `build_system_prompt()` 通过 `prompt_manager.py` 的兼容函数重新导出

### 迁移策略

- `prompt_builder.py` → 兼容层（导入新模块并重新导出）
- `core/core_prompt/__init__.py` → 兼容层（`CorePromptManager` 作为 `PromptManager` 别名）
- `agent.py` → 使用新 API `get_prompt_manager().build()`

---

## 遇到问题

无。

---

## 后续计划

1. 将 `prompt_builder.py` 兼容层在未来版本中标记为废弃（添加 DeprecationWarning）
2. 将 `core/core_prompt/__init__.py` 兼容层在未来版本中删除
3. 考虑将组件配置外部化（YAML），支持运行时热更新
