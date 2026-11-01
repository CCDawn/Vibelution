# 模型决策 Stub 约定（assistant / 编排层测试）

> **状态：现行测试规范**（2026-11-01 起）
> 权威实现以 `tests/_support/llm_turn_stub.py` 与下列先例为准；本文件描述取舍标准，不覆盖 [`tests/README.md`](../../tests/README.md) 的命令矩阵，也不取代单条测试自身的契约注释。

## 标准姿势

新写 assistant / 编排层测试时，默认采用「**模型决策用 stub、编排全真跑**」：被替换的只有模型决策点，提交、调度、worker、journal、工具生命周期、writeback 与审批等待全部走真实代码。`tests/_support/llm_turn_stub.py` 头注释（1-9 行）是本约定的原话出处：

> Stubs `invoke_llm_outcome` / `run_streaming_llm_outcome` so the real `submit_session_message` → schedule → turn worker → journal path runs without a live provider. … The real Agent tool lifecycle dispatches it; only the model decision is stubbed.

T5.1 先例的自我描述同样成立（`tests/test_research_workflow_t51_default_composition_chain.py:1-7`）：

> This gate stubs only model decisions; canonical tool calls still pass through the real Agent tool lifecycle and production source-collection writeback tool.

判定口诀：**桩的粒度是「模型这次会决定什么」，不是「系统这段怎么跑」**。工具参数、事件、权威存储（Journal / Ledger / ClaimEvidence）的分支都不许桩。

## 适用面

分支由**工具参数 / 事件**驱动的编排逻辑——文本只当信号、不当产出时，用本模式：

- 研究工作流阶段链与 PendingAction 推进：`tests/test_research_workflow_t51_default_composition_chain.py:343` 的确定性组合门（真 Session / Ledger / writeback，只桩模型决策）。
- PendingAction 续跑权威与失败隔离：`tests/test_agent_turn_completion_continuation.py:48`（fake adapter 端口承载 PendingAction，编排函数 `_wait_with_bounded_turn_continuation` 全真）。
- intent 对齐等确定性 handler：`tests/test_intent_alignment_gate.py:97`（注入 / 透传 / fail-open 分支由 store 与信号决定，不依赖模型语义）。

## 不适用面

以**文本本身为产出**的分支——stub 只能验管道，不能验语义：

- **评审结论与最终答案格式化**：stub 返回固定文本，通过不证明真实模型输出的质量或格式契约；此类语义需确定性 fixture 或人工评审证据，不得以本模式冒充覆盖。
- **legacy handoff observation-only 语义**（`tests/test_assistant_legacy_handoff.py:1`："Legacy observations never admit or replay native work."）：这类分支的正确性恰在「不产出、不采纳」，必须直接对解析与拒绝逻辑断言。
- **Provider 协议、流式事件形状、服务商边界行为**：进程内 stub 看不到 HTTP 边界，走 mock_llm 车道（见下表第三行）。

## 先例锚点

| 锚点 | 层次 | 说明 |
| --- | --- | --- |
| `tests/_support/llm_turn_stub.py:43` | 进程内 LLM stub | `install_fast_stage_writeback_llm_stub(monkeypatch)`；头注释（1-9 行）为本约定原话出处 |
| `tests/test_research_workflow_t51_default_composition_chain.py:343` | 编排全真跑用例 | `test_deterministic_composition_integration_gate`：真 Session / Ledger / writeback，只有模型决策被桩 |
| `tests/e2e/mock_llm/`（`aimock_runtime.py:1`） | HTTP mock 层 | aimock 模拟 LLM 服务商车道（详见 `docs/guides/e2e-mock-llm.md`）；验 provider 协议与流式边界，不桩进程内函数 |

## 取舍基线

- 验「编排分支 + 权威落盘」→ `llm_turn_stub` 模式（本文）。
- 验「模型 / Provider 边界协议」→ `tests/e2e/mock_llm/` HTTP mock 车道。
- 验「文本语义本身」→ 不用 stub 假装验过；换确定性 fixture、格式契约测试或人工评审证据。
