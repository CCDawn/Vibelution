# 虾宝自我进化系统 - 全局索引

**版本：** v6.0
**日期：** 2026-04-19
**用途：** AI Agent 执行任务的执行参照索引

---

## 执行前必读

> **⚠️ 每次执行任务前，必须完成以下检查**

### 开发前检查清单

```
[ ] 1. 理解需求核心目标
[ ] 2. 确定涉及模块（core/、tools/、config/）
[ ] 3. 检查 INDEX.md 中相关模块状态（✅完整/⚠️框架/❌未实现）
[ ] 4. Core First 检查：在 core/ 搜索是否有相似功能
[ ] 5. 如涉及提示词 → 必须运行提示词打靶测试
[ ] 6. 确认无阻塞依赖
```

### INDEX.md 联动规则

> **⚠️ 强制要求**：每次文件更新必须同步 INDEX.md

| 更新类型 | 必须更新的章节 |
|----------|---------------|
| 新增/修改 core 模块 | "核心模块状态表"、"项目结构"、"修改日志" |
| 新增测试文件 | "测试统计" 表格 |
| agent.py 重构 | "待重构" 章节 |
| Phase 完成 | "Phase 状态" 表格、"实施路线图" |
| 新增规划/报告 | 对应索引表格 |

---

## 项目结构

```
self-evo-baby/
├── agent.py                    # Agent 主程序 (~1070行)
│                                # 职责：运行循环、LLM调用、状态管理
├── config/                     # 配置模块
│   ├── __init__.py            # 导出所有配置
│   ├── adapters.py            # LLM Provider 适配器（MiniMax）
│   ├── models.py              # Pydantic 数据模型
│   ├── providers.py           # LLM 模型预设
│   └── settings.py            # 配置加载
├── config.toml               # TOML 配置文件
├── restarter.py              # 重启守护进程
├── core/                      # 核心模块（按功能分类）
│   ├── infrastructure/         # 基础设施
│   │   ├── tool_executor.py  # ✅ 工具执行
│   │   ├── tool_registry.py  # ✅ 工具注册表
│   │   ├── state.py          # ✅ 状态管理
│   │   ├── event_bus.py      # ✅ 事件总线
│   │   ├── security.py        # ✅ 安全模块
│   │   ├── model_discovery.py # ✅ 模型发现
│   │   ├── workspace_manager.py # ✅ 工作区管理
│   │   ├── tool_result.py    # ✅ 工具结果处理
│   │   └── agent_session.py  # ✅ Session状态管理
│   ├── orchestration/         # 编排模块
│   │   ├── llm_orchestrator.py # ✅ LLM调用
│   │   ├── llm_factory.py     # ✅ LLM工厂
│   │   ├── memory_manager.py   # ✅ 记忆管理
│   │   ├── context_compressor.py # ✅ 上下文压缩
│   │   ├── agent_lifecycle.py  # ✅ 生命周期管理
│   │   ├── task_planner.py     # ✅ 任务规划
│   │   ├── compression_persister.py # ✅ 压缩持久化
│   │   ├── semantic_retriever.py   # ✅ 语义检索
│   │   ├── forgetting_engine.py    # ✅ 遗忘引擎
│   │   └── response_parser.py      # ✅ LLM响应解析
│   ├── decision/              # 决策模块
│   │   ├── decision_tree.py      # ✅ 决策树
│   │   ├── priority_optimizer.py # ✅ 优先级优化
│   │   ├── strategy_selector.py   # ✅ 策略选择
│   │   └── task_classifier.py    # ✅ 任务分类
│   ├── evolution/             # 进化引擎
│   │   ├── evolution_engine.py    # ✅ 进化引擎
│   │   ├── evolution_gate.py      # ✅ 进化门控
│   │   ├── self_analyzer.py       # ✅ 自我分析
│   │   ├── refactoring_planner.py # ✅ 重构规划
│   │   ├── code_generator.py      # ✅ 代码生成
│   │   └── self_refactoror.py    # ⚠️ 自我重构
│   ├── knowledge/              # 知识系统
│   │   ├── knowledge_graph.py     # ✅ 知识图谱
│   │   ├── codebase_analyzer.py   # ✅ 代码分析
│   │   └── semantic_search.py    # ✅ 语义搜索
│   ├── learning/              # 学习系统
│   │   ├── learning_engine.py     # ✅ 学习引擎
│   │   ├── feedback_loop.py       # ✅ 反馈循环
│   │   ├── insight_tracker.py     # ✅ 洞察追踪
│   │   └── strategy_learner.py    # ✅ 策略学习
│   ├── autonomous/            # 自主探索
│   │   ├── autonomous_mode.py     # ⚠️ 自主模式
│   │   └── goal_generator.py      # ⚠️ 目标生成
│   ├── ecosystem/             # 工具生态
│   │   ├── tool_ecosystem.py    # ✅ 工具生态
│   │   ├── skill_registry.py    # ✅ Skill注册表
│   │   ├── skill_loader.py      # ✅ Skill加载器
│   │   ├── skill_tools.py       # ✅ Skill管理工具
│   │   └── restarter.py         # ✅ 重启管理
│   ├── capabilities/          # 能力系统
│   │   ├── prompt_manager.py    # ✅ 提示词管理
│   │   ├── task_analyzer.py     # ✅ 任务分析
│   │   ├── task_manager.py      # ✅ 任务管理
│   │   ├── prompt_builder.py    # ✅ 提示词构建
│   │   └── codebase_map_builder.py # ✅ 代码库地图
│   ├── ui/                    # 用户界面
│   │   ├── ascii_art.py        # ✅ ASCII艺术
│   │   ├── cli_ui.py           # ✅ CLI界面
│   │   ├── interactive_cli.py  # ✅ 交互CLI
│   │   ├── token_display.py    # ✅ Token显示
│   │   └── theme.py           # ⚠️ 主题
│   ├── logging/               # 日志系统
│   │   ├── logger.py          # ✅ 调试日志
│   │   ├── unified_logger.py   # ✅ 统一日志
│   │   ├── transcript_logger.py # ✅ 转录日志
│   │   ├── tool_tracker.py    # ✅ 工具追踪
│   │   └── setup.py           # ✅ 日志配置
│   ├── pet_system/           # 宠物系统
│   │   ├── pet_system.py      # ✅ 宠物核心
│   │   └── subsystems/         # ✅ 10大子系统
│   └── core_prompt/          # 核心提示词
│       ├── SOUL.md           # 使命（只读）
│       └── AGENTS.md         # 规范（只读）
├── tools/                     # 工具集
│   ├── Key_Tools.py         # ✅ 工具注册（29个）
│   ├── shell_tools.py        # ✅ Shell工具（12个）
│   ├── memory_tools.py      # ✅ 记忆工具（15个）
│   ├── search_tools.py       # ✅ 搜索工具（5个）
│   ├── rebirth_tools.py      # ✅ 重启工具（6个）
│   ├── token_manager.py      # ✅ Token管理
│   ├── compression_*.py     # ✅ 压缩相关
│   └── code_analysis_tools.py # ✅ 代码分析
├── tests/                     # 测试套件（46个文件）
├── workspace/                  # 工作区
│   ├── prompts/              # 动态提示词
│   ├── memory/archives/      # 记忆存档
│   └── skills/              # Agent自扩展Skill
├── requirement/               # 规划文档
└── report_history/           # 任务报告
```

---

## Phase 状态

| Phase | 内容 | 状态 | 测试数 | 说明 |
|-------|------|------|--------|------|
| Phase 1-2 | 基础设施 | ✅ 完成 | 150+ | 工具、状态、事件、安全 |
| Phase 3 | 进化能力 | ✅ 完成 | 50+ | 8阶段进化引擎 |
| Phase 4 | 知识系统 | ✅ 完成 | 70+ | 知识图谱、语义搜索 |
| Phase 5 | 持续学习 | ✅ 完成 | 80+ | 学习引擎、反馈循环 |
| Phase 6 | 自主决策 | ✅ 完成 | 60+ | 决策树、策略选择 |
| Phase 7 | 模块化重构 | ✅ 完成 | 71+ | LLM协调、记忆管理 |
| Phase 8 | 自主探索 | ⚠️ 进行中 | - | 探索引擎、机会发现 |
| Token优化 | 压缩系统 | ✅ 完成 | 58+ | 4级压缩策略 |

---

## 核心模块状态

### ✅ 完整模块（可直接使用）

| 模块 | 文件 | 主要功能 |
|------|------|---------|
| 工具执行 | `core/infrastructure/tool_executor.py` | 注册、超时、重试 |
| 工具注册 | `core/infrastructure/tool_registry.py` | 动态注册、分类、搜索 |
| 状态管理 | `core/infrastructure/state.py` | 单例、线程安全 |
| 事件总线 | `core/infrastructure/event_bus.py` | 发布订阅、通配符 |
| LLM调用 | `core/orchestration/llm_orchestrator.py` | 统一LLM调用 |
| 记忆管理 | `core/orchestration/memory_manager.py` | 三层记忆 |
| 决策树 | `core/decision/decision_tree.py` | 规则决策 |
| 优先级优化 | `core/decision/priority_optimizer.py` | 任务排序 |
| 策略选择 | `core/decision/strategy_selector.py` | 策略切换 |
| 进化引擎 | `core/evolution/evolution_engine.py` | 8阶段进化 |
| 知识图谱 | `core/knowledge/knowledge_graph.py` | 代码实体关系 |
| 学习引擎 | `core/learning/learning_engine.py` | 模式提取 |
| Skill系统 | `core/ecosystem/skill_registry.py` | Agent自扩展 |
| 提示词管理 | `core/capabilities/prompt_manager.py` | 双轨加载 |
| 转录日志 | `core/logging/transcript_logger.py` | 对话记录 |

### ⚠️ 框架模块（需完善）

| 模块 | 文件 | 状态 |
|------|------|------|
| 自我重构 | `core/evolution/self_refactoror.py` | ⚠️ 框架 |
| 自主模式 | `core/autonomous/autonomous_mode.py` | ⚠️ 框架 |
| 目标生成 | `core/autonomous/goal_generator.py` | ⚠️ 框架 |
| 主题系统 | `core/ui/theme.py` | ⚠️ 框架 |

### 🔴 待重构

| 模块 | 现状 | 目标 |
|------|------|------|
| agent.py | ~1007行 (已从1747行精简42%，新增模块化组件) | <500行，Core First架构 |

---

## 开发流程（强制执行）

> **参考**：`requirement/SPEC/SPEC_Agent.md` 完整流程

### 流程步骤

```
1. 需求分析
   └── 检查 core/ 是否有相似功能

2. 设计
   └── 决策：复用 / 扩展 / 新建

3. 实现
   ├── 在 core/ 对应类别添加功能
   ├── 更新 core/{category}/README.md
   └── 更新 core/{category}/__init__.py 导出

4. 测试
   └── pytest tests/ --cov=core --cov=tools --cov-fail-under=80

5. 文档归档
   ├── 规划文档 → requirement/
   ├── 任务报告 → report_history/
   └── 更新 INDEX.md

6. Git提交
```

### Core First 规则

> **⚠️ agent.py 只负责运行循环，禁止堆积功能**

```
[ ] 检查 core/ 是否有相似功能
[ ] 如有，直接导入使用
[ ] 如无，在 core/ 按类别添加
[ ] 禁止在 agent.py 直接实现功能
```

### 质量门控

```
[ ] 命名规范：snake_case 文件/函数，PascalCase 类
[ ] 类型注解：公开函数必须有
[ ] 测试通过：pytest 实际运行
[ ] 覆盖率：新模块 >= 80%
[ ] 提示词变更 → 必须打靶测试
[ ] 无空壳模块
```

---

## 测试执行

### 快速测试命令

```bash
# 所有测试
pytest tests/ -v

# 带覆盖率
pytest tests/ --cov=core --cov=tools --cov-fail-under=80

# Phase 7 模块
pytest tests/test_llm_orchestrator.py tests/test_tool_registry.py \
       tests/test_memory_manager.py tests/test_task_planner.py -v

# Token优化
pytest tests/test_compression*.py -v

# 提示词打靶
python tests/prompt_debugger.py --suite
```

### 测试统计

| Phase | 测试数 | 状态 |
|-------|--------|------|
| Phase 1-2 | 150+ | ✅ |
| Phase 3-4 | 120+ | ✅ |
| Phase 5-6 | 140+ | ✅ |
| Phase 7 | 71+ | ✅ |
| Token优化 | 58+ | ✅ |
| Phase 8 | - | ⚠️ 框架 |
| **提示词打靶** | 12 | ✅ 92% |

### 🔴 提示词打靶（强制）

> **⚠️ 每次修改 SOUL.md / AGENTS.md / 新增工具后必须执行**

```bash
python tests/prompt_debugger.py --suite
```

---

## 文档路径

### 规划文档

| 文档 | 路径 |
|------|------|
| SPEC开发流程 | `requirement/SPEC/SPEC_Agent.md` |
| Phase 8 规划 | `requirement/claude第一次规划/Phase8自主探索模块实现方案.md` |
| agent.py 拆分 | `requirement/claude第一次规划/agent.py模块化拆分方案.md` |
| core 重组 | `requirement/claude第一次规划/core目录结构重组方案.md` |

### 报告目录

```
report_history/
├── claude_report/    # Claude 任务报告
└── cursor_report/   # Cursor 任务报告
```

### 报告命名

```
task_{YYYYMMDD}_{序号}_{任务摘要}.md
```

---

## 配置系统

### config/ 结构

```
config/
├── __init__.py       # 主入口，导出所有
├── adapters.py      # MiniMax 适配器
├── models.py        # Pydantic 模型
├── providers.py     # LLM 预设
└── settings.py      # 配置加载
```

### 常用配置

| 配置节 | 说明 |
|--------|------|
| `[llm]` | provider, model_name, temperature |
| `[llm.local]` | 本地部署 (Ollama/LM Studio/vLLM) |
| `[agent]` | name, awake_interval, max_iterations |
| `[context_compression]` | 压缩阈值、摘要字数 |
| `[security]` | 目录限制、危险命令 |

### 使用方式

```python
from config import get_config, use_model

# 获取配置
config = get_config()

# 切换模型
use_model("gpt-4")
```

---

## 提示词系统

### 双轨加载

```
core/core_prompt/     ← 静态（只读）
├── SOUL.md          # 使命铁律
└── AGENTS.md       # 操作规范

workspace/prompts/   ← 动态（可编辑）
├── IDENTITY.md     # 身份定义
├── USER.md         # 用户信息
├── DYNAMIC.md     # 世代任务
└── STATE_MEMORY.md # 状态记忆
```

### PromptManager API

```python
from core.capabilities.prompt_manager import get_prompt_manager

pm = get_prompt_manager()
system_prompt, _ = pm.build()  # 构建完整提示词

# 动态组件控制
pm.select_components(["SOUL", "AGENTS", "MEMORY"])
```

---

## 命名规范

```python
# 文件
模块文件: snake_case.py    (evolution_engine.py)
测试文件: test_*.py         (test_evolution_engine.py)

# 类
Python类: PascalCase        (EvolutionEngine)
内部类: _PascalCase        (_EvolutionContext)

# 函数
公开函数: snake_case       (get_evolution_status)
私有函数: _snake_case      (_run_phase)

# 常量
SCREAMING_SNAKE_CASE       (MAX_RETRY = 3)

# 测试
测试类: TestClassName      (TestEvolutionEngine)
测试函数: test_功能_场景   (test_run_evolution_success)
```

---

## 实施路线图

```
Phase 1-2: 基础设施 ✅ 工具、状态、事件、安全
Phase 3:   进化能力 ✅ 8阶段进化引擎
Phase 4:   知识系统 ✅ 知识图谱、语义搜索
Phase 5:   持续学习 ✅ 学习引擎、反馈循环
Phase 6:   自主决策 ✅ 决策树、策略选择
Phase 7:   模块化   ✅ LLM协调、记忆管理
Phase 8:   自主探索 ⚠️ 探索引擎（进行中）
Token:     压缩系统 ✅ 4级压缩策略
UI:       形象系统 ✅ 5套ASCII Art
Core:     目录重组 ✅ 13个子目录
Prompt:   双轨加载 ✅ 动态拼装
Skill:    自扩展   ✅ Agent可自建Skill
```

---

## 修改日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v6.0 | 2026-04-19 | **全面精简**：重构为6大章节（结构/Phase/模块/流程/测试/配置），消除重复表格，精简至600行 |
| v5.1 | 2026-04-19 | Core First架构、SPEC_Agent.md升级 |
| v5.0 | 2026-04-18 | 提示词自主动态拼装 |
| v4.x | 2026-04-17 | Phase 8规划、core目录重组 |
