# Infrastructure Module (Phase 1-2)

**基础设施模块** - 为 Agent 提供底层基础设施支持

## Modules

| File | Description |
|------|-------------|
| `event_bus.py` | 事件总线，用于模块间通信 |
| `state.py` | 状态管理，Agent 状态机 |
| `tool_executor.py` | 工具执行器 |
| `tool_registry.py` | 工具注册表 |
| `security.py` | 安全验证模块 |
| `model_discovery.py` | 模型发现与服务 |
| `workspace_manager.py` | 工作区管理 |
| `exception_handler.py` | 异常处理器 |

## Usage

```python
from core.infrastructure.event_bus import EventBus, get_event_bus
from core.infrastructure.state import AgentState, get_state_manager
from core.infrastructure.tool_executor import get_tool_executor
from core.infrastructure.tool_registry import get_tool_registry
```

## Key Classes

- `EventBus` - 发布/订阅事件总线
- `AgentState` - Agent 状态枚举
- `ToolExecutor` - 统一工具执行入口
- `ToolRegistry` - 工具元数据注册表
- `SecurityValidator` - 安全验证
- `ModelDiscovery` - 模型服务发现
- `WorkspaceManager` - 文件系统工作区管理
