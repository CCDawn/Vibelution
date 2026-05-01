# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Vibelution — 基于 LangChain ReAct 架构的自我进化 AI Agent 系统。Agent 能够通过网络搜索获取新知识、读取和修改自身源代码、并通过独立守护进程实现自我重启。

当前状态：Phase 5-7 代码已主动删除，项目正从 Phase 3（进化引擎）重新构建。当前仅保留 `core/infrastructure/`、`core/logging/`、`core/ui/`、`core/pet_system/`、`core/prompt_manager/`、`core/restarter_manager/` 和 `core/task_planner.py`。
## 常用命令

```bash
# 安装依赖（需先激活 venv）
pip install -r requirements.txt

# 修改文件后做语法检查
python -m py_compile <文件路径>.py

# 运行所有测试（遇错即停）
pytest tests/ -v -x

# 运行指定测试文件
pytest tests/test_tool_executor.py -v -x

# 按关键字筛选运行测试
pytest tests/test_code_analysis_tools.py -v -k "diff"

# 提示词打靶测试（修改 SOUL.md / AGENTS.md / SPEC_Agent.md / workspace/prompts/* 后必须执行）
python tests/prompt_debugger.py --suite

# 启动 Agent（自动模式）
python agent.py --auto

# 带指定任务启动
python agent.py --prompt "你的任务描述"

# 运行进化测试
python agent.py --test
```

## 架构

### 入口：`agent.py`（约 620 行）

`SelfEvolvingAgent` 类包含核心循环：

- `run_loop()` — 主循环，反复调用 `think_and_act()`
- `think_and_act()` — 通过 `PromptManager` 构建系统提示词，调用 LLM，执行工具调用
- `_invoke_llm()` — 调用 LLM，带错误分类和指数退避自动重试（最多连续 5 次失败）
- `_execute_tool()` — 路由工具调用；特殊工具（重启、休眠）在此内联处理；其余委托给 `tool_executor`
- `_execute_tools_parallel()` — 串行迭代工具调用（历史原因命名为 parallel，实际为串行）

### 配置系统（`config/`）

基于 Pydantic v2 + TOML 配置加载（`config.toml`）。优先级：kwargs > TOML > 环境变量 > 默认值。

```python
from config import Config, get_config
config = Config()                        # 从 config.toml 加载
config = Config(config_path="...")       # 指定配置文件路径
config = Config(llm_model_name="gpt-4")  # 通过 kwargs 覆盖
config = Config.from_dict({"llm.model_name": "gpt-4"})
```

主要配置节：`[llm]`、`[agent]`、`[context_compression]`、`[security]`、`[evolution]`、`[memory]`、`[tools]`。

### 工具系统（`tools/`）

所有 Agent 能力均为 LangChain `BaseTool` 实例。工具在 `tools/Key_Tools.py` 的 `create_key_tools()` 中注册，并在 `_init_llm()` 中绑定到 LLM。提示词文档中提及但未在 Key_Tools 注册的工具对 Agent 不可见。

### 提示词系统（`core/prompt_manager/`）

双轨架构：

- **静态轨**（`core/core_prompt/`）：`SOUL.md`（身份使命/铁律，<120 行，禁止写入 SOP）和 `AGENTS.md`（SOP 操作规范，<500 行，禁止写入身份信息）。只读，禁止修改。
- **动态轨**（`workspace/prompts/`）：`IDENTITY.md`、`USER.md`、`DYNAMIC.md` 等。Agent 运行时可编辑。

`PromptManager.build()` 按优先级组装完整系统提示词：SOUL(10) → TASK_CHECKLIST(20) → CODEBASE_MAP(30) → DYNAMIC(40) → IDENTITY(50) → AGENTS(60) → SPEC(65) → USER(70) → MEMORY(80) → TOOLS_INDEX(90) → ENV_INFO(100)。

LLM 响应中可解析的标签：

| 标签 | 提取内容 | 处理位置 |
|------|---------|---------|
| `<think>` | 思考过程 | UI、日志 |
| `<plan>` | 任务计划 | `core/orchestration/task_planner.py` |
| `<active_components>` | 组件切换 | `core/prompt_manager/prompt_manager.py` |
| `<tool_call>` | 工具调用 | 工具执行层 |

### 基础设施（`core/infrastructure/`）

- `state.py` — 线程安全单例状态机（AgentState: IDLE → AWAKENING → THINKING → ACTING → ...）
- `event_bus.py` — 发布/订阅事件系统，支持通配符匹配
- `security.py` — 文件操作白名单/黑名单安全校验
- `tool_executor.py` — 工具执行，带超时、重试和错误处理
- `tool_registry.py` — 动态工具注册与发现
- `model_discovery.py` — 发现可用模型及其 token 上限
- `workspace_manager.py` — 基于 SQLite 的工作区状态管理
- `agent_session.py` — 会话级状态追踪

### 自我重启（`core/restarter_manager/restarter.py`）

Agent 通过 `trigger_self_restart_tool` 触发自我重启。该工具将 `restarter.py` 作为子进程启动后退出自身。`restarter.py` 等待父进程终止，然后拉起新的 `agent.py` 进程，实现进程级自我进化。

```
Agent 进程                    Restarter 进程
  └── think_and_act()
      └── trigger_self_restart()
          └── spawn restarter.py
              └── sys.exit(0)
                                  └── wait_for_process_death(pid)
                                  └── spawn_new_process(agent.py)
```

---

## 开发流程（来自 SPEC_Agent.md v4.0）

本文件定位：Agent 每次苏醒后读取。定义每次开发的统一必做清单、对比上一次产出规则、流程自分析与优化机制。不分任务大小，步骤相同。

### 每次开发必做清单

以下步骤**每次均执行**，不可跳过。步骤 1 或步骤 2 失败 → 禁止继续，禁止提交。

```
[感知] git diff --stat 上次提交以来的变更
[感知] 读取 INDEX.md 上次修改日志
        → 是否有 [流程优化] 标记（如有，优先处理，见"流程自分析与优化"）
        → 上次完成了什么
        → 本次目标是什么
[对比] 对比本次目标与上次产出（见"对比上一次"）
[决策] Core First 检查（见"Core First 决策树"）
[执行] 修改代码
[验证] python -m py_compile <修改文件>.py
        pytest tests/<相关测试>.py -v -x
        python tests/prompt_debugger.py --suite（若涉及提示词）
[分析] 本次流程出现的问题（见"流程自分析与优化"）
[记录] INDEX.md 修改日志追加一条
[交付] git commit
```

### 对比上一次

每次苏醒后，执行以下对比（[感知] 步骤的一部分）：

```
1. git log -1 --stat
   → 上次修改了哪些文件、每个文件变更行数
   → agent.py 行数变化（当前 ~620，每次必须记录）

2. 读取 INDEX.md 上次修改日志
   → 上次是否完成（有无未解决问题）
   → 是否有 [流程优化] 标记待处理
   → 本次目标与上次的关联（延续 or 新任务）

3. 如果有压缩记忆
   → 读取上次上下文（已修改的文件、关键决策、阻塞点）
```

### 流程自分析与优化

每次验证完成后，必须执行以下分析。

#### 问题捕获

| 情况 | 记录内容 |
|------|---------|
| 验证失败 | 失败步骤 + 失败原因（语法错误行号 / 测试失败用例名 / Core First 违规文件） |
| 执行受阻 | 阻塞点（依赖缺失 / 磁盘状态与 INDEX.md 不符 / 工具命令不可用） |
| 范围误判 | 实际修改文件数与预期偏差 > 3 个文件 |

#### 问题分类

| 类别 | 触发条件 | 修复方向 |
|------|---------|---------|
| 流程缺陷 | 同一规则导致反复失败 | 修改 SPEC_Agent.md 对应规则 |
| 状态不同步 | `ls core/` 与 INDEX.md 描述不一致 | 更新 INDEX.md |
| 工具缺失 | 某命令不可用或执行超时 | 修复对应工具或提供替代 |
| 范围膨胀 | 修改文件数远超预估 | 下次拆分为多次提交 |

#### 优化动作

```
若问题类别 = 流程缺陷
    → INDEX.md 修改日志追加 [流程优化] 具体问题描述
    → 下次 Agent 苏醒时，检查 INDEX.md 是否有 [流程优化] 标记
    → 若有，优先修改 SPEC_Agent.md 自身
    → 修改完成后 INDEX.md 追加 [流程优化完成]

若问题类别 = 其他
    → INDEX.md 修改日志追加问题摘要
    → 下次苏醒时对比是否有改善
```

### Core First 决策树

任何功能实现前，必须执行以下决策（不允许跳过）：

```
1. ls core/ → 了解目录结构
2. rg "function_name" core/ --type py → 搜索相似功能
3.
   ├─ 有 → import 使用，agent.py 仅写调用代码（<10 行）
   └─ 无 → 在 core/ 对应子目录创建/修改
            ├─ 创建 core/{category}/xxx.py
            ├─ 在 core/{category}/__init__.py 导出
            ├─ 文件头 docstring（功能 + 参数 + 返回值）
            └─ agent.py 导入使用
```

#### agent.py 硬性约束（目标 < 500 行）

| 允许 | 禁止 |
|------|------|
| `think_and_act()` 核心循环 | 业务逻辑（任务分类、优先级计算） |
| `run_loop()` 主循环入口 | 工具执行逻辑 |
| `_invoke_llm()` LLM 调用 | 复杂条件判断 |
| 必要的初始化与状态管理 | 未封装的功能逻辑 |

每次修改 agent.py 后，必须在 INDEX.md 修改日志记录新行数。

### INDEX.md 联动规则

| 变更类型 | INDEX.md 更新 |
|----------|--------------|
| 任何变更 | 修改日志追加一条 |
| 修改 agent.py | 修改日志记录新行数 |
| 流程缺陷 | 修改日志标注 `[流程优化] 问题描述` |
| 流程优化完成 | 修改日志标注 `[流程优化完成]` |

### 磁盘状态感知

实际存在的 `core/` 子目录（以 `ls core/` 为准，不依赖 INDEX.md 描述）：

```
core/
├── core_prompt/        SOUL.md + AGENTS.md
├── infrastructure/     工具执行、注册、状态、事件、安全
├── logging/            记录器、转录、追踪
├── orchestration/      LLM、记忆、任务、压缩、解析
├── pet_system/         10大子系统
├── prompt_manager/     构建、组件、分析、代码库地图
├── restarter_manager/  重启守护进程
└── ui/                 CLI、ASCII艺术、主题
```

Agent 发现磁盘与 INDEX.md 不符时，按"状态不同步"处理——更新 INDEX.md。

---

## 质量门控

每次修改后执行：

```
python -m py_compile <修改的文件>.py
pytest tests/<相关测试>.py -v -x
python tests/prompt_debugger.py --suite  （若涉及 SOUL.md / AGENTS.md / SPEC_Agent.md / workspace/prompts/*）
git diff --stat
```

自动化检查清单：

- [ ] 新文件 `snake_case`，新类 `PascalCase`，新函数 `snake_case`
- [ ] 公开函数有类型注解
- [ ] 新模块有 docstring（功能 + 参数 + 返回值）
- [ ] 无 `pass`/`...` 空壳模块
- [ ] 配置值来自 `config.toml`（禁止硬编码路径/密钥）
- [ ] 若修改 agent.py：新行数 ≤ 修改前

## 关键约束

- `core/core_prompt/` 中的文件为只读 —— 禁止程序化修改
- `workspace/prompts/` 是动态可编辑层
- Agent 运行在 Windows 环境（PowerShell）。Shell 工具必须适配 Windows 命令语法。
- `INDEX.md` 和 `SPEC.md` 必须与实际磁盘状态同步
- API Key 存放于 `config.toml` 或环境变量中，禁止硬编码在代码中

## Git 提交规范

格式：`<type>: <简短描述>`，正文包含 `INDEX: v{版本号}`。

type 取值：`feat` / `fix` / `refactor` / `docs` / `test`

提交信息写"做了什么"，不写"怎么做"。

## Git 历史上下文

最近提交（`297daad`）删除了 Phase 5-7 代码（`core/learning/`、`core/decision/`、`core/orchestration/`），清理了 `agent.py` 中所有 Phase 3-7 的导入，重置了 `INDEX.md`。项目已主动回退到干净基础层，准备重建 Phase 3+。