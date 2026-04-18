# 虾宝自我进化系统

> **版本：** v4.8 | **日期：** 2026-04-18 | **版本迭代：** 19次重大更新

一个能够通过网络搜索获取新知识、读取和修改自己源代码、进行语法自检、并通过独立守护进程实现自我重启的 **自我进化 AI Agent** 系统。

基于 LangChain 框架构建，使用 ReAct 风格的 Agent 架构，具备 **8+2 阶段进化能力**。

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
└─────────────────────────────────────────────────────────────────┘
```

---

## 项目架构

```
self-evo-baby/                    # 项目根目录
├── agent.py                      # Agent 主入口 (~1000行)
├── config.toml                   # 配置文件 (TOML格式)
│
├── config/                       # 配置模块
│   ├── __init__.py             # 统一配置入口
│   ├── models.py                # Pydantic 数据模型
│   ├── providers.py             # LLM 模型预设注册表
│   └── settings.py              # 配置加载与单例管理
│
├── core/                         # 核心模块 (13个子目录, 89个文件)
│   │
│   ├── infrastructure/          # Phase 1-2: 基础设施
│   │   ├── tool_executor.py     # 工具执行器 (注册/超时/重试)
│   │   ├── tool_registry.py     # 工具动态注册表
│   │   ├── state.py            # 状态管理 (单例/线程安全)
│   │   ├── event_bus.py        # 事件总线 (发布订阅/通配符)
│   │   ├── security.py         # 安全验证 (白名单+黑名单)
│   │   ├── model_discovery.py   # 动态模型发现
│   │   └── workspace_manager.py # SQLite 工作区管理
│   │
│   ├── evolution/               # Phase 3: 进化能力
│   │   ├── evolution_engine.py  # 8阶段进化引擎
│   │   ├── self_analyzer.py    # 10维度能力分析
│   │   ├── refactoring_planner.py # 坏味道识别
│   │   ├── code_generator.py   # 模板生成
│   │   └── self_refactoror.py  # 自我重构器 ⚠️ 框架
│   │
│   ├── knowledge/               # Phase 4: 知识系统
│   │   ├── knowledge_graph.py   # 代码实体关系图谱
│   │   ├── codebase_analyzer.py # AST 代码分析
│   │   ├── semantic_search.py   # 语义搜索
│   │   └── message_bus.py      # 发布订阅通信
│   │
│   ├── learning/                # Phase 5: 持续学习
│   │   ├── learning_engine.py   # 模式提取学习
│   │   ├── feedback_loop.py    # 多源反馈聚合
│   │   ├── insight_tracker.py   # 洞察分类管理
│   │   ├── strategy_learner.py # 策略学习
│   │   └── agent_core.py       # Agent 核心基类 ⚠️ 框架
│   │
│   ├── decision/                # Phase 6: 自主决策
│   │   ├── decision_tree.py     # 基于规则决策
│   │   ├── priority_optimizer.py # 智能任务排序
│   │   └── strategy_selector.py # 策略切换优化
│   │
│   ├── orchestration/          # Phase 7: 模块化重构
│   │   ├── llm_orchestrator.py # LLM 调用协调 (12测试)
│   │   ├── memory_manager.py   # 三层记忆管理 (20测试)
│   │   ├── task_planner.py     # 智能任务规划 (19测试)
│   │   ├── compression_persister.py # 压缩快照持久化
│   │   ├── semantic_retriever.py # 基于 embedding 搜索
│   │   ├── forgetting_engine.py # 选择性遗忘机制
│   │   └── response_parser.py  # 响应解析
│   │
│   ├── autonomous/             # Phase 8: 自主探索 ⚠️ 进行中
│   │   ├── autonomous_mode.py  # 自主模式入口
│   │   ├── autonomous_explorer.py # 探索引擎
│   │   ├── opportunity_finder.py # 机会发现
│   │   └── goal_generator.py   # 目标生成
│   │
│   ├── capabilities/           # 能力系统
│   │   ├── skills_profiler.py  # 能力画像
│   │   ├── task_analyzer.py   # 任务分析器
│   │   ├── task_manager.py    # 任务管理
│   │   ├── prompt_builder.py   # 提示词构建 (兼容层)
│   │   ├── prompt_manager.py   # 动态提示词管理器
│   │   └── pattern_library.py  # 模式库 ⚠️ 框架
│   │
│   ├── ecosystem/              # 工具生态 (Phase 8.5)
│   │   ├── tool_ecosystem.py  # DynamicLoader/PluginManager
│   │   ├── skill_registry.py  # Skill 注册中心 (25测试)
│   │   ├── skill_loader.py    # Skill 加载器 (8测试)
│   │   ├── skill_tools.py    # Skill 管理工具 (8个 LangChain Tool)
│   │   └── restarter.py       # 重启管理
│   │
│   ├── core_prompt/            # 核心提示词 (静态只读)
│   │   ├── __init__.py        # CorePromptManager (已迁移到 prompt_manager)
│   │   ├── SOUL.md            # 禁止修改
│   │   └── AGENTS.md          # 禁止修改
│   │
│   ├── logging/                # 日志系统
│   │   ├── logger.py          # 调试日志 (DebugLogger)
│   │   ├── unified_logger.py  # 统一日志 (UnifiedLogger)
│   │   ├── transcript_logger.py # 对话转录
│   │   └── tool_tracker.py    # 工具追踪
│   │
│   ├── ui/                    # 用户界面
│   │   ├── ascii_art.py       # 多形象系统 (5套 ASCII Art)
│   │   ├── cli_ui.py         # CLI UI 组件
│   │   ├── interactive_cli.py # 交互式 CLI
│   │   └── theme.py          # 主题系统 ⚠️ 框架
│   │
│   └── pet_system/            # 宠物系统 (10大子系统)
│       ├── pet_system.py      # 核心类
│       ├── models.py          # Pydantic 数据模型
│       └── subsystems/       # 子系统
│           ├── gene_system.py # 基因系统
│           ├── heart_system.py # 心跳系统
│           ├── dream_system.py # 梦境系统
│           ├── personality_system.py # 性格养成
│           ├── hunger_system.py # 饥饿系统
│           ├── diary_system.py # 成长日记
│           ├── social_system.py # 同伴社交
│           ├── health_system.py # 健康体检
│           ├── skin_system.py  # 装扮系统
│           └── sound_system.py # 声音系统
│
├── tools/                      # 工具集 (12个文件)
│   ├── shell_tools.py         # Shell 工具 (12个)
│   ├── memory_tools.py        # 记忆工具 (15个)
│   ├── code_analysis_tools.py # 代码分析 (6个)
│   ├── search_tools.py        # 搜索工具 (5个)
│   ├── rebirth_tools.py       # 重启工具 (6个)
│   ├── token_manager.py       # Token 管理 (含增强压缩)
│   ├── compression_strategy.py # 4级压缩策略 (24测试)
│   ├── key_info_extractor.py  # 关键信息提取 (16测试)
│   ├── compression_quality.py # 压缩质量评估 (18测试)
│   └── Key_Tools.py          # 工具注册
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
│   │   └── web_search/      # 示例 Skill
│   └── logs/                # 运行日志
│
├── tests/                     # 测试套件 (45个文件)
│   ├── conftest.py          # pytest 配置
│   └── test_*.py           # 各模块测试
│
├── requirement/               # 规划文档
│   ├── cursor第一次规划/
│   ├── cursor第二次规划/
│   └── claaude第一次规划/
│
├── report_history/           # 任务完成报告 (18个)
│   ├── claude_report/
│   └── cursor_report/
│
└── logs/                    # 日志
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
# 大语言模型配置
# ============================================================
[llm]
provider = "local"   # aliyun/openai/anthropic/deepseek/local
model_name = "qwen2.5:7b"
api_key = "not-required"
api_base = "http://localhost:11434/v1"
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
keep_recent_steps = 10

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
# 自动模式
python agent.py --auto

# 指定任务
python agent.py --prompt "读取并分析 agent.py 的结构"

# 首次进化测试
python agent.py --test
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
| **搜索** | `web_search` | 网络搜索 |
| | `read_webpage` | 读取网页内容 |
| **记忆** | `get_generation_tool` | 获取世代信息 |
| | `archive_generation_history` | 归档历史 |
| | `advance_generation` | 推进世代 |
| | `commit_compressed_memory` | 提交压缩记忆 |
| **任务** | `set_plan` | 设置任务清单 |
| | `tick_subtask` | 标记任务完成 |
| | `check_restart_block` | 检查重启拦截 |
| **进化** | `trigger_self_restart` | 自我重启 |
| | `backup_project` | 项目备份 |
| **Skill** | `list_skills` | 列出已安装 Skill |
| | `install_skill` | 安装 Skill |
| | `update_skill` | 更新 Skill |
| | `uninstall_skill` | 卸载 Skill |
| **Token** | 自动压缩 | 4级压缩策略 |

---

## Phase 进化路线

```
Phase 1: 基础工具整合 ✅ 完成 (2026-04-15)
├── Shell 工具 (12个) ✅
├── 记忆工具 (15个) ✅
├── 搜索工具 (5个) ✅
└── Token 管理 ✅

Phase 2: 自我分析能力 ✅ 完成 (2026-04-16)
├── 10维度能力评估 ✅
├── 代码认知地图 ✅
└── 能力画像系统 ✅

Phase 3: 进化引擎核心 ✅ 完成 (2026-04-16)
├── 8阶段进化流程 ✅
├── 自我重构规划 ✅
└── 代码生成器 ✅

Phase 4: 知识系统 ✅ 完成 (2026-04-16)
├── 知识图谱 ✅
├── 消息总线 ✅
├── 语义搜索 ✅
└── Agent 核心框架 ⚠️

Phase 5: 持续学习 ✅ 完成 (2026-04-16)
├── 学习引擎 ✅
├── 反馈循环 ✅
├── 洞察追踪 ✅
└── 策略学习器 ✅

Phase 6: 自主决策 ✅ 完成 (2026-04-16)
├── 决策树 ✅
├── 优先级优化器 ✅
└── 策略选择器 ✅

Phase 7: 模块化重构 ✅ 完成 (2026-04-17)
├── LLM Orchestrator ✅ (12测试)
├── Tool Registry ✅ (20测试)
├── Memory Manager ✅ (20测试)
└── Task Planner ✅ (19测试)

Phase 8: 自主探索 ⚠️ 进行中
├── 自主模式入口 ⚠️ 框架
├── 探索引擎 ⚠️ 框架
├── 机会发现 ⚠️ 框架
└── 目标生成 ⚠️ 框架

+2: Skill 生态 ✅ 完成 (2026-04-18)
├── SkillRegistry ✅ (25测试)
├── SkillLoader ✅ (8测试)
└── Skill 管理工具 ✅

Token 优化 ✅ 完成 (2026-04-16)
├── 4级压缩策略 ✅ (24测试)
├── 关键信息提取 ✅ (16测试)
└── 压缩质量评估 ✅ (18测试)

形象系统 ✅ 完成 (2026-04-16)
├── 5套 ASCII Art ✅
├── AvatarManager ✅
└── /avatar 命令 ✅

核心目录重构 ✅ 完成 (2026-04-17)
└── core/ 按功能分类到 13 个子目录
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
│  ├── code_insights: 代码洞察                                     │
│  └── tool_stats: 工具统计                                       │
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
├── SOUL.md                   ← 禁止修改（LLM 铁律）
├── AGENTS.md                 ← 禁止修改（Agent 执行 SOP）
└── __init__.py              ← CorePromptManager（已迁移）

workspace/prompts/            ← 动态提示词（用户可编辑，覆盖优先）
├── SOUL.md                   ✅ 可覆盖
├── AGENTS.md                 ✅ 可覆盖
├── IDENTITY.md               ✅ 可修改
├── USER.md                   ✅ 可修改
├── DYNAMIC.md                ✅ 必须修改
├── COMPRESS_SUMMARY.md       ✅ 可修改
└── STATE_MEMORY.md           ✅ 状态记忆持久化
```

**PromptManager 特性：**
- 双轨加载：workspace 优先，回退 static
- 参数驱动拼接：`build(include, exclude)`
- 规则注册表：base / code_review / creative / debug / planning / refactor
- 单例全局访问：`get_prompt_manager()`

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
- `enable_skill` - 启用 Skill
- `disable_skill` - 禁用 Skill

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

## 代码修改流程

Agent 发现需要优化时，必须遵循以下流程：

```
1. edit_local_file()    # 修改代码
2. check_syntax()        # 语法自检
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

# 只运行快速测试
pytest tests/ -m "not slow" -v

# 运行 Phase 7 测试
pytest tests/test_llm_orchestrator.py tests/test_tool_registry.py \
       tests/test_memory_manager.py tests/test_task_planner.py -v

# 运行 Token 优化测试
pytest tests/test_compression*.py tests/test_key_info_extractor.py -v
```

### 测试统计

| Phase | 测试文件数 | 测试数 | 状态 |
|-------|-----------|--------|------|
| Phase 1-2 | 7 | 150+ | ✅ 完整 |
| Phase 3 | 2 | 50+ | ✅ 完整 |
| Phase 4 | 4 | 70+ | ✅ 完整 |
| Phase 5 | 4 | 80+ | ✅ 完整 |
| Phase 6 | 3 | 60+ | ✅ 完整 |
| Phase 7 | 4 | 71 | ✅ 完整 |
| Token 优化 | 3 | 58 | ✅ 完整 |
| Phase 8 | 1 | - | ⚠️ 框架 |

---

## 任务完成报告制度

每次完成一个任务后，必须生成报告：

- **路径：** `report_history/`
  - `report_history/claude_report/` - Claude 任务报告
  - `report_history/cursor_report/` - Cursor 任务报告
- **格式：** `task_{YYYYMMDD}_{序号}_{任务摘要}.md`

---

## 文档索引

| 文档 | 路径 | 用途 |
|------|------|------|
| 全局索引 | `INDEX.md` | 所有任务的执行参照 |
| 完整规划 | `requirement/cursor第一次规划/虾宝自我进化系统完整规划.md` | Phase 规划参考 |
| 技术设计 | `requirement/cursor第一次规划/技术设计文档.md` | 架构设计参考 |
| Token 优化 | `requirement/cursor第二次规划/Token压缩机制优化规划.md` | Token 优化参考 |
| Phase 8 实现 | `requirement/claude第一次规划/Phase8自主探索模块实现方案.md` | Phase 8 参考 |
| 记忆优化 | `requirement/claude第一次规划/记忆力机制优化方案.md` | 记忆系统参考 |
| core 重构 | `requirement/claude第一次规划/core目录结构重组方案.md` | 目录重构参考 |

---

## 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v4.8 | 2026-04-18 | PromptManager 重构、Skill 系统完成、核心修复 |
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
