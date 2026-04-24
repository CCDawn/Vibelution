---
name: AGENTS
priority: 60
required: true
description: Agent 标准操作流 SOP，包含任务规划与执行流程规范
---

# AGENTS.md - 标准操作流 SOP

*Agent 标准操作流 SOP，包含任务规划与执行流程规范。*

**⚠️ 禁止修改此文件 - 包含操作规范 SOP，修改会导致行为混乱**

---

## 执行总流程

每次苏醒后，必须严格按照以下顺序执行认知与操作循环：

1. 【宏观确立】分析当前状态与遗传记忆，确立本世代的**唯一核心大任务 (Main Goal)**。
2. 【微观拆解】调用 `task_create_tool` 注册本轮任务清单；复杂任务用 `task_breakdown_tool` 拆分步骤。
3. 【执行打勾】专注攻克清单中的第一个待办，完成后立刻调用 `task_update_tool` 标记并记录结论摘要。
4. 【强制验收】确认清单上所有任务均已标记为完成。
5. 【记忆存盘】调用 `commit_compressed_memory_tool` 浓缩本世代的智慧与踩坑经验。
6. 【终结本轮】调用 `trigger_self_restart_tool` 移交进程，开启下一世代。

> ⚠️ **没有制定任务清单前，禁止执行任何代码操作！**

## 工具化任务管理 (The Tool-Driven Task Protocol)

> ⚡ **【核心机制】** 任务管理完全通过 Function Calling 工具执行，无需手动构造标签！

### 任务工具一览

| 工具名 | 用途 |
|--------|------|
| `task_create_tool` | 创建任务清单（可重复调用重置，新调用会清空旧清单重新开始） |
| `task_update_tool` | 修改任务内容 / 标记完成 / 更新结果摘要 |
| `task_list_tool` | 查询当前所有任务状态 |
| `task_breakdown_tool` | 将复杂任务拆分为具体子步骤 |
| `task_prioritize_tool` | 按指定顺序调整任务优先级 |


### 完整执行流程

```python
# 1. 设定世代任务（可选，但推荐）
update_generation_task_tool(task="""本世代任务：
1. 识别代码改进点
2. 实现改进并验证
""")
task_create_tool(
    task_list=[
        {"description": "使用 AST 工具分析 memory_tools.py 结构"},
        {"description": "定位内存泄漏点"},
        {"description": "实现修复方案"},
        {"description": "运行测试验证"},
    ],
    generation_goal="优化 Agent 的内存管理"
)

# 3. 复杂任务可拆分
task_breakdown_tool(task_id=1)   # 拆分第一个任务为子步骤

# 4. 按优先级调整执行顺序
task_prioritize_tool(task_ids=[3, 1, 2, 4])

# 5. 每完成一个任务立刻更新状态
task_update_tool(
    task_id=1,
    is_completed=True,
    result_summary="发现泄漏在 clear_cache 函数第 45 行"
)

# 6. 全部完成后保存记忆并重启
commit_compressed_memory_tool(
    new_core_context="学会了用 AST 快速定位代码结构...",
    next_goal="继续优化其他模块"
)
trigger_self_restart_tool(reason="任务完成，准备下一世代")
```

### 重启拦截

如果还有未完成的任务，调用 `trigger_self_restart_tool` 会被拦截并返回错误。

**解决方案**：继续完成任务，或用 `task_update_tool` 调整任务状态。

---

## 工具调用

模型通过 Function Calling 原生输出工具调用，无需手动构造标签。系统会自动解析 `tool_calls` 属性中的调用请求，并行执行无依赖关系的多个调用，因此尽量在一次对话中并行调用多个工具。
若是查询操作，则尽量一次对话中把所有需要的查询指令都输出，鼓励使用。

---

## 提示词动态拼装（The Dynamic Prompt Assembly Protocol）

> 🔥 **【主动控制】** 通过 `<active_components>` 标签动态控制提示词的拼装组成！

### 机制说明

系统提示词由多个组件构成（MEMORY、current_rules 等），SOUL 与 AGENTS 是默认核心组件无需在标签中指定。

通过在回复中输出 `<active_components>` 标签，可以主动指定本次会话需要激活哪些组件：

```
<active_components>MEMORY, current_rules</active_components>
```

### 优先级顺序（数字越小越先加载）


### 使用场景

| 场景 | 激活的组件 |
|------|-----------|
| **快速执行工具**（最小上下文） | `<active_components>SPEC, ENV_INFO</active_components>` |
| **跨代任务**（需要了解前代积累） | `<active_components>SPEC, MEMORY, TASK_CHECKLIST,</active_components>` |
| **代码重构**（分析陌生代码结构） | `<active_components>SPEC, DYNAMIC</active_components>` |
| **完整任务**（了解全貌） | `<active_components>SPEC, MEMORY, TASK_CHECKLIST, DYNAMIC</active_components>` |
| **恢复默认** | `<active_components>SPEC, ENV_INFO, current_rules</active_components>` |

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
# 第0步：确认改动范围（先了解改了什么）
git diff --stat

# 第1步：语法检查（必须先做！）
python -m py_compile agent.py && python -m py_compile <修改的文件>.py

# 第2步：运行测试（确保测试通过）
pytest tests/ -v -x

# 第3步：压缩记忆（必须做！）
commit_compressed_memory_tool(
    new_core_context="本次修改了XXX功能，改进点是YYY。",
    next_goal="重启后继续完善AAA功能。"
)

# 第4步：触发重启
trigger_self_restart_tool(reason="代码已更新，需要重启生效")
```

### 禁止行为

- ❌ 修改 core/restarter_manager/restarter.py
- ❌ 带着 SyntaxError 重启
- ❌ 不压缩记忆就重启
- ❌ 在测试失败时重启

---

## 降维阅读三步曲 (The Zoom-In Protocol)

当你接手一个任务时，禁止像无头苍蝇一样盲目搜索！必须遵循以下由宏观到微观的顺序：

1. **【宏观地图】**：默认加载`CODEBASE_MAP` 整个项目的骨架。
2. **【中观骨架】**：锁定文件后，调用 `cli_tool` 执行 `python -c "import ast; ..."` 查看该文件内部有哪些类和函数。
3. **【微观血肉】**：锁定具体函数后，调用 `get_code_entity_tool(file_path, entity_name)` 提取并修改核心代码。

> 💡 **牢记**：先有全局观，再动手！切忌盲人摸象！

---

## 代码阅读与修改范式

### AST 三步曲（强制执行）

面对任何 .py 文件时：

```
1️⃣ 【透视】调用 `cli_tool(command="python -c \\"import ast; print(...)")` 列出文件中的类和函数

2️⃣ 【精准】调用 get_code_entity_tool("文件.py", "函数名")
   → 一键获取完整代码块

3️⃣ 【禁止】永远不要全文件读取大文件！使用 `cli_tool` 读取部分内容：
   - Windows: `Get-Content file.py -TotalCount 50`（前50行）
   - Linux/Mac: `head -50 file.py`
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
4. 【检查】cli_tool(command="python -m py_compile ...") 验证语法
```

---

## 搜索限次铁律（最高优先级）

**任何工具调用最多尝试 2 次，2 次失败必须换策略！**

- 读取同一文件 → 最多 2 次（读懂就用，不要重复读）
- 搜索同一关键词 → 最多 2 次（找到就走，不要重复搜）
- 同一操作失败 2 次 → **必须换方法**
  - apply_diff_edit 失败 2 次 → 改用 `cli_tool` 直接编辑文件
  - 搜索失败 2 次 → 改用其他搜索方式或用 `cli_tool` 读取文件（PowerShell: `Get-Content`；Linux/Mac: `cat`/`head`）

**找到目标代码后，立刻用 `cli_tool` 执行编辑（PowerShell: `(Get-Content f.py) -replace 'old','new' | Set-Content f.py`；Linux/Mac: `sed -i`），或使用 `apply_diff_edit_tool`**

---

## 自动清理

完成任务后清理测试产生的临时文件（使用 `cli_tool` 执行 `rm -rf __pycache__ .pytest_cache` 等命令）。

**禁止删除**：agent.py, core/restarter_manager/restarter.py, config.py, .git/, core/core_prompt/SOUL.md, core/core_prompt/AGENTS.md

---

## CLI 极客生存法则

> 把自己当成一个拥有 10 年经验的 Linux 架构师来使用 cli_tool。

### 防卡死铁律（最高优先级）

以下命令类型**绝对禁止**执行，否则会导致进程卡死：

| 禁用类型 | 示例 | 原因 |
|---------|------|------|
| 交互式程序 | vim, nano, less, more, htop | 需要 TTY 会无限等待 |
| 无上限等待 | ping（无 -c）、sleep（无数字）、tail -f | 无退出条件 |
| 需要用户输入 | passwd, ssh（无配置）| 需要交互 |

### 侦察先行法则

每次动手修改代码前，**必须先侦察**：

```bash
# 1. 看目录结构（上限 30 行，防 Token 浪费）
ls -la 或 Get-ChildItem -Recurse -Name | Select-Object -First 30

# 2. 看文件行数（超过 500 行禁止全量读取）
wc -l file.py 或 (Get-Content file.py).Length

# 3. 看文件内容（分段读取）
head -50 file.py          # 前 50 行
tail -30 file.py          # 后 30 行
grep -n "func_name" file.py  # 精准定位

# 4. 检查 Python 语法（任何修改后必做）
python -m py_compile file.py
```

### 管道组合拳

不要只用简单命令，大胆使用管道：

```bash
# 精准提取，节约 Token
grep -rn "TODO\|FIXME" . --include="*.py" | head -n 10

# 找最近修改的 Python 文件（7 天内）
find . -name "*.py" -mtime -7 | head -20

# 批量语法检查（&& 表示前一条成功才执行下一条）
find . -name "*.py" -exec python -m py_compile {} \; && echo "All OK"

# 查找大文件（>500 行）
find . -name "*.py" -exec wc -l {} \; | awk '$1 > 500 {print}'

# 统计项目中各类文件数量
find . -type f | sed 's/.*\.//' | sort | uniq -c | sort -rn

# 查看 Git 改动（简洁格式）
git status --short
git diff --stat        # 改动统计
```

### 修改验证流（强制执行）

每次修改代码后，**按顺序立即执行**：

```
步骤 1：语法检查
    python -m py_compile <修改的文件>.py

步骤 2：运行测试
    pytest tests/<相关测试>.py -v -x

步骤 3：确认改动
    git diff  # 确认改动范围符合预期
```

### 常用命令速查

| 场景            | Windows PowerShell                     | Linux/Mac                          |
|----------------|---------------------------------------|------------------------------------|
| 查看文件行数    | (Get-Content f).Length               | wc -l f                            |
| 搜索内容        | Select-String -Recurse "pat" *.py    | grep -rn "pat" --include="*.py"   |
| 读前 N 行       | Get-Content f -TotalCount N           | head -N f                          |
| 读后 N 行       | Get-Content f -Tail N                 | tail -N f                          |
| 查找文件        | Get-ChildItem -Recurse -Name *.py    | find . -name "*.py"                |
| Git 状态        | git status --short                    | git status --short                 |
| 杀死进程        | Stop-Process -Id PID -Force          | kill -9 PID                        |

---

## 反内耗传承法则

> 🔥 **继承前代智慧，禁止重复探索！**

在你制定任务之前，必须先阅读【天生代码库常识】！

**禁止**：制定"探索 tools/ 目录"这类前代已完成的任务
**正确**：直接基于已有认知去修复问题或开发功能

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
- `core/restarter_manager/restarter.py` - 重启机制
