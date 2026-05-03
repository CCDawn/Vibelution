# SPEC 开发流程规范

**版本：** v5.0
**日期：** 2026-05-03
**读者：** AI Agent（本文档的执行者均为 Agent，每条规则必须可被工具验证）

---
## 1. 每次修改必做

```
[感知]  git diff --stat && git log -1 --stat
        → 了解变更范围、上次产出、本次目标
[决策]  Core First 检查（见第2节）
[执行]  修改代码
[验证]  python -m py_compile <修改文件>.py
        run_test_for_tool(<修改文件路径>)      # 映射到对应测试文件并运行
        python tests/prompt_debugger.py --suite # 仅当涉及 SOUL/SPEC/workspace/prompts 或工具变更时
[交付]  git commit
```

**编译或测试失败 → 禁止继续，禁止提交。**
修改涉及核心循环（agent.py / restarter / prompt_manager）时，提交前必须通过完整测试套件或 `test_gate.check_evolution_ready()`。

---

## 2. Core First

Agent 在实现任何功能前，执行以下决策（不允许跳过）：

```
1. ls core/                          → 了解目录结构
2. grep_search_tool("关键词", "core/") → 搜索相似功能
3.
   ├─ 已有相似功能 → import 复用，agent.py 仅写调用代码
   └─ 无相似功能 → 在 core/ 对应子目录创建
        ├─ 创建 core/{category}/xxx.py（含 docstring）
        ├─ 在 core/{category}/__init__.py 导出
        └─ agent.py 导入使用
```

**agent.py 约束**：只放 `think_and_act()` 核心循环、`run_loop()` 入口、`_invoke_llm()` 调用、初始化与状态管理。业务逻辑一律放 `core/`。

---

## 3. 质量门控

编译通过后逐条检查：

| # | 检查项 | 验证方式 |
|---|--------|---------|
| 1 | 新文件 snake_case，新类 PascalCase | 目视 |
| 2 | 公开函数有类型注解 | 目视 |
| 3 | 新模块有 docstring（功能+参数+返回值） | 目视 |
| 4 | 无空壳模块（pass/...） | grep "pass" / "\.\.\." |
| 5 | 配置值来自 config.toml | 目视（无硬编码路径/密钥） |
| 6 | 若添加/修改工具：通过 prompt_debugger 打靶 | `python tests/prompt_debugger.py --tool <工具名>` |

---

## 4. 提示词系统架构

### 已注册章节（按拼接顺序）

```
SOUL(10) → TASK_CHECKLIST(20) → CODEBASE_MAP(30) → DYNAMIC(40) →
IDENTITY(50) → SPEC(65) → USER(70) → MEMORY(80) → TOOLS_INDEX(90) → ENV_INFO(100)
```

| 章节 | 来源 | 刷新 |
|------|------|------|
| SOUL | `core/core_prompt/SOUL.md` | 静态 |
| SPEC | `core/core_prompt/SPEC.md`（本文件） | 静态 |
| CODEBASE_MAP | `workspace/prompts/CODEBASE_MAP.md` | 文件变更时自动刷新 |
| TASK_CHECKLIST | TaskPlanner 动态生成 | 每轮 |
| MEMORY | 压缩记忆 + state_memory | 每轮 |
| TOOLS_INDEX | Key_Tools 动态提取 | 静态 |
| ENV_INFO | 时间/OS/路径 | 5分钟粒度 |
| DYNAMIC/IDENTITY/USER | `workspace/prompts/` | 按需（workspace 启用且文件存在时加载） |

### LLM 响应标签

| 标签 | 提取到 |
|------|--------|
| `<think>` | UI、日志 |
| `<plan>` | `core/orchestration/task_planner.py` |
| `<active_components>` | `core/prompt_manager/prompt_manager.py` |
| `<tool_call>` | 工具执行层 |

---

## 5. Git 提交规范

```
<type>: <简短描述>
```

type: `feat` / `fix` / `refactor` / `docs` / `test`

提交信息写"做了什么"，不写"怎么做"。

---

## 6. 目录结构

以 `ls core/` 或 CODEBASE_MAP 为准（CODEBASE_MAP 自动扫描生成，文件变更时自动刷新），不依赖本文档中的手动描述。

---

## 7. 工具与测试

### 工具变更

添加/修改工具（`tools/`、`core/` 下所有注册到 Key_Tools 的模块）后，必须验证模型能正确调用：

```bash
python tests/prompt_debugger.py --tool <工具名>   # 单工具打靶
python tests/prompt_debugger.py --suite           # 全量打靶
```

### 测试框架

| 组件 | 用途 | 触发时机 |
|------|------|---------|
| `conftest.py` | 单例重置、隔离 workspace、共享 fixtures | 每次 pytest 自动加载 |
| `run_test_for_tool` | 按源文件映射测试文件并运行 | 修改代码后立即调用 |
| `test_runner.py` | 全量测试运行器 | 手动 / 进化前 |
| `test_gate.py` | 进化门控（重启前强制通过） | `trigger_self_restart` 自动调用 |
| `prompt_debugger.py` | 提示词打靶（验证 LLM 对工具的理解） | 工具变更时 |
| `simulate_lifecycle.py` | 生命周期防断裂验证 | 手动 |

---

## 8. 本文件的维护

本文件描述的对象变化时，**同步更新**对应章节，提交前用 `git diff` 确认一致性：

| 变更类型 | 更新章节 |
|---------|---------|
| 添加/移除/重命名 `core/` 子目录 | 第 6 节 |
| 添加/移除/修改已注册工具 | 第 7 节 + 第 4 节 TOOLS_INDEX 行 |
| 新增/移除提示词章节 | 第 4 节 |
| 新增测试框架组件 | 第 7 节测试框架表 |
| 修改 Core First 规则 | 第 2 节 |
| 修改质量门控检查项 | 第 3 节 |

**不是让 SPEC 自我进化，而是让 Agent 在改代码的同时改文档——和写测试一样，是修改的一部分。**
