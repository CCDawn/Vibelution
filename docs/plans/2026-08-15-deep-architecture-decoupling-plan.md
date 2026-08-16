# Vibelution 核心架构深度解耦实施计划

> - **Status**：ACTIVE PLAN / Gate 2 已关闭；Gate 3 Chat Phase F 壳化已在本分支实施，合入后关闭
> - **Plan mode**：TASK_GRAPH（多个 owner、热文件与独立验证契约）
> - **更新时间**：2026-08-16
> - **基线快照**：计划重写时的本地 `main@6aee4045e4e893af6208b043492d35b6d8fa3ef4`（当时 `agent.py` **4,680** 行）。Gate 0 必须刷新为**当前** `HEAD`，禁止把本快照当作长期权威。
> - **Gate 0 刷新**：本地 `main@296f740cae87aac1babbcc7f23e9958540881174`（领先 origin/main 64；领先快照 5 commit）
> - **计划范围**：Agent 单轮编排、Chat Workbench 壳化、FastAPI 响应契约
> - **计划维护 owner**：Gate 0 由 integration owner 认领；当前重写来源为 `codex/deep-architecture-plan-rewrite`
> - **实施 owner**：每个 Gate 启动前通过独立 worktree + claim 明确，不由本计划隐式占有
> - **Supersedes**：本文件 2026-08-15 的“评估草案”版本
> - **权威边界**：本计划低于 `AGENTS.md`、`docs/standards/`、ADR 与模块 README；不成为新的架构规范
> - **关闭条件**：全部 Gate 完成或被新决策取代后，迁入 `docs/archive/` 并更新引用

本次用户请求只覆盖计划重写；本计划本身不构成产品实现授权，也不授权远端 push/PR、发布、破坏性迁移或跨 Gate 的顺手重构。每个实施 Gate 都必须重新完成 BRT、owner、claim、验证与本地合入门。

---

## 1. 决策摘要

原方案方向正确，但不能按“大爆炸拆四个新模块 + 两个硬行数指标 + 一次清空 DTO debt”直接实施。修订后的核心决策如下：

1. **先处理基线和未提交 WIP，再继续抽取。** 未合入文件只能视为候选实现，不能写成“已就绪”。
2. **复用现有 SSOT，不建立第二套编排。** `TurnRunner`、`TurnOutcomeController`、`ToolLifecycleBridge`、`RoundStateController`、`context_engine`、`core.llm` 与 canonical tool authorization 已经拥有明确职责。
3. **按可验证职责切片，不按目标行数搬代码。** LOC 只记录趋势，不是 merge gate。
4. **Chat 沿现有 ownership map 和 Phase F 继续。** 不再创建与 `ConversationView`、`ChatStatusRail`、`ChatSessionWorkbenchShell` 等重复的新组件。
5. **FastAPI 契约按 endpoint family 分批收敛。** 每批保持 wire payload、同步前端 DTO/fixture，并单调降低 debt budget；本计划不承诺一次清空全仓 ledger。
6. **每个热文件 lane 串行实施。** `agent.py` 内各切片不能并行写；`ChatCodingRouteWorkbench.tsx` 必须等待当前 claim 释放或明确交接。

推荐关键路径：

```text
Gate 0 基线/所有权冻结
  ├─> Gate 1 收口当前 Agent 候选抽取
  │     └─> Gate 2 Agent 职责切片（严格串行）
  ├─> Gate 3 Chat Phase F 壳化
  └─> Gate 4 API 契约分批收敛

三个实施 lane 可在 scopes 完全不重叠且 integration owner 明确时并行，
但进入本地 main 的审查、验证与 ff-only merge 必须串行完成。
```

---

## 2. 目标、非目标与成功定义

### 2.1 目标

- `agent.py` 最终只承担 composition root、生命周期入口、必要兼容门面和高层调度，不再拥有授权策略、Prompt 策略、协议调用细节或工具执行细节。
- Agent 单轮链路只有一个可追踪的编排方向；状态输入、状态变更和输出均有显式契约。
- `ChatCodingRouteWorkbench.tsx` 只负责 hook 组合、owner 间 wiring 与 VUI recipe slots，不再持有可独立演化的业务状态或大块 dialog chrome。
- JSON 路由具有显式 Pydantic response contract；SSE/文件等非 JSON 路由显式声明 `response_class`。
- 每个切片都能独立回滚、独立验证，不依赖“大重构完成后再统一修测试”。

### 2.2 非目标

- 不以 `agent.py <= 1,200` 或 Workbench `<= 800` 作为硬验收条件。
- 不为了减 LOC 把逻辑搬进新的巨型 `turn_pipeline.py`、`prompt_assembler.py` 或“组件集合”。
- 不重写 LLM wire protocol、tool authorization policy、Chat URL authority、React Query key、SSE ownership 或 Launcher 生命周期行为。
- 不在 DTO 工作中改变字段名、默认值、错误码、HTTP status、别名、空值或额外字段语义。
- 不为所有抽取组件统一添加 `React.memo` / `useCallback`；优化必须由性能证据驱动。
- 不在本计划内清空 `LEGACY_UNTYPED_ENDPOINT_BUDGETS` 全仓存量。
- 不触碰进程启动、停止、轮询或后台 Git spawn；一旦 DTO lane 需要修改这些行为，立即停止并另立 HIGH_RISK 任务。

### 2.3 成功定义

成功由以下证据共同决定，而不是由单个 LOC 数字决定：

- 每项职责只有一个 owner/SSOT，依赖方向可以从 import 与调用链直接解释。
- 兼容 wrapper 有真实调用者、测试和删除条件；不存在永久的“先留着再说”代理层。
- Agent 的 carryover、cache、retry/fallback、tool authorization、tool lifecycle 与 turn outcome 行为保持一致。
- Chat 的 URL、SSE、query key、lazy boundary、pane persistence 与用户可见交互保持一致。
- API 的 OpenAPI schema 与实际 payload 一致，前端消费方通过类型与 fixture/route test 证明兼容。
- scoped tests、类型检查、contract guards、运行现场和自审均通过后才允许本地合入。

---

## 3. 经核验的基线

以下事实以计划重写时的干净 `main` 为准；Gate 0 必须刷新，禁止把静态数字当作长期权威。

### 3.1 已提交基线

- `agent.py`：**4,680 行**（`git show 6aee4045:agent.py` 的换行计数；Gate 0 刷新后覆盖）。
- `web/src/routes/chat/ChatCodingRouteWorkbench.tsx`：**3,672 行**。
- `core/orchestration/` 已有 **20 个 Python 模块**，包括：
  - `turn_runner.py`：Web/control-plane 的单 Turn 入口与 Agent 构造适配；
  - `turn_runtime.py`：Turn runtime request/context；
  - `turn_outcome.py`：停机、生命周期出口与结果分类；
  - `tool_lifecycle.py`：工具执行、结果回写与生命周期动作；
  - `round_state.py`：单轮局部状态与 `runtime_telemetry()`；
  - `response_processor.py`：LLM 响应协议处理；
  - `context_engine.py`：长生命周期上下文与 Prompt segment 组装边界。
- canonical tool authorization 已在 `core/authorization/tool_authorization_service.py`。
- canonical LLM 调用与协议元数据已在 `core/llm/invocation.py`、`invocation_context.py`、`recovery.py`、`routing.py` 等模块。
- Chat 已有 `ConversationView`、`ChatConversationIndexRail`、`ChatStatusRail`、`ChatSessionWorkspacePanel`、`ChatSessionWorkbenchShell`、`useChatWorkbenchLayout` 等 owner；`README.md` 标记 Phase F 正在进行。

### 3.2 未提交候选 WIP

根 `main` 在计划重写时存在未提交的 Agent 抽取：

- 修改：`agent.py`
- 新增候选：`agent_runtime_bindings.py`、`turn_carryover.py`、`turn_compression.py`、`turn_diagnostics.py`、`core/orchestration/README.md`

该 WIP 中的 `agent.py` 约 **3,743 行**，但它没有形成可复用基线。Gate 0 必须由原 owner 明确选择“提交、移交或废弃”，后续 worktree 不得从 dirty root 静默复制。

已发现的候选缺口必须在 Gate 1 处理：`turn_diagnostics` 查询 `telemetry_snapshot`，而当前 `RoundStateController` 暴露的是 `runtime_telemetry()`；若直接接线，stall telemetry 会静默失效。

根目录中的 `tools/Key_Tools.py`、`docs/guides/agent-dev-roi-backlog.md` 等其他改动不属于本计划，不得吸收到 Agent 解耦提交。

### 3.3 当前红色门禁

`tests/test_full_stack_contract_guards.py` 当前结果为 `1 failed, 2 passed`：

```text
launcher.py: current 36, budget 29
team_workflows/research_runtime.py: current 18, budget 23
```

解释：

- `launcher.py` 的“7”是 **超过 budget 的漂移量**，不是未类型化端点总数。
- `research_runtime.py` 的 budget 已高于实际 current，需要随契约切片降低，不能继续保留陈旧记账。
- 修复方式不是把 `launcher.py` budget 提高到 36，而是至少补齐 7 个未声明契约，使 `current <= 29`，再把 budget 降为该提交后的精确剩余值。门禁只比较个数，不要求还原“历史上是哪 7 个新加的”。
- 该红色基线必须被记录，但不能被其他 Gate 当作本次改动造成的失败。

### 3.4 Gate 0 刷新记录（2026-08-15）

- **HEAD**：`296f740cae87aac1babbcc7f23e9958540881174`。
- **根 `main` dirty**：`agent.py`（工作区 **3,743** 行）、`tools/Key_Tools.py`、`docs/guides/agent-dev-roi-backlog.md`；未跟踪 `core/orchestration/{agent_runtime_bindings,turn_carryover,turn_compression,turn_diagnostics,README}.py|md` 与本计划。
- **inventory**：`projectId=ccdawn-vibelution`，`instanceId=bcabd5ca`。`activePaths.migrated=true`（2026-08-16 T1 apply）；memory/runtime/logs/data 已切至 `%LOCALAPPDATA%\Vibelution\projects\ccdawn-vibelution\...`。legacy 仓库内 `.runtime/`、`logs/`、`.docs/project-memory/` 仍只读保留。
- **active claims（4）**：
  - `claim-7d6aaf7b43f9`（`agents` / A4 bulk HTTP）：含 `tests/test_full_stack_contract_guards.py`，**Gate 4 改 ledger 前必须协调或避开**。
  - `claim-6adab87c134b`（本计划文件）：仅 `docs/plans/2026-08-15-deep-architecture-decoupling-plan.md`。
  - `claim-a081e0c0dc72`（session runtime row IO）：与本计划三 lane 无热文件重叠。
  - `claim-df945888baa6`（`ChatCodingRoute.layout.test.ts`）：短 TTL；Gate 3 验证若改该测试需先看是否仍 active。
- **Chat 热文件**：registry **没有**名为 `chat-workbench-panel-extract` 的 active claim。但 worktree `.worktrees/chat-workbench-panel-extract`（`codex/chat-workbench-panel-extract@75fa2782e`）工作区脏，含 `ChatCodingRouteWorkbench.tsx` 与 4 个未提交抽取文件。**Gate 3 因该 worktree/WIP 阻塞，不因虚构 claim id 阻塞。**
- **`agent.py`**：无 active claim。历史 `blocked` 项（2026-07）已过期，不构成当前占用。
- **WIP 归属裁决（已执行）**：Agent 候选抽取已 **移交** 到 `.worktrees/agent-orchestration-extract`（分支 `codex/agent-orchestration-extract`，基线 `296f740ca`）。根 `main` 的 `agent.py` 已恢复为 HEAD（**4,706** 行）；候选 `agent.py`（**3,743** 行）与 4 个 orchestration 新文件只在该 worktree。`Key_Tools.py` / ROI backlog / 本计划仍留在根工作区，未进入该 lane。Chat 抽取仍归 `.worktrees/chat-workbench-panel-extract` owner 结清后再开 Gate 3。

---

## 4. 目标边界与单向依赖

### 4.1 Agent 编排边界

```text
Web / control plane
        |
        v
core.orchestration.turn_runner        外部单 Turn 入口
        |
        v
agent.py                              composition root + compatibility facade
        |
        +--> core.authorization.*     授权决策 SSOT
        +--> core.prompt_manager.*    Prompt policy / segment contract SSOT
        +--> context_engine           runtime context 组装
        +--> core.llm.*               protocol / invocation / recovery SSOT
        +--> response_processor       响应解析
        +--> tool_lifecycle           工具执行与结果回写
        +--> round_state              单轮局部状态
        +--> turn_outcome             退出与结果
```

硬约束：

- `core/*` 新模块不得反向 import 顶层 `agent.py`；仅允许 `turn_runner.default_agent_factory()` 的现有惰性构造 seam。
- 不新增拥有授权策略的 `ToolGovernor`；Agent 侧最多新增“绑定/适配器”，并调用 canonical authorization service。
- 不新增拥有 Prompt policy 的 `PromptAssembler`；turn-specific message sequencing 可以抽取，但 segment/policy 继续由 `core.prompt_manager` 与 `context_engine` 持有。
- 不复制 `core.llm.invocation`、recovery 或 routing；Agent 侧只编排模型选择、重试尝试与结果映射。
- `turn_pipeline.py` 不是预设产物。只有 Gate 2 前三个切片完成后仍存在可证明的独立协调职责，才允许创建内部 coordinator。

### 4.2 Chat Workbench 边界

```text
ChatCodingRouteWorkbench
  ├─ hooks / owner bindings
  ├─ ChatConversationIndexRail
  ├─ ChatStatusRail
  ├─ ChatSessionWorkspacePanel / ConversationView
  └─ ChatSessionWorkbenchShell
       └─ VSessionWorkbenchPage
            └─ WORKBENCH_LAYOUT_IDS.chat
```

硬约束：

- 当前 URL selection 只由 `useChatRouteSelection.ts` 写入。
- session SSE 只由 `useSessionDetailStream.ts` 持有；group SSE 只由 `useGroupRoomStream.ts` 持有。
- React Query key shape、active selection authority 和 stream connect policy 不得在结构抽取中变化。
- 不新增 `ChatMessageStreamArea`、`ChatAuxiliaryInspectorPanes`、`ChatWorkbenchTopBar` 等平行 owner。
- secondary lazy imports 不得回到 shell 的静态 import 图。
- 任何用户可见控件继续走 VUI product API；不得从 route 直连 `renderers/shadcn/*`。

### 4.3 API 契约边界

```text
route decorator + request/response DTO
        |
        v
service / pack domain behavior
        |
        v
stable wire payload
        |
        +--> OpenAPI schema
        +--> TypeScript DTO/client
        +--> shared fixtures / route tests
```

硬约束：

- route 保持薄层，DTO 不承载业务决策。
- `response_model` 会过滤未声明字段；模型字段、alias、optional/default 与 exclude 语义必须覆盖实际 wire payload。
- SSE 使用 `response_class=StreamingResponse`，不得伪装为 JSON response model。
- Launcher 契约优先复用 `core/launcher/api_contract.py`；不得重建一套同名 payload。
- 每个 endpoint family 独立降低 budget；budget 只能单调不增。

---

## 5. TASK_GRAPH 与 Gate 契约

### Gate 0：冻结、校准与所有权闭合

#### Task G0-1：处理 dirty root 与 active claims

- **Owner/Boundary**：integration owner + 当前 WIP owner；只处理归属与基线，不改产品行为。
- **Dependency**：无。
- **Mode**：SIMPLE。
- **动作**：
  1. 运行 project storage inventory，读取 active memory 路径与 claim registry；
  2. 为 Agent WIP 明确“原 owner 提交 / 显式移交 / 废弃”之一；
  3. 在 claim registry 中查找覆盖 `ChatCodingRouteWorkbench.tsx` 的任意 active claim（历史 id 如 `chat-workbench-panel-extract` 仅作线索，不作为硬编码阻塞条件）；有则等 release/handoff，没有则记录「无热文件冲突」并放行 Gate 3；
  4. 为后续每个 lane 建立独立 `codex/<task-slug>` worktree 和精确 scope；
  5. 记录 `main` SHA、dirty 状态、相关 LOC 与红色 baseline。
- **Verification/Stop**：存在未知 owner、scope overlap、无法解释的 dirty 文件或 active hot-file claim 时停止，不进入实现。

#### Task G0-2：建立行为保护账本

- **Owner/Boundary**：各 domain owner 只为自己的 Gate 建 characterization evidence。
- **Dependency**：G0-1。
- **Mode**：BDD_TDD（仅补缺失的关键行为保护）。
- **最低账本**：
  - Agent：private wrapper/monkeypatch 调用者、carryover schema、retry/fallback 次序、tool visibility/execution、cache/stall telemetry；
  - Chat：URL authority、单一 SSE、query key、lazy imports、layout persistence、dialog/submit hand tests；
  - API：每个目标 endpoint 的 status、media type、成功/错误 payload fixture 与前端消费点。
- **Verification/Stop**：关键行为没有可自动验证的 observable 时，先补 characterization test，不进行搬迁。

**Gate 0 出口条件**

- 候选 WIP 已有唯一 owner 和可审查 diff，或被明确排除。
- 三个后续 lane 的 scope、branch、claim、base SHA 和 integration 顺序已记录。
- 当前 contract guard 红色状态被保留为 baseline，没有通过扩大 budget 掩盖。

---

### Gate 1：收口当前 Agent 候选抽取

#### Task G1-1：验证并接入 carryover/compression/diagnostics/bindings

- **Owner/Boundary**：Agent orchestration owner；只处理当前候选 WIP，不追加新大模块。
- **Dependency**：Gate 0。
- **Mode**：BDD_TDD。
- **预计文件**：
  - `agent.py`
  - `core/orchestration/agent_runtime_bindings.py`
  - `core/orchestration/turn_carryover.py`
  - `core/orchestration/turn_compression.py`
  - `core/orchestration/turn_diagnostics.py`
  - 对应 tests 与模块 README
- **实施要求**：
  1. 逐个函数确认真实调用者、输入、状态写入、异常与日志；
  2. 修正 `runtime_telemetry()` 接口错配；
  3. 删除未使用 import，确保抽取函数被 production path 调用，而非只被测试直接调用；
  4. runtime dependency 通过显式 bindings 构造；禁止在函数定义时把 monkeypatch-sensitive callable 固化为默认参数；
  5. `agent.py` 只保留有证据需要的 thin wrapper；每个 wrapper 记录删除信号；
  6. 新模块不得 import `agent.py`。跨模块公共契约不得用无界 `Any` 容器替代稳定 DTO；内部适配器可暂留现有 `Any`，但必须记录收紧/删除信号，不得把新的无界 bag 扩散成第二套状态。
- **Verification/Stop**：
  - carryover round-trip、compression threshold、cache diagnostics、stall signal tests 全绿；
  - 无 dead import、无双写状态、无新循环依赖；
  - 若候选 WIP 无法解释行为差异，废弃该切片并回到干净 main 重做，不继续叠补丁。

**Gate 1 出口条件**

- 候选模块已形成独立、可回滚提交。
- `agent.py` wrapper 与新模块走同一 production path。
- runtime-scene 能观察一轮 fresh、carryover 和 compression/diagnostic 关键事件。

---

### Gate 2：Agent 编排按职责切片

Gate 2 的四个任务共享 `agent.py`，必须严格串行；每个任务单独提交、验证和自审。

#### Task G2-1：授权绑定与工具可见性

- **Owner/Boundary**：canonical policy 仍归 `core/authorization/tool_authorization_service.py`；本任务只抽 Agent binding/materialization。
- **Dependency**：Gate 1。
- **Mode**：BDD_TDD。
- **推荐路径**：
  - `agent.py` 收集 runtime identity 与 registered tools；
  - canonical service 生成 authorization decision/report；
  - 小型 orchestration adapter 将 decision 映射为 LLM-visible tools 与 execution context；
  - `ToolLifecycleBridge` 继续负责执行，不接管 policy。
- **保护行为**：shadow/enforced mode、deny code、approval requirement、hidden tool message、execution context、per-turn budget。
- **Verification/Stop**：tool authorization、Agent protocol 与 tool lifecycle tests 全绿；出现第二套 allow/deny 计算即停止。

#### Task G2-2：Turn message assembly

- **Owner/Boundary**：Prompt policy 归 `core/prompt_manager/*`，runtime context 归 `context_engine.py`；只抽取单 Turn 消息排序与 volatile/static 插入。
- **Dependency**：G2-1。
- **Mode**：BDD_TDD。
- **推荐路径**：
  - 定义 typed input/output，明确 system prefix、history、carryover、current user 与 volatile context 的顺序；
  - 复用 PromptAssemblyManifest/PromptSegment 语义；
  - seeded tool call normalization 与 untrusted content sanitization 保持原顺序；
  - 不复制 section exclusion、cache policy 或 trust policy。
- **Verification/Stop**：Prompt snapshot/manifest、cache partition、seeded messages 与 context engine tests 全绿；出现两个 Prompt policy owner 即停止。

#### Task G2-3：Agent LLM turn adapter

- **Owner/Boundary**：协议调用、metadata、recovery 与 profile routing 继续归 `core/llm/*`；本任务只抽 Agent-specific attempt loop。
- **Dependency**：G2-2。
- **Mode**：BDD_TDD。
- **推荐路径**：
  - 显式输入：messages、tool binding、mode/slot、invocation context、replay state、interrupt checker；
  - 显式输出：canonical outcome、used profile/slot、attempt ledger、replay state 与 diagnostics；
  - 每次网络调用必须走 `core.llm.invocation`；
  - retry/backoff/fallback 决策复用 `core.llm.recovery` 与 `routing`；
  - UI status 与 runtime-scene 由注入 observer 接收，不由 adapter 读取全局 UI。
- **Verification/Stop**：stream/non-stream、retry-after、provider fallback、replay、cache metadata、interrupt tests 全绿；wire payload 或 fallback 顺序变化即回滚。

#### Task G2-4：是否需要内部 Turn coordinator

- **Owner/Boundary**：架构决策任务，不预设新增 `turn_pipeline.py`。
- **Dependency**：G2-3。
- **Mode**：SIMPLE。
- **允许创建 coordinator 的必要条件**：
  1. 剩余逻辑仍同时编排至少三个稳定 owner；
  2. 能用 typed state/result 表达，不需要反射写回大量 `agent._private` 字段；
  3. 不重复 `TurnRunner` 外部入口、`TurnOutcomeController` 出口或 `ToolLifecycleBridge` 执行职责；
  4. 有独立测试能证明 coordinator 的状态转换，而非只测代理转发。
- **否则**：保留可读的 `agent.py` 高层方法，不为追求 LOC 创建空洞抽象。
- **Verification/Stop**：架构自审明确给出 `CREATE` 或 `DO_NOT_CREATE` 及证据；没有证据默认 `DO_NOT_CREATE`。

**Gate 2 出口条件**

- 单轮调用链只有一个高层入口和一个 outcome owner。
- 授权、Prompt、LLM 调用与工具执行均通过现有 SSOT。
- 兼容账本中每个 wrapper 都有 caller、test、state effect 与 removal signal。
- 记录 LOC、直接 global lookup、私有状态跨模块写入数量的趋势，但不以 LOC 单独阻止合入。
- scoped tests 与 Agent domain integration suite 全绿，并有 runtime-scene 证据。

---

### Gate 3：Chat Workbench 沿 Phase F 壳化

Gate 3 在覆盖 `ChatCodingRouteWorkbench.tsx` 的 active claim 释放或明确 handoff 前保持 BLOCKED；registry 中无此类 claim 时不因历史 id 假死。本轮用户明确授权完成 G3：审查者 `claim-bf845f98130d` 的 worktree 无未提交 WIP 且落后当前 `main`，实施落在 `.worktrees/chat-g3-phase-f`。

#### Task G3-1：完成剩余状态 owner 下沉

- **Owner/Boundary**：Chat route owner；沿 `web/src/routes/chat/README.md` Phase F。
- **Dependency**：Gate 0 + hot-file claim cleared。
- **Mode**：BDD_TDD。
- **优先项**：
  - group draft state；
  - dialog state/chrome；
  - remaining action wiring；
  - 已有 owner 可接收的 derived view model。
- **约束**：不新增第二 SSE、不改变 URL selection、query key、store authority 或用户行为。
- **Verification/Stop**：每个抽取必须减少一项独立职责；仅移动 JSX 且仍回调大量 shell 私有状态时不算完成。

#### Task G3-2：收敛 Shell slots 与 imports

- **Owner/Boundary**：`ChatCodingRouteWorkbench.tsx` 只保留 hooks composition 和 slots wiring。
- **Dependency**：G3-1。
- **Mode**：SIMPLE。
- **推荐路径**：
  - 复用 `ChatSessionWorkbenchShell` → `VSessionWorkbenchPage`；
  - 复用 Conversation/Index/Status/Center owner；
  - 保持 `WORKBENCH_LAYOUT_IDS.chat` 和 shared pane persistence；
  - 保持 secondary panels 的 `React.lazy` + conditional mount；
  - 按一次可审查的 net reduction 推进，参考现有 Phase F `net -300 LOC`，不强追 `<=800`。
- **Verification/Stop**：出现平行组件、route 直连 shadcn renderer、静态引入重型 panel 或 pane 记忆分叉即停止。

#### Task G3-3：有证据的性能边界

- **Owner/Boundary**：只处理可复现的 render/interaction 问题。
- **Dependency**：G3-2。
- **Mode**：SIMPLE；只有发现问题时执行。
- **要求**：
  - 先用 profiler、render-count test 或明确交互卡顿证据定位；
  - 仅在 referential identity 被消费时稳定 callback/object；
  - `React.memo` 必须有可解释的 props equality 与收益；
  - 无性能 finding 时本任务直接关闭，不做普遍 memoization。

**Gate 3 出口条件**

- shell 只保留 orchestration/wiring，业务状态均有明确 owner。
- URL、SSE、query、layout、lazy import 与 VUI contracts 不变。
- Chat hand-test substitutes、VUI contracts、相关 Vitest 与 `tsc -b` 全绿。
- 若 import graph 变化，bundle budget 检查通过。
- LOC 可记录为方向指标；建议窗口 `1,000–1,500` 仅用于下一轮评估，不是本 Gate 硬门。

---

### Gate 4：FastAPI 响应契约分批收敛

#### Task G4-1：修复 Launcher contract guard 漂移

- **Owner/Boundary**：Launcher route contract；不得修改 lifecycle/service/process 行为。
- **Dependency**：Gate 0。
- **Mode**：BDD_TDD。
- **推荐切片**：
  1. inventory 36 个 guard-counted route，按 status/read、desktop action、lifecycle intent、project/worktree 等 family 分类；
  2. 至少补齐 7 个未声明契约，使 `current <= 29`，guard 恢复绿色；不要求还原历史上是哪 7 个新加的；
  3. 每个 family 优先复用 `core/launcher/api_contract.py`；
  4. 用现有 `tests/test_web_runtime_routes.py` payload assertions 补齐 schema/fixture 保护；
  5. 将 budget 降为该提交后的精确剩余值，禁止提高到 36。
- **Verification/Stop**：response filtering 造成字段消失、status/error shape 变化或需要修改 spawn/lifecycle 时停止并拆新任务。

#### Task G4-2：收敛 Research runtime JSON/SSE 契约

- **Owner/Boundary**：`team_workflows/research_runtime.py` route contract；业务归对应 research service/pack。
- **Dependency**：Gate 0；与 G4-1 实施独立，但 shared guard 与 integration 必须串行。
- **Mode**：BDD_TDD。
- **推荐路径**：
  - inventory 当前 18 个 guard-counted route；
  - JSON 动作响应绑定显式 DTO；
  - SSE route 显式使用 `response_class=StreamingResponse`；
  - 复用/扩展 route-domain contract，不把 projection 变成第二写入者；
  - 扩展 `tests/test_team_workflow_routes.py` 与相关 SSE tests；
  - 同步降低 budget，不保留 23 的陈旧值。
- **Verification/Stop**：SSE media type、event framing、resume/replay、错误响应或前端解析变化时停止。

#### Task G4-3：跨层消费与后续 ledger

- **Owner/Boundary**：每个 endpoint family 的 route + TypeScript client/DTO + fixture，不能只改后端 decorator。
- **Dependency**：G4-1/G4-2 对应切片。
- **Mode**：BDD_TDD。
- **要求**：
  - `web/src/api` 类型与 runtime payload 一致；
  - `fullStackApiBoundary.test.ts` 和对应 API tests 通过；
  - budget 只记录剩余 legacy debt，不允许新增未声明 JSON endpoint；
  - 全仓 ledger 清零列为 Deferred program，另行排序，不伪装成本计划已完成。

**Gate 4 出口条件**

- `tests/test_full_stack_contract_guards.py` 全绿。
- Launcher 当前漂移归零，Research budget 与提交后的实际 remaining current 精确相等，且两者均不高于本计划基线。
- 所有本 Gate 触及 endpoint 有成功/错误 payload 与 media type 证据。
- OpenAPI/Pydantic filtering 未改变前端依赖字段。

---

## 6. 验证矩阵

命令必须在对应任务 worktree 中执行。测试数量不写死，避免随仓库演进失真。

### 6.1 Gate 0 基线

```powershell
git status --short --branch
git rev-parse HEAD
.venv\Scripts\python.exe -m pytest tests\test_full_stack_contract_guards.py -q
```

### 6.2 Gate 1–2 Agent

```powershell
.venv\Scripts\python.exe -m pytest `
  tests\test_agent_protocol.py `
  tests\test_agent_protocol_graph.py `
  tests\test_agent_modes.py `
  tests\test_agent_stall_signals.py `
  tests\test_turn_runner.py `
  tests\test_tool_lifecycle.py `
  tests\test_context_engine.py `
  tests\test_llm_turn_assembler.py `
  tests\test_llm_invocation.py `
  tests\test_llm_invocation_context.py `
  tests\test_prompt_manager.py `
  tests\test_external_agent_protocol_routing.py `
  -q

.venv\Scripts\python.exe -m pytest `
  tests\test_tool_authorization_contract.py `
  tests\test_tool_authorization_execution.py `
  tests\test_tool_authorization_shadow.py `
  tests\test_tool_authorization_test_contract.py `
  tests\test_tool_authorization_visibility.py `
  -q
```

每个 Agent 切片还必须运行与所迁函数一一对应的旧测试；Gate 2 合入前按 `tests/README.md` 运行 Agent domain integration matrix。运行现场至少覆盖：

- fresh turn；
- carryover/resume；
- tool allowed/denied/approval；
- tool-only stall；
- retry + fallback；
- compression/cache diagnostics。

### 6.3 Gate 3 Chat

```powershell
npm --prefix web test -- --run `
  src/routes/chat/chatHandTestSubstitute.test.ts `
  src/routes/chat/ChatGroupCenterSurface.test.tsx `
  src/routes/chat/ChatSessionWorkbenchShell.test.ts `
  src/routes/chat/chatRouteWriteBoundary.test.ts `
  src/routes/chat/useChatRouteSelection.test.tsx `
  src/routes/ChatCodingRoute.layout.test.ts

npm --prefix web test -- --run `
  src/components/vui/vuiShadcnRouteContract.test.ts `
  src/components/vui/vuiComponentDesignContract.test.ts `
  src/api/fullStackApiBoundary.test.ts
```

随后在 `web/` 目录执行：

```powershell
npx tsc -b --pretty false
```

若 lazy/static import 图变化，再执行：

```powershell
npm run check:bundle
```

### 6.4 Gate 4 API

```powershell
.venv\Scripts\python.exe -m pytest `
  tests\test_full_stack_contract_guards.py `
  tests\test_web_runtime_routes.py `
  tests\test_team_workflow_routes.py `
  -q

npm --prefix web test -- --run src/api/fullStackApiBoundary.test.ts
```

route suite 很大时可以先按 `-k` 跑目标 family，但合入前必须运行完整受影响文件。

---

## 7. 风险、检测与回滚

| 风险 | 早期信号 | 防御 | 回滚 |
| --- | --- | --- | --- |
| 第二套 Agent 编排 SSOT | 新模块重复 policy/retry/outcome | 先列现有 owner；adapter 只组合 | 回滚当前切片，保留 characterization tests |
| monkeypatch 穿透失败 | 旧测试 patch `agent.*` 后行为未变 | runtime bindings 在调用时解析；wrapper ledger | 恢复 facade wrapper，修正注入 seam |
| 私有状态双写 | adapter 与 `agent.py` 同时改同一字段 | typed result + facade 单点 apply | 回滚 state migration |
| cache/fallback 漂移 | model/slot/partition/attempt 次序变化 | 复用 `core.llm`，断言 attempt ledger | 回滚 LLM adapter |
| stall telemetry 静默失效 | 无事件但测试未失败 | 对齐 `runtime_telemetry()`，production-path test | 回滚 diagnostics 接线 |
| Chat 双 SSE/URL authority | 重复事件、跳转回旧 session | 固定现有 owner，hand-test substitute | 回滚状态抽取 |
| bundle 退化 | secondary panel 进入 initial chunk | lazy import contract + bundle check | 恢复 conditional lazy boundary |
| `response_model` 丢字段 | route test/OpenAPI 与前端 fixture 不一致 | 对真实 payload 建模，先测试后 decorator | 回滚该 endpoint family |
| budget 掩盖债务 | budget 增加或与 current 不符 | budget 单调不增且精确 | 拒绝合入 |
| Launcher 行为越界 | DTO diff 触及 subprocess/lifecycle | contract-only scope | 停止 Gate，拆 HIGH_RISK 任务 |
| 并发覆盖 hot file | active claim 或 merge conflict | per-lane worktree/claim，hot file 串行 | 不合入，交接或等待 |

所有切片必须保持小而可回滚。出现兼容性回归时优先 `git revert` 对应已合入切片；禁止用 hard reset 或覆盖他人改动恢复。

---

## 8. 合入、刷新与治理

### 8.1 Git / 协作

- 所有实现使用 `codex/<task-slug>` worktree；根 `main` 只接受经验证提交的 `git merge --ff-only`。
- 首次写入、scope 扩大和合入前重新运行 preflight。
- `agent.py` lane 与 Chat shell lane 各自串行；API endpoint family 可分 scope，但同一 route 文件默认串行。
- 每个任务完成后必须自审当前 task diff，确认没有吸收 dirty root 或其他 Agent 文件。
- 合入门失败、dirty main、大冲突或 active overlap 时报告精确 blocker，不临时绕过。
- 合入后立即 release claim，清理本任务 worktree/branch/临时文件与后台进程，再执行安全的 `git worktree prune`。
- 远端 push/PR 仍需用户单独授权。

### 8.2 Launcher/runtime refresh

- 计划文档、纯 Python 单元抽取和 DTO decorator 本身通常不要求 Launcher refresh。
- Agent runtime production path 改变后：用户测试前 **recommended**，发布前 **required**；先完成测试与 runtime-scene 证据。
- Chat 变更：在 `tsc -b` 和 Vitest 全绿后，用户测试前 **recommended**，发布前 **required**。
- 若 active-work guard 阻止重启，必须保留现场并报告，不绕过 guard。

### 8.3 Windows 无控制台红线

- 本计划不修改任何 spawn 路径。
- 未来任务若触及启动、停止、重启、轮询、Git 或服务子进程，必须使用项目 no-console helper、`pythonw`、`CREATE_NO_WINDOW` 或 `windowsHide`，并新增对应验证。
- 任何可能弹出 `cmd.exe`、`powershell.exe`、Windows Terminal 或 OpenConsole 的路径不得合入。

### 8.4 日志、memory 与版本

- Agent Gate：需要 runtime-scene 事件与 bounded diagnostics；不得记录完整 Prompt、完整工具输出或 secrets。
- Chat 纯结构 Gate：默认不新增日志；若行为变化则重新评估 telemetry。
- API DTO Gate：默认不新增日志；若错误语义变化则已超出本任务。
- project-memory 只记录跨会话 owner、blocker、handoff 与 Gate 状态，不复制本计划正文。
- 纯重构默认无 version bump；每个 Gate 仍需按公开契约与用户行为重新做 version impact 决策。

---

## 9. 最终 Definition of Done

### Agent

- 现有 authorization/prompt/LLM/tool/outcome SSOT 未被复制。
- `agent.py` 不再承载已抽取职责，compatibility wrappers 有删除条件。
- 相关单元、domain integration 与 runtime-scene 证据全绿。
- 没有新循环依赖、dead import、反射式状态双写或无界日志。

### Chat

- Workbench shell 只负责 composition/wiring。
- URL、SSE、query key、layout persistence、lazy boundaries 与 VUI contracts 保持不变。
- Vitest、VUI contracts、`fullStackApiBoundary`、`tsc -b` 全绿；必要时 bundle check 全绿。

### API

- `test_full_stack_contract_guards.py` 全绿，budget 精确且单调不增。
- 目标 endpoint family 的 Pydantic/OpenAPI、实际 payload 与 TypeScript 消费一致。
- SSE 明确 `response_class`，Launcher lifecycle/process 行为未改变。

### 协作与收口

- 每个 Gate 有 owner、claim、worktree、base SHA、验证记录、自审和 merge 结果。
- 本地 `main` 仅通过 `ff-only` 吸收已验证提交；合入后资源清理完成。
- Deferred 项有明确触发信号，不以“以后再做”伪装为完成。
- 全部 Gate 关闭后，本计划迁入 `docs/archive/`，不长期留在 active `docs/plans/`。

---

## 10. Deferred

以下内容明确不属于当前 Critical Path：

- 全仓 `LEGACY_UNTYPED_ENDPOINT_BUDGETS` 清零；
- 仅为达到 `agent.py <= 1,200` 或 Workbench `<= 800` 的继续搬迁；
- 无 profiler/测试证据的全局 React memoization；
- LLM protocol、authorization policy 或 Chat product behavior 重设计；
- Launcher/runtime process model 改造；
- 删除仍有真实调用者的 compatibility wrappers。

**下一执行动作：Gate 3 已按 G3-1 → G3-2 → G3-3 收口（G3-3 无新 render finding）。Gate 4 FastAPI 全量 ledger 清零仍为 Deferred。**
