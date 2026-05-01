# 测试脚本使用说明

> 本文档描述 Vibelution 项目测试脚本的结构、使用方法和规范。

---

## 一、测试目录结构

```
tests/
├── __init__.py                    # 测试包标识
├── conftest.py                    # pytest 配置和共享 fixtures
├── test_runner.py                 # 统一测试运行器（pytest 封装）
├── prompt_shooting.py             # 提示词打靶测试（工具变更时必用）
├── simulate_lifecycle.py          # 沙盘生命周期独立验证脚本
│
├── [pytest 测试文件]              # 23 个，对应实际模块
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
| `test_task_planner.py` | `core/task_planner.py` | core/ || `test_prompt_manager.py` | `core/prompt_manager/prompt_manager.py` | core/prompt_manager/ |
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
```

### 3.3 使用 prompt_shooting.py（工具变更时必用）

验证模型能够正确理解并调用工具。**每次添加或修改工具后必须运行**。

```bash
# 测试指定工具（如 shell_tools, memory_tools, search_tools）
python tests/prompt_shooting.py --tool shell_tools

# 运行内置测试用例集
python tests/prompt_shooting.py --suite

# 交互模式
python tests/prompt_shooting.py "你的测试 prompt"
```

验证标准：
- 模型能识别工具名称和用途
- 模型能正确解析工具参数
- 模型在适当场景下主动调用该工具
- 无幻觉调用（不该调用时不调用）

### 3.4 独立脚本 simulate_lifecycle.py

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
| `prompt_shooting.py` | 提示词打靶测试：验证模型对工具的理解和调用 | **添加/修改工具时必用** |
| `test_runner.py` | 单元/集成测试运行器：验证代码正确性 | 日常开发、提交前 |
| `simulate_lifecycle.py` | 生命周期验证：不调用大模型，验证防断裂机制 | 重启前必检 |
| `conftest.py` | pytest 配置：单例重置、隔离工作空间、共享 fixtures | pytest 自动加载 |
| `test_*.py` | 23 个 pytest 测试文件：覆盖各模块 | 日常开发、CI |

---

## 六、测试覆盖率目标

| 模块 | 目标覆盖率 |
|------|-----------|
| core/infrastructure/ | ≥80% |
| core/orchestration/ | ≥80% |
| core/prompt_manager/ | ≥80% |
| core/restarter_manager/ | ≥80% |
| tools/ | ≥80% |