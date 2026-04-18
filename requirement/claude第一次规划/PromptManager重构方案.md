---
name: PromptManager 重构方案
overview: 将现有的 CorePromptManager + build_system_prompt 重构为一个统一的 PromptManager 类，核心组件硬编码顺序，扩展组件可配置，支持单例模式，参数驱动拼接 API。
todos:
  - id: create-prompt-manager
    content: 创建 core/capabilities/prompt_manager.py（PromptComponent + PromptManager 类）
    status: completed
  - id: update-capabilities-init
    content: 修改 core/capabilities/__init__.py 导出新类
    status: completed
  - id: update-agent
    content: 修改 agent.py 使用新的 get_prompt_manager().build()
    status: completed
  - id: clean-prompt-builder
    content: 清理 core/capabilities/prompt_builder.py（删除 build_system_prompt）
    status: completed
  - id: clean-core-prompt
    content: 清理 core/core_prompt/__init__.py（删除 CorePromptManager）
    status: completed
  - id: fix-all-imports
    content: 更新所有直接引用旧 API 的文件
    status: completed
  - id: verify-build
    content: 运行测试验证拼接结果正确性
    status: completed
  - id: write-tests
    content: 编写 tests/test_prompt_manager.py 测试用例
    status: completed
  - id: write-report
    content: 生成任务报告并归档到 report_history/
    status: completed
  - id: update-index
    content: 更新 INDEX.md 状态标注
    status: completed
  - id: archive-requirement
    content: 归档规划文档到 requirement/claude第一次规划/
    status: in_progress
isProject: false
---

## SPEC 执行流程

本任务严格遵循 INDEX.md 的开发流程准则：

```
✅ 步骤 1: 理解任务      - 确认 prompt_builder + CorePromptManager 重构为 PromptManager 类
✅ 步骤 2: 查找规划      - 本方案即规划文档
✅ 步骤 3: 检查现有代码  - 已完成（见上述文件探索）
✅ 步骤 4: 编写/修改代码 - 见下方迁移步骤
✅ 步骤 5: 编写测试      - 新增 tests/test_prompt_manager.py
✅ 步骤 6: 更新报告      - 生成任务报告，更新 INDEX.md，归档到 requirement/ + report_history/
```

## 完整迁移步骤

将 `CorePromptManager` + `build_system_prompt()` 重构为一个统一的 `PromptManager` 类，实现：
- **参数驱动拼接**：`manager.build(include=[...], exclude=[...])`
- **单例全局访问**：`get_prompt_manager()`
- **核心硬编码 + 扩展可配**：SOUL/AGENTS 等核心部分顺序固定，任务清单/认知地图等扩展部分可配置开关

---

## 文件结构

```
core/
  core_prompt/
    __init__.py           # 删除 CorePromptManager / get_prompt_manager
    SOUL.md               # 保留
    AGENTS.md             # 保留
  capabilities/
    prompt_builder.py      # 删除 build_system_prompt / build_simple_system_prompt
    prompt_manager.py      # 新增：PromptManager 类
```

---

## PromptManager 类设计

### 1. 组件定义（Plugin Registry 模式）

每个组件是一个可注册对象，包含：

```python
class PromptComponent:
    name: str           # 唯一标识，如 "SOUL", "AGENTS", "TASK_CHECKLIST"
    priority: int       # 优先级（数字越小越靠前）
    required: bool      # 是否必选（required=True 时 exclude 无法移除）
    load_fn: Callable[[], str]  # 加载函数，返回文本内容
```

### 2. 核心组件（硬编码顺序，必选）

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

### 3. build() API（参数驱动拼接）

```python
def build(
    self,
    include: Optional[List[str]] = None,  # 只包含这些组件
    exclude: Optional[List[str]] = None,  # 排除这些组件
    generation: Optional[int] = None,
    total_generations: Optional[int] = None,
    core_context: Optional[str] = None,
    current_goal: Optional[str] = None,
) -> str
```

逻辑：
- `include` 非空时，只拼装指定的组件（忽略未注册组件不报错）
- `exclude` 非空时，从结果中移除指定组件（required=True 的组件无法被 exclude）
- 组件按 `priority` 升序排列后拼接
- 分隔符固定为 `\n\n---\n\n`

### 4. 单例模式

```python
_prompt_manager: Optional[PromptManager] = None

def get_prompt_manager() -> PromptManager:
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager
```

### 5. 内部加载逻辑

保留现有双轨加载逻辑（workspace 优先，回退 static），作为组件的 `load_fn`。

### 6. 缓存失效

`invalidate_cache(name: Optional[str] = None)` 支持按组件名清除缓存。

---

## 迁移步骤

1. **创建** `core/capabilities/prompt_manager.py`
   - 实现 `PromptComponent` dataclass
   - 实现 `PromptManager` 类（含单例 `get_prompt_manager()`）
   - 实现 `build(include, exclude, ...)` 方法
   - 注册所有硬编码组件

2. **修改** `core/capabilities/__init__.py`
   - 导出 `PromptManager`, `get_prompt_manager`

3. **修改** `agent.py`
   - `from core.capabilities.prompt_manager import get_prompt_manager`
   - 将 `Agent._build_system_prompt()` 改为：
     ```python
     def _build_system_prompt(self) -> str:
         pm = get_prompt_manager()
         return pm.build(
             generation=get_generation_tool(),
             total_generations=_get_total_generations(),
             core_context=get_core_context(),
         )
     ```

4. **删除** `core/capabilities/prompt_builder.py` 中的 `build_system_prompt` / `build_simple_system_prompt`
   - 保留辅助函数（`_load_memory_context` 等），作为 PromptManager 的内部方法或独立函数

5. **删除** `core/core_prompt/__init__.py` 中的 `CorePromptManager` 和 `get_prompt_manager()`
   - 保留路径解析函数 `_get_static_root` 等，供 PromptManager 复用

6. **更新** 任何直接引用旧 API 的文件
   - 搜索 `from core.core_prompt import get_prompt_manager` 和 `from core.capabilities.prompt_builder import build_system_prompt`，替换为新 API

---

## 效果示意

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
    core_context="学会使用 AST 工具",
)
```
