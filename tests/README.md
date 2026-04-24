# 测试脚本使用说明

> 本文档描述 self-evo-baby 项目测试脚本的结构、使用方法和规范。
> 更新日期：2026-04-24

---

## 一、测试目录结构

```
tests/
├── __init__.py                    # 测试包标识
├── conftest.py                    # pytest 配置和共享 fixtures
├── run_tests.py                   # 轻量级测试运行器（不依赖 pytest）
├── test_runner.py                 # 统一测试运行器
├── README.md                      # 本文档
│
├── [活跃测试文件]                 # 27 个，对应实际存在的模块
│   ├── test_compression.py        # Token 压缩测试
│   ├── test_memory.py             # 记忆系统测试
│   ├── test_memory_tools.py       # 记忆工具测试
│   ├── test_memory_manager.py     # 记忆管理器测试
│   ├── test_shell_tools.py        # Shell 工具测试
│   ├── test_search_tools.py       # 搜索工具测试
│   ├── test_code_analysis_tools.py # 代码分析工具测试
│   ├── test_rebirth_tools.py      # 重启工具测试
│   ├── test_token_manager.py      # Token 管理器测试
│   ├── test_tool_executor.py      # 工具执行器测试
│   ├── test_tool_registry.py      # 工具注册表测试
│   ├── test_security.py           # 安全验证测试
│   ├── test_model_discovery.py    # 模型发现测试
│   ├── test_tool_tracker.py       # 工具追踪测试
│   ├── test_task_planner.py       # 任务规划器测试
│   ├── test_llm_orchestrator.py   # LLM 编排器测试
│   ├── test_learning_engine.py    # 学习引擎测试
│   ├── test_feedback_loop.py      # 反馈循环测试
│   ├── test_insight_tracker.py    # 洞察追踪测试
│   ├── test_strategy_learner.py   # 策略学习器测试
│   ├── test_decision_tree.py      # 决策树测试
│   ├── test_strategy_selector.py  # 策略选择器测试
│   ├── test_priority_optimizer.py # 优先级优化器测试
│   ├── test_prompt_manager.py     # Prompt 管理器测试
│   ├── test_compression_strategy.py  # 压缩策略测试
│   ├── test_key_info_extractor.py # 关键信息提取测试
│   └── test_compression_quality.py # 压缩质量测试
│
├── [独立工具脚本]
│   ├── simulate_lifecycle.py      # 生命周期模拟
│   ├── prompt_test_standalone.py  # Prompt 独立测试
│   ├── prompt_debugger.py         # Prompt 调试器
│   └── compression_benchmark.py   # 压缩基准测试
│
├── backups/                       # 已移除的孤立测试文件
│   ├── test_agent_core.py
│   ├── test_codebase_analyzer.py
│   ├── test_knowledge_graph.py
│   ├── test_message_bus.py
│   ├── test_refactoring_planner.py
│   ├── test_evolution_engine.py
│   ├── test_code_generator.py
│   ├── test_autonomous_explorer.py
│   ├── test_self_analyzer.py
│   ├── test_skills_profiler.py
│   ├── test_pattern_library.py
│   ├── test_tool_ecosystem.py
│   ├── test_semantic_search.py
│   ├── test_self_refactoror.py
│   ├── test_task_analyzer.py
│   ├── test_skill_registry.py
│   ├── test_skill_loader.py
│   ├── test_tools_20260403_191656.py
│   └── compression_benchmark_*.py
│
└── test_output.log               # 测试输出日志
```

---

## 二、测试分组

### 2.1 按被测模块分组

| 测试组 | 测试文件 | 被测模块 |
|--------|---------|---------|
| **tools/** | `test_memory_tools.py` | `tools/memory_tools.py` |
| | `test_shell_tools.py` | `tools/shell_tools.py` |
| | `test_search_tools.py` | `tools/search_tools.py` |
| | `test_code_analysis_tools.py` | `tools/code_analysis_tools.py` |
| | `test_rebirth_tools.py` | `tools/rebirth_tools.py` |
| | `test_token_manager.py` | `tools/token_manager.py` |
| | `test_compression.py` | `tools/token_manager.py` |
| | `test_compression_strategy.py` | `tools/compression_strategy.py` |
| | `test_key_info_extractor.py` | `tools/key_info_extractor.py` |
| | `test_compression_quality.py` | `tools/compression_quality.py` |
| **core/orchestration/** | `test_task_planner.py` | `core/orchestration/task_planner.py` |
| | `test_llm_orchestrator.py` | `core/orchestration/llm_orchestrator.py` |
| | `test_memory_manager.py` | `core/orchestration/memory_manager.py` |
| | `test_prompt_manager.py` | `core/prompt_manager/prompt_manager.py` |
| **core/infrastructure/** | `test_tool_executor.py` | `core/infrastructure/tool_executor.py` |
| | `test_tool_registry.py` | `core/infrastructure/tool_registry.py` |
| | `test_security.py` | `core/infrastructure/security.py` |
| | `test_model_discovery.py` | `core/infrastructure/model_discovery.py` |
| | `test_tool_tracker.py` | `core/logging/tool_tracker.py` |
| **core/learning/** | `test_learning_engine.py` | `core/learning/learning_engine.py` |
| | `test_feedback_loop.py` | `core/learning/feedback_loop.py` |
| | `test_insight_tracker.py` | `core/learning/insight_tracker.py` |
| | `test_strategy_learner.py` | `core/learning/strategy_learner.py` |
| **core/decision/** | `test_decision_tree.py` | `core/decision/decision_tree.py` |
| | `test_strategy_selector.py` | `core/decision/strategy_selector.py` |
| | `test_priority_optimizer.py` | `core/decision/priority_optimizer.py` |
| **core/** | `test_memory.py` | `tools/memory_tools.py` (跨模块) |

---

## 三、使用方法

### 3.1 使用 pytest（推荐）

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定模块测试
pytest tests/test_memory.py -v
pytest tests/test_token_manager.py -v

# 运行带覆盖率
pytest tests/ --cov=core --cov=tools --cov-fail-under=80

# 运行特定分组
pytest tests/test_compression*.py -v

# 生成 HTML 覆盖率报告
pytest tests/ --cov=core --cov=tools --cov-report=html
```

### 3.2 使用 run_tests.py（轻量级，不依赖 pytest）

```bash
# 运行所有测试
python tests/run_tests.py

# 详细输出
python tests/run_tests.py -v
```

### 3.3 使用 test_runner.py

```bash
python tests/test_runner.py
```

### 3.4 独立工具脚本

```bash
# 生命周期模拟
python tests/simulate_lifecycle.py

# Prompt 调试
python tests/prompt_debugger.py --suite

# 压缩基准测试
python tests/compression_benchmark.py
```

---

## 四、测试规范

### 4.1 命名规范

- 测试文件：`test_<模块名>.py`
- 测试类：`Test<模块名>`
- 测试方法：`test_<功能名>`

### 4.2 conftest.py 共享 fixtures

```python
@pytest.fixture
def project_root():
    """项目根目录"""
    return Path(__file__).parent.parent

@pytest.fixture
def workspace_dir(project_root):
    """工作区目录"""
    return project_root / "workspace"

@pytest.fixture
def mock_llm():
    """Mock LLM 响应"""
    ...

@pytest.fixture
def test_config():
    """测试配置"""
    ...
```

### 4.3 添加新测试

1. 在 `tests/` 目录创建 `test_<模块名>.py`
2. 使用 pytest 风格编写测试
3. 导入被测模块
4. 运行 `pytest tests/test_<模块名>.py -v` 验证

---

## 五、清理记录

### 5.1 2026-04-24 清理

**移至 backups/ 的孤立测试文件（被测模块不存在）：**

| 文件 | 原引用模块 | 状态 |
|------|-----------|------|
| `test_agent_core.py` | `core/agent_core.py` | 模块不存在 |
| `test_codebase_analyzer.py` | `core/codebase_analyzer.py` | 模块在 `tools/` |
| `test_knowledge_graph.py` | `core/knowledge_graph.py` | 模块不存在 |
| `test_message_bus.py` | `core/message_bus.py` | 模块在 `event_bus.py` |
| `test_refactoring_planner.py` | `core/refactoring_planner.py` | 模块不存在 |
| `test_evolution_engine.py` | `core/evolution_engine.py` | 模块不存在 |
| `test_code_generator.py` | `core/code_generator.py` | 模块不存在 |
| `test_autonomous_explorer.py` | `core/autonomous_explorer.py` | 模块不存在 |
| `test_self_analyzer.py` | `core/self_analyzer.py` | 模块不存在 |
| `test_skills_profiler.py` | `core/skills_profiler.py` | 模块不存在 |
| `test_pattern_library.py` | `core/pattern_library.py` | 模块不存在 |
| `test_tool_ecosystem.py` | `core/tool_ecosystem.py` | 模块不存在 |
| `test_semantic_search.py` | `core/semantic_search.py` | 模块不存在 |
| `test_self_refactoror.py` | `core/self_refactoror.py` | 模块不存在 |
| `test_task_analyzer.py` | `core/task_analyzer.py` | 路径错误（应在 `core/prompt_manager/`） |
| `test_skill_registry.py` | `core/ecosystem/skill_registry` | 目录不存在 |
| `test_skill_loader.py` | `core/ecosystem/skill_loader` | 目录不存在 |

**修复的文件：**
- `run_tests.py` - 移除对不存在的 `test_tools.py` 的引用

**清理后统计：**
- 活跃测试文件：27 个
- 孤立测试文件：17 个（移至 backups/）
- 备份文件：3 个

---

## 六、测试覆盖率目标

| 模块 | 目标覆盖率 |
|------|-----------|
| core/infrastructure/ | ≥80% |
| core/orchestration/ | ≥80% |
| core/learning/ | ≥80% |
| core/decision/ | ≥80% |
| tools/ | ≥80% |

---

*最后更新：2026-04-24*