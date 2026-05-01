# Vibelution - 全局索引

**版本：** v7.0
**日期：** 2026-04-30
**用途：** AI Agent 执行任务的执行参照索引

---

## 项目结构

```
self-evo-baby/
├── agent.py                    # Agent 主程序 (~620行，Phase 3-7 代码已移除)
├── config/                     # 配置模块
│   ├── __init__.py
│   ├── models.py
│   ├── providers.py
│   └── settings.py
├── config.toml                 # TOML 配置文件
├── core/                       # 核心模块（按功能分类）
│   ├── infrastructure/         # 基础设施
│   │   ├── tool_executor.py
│   │   ├── tool_registry.py
│   │   ├── state.py
│   │   ├── event_bus.py
│   │   ├── security.py
│   │   ├── model_discovery.py
│   │   ├── workspace_manager.py
│   │   ├── tool_result.py
│   │   └── agent_session.py
│   ├── ui/                     # 用户界面
│   │   ├── ascii_art.py
│   │   ├── cli_ui.py
│   │   ├── interactive_cli.py
│   │   ├── token_display.py
│   │   └── theme.py
│   ├── logging/                # 日志系统
│   │   ├── logger.py
│   │   ├── unified_logger.py
│   │   ├── transcript_logger.py
│   │   ├── tool_tracker.py
│   │   └── setup.py
│   ├── pet_system/             # 宠物系统
│   │   ├── pet_system.py
│   │   ├── models.py
│   │   ├── subsystems/
│   │   └── utils/
│   ├── core_prompt/            # 核心提示词
│   │   ├── SOUL.md
│   │   └── AGENTS.md
│   ├── prompt_manager/         # 提示词管理
│   │   ├── prompt_manager.py
│   │   ├── prompt_builder.py
│   │   ├── task_analyzer.py
│   │   └── codebase_map_builder.py
│   └── restarter_manager/      # 重启管理
│       └── restarter.py
├── tools/                      # 工具集
│   ├── Key_Tools.py
│   ├── shell_tools.py
│   ├── memory_tools.py
│   ├── search_tools.py
│   ├── rebirth_tools.py
│   ├── token_manager.py
│   ├── web_search_tool.py
│   └── code_analysis_tools.py
├── tests/                      # 测试套件
├── workspace/                   # 工作区
│   ├── prompts/
│   ├── memory/archives/
│   └── skills/
├── requirement/                # 规划文档
│   └── SPEC/SPEC_Agent.md     # 开发流程规范 v4.0
└── report_history/             # 任务报告
```

---

## Phase 状态

| Phase | 内容 | 状态 | 说明 |
|-------|------|------|------|
| Phase 1-2 | 基础设施 | ✅ 完成 | core/infrastructure/、core/logging/、core/ui/、工具集 |
| Phase 3 | 进化能力 | ❌ 待开发 | 下一开发目标 |

> 下一开发目标：**Phase 3 进化引擎**

---

## 开发流程

> 参考：[`requirement/SPEC/SPEC_Agent.md`](requirement/SPEC/SPEC_Agent.md) v4.0

每次 Agent 苏醒后执行（不分任务大小）：

```
[感知] git diff --stat 上次变更
[感知] 读取 INDEX.md 上次修改日志，检查 [流程优化] 标记
[决策] Core First 检查
[执行] 修改代码
[验证] py_compile + pytest + prompt_debugger
[分析] 流程自分析（问题捕获→分类→优化）
[记录] INDEX.md 修改日志追加
[交付] git commit
```

---

## 测试

```bash
# 语法检查
python -m py_compile <修改的文件>.py

# 运行测试
pytest tests/ -v -x

# 提示词打靶
python tests/prompt_debugger.py --suite
```

---

## 配置系统

```python
from config import Config, get_config
config = get_config()
```

| 配置节 | 说明 |
|--------|------|
| `[llm]` | provider, model_name, temperature |
| `[agent]` | name, awake_interval, max_iterations |
| `[context_compression]` | 压缩阈值、摘要字数 |
| `[security]` | 目录限制、危险命令 |

---

## 提示词系统

```python
from core.prompt_manager import get_prompt_manager
pm = get_prompt_manager()
system_prompt, _ = pm.build()
```

| 文件 | 职责 |
|------|------|
| `core/core_prompt/SOUL.md` | 身份铁律 |
| `core/core_prompt/AGENTS.md` | SOP 操作规范 |
| `requirement/SPEC/SPEC_Agent.md` | 开发流程规范 |
| `workspace/prompts/DYNAMIC.md` | 本世代任务 |

---

## 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块文件 | snake_case | `evolution_engine.py` |
| Python 类 | PascalCase | `EvolutionEngine` |
| 公开函数 | snake_case | `get_evolution_status` |
| 测试文件 | `test_*.py` | `test_evolution_engine.py` |

---

## 修改日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v7.0 | 2026-04-30 | **Phase 3-8 重启**：删除 core/learning/、core/decision/、core/orchestration/ 三个目录；删除唯一死引用 `core/autonomous/`；清理 agent.py 中所有 Phase 5-7 代码（导入、`__init__`、`_init_llm`、`_init_token_compressor`、`think_and_act` 决策/解析逻辑、`_execute_tool` 策略选择、`_optimize_tool_order` 方法、`run_loop` AgentLifecycle）；删除 13 个对应测试文件；INDEX.md 重写为实际状态 |
| v6.3 | 2026-04-24 | 任务管理工具化 |
| v6.2 | 2026-04-24 | 测试整理 |
| v6.1 | 2026-04-20 | UI 修复 |
| v6.0 | 2026-04-19 | 全面精简 |