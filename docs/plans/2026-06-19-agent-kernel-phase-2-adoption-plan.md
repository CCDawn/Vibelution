# Agent Kernel Phase 2 Adoption Plan

日期：2026-06-19
状态：实施前规划草案
归属分线：agent-runtime-core / quality-and-operations / chat-coding-surface
范围：Phase 2A 采用计划，不包含运行时代码改动

## 1. 目的

Agent Kernel MVP 已经完成第一阶段：

- `POST /api/kernel/events` 可接收标准事件；
- `TaskLedger`、`WorkRun`、`Outcome` 已经形成最小闭环；
- Kernel state 以 `workspace/agent_kernel/*.jsonl` 与 `index.json` 保存；
- Agent inbox projection 与 `wakeTarget` 唤醒策略已接入；
- contract tests 已覆盖 idempotency、missing recipient、inbox ack、proposal stub、developer sandbox routing 和 wake evidence。

Phase 2 的目标不是继续扩展一个完整 Agent OS，而是把 Kernel 从“旁路 API”推进到“现有会话、群聊、Agent 管理能使用的协作底座”。

本计划只定义下一阶段如何落地，不直接修改运行时代码。

## 2. Phase 2 总目标

Phase 2 要建立这条可观察、可测试、可渐进替换的链路：

```text
Session / Room / Agent Action
  -> Kernel Adapter
  -> Kernel Event
  -> TaskLedger
  -> Inbox Delivery / Wake
  -> Outcome
  -> Projection Update
  -> Read Model / UI
```

核心原则：

- `TaskLedger` 仍然是任务状态事实源。
- `Session`、`Room`、`Conversation` 只触发或显示 Kernel state，不反写覆盖 task lifecycle。
- `EvaluationGate` 仍然是 outcome 后的 side workflow，不进入 runtime critical path。
- `ContextResolver` 只做 minimal refs，不提前实现 memory OS。
- 任何旧测试失败必须分类为 contract / compatibility / implementation-lock / characterization / smoke，不允许无解释跳过。

## 3. 现状差距

### 3.1 已有能力

| 能力 | 当前状态 | 证据 |
|---|---|---|
| Kernel event intake | 已完成 | `core/agent_kernel/service.py` |
| Task/Execution/Outcome lifecycle | 已完成 | `tests/test_agent_kernel.py` |
| Agent inbox projection | 已完成 | `/api/agents/{agent_id}/inbox` |
| wakeTarget delivery policy | 已完成 | `delivery.wake.wakeStatus` |
| Runtime scene evidence | 部分完成 | `kernel.event.rejected` / `kernel.event.completed` |
| Proposal stub | 已完成 | outcome 后 `proposalRefs` |

### 3.2 缺口

| 缺口 | 影响 |
|---|---|
| 现有 session / room / agent message 入口尚未统一走 Kernel adapter | Kernel 仍像旁路能力，不能承接平台主流程 |
| 缺少 task timeline read model | 用户和后续 Agent 不容易追踪事件、投递、wake、outcome 的完整链路 |
| 缺少 projection repair 记录约定 | Session/Room 投影失败时，难以证明 TaskLedger 仍是事实源 |
| 缺少可见 Task Center 或只读面板 | 用户无法直接看到平台正在处理哪些 Kernel task |
| 旧入口仍可能直接写 inbox 或 room state | 后续协作路径会继续分叉 |

## 4. 推荐实施顺序

### Phase 2A：Kernel Adapter + Task Timeline API

这是下一轮代码实现的推荐范围。

交付目标：

1. 新增 Kernel adapter service。
2. 为现有入口提供统一事件构造函数。
3. 新增 task timeline/read model API。
4. 保持旧入口默认行为不破坏，只在明确试点入口启用 adapter。
5. 增加 contract tests 保护 adapter 与 timeline。

不交付：

- 不把所有 session 消息默认切到 Kernel。
- 不改完整群聊 scheduler。
- 不做前端 Task Center。
- 不做完整 ContextResolver。
- 不做 EvaluationGate approval API。
- 不做 SQLite migration。

### Phase 2B：试点接入现有 Agent-to-Agent / ProjectAgentBus

在 Phase 2A 可观察后，再接入一个真实业务入口。

推荐先接入：

```text
ProjectAgentBus targeted message
  -> Kernel Adapter
  -> Kernel Event
  -> Agent inbox / wake
```

原因：

- ProjectAgentBus 本来就是 Agent-to-Agent communication；
- 现有逻辑已经包含 inbox delivery 和 wake；
- 接入 Kernel 后能立刻减少“私信路径”和“Kernel 路径”分裂；
- 风险低于直接改 session submit 或 chat room round。

### Phase 2C：只读 Kernel Task Center

当 timeline API 稳定后，再做 UI。

第一版只读：

- 最近 tasks；
- status；
- sender / recipients；
- event id；
- outcome summary；
- delivery status；
- wakeStatus；
- runtime evidence refs。

不提供取消、重试、审批、apply 等控制动作。

## 5. Phase 2A 行为契约

### 5.1 Kernel Adapter

新增建议模块：

```text
core/agent_kernel/adapters.py
```

职责：

- 把现有业务入口转换成 Kernel event payload；
- 生成稳定 `eventId` / `idempotencyKey`；
- 附带 `correlationId` / `causationId`；
- 保留 sender、recipient、source surface 和 projection ref；
- 不直接写 Session、Room、Conversation；
- 不直接调用 LLM；
- 不直接写 memory。

建议函数：

```python
def build_agent_message_event(
    *,
    source: str,
    sender: dict,
    recipient_agent_ids: list[str],
    content: str,
    correlation_id: str = "",
    causation_id: str = "",
    wake_target: bool = True,
    metadata: dict | None = None,
) -> dict:
    ...

def submit_agent_message_event(...) -> dict:
    event = build_agent_message_event(...)
    return handle_kernel_event(event)
```

第一版 adapter 只支持 `semanticType = "agent.message"`。

### 5.2 Event Metadata Contract

Phase 2A 事件必须携带最小来源信息：

```json
{
  "metadata": {
    "sourceSurface": "project_agent_bus | session | chat_room | manual_api",
    "sourceSessionId": "",
    "sourceRoomId": "",
    "sourceMessageId": "",
    "projectionRef": "",
    "adapterVersion": "kernel-adapter-v1"
  }
}
```

规则：

- `sourceSurface` 必填。
- 不适用字段保留空字符串。
- metadata 只做审计和 projection 关联，不拥有 task 状态。
- 不能把完整 prompt、secret、长工具输出写入 metadata。

### 5.3 Idempotency Rule

Adapter 必须生成业务稳定的 `idempotencyKey`。

建议格式：

```text
kernel-adapter:{sourceSurface}:{sourceId}:{recipientHash}:{contentHash}
```

其中：

- `sourceId` 优先使用已有 message/round/event id；
- 如果没有 source id，使用 caller 显式传入的 `eventId`；
- 不允许只用当前时间作为 idempotency key；
- `contentHash` 使用安全裁剪后的内容摘要；
- 同一业务动作重复提交必须复用已有 task。

### 5.4 Timeline Read Model

新增建议 service 函数：

```python
def get_kernel_task_timeline(task_id: str) -> dict:
    ...
```

新增建议 API：

```http
GET /api/kernel/tasks/{task_id}/timeline
```

返回结构：

```json
{
  "taskId": "",
  "task": {},
  "event": {},
  "execution": {},
  "outcome": {},
  "deliveries": [],
  "proposals": [],
  "runtimeEvidenceRefs": [],
  "projectionRefs": [],
  "timeline": [
    {
      "kind": "event.accepted",
      "status": "accepted",
      "at": "",
      "summary": "",
      "refs": []
    }
  ]
}
```

规则：

- timeline 是 read model，不是新的事实源。
- timeline 从 `index.json`、JSONL 当前索引和 outcome/delivery 字段组装。
- 不反写 task 状态。
- 缺少 projection 时返回空 refs，不失败。
- 如果 task 不存在，返回 404。

### 5.5 Projection Boundary

Phase 2A 不主动刷新 Session/Room projection。

但文档和测试必须明确：

```text
Given a Kernel task has terminal outcome
When a session or room projection update fails or is missing
Then TaskLedger remains authoritative
And timeline exposes projectionRefs as missing/empty
And runtime evidence records the projection repair need only if repair was attempted
```

## 6. API 设计

Phase 2A 新增最小 API：

```http
POST /api/kernel/adapter/agent-message
GET /api/kernel/tasks/{task_id}/timeline
```

### 6.1 POST /api/kernel/adapter/agent-message

用途：

- 提供试点入口；
- 避免每个调用方手写 Kernel event payload；
- 为 Phase 2B 替换 ProjectAgentBus 做准备。

请求：

```json
{
  "source": "manual_api",
  "sender": {"type": "user", "id": "operator"},
  "recipientAgentIds": ["agent-a"],
  "content": "请分析这条消息",
  "correlationId": "",
  "causationId": "",
  "wakeTarget": true,
  "metadata": {}
}
```

响应：

与 `POST /api/kernel/events` 保持兼容，额外可返回：

```json
{
  "adapter": {
    "source": "manual_api",
    "adapterVersion": "kernel-adapter-v1"
  }
}
```

### 6.2 GET /api/kernel/tasks/{task_id}/timeline

用途：

- 为 UI、debug、后续 Agent 审查提供可读链路；
- 避免直接让前端理解 JSONL/index 内部结构。

## 7. 数据与存储

Phase 2A 继续使用 JSONL + index。

允许新增字段：

- event.metadata.sourceSurface；
- event.metadata.projectionRef；
- execution.deliveryRefs.wakeStatus 已存在；
- outcome.deliveries 已存在；
- timeline read model 运行时组装，不持久化。

不允许：

- 把 timeline 作为独立事实源持久化；
- 在 adapter 中写 session/room 文件；
- 在 adapter 中写 memory；
- 为了查询便利直接迁移 SQLite。

## 8. Runtime Scene 与日志

Phase 2A 需要新增或确认以下 runtime scene event：

| Event code | 触发点 | 字段 |
|---|---|---|
| `kernel.adapter.event_built` | adapter 构造 event 成功 | sourceSurface, eventId, recipientCount |
| `kernel.adapter.event_submitted` | adapter 调用 Kernel 成功 | eventId, taskId, outcomeId, reused |
| `kernel.timeline.loaded` | timeline API 成功 | taskId, timelineItemCount |
| `kernel.timeline.missing_task` | timeline API 404 | taskId |

日志限制：

- 不记录完整 content。
- 不记录完整 prompt。
- 不记录 secrets。
- 只记录稳定 id、状态、计数和安全摘要。

## 9. 测试矩阵

### 9.1 Contract Tests

新增建议文件：

```text
tests/test_agent_kernel_adapters.py
```

必测：

1. `build_agent_message_event` 生成标准 Kernel event。
2. 同一 source/message/content 重复提交复用 task。
3. `wakeTarget=false` 经 adapter 传递到 deliveryPolicy。
4. adapter 不直接写 session/room/memory。
5. timeline API 返回 event、task、execution、outcome、delivery、wakeStatus。
6. task 不存在时 timeline API 返回 404。

### 9.2 Compatibility Tests

必测：

1. 现有 `POST /api/kernel/events` 仍可直接使用。
2. 现有 `/api/agents/{agent_id}/inbox` 仍按 status/limit 返回。
3. 现有 ProjectAgentBus 在 Phase 2A 不被默认替换。

### 9.3 Projection Boundary Tests

必测：

```text
Given adapter event creates a terminal task
When no session/room projection ref exists
Then timeline returns empty projectionRefs
And task remains succeeded/blocked according to Kernel outcome
```

### 9.4 Developer Mode Tests

必须保持：

- formal mode 写入 operator data home 的 `workspace/agent_kernel`；
- developer mode 写入 sandbox workspace 的 `workspace/agent_kernel`；
- adapter 和 timeline API 使用同一 `_kernel_root()` 路由。

## 10. 评审结论

### 核心用户视角

用户需要知道“系统到底在做什么”。Phase 2A 的 timeline API 是最低成本答案；先做 UI 但没有 read model 会继续导致前端猜状态。

结论：先做 read model，再做 Task Center。

### 维护者视角

现有入口很多：session、chat room、ProjectAgentBus、research organization、agents messages。直接全量替换风险高。

结论：先新增 adapter，随后只接一个真实入口做试点。

### 测试/QA 视角

旧测试全绿不能证明 Kernel adoption 正确；必须新增 adapter/timeline contract tests。

结论：Phase 2A 的 done condition 必须以新 contract tests 为主。

### 后续集成方视角

后续 UI、scheduler、EvaluationGate 都需要稳定 read model。如果 timeline 结构频繁变化，集成成本会很高。

结论：timeline response shape 在 Phase 2A 后应视为兼容 API。

## 11. 决策记录

### Decision 1：Phase 2A 先做 adapter + timeline，不先做 UI

原因：

- UI 没有 read model 会复制后端推理；
- adapter 是接入现有系统的最小扩展点；
- timeline 能直接降低调试和用户理解成本。

代价：

- 用户短期仍看不到完整 Task Center；
- 需要通过 API 或后续 UI 才能消费 timeline。

### Decision 2：ProjectAgentBus 作为 Phase 2B 第一个试点入口

原因：

- 它天然是 Agent-to-Agent 消息总线；
- 现有实现已包含 inbox/wake，和 Kernel 能力重叠；
- 迁移收益明确，风险低于 session submit 或 chat room round。

代价：

- 群聊 round-robin / 抢占式讨论不会在 Phase 2A 解决；
- 需要保留旧 ProjectAgentBus 行为直到试点验证通过。

### Decision 3：不在 Phase 2A 做 SQLite

原因：

- 当前数据量和查询复杂度还不需要；
- JSONL + index 更容易审计和回滚；
- 过早 SQLite 会把迁移问题提前引入。

代价：

- timeline 查询只能基于当前 index 和有限 JSONL 读取；
- 如果任务量增长，需要 Phase 3 做存储迁移评估。

## 12. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| adapter 与 `POST /api/kernel/events` 产生两套输入契约 | 调用方困惑 | adapter 只做 event builder，最终仍调用 `handle_kernel_event` |
| timeline 被误当作事实源 | 状态分裂 | 文档和测试明确 timeline 是 read model |
| 旧入口继续直接写 inbox | 路径分裂 | Phase 2B 选择 ProjectAgentBus 试点收束 |
| 旧测试阻碍迁移 | 重构被旧实现锁死 | 使用 test strategy 分类旧测试 |
| wake 失败被误判为 task 失败 | TaskLedger 不稳定 | 保持 delivery wake evidence 与 task outcome 分离 |

## 13. Phase 2A Done Criteria

Phase 2A 可以合并的最低标准：

```text
adapter contract tests pass
+ timeline API tests pass
+ existing kernel tests pass
+ developer sandbox path test pass
+ no unexplained legacy test failure
+ docs mention Phase 2B pilot target
```

建议验证命令：

```powershell
py -m pytest tests\test_agent_kernel.py tests\test_agent_kernel_adapters.py -q
py -m py_compile core\agent_kernel\__init__.py core\agent_kernel\service.py core\agent_kernel\adapters.py core\web\routes\kernel.py
git diff --check
```

如果 Phase 2A 修改前端 DTO 或 UI，再追加：

```powershell
npm --prefix web run build
```

## 14. 后续实施任务拆分

### Task 1：Adapter Service

范围：

- `core/agent_kernel/adapters.py`
- adapter unit tests

输出：

- build event；
- submit event；
- idempotency helper；
- metadata normalizer。

### Task 2：Timeline Read Model

范围：

- `core/agent_kernel/service.py`
- `core/web/routes/kernel.py`
- timeline tests

输出：

- `get_kernel_task_timeline(task_id)`；
- `GET /api/kernel/tasks/{task_id}/timeline`；
- runtime scene evidence。

### Task 3：ProjectAgentBus Pilot Plan

范围：

- 先写小型迁移计划或 behind-flag adapter call；
- 不直接删除旧 bus delivery。

输出：

- ProjectAgentBus 可选择调用 adapter；
- old path 和 kernel path 结果可对比；
- pilot tests。

### Task 4：Task Center UI Spec

范围：

- 只写 UI spec 或后续单独实施；
- 不与 Phase 2A 混合。

输出：

- 只读 task list；
- task timeline detail；
- delivery/wake evidence 展示。

## 15. 下一步推荐

下一步直接开实现分支：

```text
codex/agent-kernel-adapter-timeline
```

实施范围限定为：

- `core/agent_kernel/adapters.py`
- `core/agent_kernel/service.py`
- `core/web/routes/kernel.py`
- `tests/test_agent_kernel.py`
- `tests/test_agent_kernel_adapters.py`

不碰：

- `session_service.py`
- `chat_room_service.py`
- `project_agent_bus_service.py`
- frontend
- project memory

这样可以先把 Kernel 接入面和可观察面打稳，再进入真实业务入口迁移。
