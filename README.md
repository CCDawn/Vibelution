# 虾宝自我进化系统

<<<<<<< HEAD
> **版本：** v4.0 | **日期：** 2026-04-17
=======
一个能够通过网络搜索获取新知识、读取和修改自己源代码、进行语法自检、并通过独立守护进程实现自我重启，能够给用户提供情绪价值的 AI Agent 系统。
>>>>>>> 0af0688e934acc6eae1587ceb7310c882f10a843

一个能够通过网络搜索获取新知识、读取和修改自己源代码、进行语法自检、并通过独立守护进程实现自我重启的 **自我进化 AI Agent** 系统。

基于 LangChain 框架构建，使用 ReAct 风格的 Agent 架构，具备 **8 阶段进化能力**。

---

## 核心特性

```
┌─────────────────────────────────────────────────────────────────┐
│                     虾宝自我进化系统 SPEC                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  🌟 自我进化 - 8 阶段渐进式架构升级                               │
│     Phase 1-7: 工具整合 → 基础设施 → 进化能力 → 知识系统 →      │
│                持续学习 → 自主决策 → 模块化重构                   │
│     Phase 8: 自主探索模式 ⚠️ 进行中                             │
│                                                                  │
│  🧠 三层记忆系统                                                 │
│     短期记忆：会话中的工具调用和思考过程                          │
│     中期记忆：世代内的任务、洞察、代码理解                        │
│     长期记忆：跨世代的核心智慧和能力画像                          │
│                                                                  │
│  🎭 多形象系统                                                   │
│     5 套 ASCII Art 角色：龙虾 🦞 / 小虾 🦐 / 螃蟹 🦀 /          │
│                          猫猫 🐱 / 小鸡 🐣                        │
│                                                                  │
│  📊 Token 优化                                                   │
│     4 级压缩策略：light / standard / deep / emergency           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 项目架构

```
self-evo-baby/                    # 项目根目录
├── agent.py                      # Agent 主入口 (~1000行)
├── config.py                     # 配置文件
├── config.toml                   # 配置文件 (TOML格式)
│
├── core/                         # 核心模块 (46个)
│   ├── Phase 1-2: 基础设施
│   │   ├── tool_executor.py     # 工具执行器
│   │   ├── state.py             # 状态管理
│   │   ├── event_bus.py         # 事件总线
│   │   ├── security.py          # 安全验证
│   │   ├── model_discovery.py    # 动态模型发现 ✅ (新增)
│   │   └── workspace_manager.py # 工作区管理
│   │
│   ├── Phase 3: 进化能力
│   │   ├── evolution_engine.py   # 8阶段进化引擎
│   │   ├── self_analyzer.py     # 10维度能力分析
│   │   ├── refactoring_planner.py # 重构规划
│   │   └── code_generator.py    # 代码生成
│   │
│   ├── Phase 4: 知识系统
│   │   ├── agent_core.py        # Agent 核心框架 ⚠️
│   │   ├── knowledge_graph.py    # 知识图谱
│   │   ├── message_bus.py       # 消息总线
│   │   ├── codebase_analyzer.py  # 代码分析
│   │   └── semantic_search.py   # 语义搜索
│   │
│   ├── Phase 5: 持续学习
│   │   ├── learning_engine.py    # 学习引擎
│   │   ├── feedback_loop.py     # 反馈循环
│   │   ├── insight_tracker.py    # 洞察追踪
│   │   └── strategy_learner.py  # 策略学习
│   │
│   ├── Phase 6: 自主决策
│   │   ├── decision_tree.py      # 决策树
│   │   ├── priority_optimizer.py # 优先级优化
│   │   └── strategy_selector.py  # 策略选择
│   │
│   ├── Phase 7: 模块化重构 ✅
│   │   ├── llm_orchestrator.py  # LLM 协调器
│   │   ├── tool_registry.py     # 工具注册表
│   │   ├── memory_manager.py     # 记忆管理器
│   │   └── task_planner.py      # 任务规划器
│   │
│   ├── Phase 8: 自主探索 ⚠️
│   │   ├── autonomous_mode.py   # 自主模式
│   │   ├── autonomous_explorer.py # 探索引擎
│   │   ├── opportunity_finder.py # 机会发现
│   │   └── goal_generator.py    # 目标生成
│   │
│   └── UI 与工具
│       ├── ascii_art.py         # 多形象系统
│       ├── cli_ui.py            # CLI UI
│       ├── interactive_cli.py   # 交互式 CLI
│       ├── prompt_builder.py    # 提示词构建
│       └── ... (更多模块)
│
├── tools/                        # 工具集 (12个)
│   ├── shell_tools.py            # Shell 工具 (12个)
│   ├── memory_tools.py           # 记忆工具 (15个)
│   ├── code_analysis_tools.py    # 代码分析 (6个)
│   ├── search_tools.py           # 搜索工具 (5个)
│   ├── rebirth_tools.py          # 重启工具 (6个)
│   ├── token_manager.py          # Token 管理
│   ├── compression_strategy.py   # 4级压缩策略
│   ├── key_info_extractor.py     # 关键信息提取
│   └── compression_quality.py    # 压缩质量评估
│
├── tests/                        # 测试套件 (46个)
│   ├── conftest.py              # pytest 配置
│   └── test_*.py               # 各模块测试
│
├── requirement/                   # 规划文档
│   └── cursor第一次规划/
│
├── workspace/                    # 工作区
│   ├── memory/                   # 记忆存储
│   ├── prompts/                  # 提示词
│   └── analytics/                # 分析结果
│
└── cursor_report_history/        # 任务完成报告 (11个)
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 (config.toml)

所有参数都在 `config.toml` 中配置：

```toml
# ============================================================
# 形象配置
# ============================================================
[avatar]
preset = "lobster"  # lobster/shrimp/crab/cat/chick

# ============================================================
# 大语言模型配置 (阿里云百炼)
# ============================================================
[llm]
provider = "aliyun"
model_name = "qwen-32b-awq"
api_key = "EMPTY"
api_base = "http://[::1]:8000/v1"
temperature = 0.2
max_tokens = 4096
api_timeout = 600

# ============================================================
# Agent 行为配置
# ============================================================
[agent]
name = "SelfEvolvingAgent"
awake_interval = 1
max_iterations = 100
auto_backup = true

# ============================================================
# 上下文压缩配置 (4级压缩)
# ============================================================
[context_compression]
enabled = true
max_token_limit = 16000

[context_compression.thresholds]
light_threshold = 0.6
standard_threshold = 0.8
deep_threshold = 0.9
emergency_threshold = 0.95
```

### 3. 切换形象

```bash
# 方式1: 修改配置文件
[avatar]
preset = "shrimp"  # 切换到小虾米

# 方式2: 命令行切换 (运行时)
/avatar          # 查看所有可用形象
/avatar shrimp   # 切换到小虾米
```

### 4. 运行

```bash
python agent.py
```

---

## 核心工具

| 类别 | 工具 | 功能 |
|------|------|------|
| **Shell** | `list_directory` | 列出目录内容 |
| | `read_local_file` | 读取文件 |
| | `edit_local_file` | 编辑代码 |
| | `create_new_file` | 创建文件 |
| | `run_command` | 执行命令 |
| | `search_files` | 搜索文件 |
| | `get_file_info` | 获取文件信息 |
| **搜索** | `web_search` | 网络搜索 |
| | `read_webpage` | 读取网页内容 |
| **记忆** | `get_generation_tool` | 获取世代信息 |
| | `archive_generation_history` | 归档历史 |
| | `advance_generation` | 推进世代 |
| **进化** | `trigger_self_restart` | 自我重启 |
| | `backup_project` | 项目备份 |
| **Token** | 自动压缩 | 4级压缩策略 |

---

## Phase 进化路线

```
Phase 1: 基础工具整合 ✅ 完成
├── Shell 工具 (12个) ✅
├── 记忆工具 (15个) ✅
├── 搜索工具 (5个) ✅
└── Token 管理 ✅

Phase 2: 自我分析能力 ✅ 完成
├── 10维度能力评估 ✅
├── 代码认知地图 ✅
└── 能力画像系统 ✅

Phase 3: 进化引擎核心 ✅ 完成
├── 8阶段进化流程 ✅
├── 自我重构规划 ✅
└── 代码生成器 ✅

Phase 4: 知识系统 ✅ 完成
├── 知识图谱 ✅
├── 消息总线 ✅
├── 语义搜索 ✅
└── Agent 核心框架 ⚠️

Phase 5: 持续学习 ✅ 完成
├── 学习引擎 ✅
├── 反馈循环 ✅
├── 洞察追踪 ✅
└── 策略学习器 ✅

Phase 6: 自主决策 ✅ 完成
├── 决策树 ✅
├── 优先级优化器 ✅
└── 策略选择器 ✅

Phase 7: 模块化重构 ✅ 完成
├── LLM Orchestrator ✅ (12测试)
├── Tool Registry ✅ (20测试)
├── Memory Manager ✅ (20测试)
└── Task Planner ✅ (19测试)

Phase 8: 自主探索 ⚠️ 进行中
├── 自主模式入口 ⚠️
├── 探索引擎 ⚠️
├── 机会发现 ⚠️
└── 目标生成 ⚠️
```

---

## 进程接力模式

```
┌─────────────────────────────────────────────────────┐
│                    Agent 进程                        │
│                                                     │
│   Agent Loop                                        │
│   └── think_and_act()                              │
│       └── LLM + Tools                              │
│           └── trigger_self_restart()               │
│                                    │                │
│                                    ▼                │
│                          spawn restarter.py         │
│                                    │                │
│                                    ▼                │
│                          sys.exit(0)  ──── X        │
└─────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────┐
│                  Restarter 进程                       │
│                                                     │
│   wait_for_process_death(pid)                       │
│   └── [等待原进程结束]                               │
│                                                     │
│   spawn_new_process(agent.py)                       │
│   └── [拉起新 Agent]                                │
└─────────────────────────────────────────────────────┘
```

---

## 代码修改流程

Agent 发现需要优化时，必须遵循以下流程：

```
1. edit_local_file()    # 修改代码
2. check_syntax()       # 语法自检
3. trigger_self_restart()  # 重启应用
```

---

## 开发指南

### 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定模块测试
pytest tests/test_llm_orchestrator.py -v

# 运行带覆盖率
pytest tests/ --cov=core --cov=tools --cov-fail-under=80
```

### 任务完成报告

每次完成一个任务后，必须生成报告：

- **路径：** `cursor_report_history/`
- **格式：** `task_{YYYYMMDD}_{序号}_{任务摘要}.md`
- **示例：** `task_20260417_01_Phase8自主探索模块实现.md`

---

## 文档索引

| 文档 | 路径 | 用途 |
|------|------|------|
| 全局索引 | `INDEX.md` | 所有任务的执行参照 |
| 完整规划 | `requirement/cursor第一次规划/虾宝自我进化系统完整规划.md` | Phase 规划参考 |
| 技术设计 | `requirement/cursor第一次规划/技术设计文档.md` | 架构设计参考 |
| 报告历史 | `cursor_report_history/` | 历史任务记录 |

---

## License

MIT
