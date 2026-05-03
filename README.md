# Vibelution — 自我进化 AI Agent 系统

> **版本：** v7.0 | **日期：** 2026-05-01

基于 LangChain ReAct 架构的自我进化 AI Agent。能够通过网络搜索获取新知识、读取和修改自身源代码、进行语法自检、并通过独立守护进程实现自我重启。

---

## 核心特性

```
┌─────────────────────────────────────────────────────────────────┐
│                     Vibelution 自我进化系统                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  🧠 三层记忆系统                                                 │
│     短期记忆：会话中的工具调用和思考过程                           │
│     中期记忆：世代内的任务、洞察、代码理解                         │
│     长期记忆：跨世代的核心智慧和能力画像                           │
│                                                                  │
│  🎭 双轨提示词架构                                               │
│     静态层：core/core_prompt/ (只读内置)                        │
│     动态层：workspace/prompts/ (Agent 运行时可编辑)              │
│                                                                  │
│  🔄 自我重启机制                                                 │
│     Agent 可通过 trigger_self_restart 触发进程级重启，            │
│     由 restarter.py 守护进程拉起新 Agent 实例                     │
│                                                                  │
│  📋 TaskManager 任务追踪                                         │
│     基于 tasks.json 的任务状态管理，支持创建/更新/查询            │
│                                                                  │
│  🏗️ Core First 架构                                              │
│     agent.py ~611行（入口 + 核心循环）                            │
│     业务逻辑迁移到 core/ 各模块                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 项目架构

```
Vibelution/                     # 项目根目录
├── agent.py                     # Agent 主入口 (~611行)
│                                 # 职责：运行循环、LLM调用、工具执行
├── config.toml                  # 配置文件 (TOML格式)
│
├── config/                      # 配置模块
│   ├── __init__.py           # 统一配置入口
│   ├── models.py              # Pydantic 数据模型
│   ├── providers.py           # LLM 模型预设注册表
│   └── settings.py            # 配置加载与单例管理
│
├── core/                        # 核心模块 (9个子目录)
│   │
│   ├── infrastructure/         # 基础设施
│   │   ├── tool_executor.py    # 工具执行器 (超时/重试/并行)
│   │   ├── state.py           # 状态管理 (单例/线程安全)
│   │   ├── event_bus.py       # 事件总线 (发布订阅/通配符)
│   │   ├── security.py        # 安全验证 (白名单+黑名单)
│   │   ├── model_discovery.py  # 动态模型发现
│   │   ├── workspace_manager.py # SQLite 工作区管理
│   │   ├── tool_result.py     # 工具结果处理
│   │   └── agent_session.py   # Session 状态管理
│   │
│   ├── orchestration/          # 任务编排
│   │   └── task_planner.py     # 智能任务规划 (TaskManager)
│   │
│   ├── evolution/              # 进化引擎
│   │   └── evolution_goal_analyzer.py  # 进化目标分析
│   │
│   ├── prompt_manager/         # 提示词管理
│   │   ├── prompt_manager.py  # 动态提示词管理器
│   │   ├── prompt_builder.py  # 提示词构建
│   │   ├── task_analyzer.py   # 任务分析器
│   │   └── codebase_map_builder.py # 代码库地图
│   │
│   ├── core_prompt/           # 核心提示词 (静态只读)
│   │   ├── SOUL.md           # 使命铁律
│   │   └── SPEC.md          # 开发流程规范
│   │
│   ├── logging/               # 日志系统
│   │   ├── logger.py         # 调试日志
│   │   ├── unified_logger.py # 统一日志
│   │   ├── transcript_logger.py # 对话转录
│   │   ├── tool_tracker.py   # 工具追踪
│   │   └── setup.py          # 日志配置
│   │
│   ├── ui/                    # 用户界面
│   │   ├── ascii_art.py      # ASCII Art 形象系统
│   │   ├── cli_ui.py         # CLI UI 组件
│   │   ├── interactive_cli.py # 交互式 CLI
│   │   ├── token_display.py  # Token 显示
│   │   └── theme.py          # 主题系统
│   │
│   ├── pet_system/            # 宠物系统
│   │   ├── pet_system.py     # 核心类
│   │   └── models.py         # 数据模型
│   │
│   └── restarter_manager/     # 重启守护
│       └── restarter.py       # 进程接力重启
│
├── tools/                       # 工具集
│   ├── Key_Tools.py           # 工具注册 (14个 LLM 可见工具)
│   ├── shell_tools.py         # Shell 工具
│   ├── memory_tools.py        # 记忆与任务工具
│   ├── code_analysis_tools.py # 代码分析工具 (AST/Diff)
│   ├── rebirth_tools.py       # 重启/休眠工具
│   ├── search_tools.py        # Grep 搜索工具
│   ├── web_search_tool.py     # 网络搜索工具
│   └── token_manager.py       # Token 管理
│
├── workspace/                   # 工作区
│   ├── memory/               # 记忆存储
│   │   └── archives/        # 世代档案
│   ├── prompts/              # 动态提示词
│   │   ├── IDENTITY.md      # 身份定义
│   │   ├── USER.md          # 用户信息
│   │   ├── DYNAMIC.md       # 动态提示词
│   │   └── STATE_MEMORY.md  # 状态记忆
│   ├── skills/              # Skill 拓展目录
│   └── logs/                # 运行日志
│
├── tests/                      # 测试套件 (20个文件, ~150+ tests)
│   ├── conftest.py           # pytest 配置与共享 fixtures
│   └── test_*.py            # 各模块测试
│
└── requirement/               # 规划文档
```

---

## Core First 架构

agent.py 遵循 Core First 原则，仅负责：
- 运行循环 (`run_loop`)
- 思考-行动循环 (`think_and_act`)
- LLM 调用和工具执行

所有业务逻辑迁移到 `core/` 对应模块：

| agent.py 原逻辑 | 迁移到 core/ |
|----------------|-------------|
| 状态管理 | `core/infrastructure/state.py` |
| 事件总线 | `core/infrastructure/event_bus.py` |
| 安全验证 | `core/infrastructure/security.py` |
| 工具执行 | `core/infrastructure/tool_executor.py` |
| 工作区管理 | `core/infrastructure/workspace_manager.py` |
| 提示词管理 | `core/prompt_manager/prompt_manager.py` |
| 任务规划 | `core/orchestration/task_planner.py` |

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 (config.toml)

```toml
[llm]
provider = "minimax"
model_name = "MiniMax-M2.7"
api_key = "your-api-key"
api_base = "https://api.minimaxi.com/v1"
temperature = 0.2
max_tokens = 4096

[agent]
name = "SelfEvolvingAgent"
awake_interval = 60
max_iterations = 100
```

### 3. 运行

```bash
# 自动模式
python agent.py --auto

# 指定任务
python agent.py --prompt "读取并分析 agent.py 的结构"

# 进化测试
python agent.py --test

# 交互模式
python agent.py
```

---

## Agent 工具 (14个 LLM 可见)

| 类别 | 工具 | 功能 |
|------|------|------|
| **核心** | `commit_compressed_memory_tool` | 重启前压缩存盘记忆 |
| **世代** | `set_generation_task_tool` | 设置当前世代任务 |
| | `trigger_self_restart_tool` | 触发自我重启 |
| **代码** | `grep_search_tool` | 全局正则搜索 |
| | `apply_diff_edit_tool` | Diff 块精准编辑 |
| | `validate_diff_format_tool` | 验证 Diff 格式 |
| | `list_file_entities_tool` | AST 列出文件实体 |
| | `get_code_entity_tool` | AST 提取特定实体 |
| **搜索** | `web_search_tool` | 网络搜索 |
| **文件** | `cli_tool` | 万能 Shell 命令 |
| **休眠** | `enter_hibernation_tool` | 主动休眠 |
| **任务** | `task_create_tool` | 创建任务清单 |
| | `task_update_tool` | 更新任务状态 |
| | `task_list_tool` | 查询任务进度 |

---

## 双轨提示词架构

```
core/core_prompt/              ← 静态核心提示词（只读模板）
├── SOUL.md                   ← 使命铁律（禁止修改）
└── SPEC.md                   ← 开发流程规范（禁止修改）

workspace/prompts/            ← 动态提示词（Agent 运行时可编辑）
├── IDENTITY.md               ✅ 可修改
├── USER.md                   ✅ 可修改
├── DYNAMIC.md                ✅ 必须修改
└── STATE_MEMORY.md           ✅ 状态记忆持久化
```

**PromptManager 特性：**
- 双轨加载：workspace 优先，回退 static
- 优先级组件拼装：SOUL(10) → DYNAMIC(40) → SPEC(65) → MEMORY(80)
- 状态记忆持久化

---

## 三层记忆架构

```
短期记忆 (会话)          中期记忆 (世代)          长期记忆 (跨世代)
├── session_id           ├── generation            ├── current_generation
├── task_list            ├── current_task          ├── total_generations
├── tool_calls           ├── task_plan             ├── core_wisdom
├── thoughts             ├── completed_tasks       ├── skills_profile
└── user_inputs          ├── insights              ├── evolution_history
                         └── tool_stats            └── archive_index
```

---

## 自我重启机制

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

## 开发指南

### 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定模块测试
pytest tests/test_tool_executor.py -v

# 提示词打靶测试
python tests/prompt_debugger.py
```

### 质量门控

每次修改后执行：

```bash
python -m py_compile <修改的文件>.py
pytest tests/<相关测试>.py -v -x
git diff --stat
```

---

## 文档索引

| 文档 | 路径 | 用途 |
|------|------|------|
| 代码库地图 | `workspace/prompts/CODEBASE_MAP.md` | 自动生成的项目结构地图 |
| 开发规范 | `CLAUDE.md` | Claude Code 协作文档 |
| 核心使命 | `core/core_prompt/SOUL.md` | Agent 身份与铁律 |
| 操作规范 | `core/core_prompt/SPEC.md` | Agent 开发流程规范 |

---

## 最近变更

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v7.0 | 2026-05-01 | 大清理：移除 ~4000 行死代码、删除 tool_registry.py、精简 14 个 LLM 工具 |
| v6.0 | 2026-04-19 | Core First 架构、agent.py 精简52%、新增 5 个 Core 模块 |
| v5.1 | 2026-04-19 | Core First 架构升级 |
| v5.0 | 2026-04-18 | 提示词自主动态拼装 |
| v4.0 | 2026-04-17 | 全面重构：SPEC、Phase 8、Token 优化 |

---

## License

MIT
