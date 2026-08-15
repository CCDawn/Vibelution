# Core Orchestration

Agent 单轮编排的现有 SSOT。新逻辑优先扩这里的模块，不要在 `agent.py` 再堆业务，也不要新建第二套 pipeline。

`agent.py` 在仓库根，只做 composition root 与兼容门面。本包不得反向 import `agent.py`；仅 `turn_runner.default_agent_factory()` 可惰性构造 Agent。

## 已有 owner

| 模块 | 职责 |
| --- | --- |
| `turn_runner.py` | Web/control-plane 单 Turn 入口与 Agent 构造适配 |
| `turn_runtime.py` | Turn runtime request/context |
| `turn_outcome.py` | 停机、生命周期出口与结果分类 |
| `tool_lifecycle.py` | 工具执行、结果回写与生命周期动作 |
| `round_state.py` | 单轮局部状态；卡住信号读 `runtime_telemetry()` |
| `response_processor.py` | LLM 响应协议处理 |
| `context_engine.py` | 长生命周期上下文与 Prompt segment 组装 |
| `agent_modes.py` | `AgentMode` / `ModePolicy` |
| `runtime_goal.py` | 运行目标包 |

## Gate 1 候选抽取

| 模块 | 职责 | 生产入口 |
| --- | --- | --- |
| `agent_runtime_bindings.py` | 环境绑定、目标归一、场景事件、stall 阈值 | `agent.py` 导入并转发 |
| `turn_carryover.py` | 转轮消息序列化 / 反序列化 | `SelfEvolvingAgent` 的 serialize/deserialize wrapper |
| `turn_compression.py` | 上下文压缩与账本检查点 | `SelfEvolvingAgent._compress_messages` |
| `turn_diagnostics.py` | 重试广播、cache 诊断、invocation context、stall 报告 | `SelfEvolvingAgent` 对应 wrapper |
| `tool_authorization_binding.py` | 运行时身份绑定、可见工具物化、隐藏工具文案、重启护栏 | `SelfEvolvingAgent` 对应 wrapper；policy 仍在 `core.authorization` |

硬约束：

- 卡住信号只读 `RoundStateController.runtime_telemetry()`，忽略 `telemetry_snapshot`。
- monkeypatch 敏感依赖在调用时解析，不写进默认参数。
- `agent.py` wrapper 只在测试仍 patch `agent.*` 时保留，并写删除信号。
