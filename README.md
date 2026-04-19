# 虾宝自我进化系统

> **版本：** v6.0 | **日期：** 2026-04-19 | **版本迭代：** 20+次重大更新

一个能够通过网络搜索获取新知识、读取和修改自己源代码、进行语法自检、并通过独立守护进程实现自我重启的 **自我进化 AI Agent** 系统。

基于 LangChain 框架构建，使用 ReAct 风格的 Agent 架构，具备 **8+2 阶段进化能力**，遵循 **Core First** 架构原则。

---

## 核心特性

```
┌─────────────────────────────────────────────────────────────────┐
│                     虾宝自我进化系统 SPEC                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  🌟 自我进化 - 8+2 阶段渐进式架构升级                            │
│     Phase 1-7: 工具整合 → 基础设施 → 进化能力 → 知识系统 →       │
│                持续学习 → 自主决策 → 模块化重构                   │
│     Phase 8: 自主探索模式 ⚠️ 进行中                              │
│     +2: Skill 生态 ✅ / Token 优化 ✅                          │
│                                                                  │
│  🧠 三层记忆系统                                                 │
│     短期记忆：会话中的工具调用和思考过程                           │
│     中期记忆：世代内的任务、洞察、代码理解                         │
│     长期记忆：跨世代的核心智慧和能力画像                           │
│                                                                  │
│  🎭 双轨提示词加载                                               │
│     静态层：core/core_prompt/ (只读内置)                        │
│     动态层：workspace/prompts/ (用户可编辑)                     │
│                                                                  │
│  🛠️ Skill 自我扩展系统                                          │
│     Agent 可在 workspace/skills/ 自建/修改/删除 Skill            │
│                                                                  │
│  📊 Token 优化                                                   │
│     4 级压缩策略：light / standard / deep / emergency           │
│                                                                  │
│  🏗️ Core First 架构                                             │
│     agent.py ~830行（已从1747行精简52%）                        │
│     业务逻辑迁移到 core/ 各模块                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 项目架构

```
self-evo-baby/                    # 项目根目录
├── agent.py                      # Agent 主入口 (~830行)
│                                  # 职责：运行循环、LLM调用、状态管理
├── config.toml                   # 配置文件 (TOML格式)
│
├── config/                       # 配置模块
│   ├── __init__.py            # 统一配置入口
│   ├── adapters.py             # LLM Provider 适配器（MiniMax）
│   ├── models.py               # Pydantic 数据模型
│   ├── providers.py            # LLM 模型预设注册表
│   └── settings.py             # 配置加载与单例管理
│
├── core/                         # 核心模块 (13个子目录, 95+个文件)
│   │
│   ├── infrastructure/          # Phase 1-2: 基础设施
│   │   ├── tool_executor.py     # 工具执行器 (注册/超时/重试/并行)
│   │   ├── tool_registry.py     # 工具动态注册表
│   │   ├── state.py            # 状态管理 (单例/线程安全)
│   │   ├── event_bus.py        # 事件总线 (发布订阅/通配符)
│   │   ├── security.py         # 安全验证 (白名单+黑名单)
│   │   ├── model_discovery.py   # 动态模型发现
│   │   ├── workspace_manager.py # SQLite 工作区管理
│   │   ├── tool_result.py      # 工具结果处理
│   │   └── agent_session.py     # Session 状态管理
│   │
│   ├── orchestration/           # Phase 7: 模块化重构
│   │   ├── llm_orchestrator.py  # LLM 调用协调
│   │   ├── llm_factory.py       # LLM 创建工厂 ⭐新增
│   │   ├── memory_manager.py    # 三层记忆管理
│   │   ├── context_compressor.py # 上下文压缩管理 ⭐新增
│   │   ├── agent_lifecycle.py    # 生命周期管理 ⭐新增
│   │   ├── task_planner.py      # 智能任务规划
│   │   ├── compression_persister.py # 压缩快照持久化
│   │   ├── semantic_retriever.py # 基于 embedding 搜索
│   │   ├── forgetting_engine.py  # 选择性遗忘机制
│   │   └── response_parser.py   # 响应解析
│   │
│   ├── evolution/               # Phase 3: 进化能力
│   │   ├── evolution_engine.py   # 8阶段进化引擎
│   │   ├── evolution_gate.py     # 进化测试门控
│   │   ├── self_analyzer.py      # 10维度能力分析
│   │   ├── refactoring_planner.py # 坏味道识别
│   │   ├── code_generator.py     # 模板生成
│   │   └── self_refactoror.py   # 自我重构器 ⚠️ 框架
│   │
│   ├── knowledge/               # Phase 4: 知识系统
│   │   ├── knowledge_graph.py    # 代码实体关系图谱
│   │   ├── codebase_analyzer.py  # AST 代码分析
│   │   └── semantic_search.py    # 语义搜索
│   │
│   ├── learning/                # Phase 5: 持续学习
│   │   ├── learning_engine.py    # 模式提取学习
│   │   ├── feedback_loop.py      # 多源反馈聚合
│   │   ├── insight_tracker.py     # 洞察分类管理
│   │   └── strategy_learner.py  # 策略学习
│   │
│   ├── decision/                # Phase 6: 自主决策
│   │   ├── decision_tree.py      # 基于规则决策
│   │   ├── priority_optimizer.py # 智能任务排序
│   │   ├── strategy_selector.py  # 策略切换优化
│   │   └── task_classifier.py   # 任务分类
│   │
│   ├── autonomous/             # Phase 8: 自主探索 ⚠️ 进行中
│   │   ├── autonomous_mode.py  # 自主模式入口 ⚠️ 框架
│   │   └── goal_generator.py   # 目标生成 ⚠️ 框架
│   │
│   ├── ecosystem/              # 工具生态
│   │   ├── tool_ecosystem.py   # DynamicLoader/PluginManager
│   │   ├── skill_registry.py   # Skill 注册中心
│   │   ├── skill_loader.py     # Skill 加载器
│   │   ├── skill_tools.py      # Skill 管理工具 (8个)
│   │   └── restarter.py        # 重启管理
│   │
│   ├── capabilities/           # 能力系统
│   │   ├── prompt_manager.py   # 动态提示词管理器
│   │   ├── task_analyzer.py     # 任务分析器
│   │   ├── task_manager.py     # 任务管理
│   │   ├── prompt_builder.py   # 提示词构建
│   │   └── codebase_map_builder.py # 代码库地图
│   │
│   ├── core_prompt/            # 核心提示词 (静态只读)
│   │   ├── SOUL.md            # 使命铁律
│   │   └── AGENTS.md          # 操作规范
│   │
│   ├── logging/                # 日志系统
│   │   ├── logger.py          # 调试日志 (DebugLogger)
│   │   ├── unified_logger.py  # 统一日志 (UnifiedLogger)
│   │   ├── transcript_logger.py # 对话转录
│   │   ├── tool_tracker.py    # 工具追踪
│   │   └── setup.py           # 日志配置
│   │
│   ├── ui/                    # 用户界面
│   │   ├── ascii_art.py       # 多形象系统 (5套 ASCII Art)
│   │   ├── cli_ui.py          # CLI UI 组件
│   │   ├── interactive_cli.py # 交互式 CLI
│   │   ├── token_display.py   # Token 显示 ⭐新增
│   │   └── theme.py          # 主题系统 ⚠️ 框架
│   │
│   └── pet_system/            # 宠物系统 (10大子系统)
│       ├── pet_system.py      # 核心类
│       └── subsystems/       # 子系统
│
├── tools/                      # 工具集 (12个文件)
│   ├── shell_tools.py         # Shell 工具 (12个)
│   ├── memory_tools.py        # 记忆工具 (15个)
│   ├── code_analysis_tools.py # 代码分析 (6个)
│   ├── search_tools.py        # 搜索工具 (5个)
│   ├── rebirth_tools.py       # 重启工具 (6个)
│   ├── token_manager.py       # Token 管理 (含增强压缩)
│   ├── compression_*.py       # 压缩相关工具
│   ├── Key_Tools.py          # 工具注册 (29个)
│
├── workspace/                  # 工作区
│   ├── memory/               # 记忆存储
│   │   ├── archives/        # 压缩快照存储
│   │   ├── semantic_index.json # 语义检索索引
│   │   ├── forgotten/        # 遗忘回收站
│   │   └── pet_info.json    # 宠物投喂记录
│   ├── prompts/              # 动态提示词
│   │   ├── IDENTITY.md       # 身份定义
│   │   ├── USER.md          # 用户信息
│   │   ├── DYNAMIC.md       # 动态提示词
│   │   ├── COMPRESS_SUMMARY.md # 压缩摘要
│   │   └── STATE_MEMORY.md   # 状态记忆
│   ├── skills/              # Skill 拓展目录
│   └── logs/                # 运行日志
│
├── tests/                     # 测试套件 (46个文件)
│   ├── conftest.py          # pytest 配置
│   └── test_*.py           # 各模块测试
│
├── requirement/               # 规划文档
│
├── report_history/           # 任务完成报告
│   ├── claude_report/
│   └── cursor_report/
│
└── logs/                    # 日志
```

---

## Core First 架构

agent.py 遵循 Core First 原则，仅负责：
- 运行循环（run_loop）
- 思考-行动循环（think_and_act）
- LLM 调用和工具执行

所有业务逻辑迁移到 core/ 对应模块：

| agent.py 原逻辑 | 迁移到 core/ |
|----------------|-------------|
| LLM 初始化 | `core/orchestration/llm_factory.py` |
| 生命周期管理 | `core/orchestration/agent_lifecycle.py` |
| Token 压缩 | `core/orchestration/context_compressor.py` |
| Session 状态 | `core/infrastructure/agent_session.py` |
| Token 显示 | `core/ui/token_display.py` |
| 并行工具执行 | `core/infrastructure/tool_executor.py` |

**精简进度：** 1747行 → 830行（52%精简，目标 <500行）

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
# 大语言模型配置
# ============================================================
[llm]
provider = "minimax"   # minimax/openai/local
model_name = "MiniMax-M2.7"
api_key = "your-api-key"
api_base = "https://api.minimaxi.com/v1"
temperature = 0.2
max_tokens = 4096
api_timeout = 600

# ============================================================
# Agent 行为配置
# ============================================================
[agent]
name = "SelfEvolvingAgent"
awake_interval = 60
max_iterations = 100
auto_backup = true
backup_interval = 300

# ============================================================
# 上下文压缩配置 (4级压缩)
# ============================================================
[context_compression]
enabled = true
max_token_limit = 16000
keep_recent_steps = 10
compression_model = "gpt-4o-mini"
```

### 3. 运行

```bash
# 自动模式
python agent.py --auto

# 指定任务
python agent.py --prompt "读取并分析 agent.py 的结构"

# 首次进化测试
python agent.py --test

# 交互模式
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
| **搜索** | `grep_search` | Grep 搜索 |
| | `find_function_calls` | 查找函数调用 |
| **记忆** | `get_generation` | 获取世代信息 |
| | `archive_generation_history` | 归档历史 |
| | `advance_generation` | 推进世代 |
| | `commit_compressed_memory` | 提交压缩记忆 |
| **任务** | `set_plan` | 设置任务清单 |
| | `tick_subtask` | 标记任务完成 |
| | `check_restart_block` | 检查重启拦截 |
| **进化** | `trigger_self_restart` | 自我重启 |
| | `enter_hibernation` | 主动休眠 |
| **Skill** | `list_skills` | 列出已安装 Skill |
| | `install_skill` | 安装 Skill |
| | `update_skill` | 更新 Skill |
| | `uninstall_skill` | 卸载 Skill |

---

## Phase 进化路线

```
Phase 1-2: 基础设施 ✅ 完成
├── Shell 工具 ✅
├── 记忆工具 ✅
├── 搜索工具 ✅
├── Token 管理 ✅
├── 状态管理 ✅
├── 事件总线 ✅
└── 安全验证 ✅

Phase 3: 进化引擎核心 ✅ 完成
├── 8阶段进化流程 ✅
├── 进化测试门控 ✅
├── 自我重构规划 ✅
└── 代码生成器 ✅

Phase 4: 知识系统 ✅ 完成
├── 知识图谱 ✅
├── 语义搜索 ✅
└── 代码分析 ✅

Phase 5: 持续学习 ✅ 完成
├── 学习引擎 ✅
├── 反馈循环 ✅
├── 洞察追踪 ✅
└── 策略学习器 ✅

Phase 6: 自主决策 ✅ 完成
├── 决策树 ✅
├── 优先级优化器 ✅
├── 策略选择器 ✅
└── 任务分类器 ✅

Phase 7: 模块化重构 ✅ 完成
├── LLM 工厂 ⭐新增
├── 生命周期管理 ⭐新增
├── 上下文压缩管理 ⭐新增
├── Session 状态管理 ⭐新增
└── Token 显示 ⭐新增

Phase 8: 自主探索 ⚠️ 进行中
├── 自主模式入口 ⚠️ 框架
└── 目标生成 ⚠️ 框架

+2: Skill 生态 ✅ 完成
├── SkillRegistry ✅
├── SkillLoader ✅
└── Skill 管理工具 ✅

Token 优化 ✅ 完成
├── 4级压缩策略 ✅
└── 压缩质量评估 ✅

形象系统 ✅ 完成
├── 5套 ASCII Art ✅
├── AvatarManager ✅
└── /avatar 命令 ✅
```

---

## 三层记忆架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    三层记忆架构                                   │
├─────────────────────────────────────────────────────────────────┤
│  短期记忆 (ShortTermMemory)                                      │
│  ├── session_id: 会话标识                                        │
│  ├── task_list: 任务列表                                         │
│  ├── tool_calls: 工具调用记录                                    │
│  ├── thoughts: 思考过程                                          │
│  └── user_inputs: 用户输入                                       │
├─────────────────────────────────────────────────────────────────┤
│  中期记忆 (MidTermMemory)                                        │
│  ├── generation: 世代号                                          │
│  ├── current_task: 当前任务                                      │
│  ├── task_plan: 任务计划                                         │
│  ├── completed_tasks: 已完成任务                                  │
│  ├── insights: 洞察                                              │
│  └── tool_stats: 工具统计                                        │
├─────────────────────────────────────────────────────────────────┤
│  长期记忆 (LongTermMemory)                                        │
│  ├── current_generation: 当前世代                                 │
│  ├── total_generations: 总世代数                                 │
│  ├── core_wisdom: 核心智慧                                      │
│  ├── skills_profile: 能力画像                                   │
│  ├── evolution_history: 进化历史                                 │
│  └── archive_index: 归档索引                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 双轨提示词架构

```
core/core_prompt/              ← 静态核心提示词（内置只读模板）
├── SOUL.md                   ← 使命铁律（禁止修改）
└── AGENTS.md                 ← 操作规范（禁止修改）

workspace/prompts/            ← 动态提示词（用户可编辑，覆盖优先）
├── IDENTITY.md               ✅ 可修改
├── USER.md                   ✅ 可修改
├── DYNAMIC.md                ✅ 必须修改
├── COMPRESS_SUMMARY.md       ✅ 可修改
└── STATE_MEMORY.md           ✅ 状态记忆持久化
```

**PromptManager 特性：**
- 双轨加载：workspace 优先，回退 static
- 组件动态拼装：SOUL / AGENTS / MEMORY / IDENTITY / RULES
- 状态记忆持久化
- 单例全局访问

---

## Skill 自我扩展系统

Agent 可以在运行时自我扩展功能，通过 Skill 系统实现：

```
workspace/skills/              # Skill 存储目录
└── web_search/               # 示例 Skill
    ├── SKILL.md             # 元数据定义
    └── impl.py              # 实现代码
```

**内置 Skill 管理工具（8个 LangChain Tool）：**
- `list_skills` - 列出已安装 Skill
- `install_skill` - 安装 Skill
- `update_skill` - 更新 Skill
- `uninstall_skill` - 卸载 Skill
- `search_skills` - 搜索可用 Skill
- `get_skill_info` - 获取 Skill 信息
- `execute_skill` - 执行 Skill
- `render_skill_prompt` - 渲染 Skill 提示词

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
│                          sys.exit(0)               │
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

## 开发指南

### 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定模块测试
pytest tests/test_llm_orchestrator.py -v

# 运行带覆盖率
pytest tests/ --cov=core --cov=tools --cov-fail-under=80

# 运行 Token 优化测试
pytest tests/test_compression*.py -v

# 提示词打靶测试
python tests/prompt_debugger.py --suite
```

### 测试统计

| Phase | 测试文件数 | 测试数 | 状态 |
|-------|-----------|--------|------|
| Phase 1-2 | 7 | 150+ | ✅ 完整 |
| Phase 3 | 2 | 50+ | ✅ 完整 |
| Phase 4 | 4 | 70+ | ✅ 完整 |
| Phase 5 | 4 | 80+ | ✅ 完整 |
| Phase 6 | 4 | 60+ | ✅ 完整 |
| Phase 7 | 4 | 71+ | ✅ 完整 |
| Token 优化 | 3 | 58+ | ✅ 完整 |
| Phase 8 | - | - | ⚠️ 框架 |
| **总计** | **46** | **500+** | **✅** |

---

## 文档索引

| 文档 | 路径 | 用途 |
|------|------|------|
| 全局索引 | `INDEX.md` | 所有任务的执行参照 |
| 开发流程 | `requirement/SPEC/SPEC_Agent.md` | SPEC 开发流程 |
| Phase 8 规划 | `requirement/claude第一次规划/Phase8自主探索模块实现方案.md` | Phase 8 参考 |
| agent.py 拆分 | `requirement/claude第一次规划/agent.py模块化拆分方案.md` | 重构参考 |
| core 重组 | `requirement/claude第一次规划/core目录结构重组方案.md` | 目录重构参考 |
| 重构报告 | `report_history/claude_report/task_20260419_01_全局架构解耦与重构完成报告.md` | 重构进度 |

---

## 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v6.0 | 2026-04-19 | Core First 架构、agent.py 精简52%、新增5个 Core 模块 |
| v5.1 | 2026-04-19 | Core First 架构升级、SPEC_Agent.md 升级 |
| v5.0 | 2026-04-18 | 提示词自主动态拼装 |
| v4.8 | 2026-04-18 | PromptManager 重构、Skill 系统完成 |
| v4.7 | 2026-04-18 | SkillRegistry/SkillLoader/SkillTools 新增 |
| v4.6 | 2026-04-18 | set_plan_tool/check_restart_block Bug 修复 |
| v4.5 | 2026-04-18 | 提示词审查修复 |
| v4.4 | 2026-04-18 | 提示词系统双轨加载架构 |
| v4.3 | 2026-04-17 | core/ 目录结构重组 |
| v4.2 | 2026-04-17 | Phase 8 规划文档新增 |
| v4.1 | 2026-04-17 | 配置系统重构 |
| v4.0 | 2026-04-17 | 全面重构：SPEC、Phase 8、Token 优化 |

---

## License

MIT
