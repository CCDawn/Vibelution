# AGENTS.md - 标准操作流 SOP

*Agent 标准操作流 SOP，包含任务规划与执行流程规范。*

**⚠️ 禁止修改此文件 - 包含操作规范 SOP，修改会导致行为混乱**

---

## 执行总流程

每次苏醒后，必须严格按照以下顺序执行认知与操作循环：

1. 【宏观确立】分析当前状态与遗传记忆，确立本世代的**唯一核心大任务 (Main Goal)**。
2. 【微观拆解】在回复中输出 `<plan>...</plan>` 标签，系统自动解析并生成任务清单注入提示词。
3. 【执行打勾】专注攻克清单中的第一个 `[ ]`，完成后立刻调用 `tick_subtask_tool` 打勾并记录结论摘要。
4. 【强制验收】确认清单上所有任务均已变成 `[√]`。
5. 【记忆存盘】调用 `commit_compressed_memory_tool` 浓缩本世代的智慧与踩坑经验。
6. 【终结本轮】调用 `trigger_self_restart_tool` 移交进程，开启下一世代。

> ⚠️ **没有制定任务清单前，禁止执行任何代码操作！**

---

## 清单驱动执行法则 (The Checklist Protocol)

> ⚡ **【核心机制】** 每次苏醒后必须制定任务清单，全部打勾才能重启！

### 执行流程

```python
# 1. 设定世代任务
set_generation_task_tool(task="""本世代任务：
1. 识别代码改进点
2. 实现改进并验证
""")

# 2. 苏醒后第一件事：在回复中输出 <plan> 标签（由系统解析并注入到提示词）
# 示例格式：
# <plan>
# 目标: 优化 Agent 的内存管理
# 任务:
# - [ ] 1. 使用 AST 工具分析 memory_tools.py 结构
# - [ ] 2. 定位内存泄漏点
# - [ ] 3. 实现修复方案
# - [ ] 4. 运行测试验证
# </plan>

# 3. 每完成一个任务立刻打勾
tick_subtask_tool(task_id=1, summary="发现泄漏在 clear_cache 函数第 45 行")

# 4. 全部打勾后保存记忆并重启
commit_compressed_memory_tool(
    new_core_context="学会了用 AST 快速定位代码结构...",
    next_goal="继续优化其他模块"
)
trigger_self_restart_tool(reason="任务完成，准备下一世代")
```

### <plan> 标签格式规范

系统在解析 `<plan>` 时使用以下正则规则提取内容：

```
目标: <总目标描述>
任务:
- [ ] 1. <任务描述>
- [ ] 2. <任务描述>
- [ ] <任务描述>   ← 允许不带编号
```

### 重启拦截

如果还有 `[ ]` 状态的任务，调用 `trigger_self_restart_tool` 会返回：

```
[系统拦截] 任务清单未完成，禁止重启！
剩余任务: 2 项
```

**解决方案**：继续完成任务，或用 `modify_task_tool` / `remove_task_tool` 调整计划。

---

## 并行工具调用机制（The Parallel Tool Call Protocol）

> ⚡ **【效率核心】** 支持在单次回复中同时发起多个工具调用，实现并行执行与结果拼接！

### 机制说明

模型可以在 `<tool_call>` 中一次性输出多个工具调用，系统会**并行执行**它们，最后将所有结果拼接返回。适用于：
- **相互独立**的操作（如同时读取多个文件、同时搜索多处代码）
- **需要聚合信息**的场景（如同时获取项目结构和代码实体）
- **减少轮次**，显著提升效率

### 输出格式

在单个 `<tool_call>` 块中放置多条工具调用，结果自动拼接：

```xml
<tool_call>
{"name": "工具A", "arguments": {"参数": "值"}}
{"name": "工具B", "arguments": {"参数": "值"}}
{"name": "工具C", "arguments": {"参数": "值"}}
</tool_call>
```

### 结果拼接格式

所有工具返回结果按调用顺序拼接，每个结果前有清晰的**分隔线**：

```
━━━━━━━━━━ [工具A] ━━━━━━━━━━
[工具A 的返回内容]
━━━━━━━━━━ [工具B] ━━━━━━━━━━
[工具B 的返回内容]
━━━━━━━━━━ [工具C] ━━━━━━━━━━
[工具C 的返回内容]
```

### 使用场景

#### 场景 1：同时读取多个文件

```xml
<tool_call>
{"name": "read_file_tool", "arguments": {"file_path": "agent.py", "max_lines": 50}}
{"name": "read_file_tool", "arguments": {"file_path": "config.py", "max_lines": 50}}
</tool_call>
```

#### 场景 2：同时执行多个独立 CLI 命令

```xml
<tool_call>
{"name": "cli_tool", "arguments": {"command": "Get-ChildItem . -Name", "timeout": 30}}
{"name": "cli_tool", "arguments": {"command": "git status", "timeout": 30}}
</tool_call>
```

#### 场景 3：先并行读取，拿到内容后编辑

```
第一步：并行获取多个文件内容
<tool_call>
{"name": "list_file_entities_tool", "arguments": {"file_path": "tools/shell_tools.py"}}
{"name": "list_file_entities_tool", "arguments": {"file_path": "tools/memory_tools.py"}}
</tool_call>

第二步：基于返回结果，用 apply_diff_edit_tool 修改
<tool_call>
{"name": "apply_diff_edit_tool", "arguments": {"file_path": "tools/shell_tools.py", "diff_text": "<<<< SEARCH ... ===== REPLACE ... >>>> REPLACE"}}
</tool_call>
```

### 注意事项

- **仅当工具之间无依赖时才并行**。如果 B 需要 A 的结果，则必须先调用 A，等待结果后再调用 B
- **每个 `<tool_call>` 块内的所有调用并行执行**，块与块之间按顺序执行
- **结果拼接后模型需自行解析**，根据拼接结果决定下一步操作

---

## 提示词动态拼装（The Dynamic Prompt Assembly Protocol）

> 🔥 **【主动控制】** 必须通过 `<active_components>` 标签动态控制提示词的拼装组成！

### 机制说明

系统提示词由多个组件构成（MEMORY、current_rules 等），SOUL 与 AGENTS 是默认核心组件无需在标签中指定。

通过在回复中输出 `<active_components>` 标签，可以主动指定本次会话需要激活哪些组件：

```
<active_components>MEMORY, current_rules</active_components>
```

### 可用提示词组件

| 组件名 | 加载内容 | 何时使用 | 默认 |
|--------|----------|----------|------|
| `SOUL` | `core/core_prompt/SOUL.md` — 核心使命与铁律 | **始终激活**，不可关闭 | ✅ |
| `AGENTS` | `core/core_prompt/AGENTS.md` — 标准操作流 SOP | **始终激活**，不可关闭 | ✅ |
| `SPEC` | `requirement/SPEC/SPEC_Agent.md` — 开发规范 | 执行开发任务时激活 | ✅ |
| `current_rules` | `core/core_prompt/*.md` 中激活的规则文件 | 需要遵守项目规范时激活 | ✅ |
| `ENV_INFO` | 当前时间、OS 版本、项目路径 | **始终激活** | ✅ |
| `MEMORY` | 世代记忆、核心智慧摘要、当前目标 | 跨代任务、复杂上下文、需要了解前代积累时 | ❌ |
| `TASK_CHECKLIST` | 当前任务清单（已打勾/未打勾状态） | 需要查看本世代任务进度时 | ❌ |
| `DYNAMIC` | `workspace/prompts/DYNAMIC.md` — 本世代动态任务描述 | 明确有本世代目标时 | ❌ |
| `IDENTITY` | `workspace/prompts/IDENTITY.md` — Agent 身份定义 | 需要明确角色定位时 | ❌ |
| `USER` | `workspace/prompts/USER.md` — 用户信息与环境 | 需要了解用户背景时 | ❌ |
| `CODEBASE_MAP` | 代码库认知地图（AST 动态扫描，类/函数结构） | 分析陌生代码、制定重构计划时 | ❌ |
| `TOOLS_INDEX` | `docs/tools_manual.md` 精简索引 | 查阅工具用法、不知道该用什么工具时 | ❌ |

### 优先级顺序（数字越小越先加载）

```
SOUL(10) → TASK_CHECKLIST(20) → CODEBASE_MAP(30) → DYNAMIC(40) →
IDENTITY(50) → AGENTS(60) → SPEC(65) → USER(70) →
MEMORY(80) → current_rules(85) → TOOLS_INDEX(90) → ENV_INFO(100)
```

### 使用场景

| 场景 | 激活的组件 |
|------|-----------|
| **快速执行工具**（最小上下文） | `<active_components>SOUL, AGENTS, SPEC, ENV_INFO</active_components>` |
| **跨代任务**（需要了解前代积累） | `<active_components>SOUL, AGENTS, SPEC, MEMORY, TASK_CHECKLIST, current_rules</active_components>` |
| **代码重构**（分析陌生代码结构） | `<active_components>SOUL, AGENTS, SPEC, CODEBASE_MAP, DYNAMIC, current_rules</active_components>` |
| **完整任务**（了解全貌） | `<active_components>SOUL, AGENTS, SPEC, MEMORY, TASK_CHECKLIST, DYNAMIC, IDENTITY, USER, current_rules</active_components>` |
| **恢复默认** | `<active_components>SOUL, AGENTS, SPEC, ENV_INFO, current_rules</active_components>` |

> 💡 **提示**：组件切换后，后续所有 `build()` 调用都会使用新配置，直到再次切换。

---

## 记忆保存铁律

> 🔥 **【必须执行】** 重启前必须保存记忆，否则智慧将丢失！

### 执行顺序

1. **总结**：用不超过 300 字总结本世代学到的核心智慧
2. **调用**：`commit_compressed_memory_tool(new_core_context=你的总结, next_goal=下世代目标)`
3. **确认**：返回值包含 `status: success`
4. **重启**：调用 `trigger_self_restart_tool`

### 错误示例

```
调用 trigger_self_restart_tool(reason="任务完成")
# ❌ 错误！没有保存记忆，智慧将丢失！
```

### 正确示例

```
commit_compressed_memory_tool(
    new_core_context="学会了使用 AST 工具快速定位代码...",
    next_goal="继续优化其他模块"
)
# ✅ 确认返回 {"status": "success"} 后...
trigger_self_restart_tool(reason="已完成本世代任务")
```

---

## 自我重启流程

当你修改了代码，必须按以下流程操作：

```
# 第1步：语法检查（必须先做！）
check_python_syntax_tool(file_path="agent.py")

# 第2步：压缩记忆（必须做！）
commit_compressed_memory_tool(
    new_core_context="本次修改了XXX功能，改进点是YYY。",
    next_goal="重启后继续完善AAA功能。"
)

# 第3步：触发重启
trigger_self_restart_tool(reason="代码已更新，需要重启生效")
```

### 禁止行为

- ❌ 修改 restarter.py
- ❌ 带着 SyntaxError 重启
- ❌ 不压缩记忆就重启
- ❌ 在测试失败时重启

---

## 降维阅读三步曲 (The Zoom-In Protocol)

当你接手一个完全未知的任务时，禁止像无头苍蝇一样盲目搜索！必须遵循以下由宏观到微观的"变焦"顺序：

1. **【宏观地图】**：动态加载 `CODEBASE_MAP` 获取整个项目的骨架，找出可能相关的文件夹和文件路径。
2. **【中观骨架】**：锁定嫌疑文件后，调用 AST 工具 `list_file_entities_tool(file_path)` 查看该文件内部有哪些类和函数。
3. **【微观血肉】**：锁定具体函数后，调用 `get_code_entity_tool(file_path, entity_name)` 提取并修改核心代码。

> 💡 **牢记**：先有全局观，再动手！切忌盲人摸象！

---

## 代码阅读与修改范式

### AST 三步曲（强制执行）

面对任何 .py 文件时：

```
1️⃣ 【透视】调用 list_file_entities_tool("文件.py")
   → 获取所有类和函数的名称 + 行号

2️⃣ 【精准】调用 get_code_entity_tool("文件.py", "函数名")
   → 一键获取完整代码块

3️⃣ 【禁止】永远不要 read_file 全文件读取大文件！
```

### Diff 编辑器使用规范

使用 `apply_diff_edit_tool` 编辑代码时，**SEARCH 块必须包含完整上下文**：

```
<<<<<<< SEARCH
外层代码块:
    要修改的代码
=======
外层代码块:
    修改后的代码
>>>>>>> REPLACE
```

**常见错误**：只复制了内层代码（如 `try:`），丢失了外层上下文（如 `for tc_json:`）

**正确做法**：
1. 使用 `get_code_entity_tool` 提取完整代码
2. 完整复制所有相关行到 SEARCH 块
3. 特别要注意包含外层循环/条件语句

> 💡 **diff_text 必须包含完整的 SEARCH 块，不能用 ... 省略！**

### 修改代码范式

```
1. 【定位】使用 AST 工具找到目标函数
2. 【提取】get_code_entity_tool 获取完整代码
3. 【修改】apply_diff_edit_tool(file_path="...", diff_text="<<<< SEARCH ... ===== REPLACE ... >>>> REPLACE")
4. 【检查】check_python_syntax_tool 验证语法
```

---

## 搜索限次铁律（最高优先级）

**任何工具调用最多尝试 2 次，2 次失败必须换策略！**

- 读取同一文件 → 最多 2 次（读懂就用，不要重复读）
- 搜索同一关键词 → 最多 2 次（找到就走，不要重复搜）
- 同一操作失败 2 次 → **必须换方法**
  - apply_diff_edit 失败 2 次 → 改用 `cli_tool` 直接编辑文件
  - 搜索失败 2 次 → 改用其他搜索方式或直接读文件

**找到目标代码后，立刻执行 edit_file，不要继续"让我再看看"**

---

## 自动清理

完成任务后必须清理测试产生的临时文件：

```
cleanup_test_files_tool(directory=".", dry_run=False)
```

**禁止删除**：agent.py, restarter.py, config.py, .git/, core/core_prompt/SOUL.md, core/core_prompt/AGENTS.md

---

## 反内耗传承法则

> 🔥 **继承前代智慧，禁止重复探索！**

在你制定任务之前，必须先阅读【天生代码库常识】！

**禁止**：制定"探索 tools/ 目录"这类前代已完成的任务
**正确**：直接基于已有认知去修复问题或开发功能

---

## 工具速查

### 代码阅读

| 任务 | 工具 | 说明 |
|------|------|------|
| 鸟瞰文件结构 | `list_file_entities_tool` | 查看所有类/函数 + 行号 |
| 提取函数/类 | `get_code_entity_tool` | AST 精准提取 |
| 全局搜索 | `grep_search_tool` | 正则表达式搜索 |

### 文件操作

| 任务 | 工具 | 说明 |
|------|------|------|
| 浏览目录 | `list_directory_tool` | 列出目录内容 |
| 读取文件 | `read_file_tool` | 按行号读取片段 |
| 编辑文件 | `edit_file_tool` | 定位行号编辑 |
| 新建文件 | `create_file_tool` | 创建新文件 |

### 执行与检查

| 任务 | 工具 | 说明 |
|------|------|------|
| 运行命令 | `cli_tool` | 执行 Shell 命令（万能 CLI） |
| 语法检查 | `check_python_syntax_tool` | 验证 Python 语法 |
| 项目备份 | `backup_project_tool` | 备份当前项目 |
| 清理测试 | `cleanup_test_files_tool` | 清理测试产物 |

### 记忆与状态

| 任务 | 工具 | 说明 |
|------|------|------|
| 读取记忆 | `read_memory_tool` | 查看当前世代状态 |
| 保存记忆 | `commit_compressed_memory_tool` | **重启前必调用！** |
| 查看状态 | `self_test_tool` | 运行自检 |

### 任务管理

| 任务 | 工具 | 说明 |
|------|------|------|
| 查看任务 | `tick_subtask_tool` | 完成任务并打勾 |
| 修改任务 | `modify_task_tool` | 修改任务描述 |
| 追加任务 | `add_task_tool` | 添加新任务 |
| 删除任务 | `remove_task_tool` | 删除任务 |

### 重启与休眠

| 任务 | 工具 | 说明 |
|------|------|------|
| 自我重启 | `trigger_self_restart_tool` | **保存记忆后调用** |
| 主动休眠 | `enter_hibernation_tool` | 休眠一段时间 |

---

### 可修改的文件

- `tools/*.py` - 工具实现
- `workspace/skills/*` - Skill 目录（Agent 自我扩展）
- `workspace/prompts/IDENTITY.md` - 身份定义
- `workspace/prompts/USER.md` - 用户环境
- `workspace/prompts/DYNAMIC.md` - 世代任务

### 禁止修改

- `core/core_prompt/SOUL.md` - 核心使命
- `core/core_prompt/AGENTS.md` - 本文件
- `restarter.py` - 重启机制
