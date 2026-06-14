# 测试脚本使用说明

> 本文档描述 Vibelution 项目测试脚本的结构、使用方法和规范。

---

## 一、测试目录结构

```
tests/
├── __init__.py                    # 测试包标识
├── conftest.py                    # pytest 配置和共享 fixtures
├── test_runner.py                 # 统一测试运行器（pytest 封装）
├── prompt_debugger.py             # 提示词打靶测试（工具变更时必用）
├── simulate_lifecycle.py          # 沙盘生命周期独立验证脚本
│
├── [pytest 测试文件]              # 以 test_*.py 为准，按功能面持续增长
│   ├── test_code_analysis_tools.py # 代码分析工具
│   ├── test_event_bus.py          # 事件总线
│   ├── test_key_info_extractor.py # 关键信息提取
│   ├── test_memory.py             # 记忆系统
│   ├── test_memory_tools.py       # 记忆工具
│   ├── test_model_discovery.py    # 模型发现
│   ├── test_prompt_manager.py     # Prompt 管理器
│   ├── test_rebirth_tools.py      # 重启工具
│   ├── test_restarter.py          # 重启守护进程
│   ├── test_search_tools.py       # 搜索工具
│   ├── test_security.py            # 安全验证
│   ├── test_shell_tools.py        # Shell 工具
│   ├── test_state.py               # 状态管理器
│   ├── test_task_planner.py        # 任务规划器
│   ├── test_token_manager.py       # Token 管理器
│   ├── test_tool_executor.py      # 工具执行器
│   ├── test_tool_registry.py      # 工具注册表
│   ├── test_tool_result.py        # 工具结果处理
│   ├── test_tool_tracker.py       # 工具追踪
│   ├── test_workspace_manager.py  # 工作区管理器
│   └── test_event_bus.py           # 事件总线
```

---

## 二、测试分组

### 2.1 按被测模块分组

| 测试文件 | 被测模块 | 分类 |
|---------|---------|------|
| `test_memory_tools.py` | `tools/memory_tools.py` | tools/ |
| `test_shell_tools.py` | `tools/shell_tools.py` | tools/ |
| `test_search_tools.py` | `tools/search_tools.py` | tools/ |
| `test_code_analysis_tools.py` | `tools/code_analysis_tools.py` | tools/ |
| `test_rebirth_tools.py` | `tools/rebirth_tools.py` | tools/ |
| `test_token_manager.py` | `tools/token_manager.py` | tools/ |
| `test_key_info_extractor.py` | `tools/key_info_extractor.py` | tools/ |
| `test_task_planner.py` | `core/task_planner.py` | core/ |
| `test_prompt_manager.py` | `core/prompt_manager/prompt_manager.py` | core/prompt_manager/ |
| `test_tool_executor.py` | `core/infrastructure/tool_executor.py` | core/infrastructure/ |
| `test_tool_registry.py` | `core/infrastructure/tool_registry.py` | core/infrastructure/ |
| `test_security.py` | `core/infrastructure/security.py` | core/infrastructure/ |
| `test_model_discovery.py` | `core/infrastructure/model_discovery.py` | core/infrastructure/ |
| `test_tool_tracker.py` | `core/logging/tool_tracker.py` | core/logging/ |
| `test_restarter.py` | `core/restarter_manager/restarter.py` | core/restarter_manager/ |
| `test_workspace_manager.py` | `core/infrastructure/workspace_manager.py` | core/infrastructure/ |
| `test_state.py` | `core/infrastructure/state.py` | core/infrastructure/ |
| `test_event_bus.py` | `core/infrastructure/event_bus.py` | core/infrastructure/ |
| `test_tool_result.py` | `core/infrastructure/tool_result.py` | core/infrastructure/ |
| `test_memory.py` | 跨模块（记忆系统集成） | 集成测试 |
| `test_web_app.py` | Web API 与工作台聚合路由 | web/ |
| `test_web_git_routes.py` | Git 页面相关 API 路由 | web/git |

---

## 三、使用方法

### 3.1 使用 pytest（推荐）

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定模块测试
pytest tests/test_memory.py -v

# 按关键字筛选
pytest tests/test_code_analysis_tools.py -v -k "diff"

# 查看当前 pytest 文件数量
python -c "from pathlib import Path; print(len(list(Path('tests').glob('test_*.py'))))"

# 遇错即停
pytest tests/ -v -x
```

### 3.2 使用 test_runner.py

```bash
# 运行所有测试（简洁模式）
python tests/test_runner.py

# 详细输出
python tests/test_runner.py --verbose

# 跳过慢速测试
python tests/test_runner.py --fast

# 使用进程级并行执行可并行测试文件
python tests/test_runner.py --parallel --workers 4

# 快速并行：跳过 slow 和 serial 标记
python tests/test_runner.py --fast --parallel --workers 4
```

### 3.3 进程级并行策略

Vibelution 支持通过 `pytest-xdist` 做进程级并行，但默认测试命令仍保持串行，避免全局状态、真实工作区、端口和后台进程类测试被误并发执行。

推荐入口：

```bash
# 直接使用 pytest-xdist
pytest tests/ -n 4 --dist loadfile -m "not serial"

# 使用项目 test runner
python tests/test_runner.py --parallel --workers 4
```

并行策略：

- 优先使用 `--dist loadfile`，按测试文件分发，降低同一文件内共享 fixture/全局状态的交叉风险。
- 在并行模式下排除 `serial` 标记；涉及真实进程、端口、共享全局状态、真实 workspace、外部 config 或 Launcher/runtime 生命周期的测试应标记为 `serial`。
- 不把 `-n auto` 作为默认；本地开发建议先用 `--workers 2` 或 `--workers 4`，再根据耗时和稳定性调整。
- 广义全量回归仍应保留串行兜底；并行适合日常快速反馈和已标注边界的稳定子集。

### 3.4 使用影响面测试选择器

`tests/test_matrix.yaml` 记录高频改动范围到验证命令的映射，`tests/select_tests.py` 根据变更文件输出建议测试命令。它只做选择和解释，不自动执行命令，也不改变默认 pytest 串行策略。

```bash
# 手动输入变更文件并查看结构化结果
python tests/select_tests.py --changed-file core/web/services/session_service.py --json

# 从 git diff 读取变更文件
python tests/select_tests.py --from-git HEAD~1

# 只输出命令，便于复制到当前 worktree 执行
python tests/select_tests.py --from-git main --commands-only
```

使用原则：

- 先运行 selector 给出的聚焦命令，再按风险扩大到相关文件或全量回归。
- selector 输出的是建议，不替代工程判断；涉及 Launcher、真实进程、外部 config、Git 副作用或共享 workspace 的测试仍按 `serial` 边界处理。
- 没有规则命中时，默认输出轻量 runner smoke、collect-only 和 `git diff --check`，帮助 Agent 先判断测试集合是否可收集。
- 新增高频模块或拆分测试文件后，同步补充 `tests/test_matrix.yaml` 和 `tests/test_select_tests.py`。

### 3.5 使用 prompt_debugger.py（工具变更时必用）

验证模型能够正确理解并调用工具。**每次添加或修改工具后必须运行**。

```bash
# 测试指定工具（如 shell_tools, memory_tools, search_tools）
python tests/prompt_debugger.py --tool shell_tools

# 运行内置测试用例集
python tests/prompt_debugger.py --suite

# 交互模式
python tests/prompt_debugger.py "你的测试 prompt"
```

验证标准：
- 模型能识别工具名称和用途
- 模型能正确解析工具参数
- 模型在适当场景下主动调用该工具
- 无幻觉调用（不该调用时不调用）

### 3.5 独立脚本 simulate_lifecycle.py

不调用大模型，验证生命周期防断裂加固：

```bash
python tests/simulate_lifecycle.py
```

测试内容：
1. CLI 命令错误检测
2. 记忆保存功能
3. 重启前强制快照
4. 数据库写入
5. workspace 结构完整性

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

## 五、测试框架组件

| 组件 | 职责 | 调用场景 |
|------|------|---------|
| `prompt_debugger.py` | 提示词打靶测试：验证模型对工具的理解和调用 | **添加/修改工具时必用** |
| `test_runner.py` | 单元/集成测试运行器：验证代码正确性 | 日常开发、提交前 |
| `simulate_lifecycle.py` | 生命周期验证：不调用大模型，验证防断裂机制 | 重启前必检 |
| `conftest.py` | pytest 配置：单例重置、隔离工作空间、共享 fixtures | pytest 自动加载 |
| `test_*.py` | pytest 测试文件集合：覆盖核心、工具、Web、进化、运行时和配置等模块 | 日常开发、CI |

---

## 六、测试覆盖率目标

| 模块 | 目标覆盖率 |
|------|-----------|
| core/infrastructure/ | ≥80% |
| core/orchestration/ | ≥80% |
| core/prompt_manager/ | ≥80% |
| core/restarter_manager/ | ≥80% |
| tools/ | ≥80% |
