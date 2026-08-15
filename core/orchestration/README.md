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
| `turn_message_assembly.py` | 单 Turn 消息排序：seed normalize/sanitize、static/volatile 插入 | `SelfEvolvingAgent` 对应 wrapper；Prompt 策略仍在 `prompt_manager` / `context_engine` |
| `turn_llm_adapter.py` | Agent 主/备路由 attempt loop；UI/scene 由注入 observer 接收 | `SelfEvolvingAgent._invoke_llm` wrapper；调用/recovery/routing 仍在 `core.llm` |

硬约束：

- 卡住信号只读 `RoundStateController.runtime_telemetry()`，忽略 `telemetry_snapshot`。
- monkeypatch 敏感依赖在调用时解析，不写进默认参数。
- `agent.py` wrapper 只在测试仍 patch `agent.*` 时保留，并写删除信号。

## Gate 2-4：内部 Turn coordinator

**裁决：`DO_NOT_CREATE`。禁止新增 `turn_pipeline.py` 或同职责的第二套内部编排器。**

Gate 2 切片后，单轮链路已经是：

```text
TurnRunner (web/control-plane 入口)
  -> SelfEvolvingAgent.think_and_act / run_single_turn / _run_orchestrated_turn
       -> turn_message_assembly + prompt_manager / context_engine
       -> turn_llm_adapter -> core.llm.invocation / recovery
       -> TurnOutcomeController.decide_llm_iteration / finalize_round
       -> ToolLifecycleBridge.execute_tools
       -> RoundStateController.runtime_telemetry()
```

创建 coordinator 的四项必要条件（须全部成立）对照：

| # | 条件 | 结论 |
| --- | --- | --- |
| 1 | 剩余逻辑仍同时编排至少三个稳定 owner | **成立**。`_run_orchestrated_turn` 仍顺序调用 message assembly、LLM adapter、`TurnOutcomeController`、`ToolLifecycleBridge`、`RoundStateController`、`ResponseProcessor`。 |
| 2 | 能用 typed state/result 表达，不需要反射写回大量 `agent._private` 字段 | **不成立**。该循环写回 `_active_goal`、`_last_turn_metadata`、`_last_llm_error_*`、`_cached_system_prompt`、压缩计数、`_chat_provider_replay_state`、`_pending_lifecycle_action`、runtime state memory 等实例字段；抽出后只能变成伪装成 DTO 的 Agent 状态袋。 |
| 3 | 不重复 `TurnRunner` 入口、`TurnOutcomeController` 出口或 `ToolLifecycleBridge` 执行 | **不成立**。外部入口与停机/工具执行已有 SSOT；再包一层只会成为第二 pipeline。 |
| 4 | 独立测试能证明 coordinator 状态转换，而非代理转发 | **不成立**。现有证明面是 `tests/test_agent_protocol.py` 对 `_invoke_llm` / `_run_orchestrated_turn` 的行为测试；新模块测试会退化成转发断言。 |

因此保留 `agent.py` 的 `_run_orchestrated_turn` 作为 composition root 的高层方法。后续只允许继续把**单一职责**切片进现有 owner，不允许为减 LOC 新建 coordinator。

## Compatibility wrapper ledger

| wrapper | 生产调用者 | 测试/删除信号 |
| --- | --- | --- |
| `_record_llm_route_success` / `_record_agent_tool_surface_event` | LLM adapter / tool surface | 测试仍 patch `agent._record_agent_scene_event` |
| `_resolve_tool_authorization` / `_materialize_authorized_tools` / `_is_tool_visible_to_current_agent` / `_hidden_tool_call_message` | `__init__`、session reuse、tool path | `tests/test_tool_authorization_visibility.py` |
| `_normalize_seeded_tool_calls` / `_sanitize_seeded_chat_content` / `_insert_pending_volatile_context_messages` | `seed_chat_history`、volatile insert | `tests/test_turn_message_assembly.py`、protocol seeded/volatile 用例 |
| `_invoke_llm` | `_run_orchestrated_turn` | `tests/test_agent_protocol.py` 的 `test_invoke_llm_*`；patch `agent.plan_llm_recovery` / `get_ui` / invocation helpers |
| `_guard_tool_execution` | `ToolLifecycleBridge` 构造绑定 | 测试仍把该方法传给 bridge |

这些 wrapper 在对应测试改走新模块公共 API 之前不得删除。
