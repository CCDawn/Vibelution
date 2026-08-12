# 挑战杯科研工作流运行时详细技术方案

**状态：** Ready for implementation

**日期：** 2026-08-12

**上位方案：** [挑战杯科研工作流运行架构与实施方案](2026-08-12-challenge-cup-research-workflow-runtime-architecture.md)

**权威决策：** [ADR 0006](../adr/0006-challenge-cup-workflow-runtime-and-single-canvas.md)、[ADR 0007](../adr/0007-research-workflow-handoff-and-agent-session-binding.md)

**执行对象：** 负责实现的开发 Agent、后续审查 Agent、集成 Owner

**实现边界：** 本文只把已经冻结的架构决策下沉为文件、schema、事务、API、前端和验收合同；不得重新引入兼容运行时、第二状态机或第二写入者。

---

## 1. 交付目标

执行 Agent 最终必须交付一条可以由普通用户纯点击完成的正式科研运行链：

```text
选择 SCI-096
  -> 创建运行
  -> 执行知识搜集五个节点
  -> 人工接受知识包
  -> 执行实验设计五个节点
  -> 人工冻结协议并放行 Smoke
  -> 受控运行
  -> 结果评价与迭代决策
  -> 版本治理与人工晋升/停止
  -> 结果打包
```

每一次可见操作必须对应一个后端签发的 `CommandOffer`；每一次状态变化必须对应同一 `Workflow Ledger` 中已提交的 command、event 和必要 outbox；每一个 Agent 节点必须能跳到真实 `sessionId + taskId + turnId`；每一个 Handoff 只能接收已在领域事实源中物化并经过 read-back 校验的 artifact。

以下情况一律判定未完成：

- Canvas 显示可执行，但点击后由 adapter 的另一套规则拒绝；
- preflight 失败后留下预算 reservation、TaskBundle、Session、Turn 或 accepted Handoff；
- UI 根据本地条件猜按钮是否可用；
- LangGraph checkpoint、JSON Run 文件或 Canvas projection 成为产品状态写入者；
- `teamId` 缺失时回退到 selected team、默认 team 或 `research-team`；
- 为了迁移保留双写、旧 route fallback、旧 JSON writer 或 silent recovery；
- 测试只能通过 API、DOM script、SQLite/JSON 注入才能推进流程。

## 2. 冻结决策

执行期间不得自行改变以下结论：

1. **唯一控制流：** 继续使用 LangGraph；不引入 CrewAI、Dify、n8n、AutoGen 等第二运行时。
2. **唯一运行写模型：** `Workflow Ledger`；LangGraph checkpoint 只保存控制位置，领域 Store 保存业务事实，projection 只读。
3. **唯一可执行性判定：** `NodeReadinessService`；命令受理与前端按钮消费同一个结果。
4. **唯一团队作用域：** `teamId`；缺失、不匹配或资源不属于该团队时显式失败。
5. **唯一命令入口：** `POST /api/research/workflow-runs/{runId}/commands`；节点命令、人工决策、绑定变更均为 typed command。
6. **无兼容运行层：** 旧数据只允许被一次性迁移器读取；正式切换后删除旧 writer、旧写 route 和 fallback。
7. **预算语义：** 默认每阶段 `250000` tokens、全流程 `300` tool calls、`21600` 秒、自动重试 `2` 次；预算只防无限循环，不压缩 Agent 的正常工作。
8. **前端约束：** VUI 产品 API + shadcn/Radix renderer；页面业务层不得直连 renderer。
9. **Agent 会话：** 一个项目 Agent 保持连续 session；节点定位到具体 task/turn；绑定失败不伪造“已运行”。
10. **结构约束：** 一个功能一个文件或小模块；route、service facade、React 页面不得重新聚合独立职责。

## 3. 当前基线与硬切换边界

### 3.1 当前可复用部分

保留并演进：

- `core/research/workflow/definition.py` 中固定 16 节点、三阶段和 edge 定义；
- `core/research/workflow/challenge_cup_graph.py` 的图拓扑意图；
- `core/research/workflow/checkpoint_store.py` 的 LangGraph SQLite checkpointer；
- `core/chat/conversation_store/` 已验证的 APSW/WAL、单写入 actor、有界队列、`BEGIN IMMEDIATE`、savepoint 和 after-commit 行为模式；
- 各领域事实源：Source Collection、Evidence、Knowledge、Experiment、Budget、Agent/Chat；
- 现有 VUI 工作流 Canvas、Inspector、Toolbar、Timeline 结构；
- 现有 deterministic event reducer、run 切换 cursor reset、single-flight polling/SSE 基础。

### 3.2 必须替换部分

正式切换时物理删除或停止引用：

- `core/web/services/team_workflow/research_runtime/store.py`；
- `core/web/services/team_workflow/research_runtime/durable_index.py`；
- 任何以 Run JSON 内嵌 `events/handoffs/humanTasks/sessionBindings` 为权威的逻辑；
- 生产路径中用 `update_state(..., as_node=...)` 从外部伪装节点完成的 vertical slice；
- `POST .../nodes/{nodeId}/commands`；
- `PUT .../nodes/{nodeId}/session-binding`；
- 前端本地推导的 `NodeCommandCapability`；
- 旧 stage 页面、未连接页面、重复入口与 legacy resolver。

### 3.3 名称隔离

`Workflow Ledger` 与当前 `research_runtime/research_ledger.py` 不是同一对象：

- `Workflow Ledger`：Run/Attempt/Command/Event/Handoff/Anchor/Receipt 的唯一写模型；
- `ResearchLedger`：Claim/Evidence/Knowledge/Experiment 的只读聚合投影。

禁止让 `ResearchLedger` 写 Workflow 状态，也禁止把领域内容复制进 `Workflow Ledger`。

## 4. 目标目录与职责

### 4.1 Core contracts

```text
core/research/workflow/contracts/
  node_readiness.py       # NodeReadiness / ReadinessBlocker / revision vector
  workflow_command.py     # CommandRequest / CommandReceipt / CommandOffer
  workflow_event.py       # WorkflowEventEnvelope / event payload registry
  execution_anchor.py     # Agent/System/Human execution anchor
  artifact_receipt.py     # ArtifactReceipt / BudgetReceipt
  pending_action.py       # LangGraph PendingAction / ExecutionReceipt
  workflow_problem.py     # stable error code and remediation contract
```

规则：

- 使用 frozen dataclass、Enum 和明确验证函数；
- core 内部字段用 Python snake_case，`to_dict()` 只在 API 边界输出 camelCase；
- 禁止 `dict[str, Any]` 穿过 command/readiness/receipt 主链；
- 现有 `artifact_manifest.py`、`budget.py`、`execution.py` 若语义相同则扩展，不创建同义合同。

### 4.2 Workflow Ledger

```text
core/research/workflow/ledger/
  __init__.py
  errors.py               # corruption/backpressure/conflict/closed
  schema.py               # deterministic migrations + checksum
  runtime.py              # APSW capability and version guard
  database.py             # writer/read-only connection policy
  records.py              # persistence records only
  repository.py           # SQL only; no domain calls
  unit_of_work.py         # transaction-scoped repository + after-commit
  writer.py               # bounded single writer
  store.py                # public mutation/query facade
  outbox.py               # lease/ack/retry primitives
  reconciliation.py       # checkpoint/outbox/domain anchor reconciliation

core/research/workflow/
  challenge_cup_runtime.py # formal interrupt/resume coordinator
```

不得直接 import `core/chat/conversation_store/repository.py`。允许复用其底层行为和局部通用 helper；若提炼公共 SQLite helper 会扩大 Chat 风险，则在研究包内实现同样的小型策略，公共提炼延期。

### 4.3 Runtime services

```text
core/web/services/team_workflow/research_runtime/
  command_service.py
  query_service.py
  projection_builder.py
  graph_dispatch_worker.py
  adapter_dispatch_worker.py
  action_registry.py
  readiness/
    __init__.py
    service.py
    common.py
    source_collection.py
    evidence.py
    knowledge.py
    experiment.py
    iteration.py
    budget.py
    actor.py
```

`service.py` 最终只组装依赖和导出 facade，不再包含状态机、持久化、readiness 或 adapter 规则。

### 4.4 Migration

```text
core/research/workflow/migration/
  inventory.py
  validator.py
  importer.py
  verifier.py
  manifest.py

scripts/
  audit_research_workflow_runtime.py
  migrate_research_workflow_ledger.py
```

### 4.5 Frontend

```text
web/src/api/research-workflow/
  index.ts
  client.ts
  definitions.ts
  runs.ts
  commands.ts
  events.ts
  bindings.ts
  domain-projections.ts

web/src/api/types/research-workflow/
  index.ts
  core.ts
  readiness.ts
  commands.ts
  events.ts
  anchors.ts
  artifacts.ts

web/src/routes/teams/research-workflow/
  useResearchWorkflowSnapshot.ts
  useResearchWorkflowEventStream.ts
  useResearchWorkflowCommand.ts
  researchWorkflowSnapshotReducer.ts
  researchWorkflowRouteState.ts
  researchRunLabel.ts
  ResearchWorkflowToolbar.tsx
  ResearchProcessNodeInspector.tsx
```

现有 `web/src/api/researchWorkflow.ts` 和 `web/src/api/types/researchWorkflow.ts` 在同一切换提交中被替换；允许保留仅做 canonical export 的 index，不允许保留旧请求实现或两套类型。

## 5. 核心类型合同

### 5.1 CommandRequest

```python
@dataclass(frozen=True)
class CommandRequest:
    command_id: str
    run_id: str
    team_id: str
    command: WorkflowCommandKind
    node_id: str | None
    expected_run_version: int
    idempotency_key: str
    payload: Mapping[str, JsonValue]
    requested_by: ActorRef
    requested_at_ms: int
```

`command_id` 由服务端生成。客户端只提交：

```json
{
  "teamId": "research-team",
  "nodeId": "source_extraction",
  "command": "start_node",
  "expectedRunVersion": 17,
  "idempotencyKey": "ui:run-...:source_extraction:start:v17",
  "payload": {}
}
```

客户端不得提交 `available`、目标状态、下一节点、ArtifactReceipt、agentId 快照或 Handoff status。

### 5.2 CommandOffer

```python
@dataclass(frozen=True)
class CommandOffer:
    command: WorkflowCommandKind
    node_id: str | None
    available: bool
    label: str
    reason_code: str
    blocker_ids: tuple[str, ...]
    idempotency_key: str
    expected_run_version: int
    payload: Mapping[str, JsonValue]
    destructive: bool = False
    confirmation: ConfirmationContract | None = None
```

`idempotencyKey` 与 `payload` 由后端签发，前端原样回传。Offer 只在对应 `runVersion` 有效。

### 5.3 NodeReadiness

```python
@dataclass(frozen=True)
class NodeReadiness:
    run_id: str
    team_id: str
    node_id: str
    run_version: int
    ready: bool
    evaluated_at_ms: int
    domain_revision_vector: Mapping[str, str]
    accepted_handoff_ids: tuple[str, ...]
    input_artifact_refs: tuple[ArtifactRef, ...]
    actor: ActorReadiness
    budget: BudgetReadiness
    blockers: tuple[ReadinessBlocker, ...]
```

`NodeReadiness` 是计算结果，不作为可变事实持久化。可按以下完整 key 做短时缓存：

```text
(teamId, runId, runVersion, nodeId, domainRevisionVector)
```

任一 revision 改变即失效。命令受理必须重新计算，不能只信前端刚读到的结果。

### 5.4 WorkflowProblem

```json
{
  "code": "source_candidates_missing",
  "title": "没有可提炼的资料",
  "detail": "资料权威存储中没有属于当前运行的候选资料。",
  "retryable": false,
  "scope": {"teamId": "...", "runId": "...", "nodeId": "source_extraction"},
  "remediation": {
    "kind": "navigate_node",
    "targetNodeId": "source_finding",
    "label": "返回资料寻找"
  }
}
```

错误 code 稳定；`detail` 面向用户，不显示内部路径、raw exception 或 run UUID 解释要求。

### 5.5 PendingAction 与 ExecutionReceipt

```python
@dataclass(frozen=True)
class PendingAction:
    action_id: str
    run_id: str
    node_run_id: str
    node_id: str
    attempt: int
    actor_kind: ActorKind
    action_kind: str
    input_snapshot_hash: str
    input_artifact_refs: tuple[ArtifactRef, ...]
    binding_snapshot_id: str | None
    budget_policy_hash: str

@dataclass(frozen=True)
class ExecutionReceipt:
    action_id: str
    node_run_id: str
    outcome: Literal["succeeded", "failed", "blocked", "cancelled"]
    artifact_receipt_ids: tuple[str, ...]
    execution_anchor_id: str | None
    budget_receipt_id: str | None
    problem: WorkflowProblem | None
    completed_at_ms: int
```

Runner 只消费 receipt，不直接读取 adapter 的临时对象。

### 5.6 命令、身份与 hash 规则

正式 command kind 只允许：

```text
start_node
retry_node
cancel_node
resolve_human_task
rebind_node
fork_revision
extend_budget
cancel_run
reconcile_run
```

节点完成、Handoff accepted、Artifact verified 和 Run succeeded 不是客户端 command；它们只能由已验证 receipt 或人工 command 的服务端状态转移产生。

ID 由服务端生成，带稳定前缀并使用同一 UUID/随机 ID helper：

```text
run- / cmd- / nr- / act- / evt- / ho- / ht- / ar- / br- / rec-
```

ID 只用于身份和深链，不直接作为用户标题。所有时间使用服务端 UTC epoch milliseconds；API 边界转 RFC 3339。

canonical JSON 规则固定为 UTF-8、对象 key 排序、无多余空白、数组保持业务顺序；`requestHash` 为完整 command body（排除服务端时间与 commandId）的 SHA-256。`inputSnapshotHash` 对按 `(artifactKind, authority, artifactId, version, sha256)` 排序后的不可变 refs、题目快照和 binding/budget policy hash 计算。不同语言必须用共享 fixture 证明 hash 一致。

状态转移只能由 domain transition function 执行，repository 不接受任意 status 字符串：

| 对象 | 主要合法转移 |
| --- | --- |
| Run | `created -> running/waiting_human/blocked -> succeeded/failed/cancelled`；任一非 terminal 可进入 `reconciliation_required` |
| NodeAttempt | `starting -> dispatching -> running/waiting_human -> succeeded/failed/blocked/cancelled` |
| Handoff | `pending -> ready/waiting_human -> accepted/rejected`；新版本可把旧记录置 `superseded` |
| Outbox | `pending -> leased -> succeeded`；可重试失败回 `pending`，不可恢复失败为 `failed` |
| HumanTask | `pending -> accepted/rejected/revised/cancelled` |

terminal 状态不可被普通 command 改回运行；重做必须创建新 attempt 或 fork child Run。

## 6. Workflow Ledger SQLite 设计

### 6.1 文件与连接策略

默认文件：

```text
%USERPROFILE%/Documents/Vibelution/data/research_workflows/workflow-ledger.sqlite3
```

测试必须显式注入临时路径。生产连接要求：

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;
PRAGMA temp_store = MEMORY;
```

- 使用项目已固定的 APSW 安全 SQLite runtime；
- 一个 writer connection；默认 4 个 read-only connections；
- writer queue 默认 `2048`，入队超时默认 `250ms`；
- command mutation 一律 `force_flush=True`，不与别的 command 共用提交语义；
- maintenance 与 migration 通过同一 writer 串行；
- startup 必须验证 SQLite 版本、WAL、`json_valid`、migration checksum 和 `integrity_check`；
- 任何能力不满足时启动失败，禁止回退 JSON store。

### 6.2 schema_migrations

```sql
CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  checksum TEXT NOT NULL,
  applied_at_ms INTEGER NOT NULL
);
```

迁移声明必须 deterministic；已应用 version 的 checksum 不一致时启动失败。

### 6.3 workflow_runs

```sql
CREATE TABLE workflow_runs (
  run_id TEXT PRIMARY KEY,
  team_id TEXT NOT NULL,
  workflow_id TEXT NOT NULL,
  workflow_version_id TEXT NOT NULL,
  thread_id TEXT NOT NULL UNIQUE,
  project_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN (
    'created','running','waiting_human','blocked',
    'reconciliation_required','succeeded','failed','cancelled','archived'
  )),
  run_version INTEGER NOT NULL CHECK (run_version >= 1),
  last_event_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_event_sequence >= 0),
  input_snapshot_json TEXT NOT NULL CHECK (json_valid(input_snapshot_json)),
  input_snapshot_hash TEXT NOT NULL,
  safety_limits_json TEXT NOT NULL CHECK (json_valid(safety_limits_json)),
  binding_snapshot_set_id TEXT NOT NULL,
  active_node_id TEXT,
  parent_run_id TEXT,
  forked_from_checkpoint_id TEXT,
  completion_kind TEXT,
  terminal_reason TEXT,
  blocked_problem_json TEXT CHECK (
    blocked_problem_json IS NULL OR json_valid(blocked_problem_json)
  ),
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  completed_at_ms INTEGER,
  FOREIGN KEY (parent_run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT
);

CREATE INDEX idx_workflow_runs_team_recent
ON workflow_runs(team_id, workflow_id, created_at_ms DESC, run_id DESC);

CREATE INDEX idx_workflow_runs_status
ON workflow_runs(status, updated_at_ms, run_id);
```

`input_snapshot_json` 只保存启动输入、题目版本、配置/预算快照引用；不复制资料、证据或实验数据。

### 6.4 workflow_commands

```sql
CREATE TABLE workflow_commands (
  command_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  team_id TEXT NOT NULL,
  node_id TEXT,
  command_kind TEXT NOT NULL,
  expected_run_version INTEGER NOT NULL,
  accepted_run_version INTEGER,
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  request_json TEXT NOT NULL CHECK (json_valid(request_json)),
  requested_by_json TEXT NOT NULL CHECK (json_valid(requested_by_json)),
  status TEXT NOT NULL CHECK (status IN ('accepted','completed','failed')),
  result_json TEXT CHECK (result_json IS NULL OR json_valid(result_json)),
  problem_json TEXT CHECK (problem_json IS NULL OR json_valid(problem_json)),
  created_at_ms INTEGER NOT NULL,
  completed_at_ms INTEGER,
  UNIQUE (run_id, idempotency_key),
  FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT
);

CREATE INDEX idx_workflow_commands_run_created
ON workflow_commands(run_id, created_at_ms DESC, command_id DESC);
```

相同 `(runId, idempotencyKey)`：

- `requestHash` 相同：返回原 CommandReceipt；
- `requestHash` 不同：`409 idempotency_conflict`；
- 幂等命中检查发生在 expectedVersion 检查之前，保证响应丢失后的安全重试。

### 6.5 node_attempts

```sql
CREATE TABLE node_attempts (
  node_run_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  attempt INTEGER NOT NULL CHECK (attempt >= 1),
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('agent','system','human')),
  status TEXT NOT NULL CHECK (status IN (
    'starting','dispatching','running','waiting_human','succeeded',
    'failed','blocked','cancelled','stale'
  )),
  command_id TEXT NOT NULL,
  binding_snapshot_id TEXT,
  input_snapshot_hash TEXT NOT NULL,
  pending_action_id TEXT,
  execution_anchor_id TEXT,
  retry_of_node_run_id TEXT,
  problem_json TEXT CHECK (problem_json IS NULL OR json_valid(problem_json)),
  started_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  finished_at_ms INTEGER,
  UNIQUE (run_id, node_id, attempt),
  FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
  FOREIGN KEY (command_id) REFERENCES workflow_commands(command_id) ON DELETE RESTRICT,
  FOREIGN KEY (retry_of_node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT
);

CREATE INDEX idx_node_attempts_run_status
ON node_attempts(run_id, status, node_id, attempt DESC);
```

`ready/pending` 是 projection，不作为 attempt 行；只有命令被接受后才创建 attempt。

### 6.6 workflow_events

```sql
CREATE TABLE workflow_events (
  run_id TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK (sequence >= 1),
  event_id TEXT NOT NULL UNIQUE,
  run_version INTEGER NOT NULL CHECK (run_version >= 1),
  event_type TEXT NOT NULL,
  actor_json TEXT NOT NULL CHECK (json_valid(actor_json)),
  correlation_id TEXT NOT NULL,
  causation_id TEXT,
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
  occurred_at_ms INTEGER NOT NULL,
  PRIMARY KEY (run_id, sequence),
  FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT
);
```

事件不可更新和删除。一个 command transaction 只增加一次 `runVersion`，但可分配连续多个 event sequence。

### 6.7 outbox_actions

```sql
CREATE TABLE outbox_actions (
  action_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  command_id TEXT,
  node_run_id TEXT,
  action_kind TEXT NOT NULL CHECK (action_kind IN (
    'graph_dispatch','adapter_dispatch','event_publish','reconcile'
  )),
  idempotency_key TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
  status TEXT NOT NULL CHECK (status IN (
    'pending','leased','succeeded','failed','cancelled'
  )),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  available_at_ms INTEGER NOT NULL,
  lease_owner TEXT,
  lease_expires_at_ms INTEGER,
  last_problem_json TEXT CHECK (
    last_problem_json IS NULL OR json_valid(last_problem_json)
  ),
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  CHECK (action_kind = 'reconcile' OR command_id IS NOT NULL),
  FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
  FOREIGN KEY (command_id) REFERENCES workflow_commands(command_id) ON DELETE RESTRICT,
  FOREIGN KEY (node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT
);

CREATE INDEX idx_outbox_ready
ON outbox_actions(status, available_at_ms, lease_expires_at_ms, action_id);
```

lease 领取必须在一个 `BEGIN IMMEDIATE` 事务中完成。过期 lease 可被重新领取；adapter 仍需使用 stable idempotency key 防止外部副作用重复。

### 6.8 execution_anchors

```sql
CREATE TABLE execution_anchors (
  anchor_id TEXT PRIMARY KEY,
  node_run_id TEXT NOT NULL UNIQUE,
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('agent','system','human')),
  agent_id TEXT,
  role_key TEXT,
  session_id TEXT,
  session_attempt INTEGER,
  task_id TEXT,
  turn_id TEXT,
  system_action_id TEXT,
  human_task_id TEXT,
  checkpoint_id TEXT,
  status TEXT NOT NULL,
  anchor_json TEXT NOT NULL CHECK (json_valid(anchor_json)),
  created_at_ms INTEGER NOT NULL,
  FOREIGN KEY (node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT
);
```

Agent anchor 的 `agent_id/session_id/task_id/turn_id` 全部非空才可把 attempt 置为 `running`。System/Human 由各自字段约束在 repository 层验证。

### 6.9 artifact_receipts 与 budget_receipts

```sql
CREATE TABLE artifact_receipts (
  receipt_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  node_run_id TEXT NOT NULL,
  team_id TEXT NOT NULL,
  artifact_kind TEXT NOT NULL,
  canonical_ref_json TEXT NOT NULL CHECK (json_valid(canonical_ref_json)),
  artifact_version TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  domain_revision TEXT NOT NULL,
  materialized INTEGER NOT NULL CHECK (materialized IN (0,1)),
  verified_at_ms INTEGER NOT NULL,
  UNIQUE (node_run_id, artifact_kind, artifact_version, sha256),
  FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
  FOREIGN KEY (node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT
);

CREATE TABLE budget_receipts (
  receipt_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  node_run_id TEXT NOT NULL,
  reservation_id TEXT NOT NULL UNIQUE,
  stage_id TEXT NOT NULL,
  policy_hash TEXT NOT NULL,
  reserved_json TEXT NOT NULL CHECK (json_valid(reserved_json)),
  settled_json TEXT CHECK (settled_json IS NULL OR json_valid(settled_json)),
  status TEXT NOT NULL CHECK (status IN ('reserved','settled','released','failed')),
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
  FOREIGN KEY (node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT
);
```

`canonical_ref_json` 只能是领域 Store 的稳定引用；不得写入 Artifact 正文。

### 6.10 handoffs 与 handoff_receipts

```sql
CREATE TABLE handoffs (
  handoff_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  from_node_run_id TEXT NOT NULL,
  to_node_id TEXT NOT NULL,
  to_node_run_id TEXT,
  gate_kind TEXT NOT NULL,
  input_snapshot_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN (
    'pending','ready','waiting_human','accepted','rejected',
    'superseded','failed'
  )),
  accepted_by_json TEXT CHECK (accepted_by_json IS NULL OR json_valid(accepted_by_json)),
  rejection_problem_json TEXT CHECK (
    rejection_problem_json IS NULL OR json_valid(rejection_problem_json)
  ),
  supersedes_handoff_id TEXT,
  offered_at_ms INTEGER NOT NULL,
  accepted_at_ms INTEGER,
  UNIQUE (run_id, edge_id, from_node_run_id, input_snapshot_hash),
  FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
  FOREIGN KEY (from_node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT,
  FOREIGN KEY (to_node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT,
  FOREIGN KEY (supersedes_handoff_id) REFERENCES handoffs(handoff_id) ON DELETE RESTRICT
);

CREATE TABLE handoff_receipts (
  handoff_id TEXT NOT NULL,
  receipt_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
  PRIMARY KEY (handoff_id, receipt_id),
  UNIQUE (handoff_id, ordinal),
  FOREIGN KEY (handoff_id) REFERENCES handoffs(handoff_id) ON DELETE RESTRICT,
  FOREIGN KEY (receipt_id) REFERENCES artifact_receipts(receipt_id) ON DELETE RESTRICT
);
```

`edgeId` 是 Handoff 业务身份的一部分；人工接受不得再生成一条自动 Handoff。

### 6.11 human_tasks、recovery_records、projection_cursors

```sql
CREATE TABLE human_tasks (
  task_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  node_run_id TEXT NOT NULL,
  handoff_id TEXT,
  task_kind TEXT NOT NULL,
  prompt_json TEXT NOT NULL CHECK (json_valid(prompt_json)),
  status TEXT NOT NULL CHECK (status IN ('pending','accepted','rejected','revised','cancelled')),
  decision_json TEXT CHECK (decision_json IS NULL OR json_valid(decision_json)),
  created_at_ms INTEGER NOT NULL,
  resolved_at_ms INTEGER,
  FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT,
  FOREIGN KEY (node_run_id) REFERENCES node_attempts(node_run_id) ON DELETE RESTRICT,
  FOREIGN KEY (handoff_id) REFERENCES handoffs(handoff_id) ON DELETE RESTRICT
);

CREATE TABLE recovery_records (
  recovery_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  problem_code TEXT NOT NULL,
  evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
  status TEXT NOT NULL CHECK (status IN ('open','resolved','waived')),
  resolution_json TEXT CHECK (resolution_json IS NULL OR json_valid(resolution_json)),
  created_at_ms INTEGER NOT NULL,
  resolved_at_ms INTEGER,
  FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE RESTRICT
);

CREATE TABLE projection_cursors (
  projection_name TEXT NOT NULL,
  run_id TEXT NOT NULL,
  last_sequence INTEGER NOT NULL CHECK (last_sequence >= 0),
  updated_at_ms INTEGER NOT NULL,
  PRIMARY KEY (projection_name, run_id),
  FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE CASCADE
);
```

## 7. 单写入事务协议

### 7.1 Unit of Work

所有正式 mutation 通过：

```python
ledger.writer.submit(
    lambda uow: command_handler.handle(uow, request),
    force_flush=True,
).result(timeout=...)
```

`WorkflowLedgerUnitOfWork` 提供：

```text
runs
commands
attempts
events
outbox
handoffs
human_tasks
anchors
artifact_receipts
budget_receipts
recovery
after_commit(callback)
```

repository 不允许进行网络请求、文件系统领域读取、Agent 调用或 LangGraph invoke。

### 7.2 命令受理顺序

`start_node` 的同步受理算法：

1. route 校验 `teamId` 非空，只构造 typed request；
2. Command Service 读取 Run 并校验 Run 的 `teamId` 精确相等；
3. 计算 canonical JSON `requestHash`；
4. 先查 `(runId, idempotencyKey)`：同 hash 返回原结果，不同 hash 返回 `409`；
5. 校验 `expectedRunVersion`；
6. 从领域事实源重新计算 `NodeReadiness`；
7. 不 ready：返回 `412 node_not_ready` 及 blockers，不写预算、TaskBundle、Session、Turn、Attempt、Handoff；可记录拒绝 metric，但不改变 Run version；
8. ready：进入一个 `BEGIN IMMEDIATE` Ledger transaction；
9. 再次按版本条件更新 Run，`runVersion + 1`；
10. 插入 accepted command；
11. 插入 `NodeAttempt(status='starting')`；
12. 插入 `graph_dispatch` outbox；
13. 分配 event sequence，插入 `command_accepted`、`node_starting`；
14. 提交后才唤醒 outbox worker；
15. 返回 `202 CommandReceipt` 和新 Snapshot token。

版本更新必须使用条件语句：

```sql
UPDATE workflow_runs
SET run_version = run_version + 1,
    last_event_sequence = last_event_sequence + :event_count,
    updated_at_ms = :now
WHERE run_id = :run_id
  AND team_id = :team_id
  AND run_version = :expected_version
RETURNING run_version, last_event_sequence;
```

返回零行即 `409 run_version_conflict`。

### 7.3 外部副作用顺序

严禁在 Ledger transaction 中执行外部副作用。正式顺序：

```text
Command transaction
  -> graph_dispatch outbox
  -> Graph Worker invoke/resume
  -> PendingAction interrupt
  -> Ledger transaction 写 adapter_dispatch
  -> Adapter Worker 再次 read-back readiness 输入
  -> Budget reservation
  -> TaskBundle / Session / Task / Turn 或 system action
  -> Domain adapter write
  -> Domain read-back + hash/version verification
  -> Ledger transaction 写 receipts + graph_dispatch resume
  -> Graph Worker Command(resume=ExecutionReceipt)
  -> Ledger transaction 写 completion/handoff/next state/events
```

任何步骤失败都必须能由 stable action id 重试或进入显式 `blocked/reconciliation_required`。

### 7.4 after-commit

- SSE/condition variable 只在 commit 后通知；
- after-commit callback 失败不回滚已经提交的 command；
- `event_publish` outbox 或基于 Ledger tail 的补偿负责恢复通知；
- 不允许先向浏览器推 event 再提交数据库。

## 8. LangGraph 正式 Runner

### 8.1 GraphState

GraphState 只保存控制引用：

```python
class ChallengeCupGraphState(TypedDict):
    run_id: str
    team_id: str
    workflow_version_id: str
    input_snapshot_hash: str
    active_node_id: str
    active_attempt: int
    pending_action_id: str | None
    last_receipt_id: str | None
    branch_decision: str | None
    checkpoint_version: int
```

禁止保存资料正文、Evidence graph、实验指标、预算余额、完整会话或 Canvas projection。

### 8.2 节点函数模板

Agent/System 节点函数必须保持可重放：

```python
def source_extraction_node(state: ChallengeCupGraphState):
    pending = build_pending_action_from_state(state)
    receipt = interrupt(pending.to_dict())
    verified = ExecutionReceipt.from_dict(receipt)
    verified.assert_matches(pending.action_id, pending.node_run_id)
    return apply_receipt_to_graph_state(state, verified)
```

由于 LangGraph resume 会从节点开头重新执行，`interrupt()` 之前不得有外部副作用。`action_id` 必须由 Ledger 预先冻结，重放得到相同值。

Human 节点同样使用 `interrupt(HumanTaskInput)`；用户点击接受/拒绝后，由 command 写 decision receipt 和 `graph_dispatch`，Runner 使用 `Command(resume=...)` 恢复。

### 8.3 GraphCoordinator API

```python
class ChallengeCupGraphCoordinator:
    def start_attempt(self, dispatch: GraphDispatch) -> GraphDispatchResult: ...
    def resume_action(self, dispatch: GraphDispatch) -> GraphDispatchResult: ...
    def resume_human(self, dispatch: GraphDispatch) -> GraphDispatchResult: ...
    def snapshot(self, run_id: str, thread_id: str) -> GraphSnapshotRef: ...
    def fork_from_checkpoint(self, request: ForkRequest) -> ForkReceipt: ...
```

生产 service 不再调用 `update_state(..., as_node=...)` 宣称外部任务已完成。切换后 grep 门禁必须确保该模式只出现在迁移/测试说明中。

### 8.4 分支语义

`iteration_decision`：

- `rerun_same_protocol`：同 Run 新建 `controlled_run` attempt；
- `revise_protocol`：从实验设计 checkpoint fork 新 Run；父 Run 保持不可变 lineage；
- `promote_candidate`、`rollback_candidate`、`stop`：进入 `version_governance`；
- 未识别 decision：Graph 不前进，Run 进入 blocked，返回显式问题。

`revision fork` 必须在一个 Ledger transaction 中创建 child Run、parent/child event 和 graph dispatch；checkpoint fork 成功后再提交 child 可运行状态。若 checkpoint fork 已发生但 Ledger 未提交，reconciler 标记并清理孤立 checkpoint，不猜测 child 成功。

## 9. NodeReadiness 详细矩阵

### 9.1 公共检查顺序

每个 evaluator 先执行同一组公共检查：

1. `teamId` 与 Run、Project、Artifact、Agent binding 精确一致；
2. Run 非 terminal，且不处于 `reconciliation_required`；
3. `nodeId` 属于冻结的 WorkflowDefinition；
4. 节点是当前合法后继，不存在同节点 live attempt；
5. 所有入边 Handoff 为 accepted，receipt 可 read-back；起始节点除外；
6. RunAgentBindingSnapshot 存在且 Agent 当前可解析；Human/System 节点验证相应能力；
7. Budget policy 可容纳一次新 attempt，未触发全局循环上限；
8. Domain revision vector 可读取且无 corruption；
9. 对应 adapter 已注册并健康；
10. 未解决的 blocking recovery record 为零。

任何失败都返回 stable blocker，不抛 raw exception 给 UI。

### 9.2 节点矩阵

| 节点 | 领域权威 | 必需输入与 read-back | 主要 blocker | 输出 receipt |
| --- | --- | --- | --- | --- |
| `source_finding` | Question authority + Source Collection | 冻结题目、检索范围、来源策略、项目 | `question_snapshot_missing` | `source_candidate_batch` |
| `source_extraction` | Source Collection | 当前 Run 的 candidate/data record 数量 > 0，来源可打开，provenance 完整 | `source_candidates_missing` | `evidence_card_batch` |
| `evidence_relations` | Evidence Store | evidence cards 已物化、版本/hash 可读、最小主张字段完整 | `evidence_cards_missing` | `evidence_relation_graph` |
| `knowledge_ingestion` | Evidence + Knowledge Store | graph 可解析；blocking missing links 为零或有有效 waiver | `evidence_graph_incomplete` | `knowledge_package_draft` |
| `knowledge_handoff` | Knowledge Store | draft 已正式写回；冲突、重复和 provenance 审计完成 | `knowledge_package_not_reviewable` | `knowledge_package` |
| `hypothesis_design` | Workflow Handoff + Knowledge Store | accepted `knowledge_package`，version/hash 固定 | `knowledge_handoff_not_accepted` | `hypothesis_set` |
| `protocol_design` | Experiment Store | hypothesis 可证伪，变量、失败条件、baseline 已定义 | `hypothesis_contract_incomplete` | `protocol_draft` |
| `protocol_review` | Experiment Store | dataset/baseline/metric/seed/预算/停止条件齐全 | `protocol_draft_incomplete` | `protocol_review_report` |
| `protocol_freeze` | Experiment Store | 阻塞问题为零；waiver 有操作者、理由、时间 | `protocol_review_blocked` | `frozen_protocol` |
| `smoke_gate` | Experiment Runner + Artifact Store | frozen protocol；smoke 已真实运行，日志/metric/artifact 完整 | `smoke_evidence_missing` | `smoke_evidence`,`smoke_release` |
| `controlled_run` | Formal Runner + Budget Ledger | accepted smoke release、同一 frozen protocol、执行资源可用 | `formal_run_not_released` | `run_artifacts` |
| `result_evaluation` | Experiment Store | runner terminal；日志、metric、artifact hash 完整 | `run_artifacts_incomplete` | `evaluation_report` |
| `iteration_decision` | Evaluation Store | baseline 对比、失败、置信边界、版本引用完整 | `evaluation_incomplete` | `iteration_decision` |
| `version_governance` | Version/Experiment Store | decision kind、目标版本、lineage、理由一致 | `version_lineage_invalid` | `version_governance_record` |
| `candidate_promotion` | Promotion Store | 仅 promote；proposal 与治理记录、candidate hash 一致 | `promotion_proposal_invalid` | `promotion_proposal` |
| `result_package` | Result Package service | 必需 artifacts 完整、未决 HumanTask=0、终止原因明确 | `result_package_incomplete` | `research_result_package` |

### 9.3 evaluator registry

```python
READINESS_EVALUATORS: Mapping[str, NodeReadinessEvaluator] = {
    "source_finding": SourceFindingReadiness(...),
    ...
}
```

缺少 evaluator 时启动测试失败，不把未知节点视为不可执行的普通状态。Definition 的 node set 与 registry key set 必须完全相等。

### 9.4 副作用零增长断言

每个 readiness RED case 都要记录并比较：

```text
budget reservation count
task bundle count
session count
turn count
node attempt count
accepted handoff count
outbox external-action count
```

拒绝前后必须完全相同。

## 10. Adapter 与收据

### 10.1 ActionAdapter 协议

```python
class ActionAdapter(Protocol):
    action_kind: str
    def preflight(self, action: PendingAction) -> AdapterPreflight: ...
    def execute(self, action: PendingAction, context: ExecutionContext) -> AdapterResult: ...
    def verify(self, result: AdapterResult) -> VerifiedDomainResult: ...
```

所有 adapter 必须：

- 接收 stable `actionId` 作为 idempotency key；
- 先 read-back 输入 ref/hash；
- 预算 reservation 成功后才创建 TaskBundle/Session/Turn；
- 创建外部对象后立刻持久其 id，避免 crash 后无法 reconcile；
- 完成后从领域 Store 重新读取，而不是信 Agent 返回文本；
- verify 成功才生成 ArtifactReceipt；
- retry 不重复创建同一外部副作用。

### 10.2 Agent adapter

Agent 节点顺序：

1. 解析冻结 `RunAgentBindingSnapshot`；
2. 验证 Agent 配置、模型、工具和 session authority；
3. 预算 reservation；
4. 创建/复用项目 Agent session attempt；
5. 创建 TaskBundle 与 task；
6. 提交 turn；
7. 写回完整 `sessionId/taskId/turnId`；
8. Ledger 写 `ExecutionAnchor` 后，attempt 才进入 `running`；
9. 任务完成后验证 artifact manifests；
10. 领域 Store read-back；
11. 写 ArtifactReceipt 与预算 settlement；
12. 返回 ExecutionReceipt。

若步骤 4-7 只完成一部分，进入 reconcile；不得把空字段 anchor 标成 running。

### 10.3 System adapter

`controlled_run` 和 `result_package` 走 system action：

- 使用受管 no-console helper / `pythonw` / `CREATE_NO_WINDOW`；
- 不允许裸 `cmd.exe`、PowerShell 窗口或 `taskkill.exe`；
- action lease、process/job id、artifact root 进入 System ExecutionAnchor；
- crash 后由 lease + artifact read-back 判断，不依靠内存 future。

### 10.4 Human adapter

Human 节点不预留模型 token，不创建 Agent task。它创建 `human_tasks` 并等待显式 command。人工决策必须记录 operator、理由（拒绝/waiver 必填）、输入 snapshot hash 和 decision receipt。

## 11. HTTP API 硬收敛

### 11.1 保留的读取接口

```text
GET  /api/research/workflows/{workflowId}/definition
GET  /api/research/workflows/{workflowId}/launch-options?teamId=...
GET  /api/research/workflows/{workflowId}/runs?teamId=...
GET  /api/research/workflows/{workflowId}/agent-bindings/effective?teamId=...
GET  /api/research/workflow-runs/{runId}/snapshot?teamId=...
GET  /api/research/workflow-runs/{runId}/nodes/{nodeId}?teamId=...
GET  /api/research/workflow-runs/{runId}/events?teamId=...&afterSequence=...
GET  /api/research/workflow-runs/{runId}/stream?teamId=...
GET  /api/research/workflow-runs/{runId}/handoffs?teamId=...
GET  /api/research/workflow-runs/{runId}/research-ledger?teamId=...
GET  /api/research/workflow-runs/{runId}/budget?teamId=...
GET  /api/research/workflow-runs/{runId}/hypotheses?teamId=...
GET  /api/research/workflow-runs/{runId}/experiment-campaigns?teamId=...
GET  /api/research/workflow-runs/{runId}/evaluation?teamId=...
```

`snapshot` 替代分别请求 run + canvas 后再由前端拼接的主读取路径。领域面板可按需加载独立 projection。

切换时同时删除当前重复的：

```text
GET /api/research/workflow-runs/{runId}
GET /api/research/workflow-runs/{runId}/canvas
```

### 11.2 写接口

```text
POST /api/research/workflows/{workflowId}/runs
POST /api/research/workflow-runs/{runId}/commands
PUT  /api/research/workflows/{workflowId}/agent-bindings
```

`PUT agent-bindings` 只改未来 Run 配置；运行中换绑必须发 `rebind_node` command。

`requestedBy`、operator identity 和权限由服务端请求上下文生成，客户端不得自报。`resolve_human_task`、`rebind_node`、预算扩容、取消、fork 和 promotion 等命令必须经过 operator authorization；权限不足返回 `403 command_forbidden`，不得降级为匿名 operator。

以下接口切换时删除：

```text
POST /api/research/workflow-runs/{runId}/nodes/{nodeId}/commands
PUT  /api/research/workflow-runs/{runId}/nodes/{nodeId}/session-binding
POST /api/research/workflow-runs/{runId}/human-tasks/{taskId}/resolve
```

人工决策统一为：

```json
{
  "teamId": "research-team",
  "nodeId": "knowledge_handoff",
  "command": "resolve_human_task",
  "expectedRunVersion": 12,
  "idempotencyKey": "...",
  "payload": {"taskId": "...", "decision": "accept", "reason": "..."}
}
```

### 11.3 SnapshotResponse

```ts
export type ResearchWorkflowSnapshot = {
  run: WorkflowRunSummary;
  definition: WorkflowDefinition;
  nodeAttempts: Record<ChallengeCupNodeId, NodeAttemptSummary[]>;
  activeNodeIds: ChallengeCupNodeId[];
  pendingHumanTasks: HumanTaskSummary[];
  commandOffers: CommandOffer[];
  handoffSummary: HandoffSummary;
  agentBindingSummary: AgentBindingSummary;
  budgetSummary: BudgetSummary;
  latestEventSequence: number;
  generatedAt: string;
};
```

Snapshot 中不包含选中节点、打开面板、缩放或其他 UI state。

### 11.4 CommandReceipt

成功受理返回 `202`：

```json
{
  "commandId": "cmd-...",
  "runId": "run-...",
  "status": "accepted",
  "acceptedRunVersion": 18,
  "idempotencyKey": "...",
  "latestEventSequence": 74,
  "problem": null
}
```

同步拒绝不创建 command 行时返回结构化 HTTP error；已受理后的异步失败通过 event/snapshot 体现。

### 11.5 错误映射

| HTTP | code | 语义 |
| --- | --- | --- |
| 404 | `run_not_found` / `team_scope_mismatch` | 资源不存在或不属于 team |
| 403 | `command_forbidden` | 当前 operator 无该命令权限 |
| 409 | `run_version_conflict` | 页面版本已过期，刷新 Snapshot |
| 409 | `idempotency_conflict` | 同 key 不同请求 |
| 409 | `command_not_allowed` | 当前状态不允许该命令 |
| 412 | `node_not_ready` | 依赖未满足，包含 blockers/remediation |
| 429 | `budget_safety_limit_reached` | 防无限循环上限 |
| 503 | `workflow_ledger_unavailable` | Ledger 不可用，禁止 fallback |
| 503 | `workflow_migration_required` | 未完成硬切换或校验失败 |
| 503 | `workflow_reconciliation_required` | 状态需人工/后台对账 |

## 12. Event 与 SSE

### 12.1 EventEnvelope

```ts
export type WorkflowEventEnvelope<TType extends string, TPayload> = {
  eventId: string;
  sequence: number;
  runId: string;
  teamId: string;
  runVersion: number;
  type: TType;
  correlationId: string;
  causationId?: string;
  occurredAt: string;
  payload: TPayload;
};
```

不得继续使用 `Array<Record<string, unknown>>` 作为主事件合同。所有 event type 进入 registry，并有 Python/TypeScript contract fixture。

### 12.2 传输

- SSE `id` 使用 `{runId}:{sequence}`；
- 浏览器首读 Snapshot，随后从 `latestEventSequence` 建立 stream；
- `Last-Event-ID` 重连时从 Ledger 重放，不依赖进程内缓存；
- event sequence 重复则 reducer 丢弃；
- sequence 出现 gap 则停止增量合并并重新读取 Snapshot；
- runId 改变时立即关闭旧连接、清空 cursor/error/pending command；
- 慢旧请求不得覆盖新 run；
- Snapshot 空 event 不触发无条件全量刷新循环。

### 12.3 事件最小集合

```text
run_created
command_accepted
command_failed
node_starting
node_running
node_waiting_human
node_succeeded
node_failed
node_blocked
handoff_ready
handoff_accepted
handoff_rejected
budget_reserved
budget_settled
execution_anchor_bound
artifact_verified
run_forked
run_blocked
run_succeeded
reconciliation_required
```

## 13. 前端状态与交互

### 13.1 三类状态严格分离

1. **Server state：** Snapshot、NodeDetail、领域 projection、events；React Query/专用 hooks 管理。
2. **URL state：** `teamId/researchView/workflowId/runId/node/panel/questionId`；只由 route parser 管理。
3. **Ephemeral UI state：** dialog open、hover、canvas viewport；不得写入 URL 或 server projection。

不得在一个 hook 中同时拥有 fetch、event reducer、URL replace、command mutation 和展示文案。

### 13.2 Toolbar

- “创建运行”在已有 run 时仍可见；
- 运行选择项显示：`SCI-096 · 2026-08-12 14:30 · 等待处理`；
- raw `run-xxxx · blocked` 只放 Tooltip/技术详情；
- 创建后通过正式 response 中的 `runId` 导航；
- 切 run 清理 command error、pending state 和旧 node selection；
- 选项来自当前 `teamId + workflowId`，不跨 team 混合。

### 13.3 Node Inspector

按固定顺序展示：

```text
节点状态
当前操作（CommandOffer）
阻塞与修复动作
Agent 配置
执行锚点 / 继续会话
输入输出 Artifact
Handoff
预算与时间线
```

Agent 区分三件事：

- 当前配置：未来执行用哪个 Agent；
- 本 attempt 执行锚点：实际用了哪个 Agent/session/task/turn；
- 会话操作：继续会话或显示锚点不可用。

“未绑定会话”只在 attempt 尚未执行时出现；若 attempt 为 running/succeeded 但 anchor 缺失，显示错误并禁止伪装成功。

### 13.4 Command UI

- 按钮只来自 `CommandOffer.available=true`；
- unavailable offer 不渲染成可点击按钮，可在状态区域显示 blocker；
- 点击期间按 `commandId` 局部 pending，不锁死无关按钮；
- `409 run_version_conflict` 自动刷新 Snapshot 并提示“状态已更新，请确认后重试”；
- `412 node_not_ready` 用 `remediation` 导航，不显示 raw adapter 文本；
- destructive command 使用 VUI confirmation；
- 不在前端生成业务 payload，只回传 Offer payload。

### 13.5 VUI 门禁

- 页面只使用 `web/src/components/vui` 的 `V*` API；
- 若新增 VUI 元素，先查重，再增加 `designs/` 专节和 `designs/INDEX.md`；
- 页面不 import `components/vui/renderers/shadcn/*`；
- 布局宽度只通过 `WORKBENCH_LAYOUT_IDS` 和 shared persistence；
- 必跑 `vuiShadcnRouteContract.test.ts`、`vuiComponentDesignContract.test.ts`。

## 14. 数据迁移与硬切换

### 14.1 不做的事

- 不双写 JSON + SQLite；
- 不在读取失败时切回 JSON；
- 不保留 `/nodes/{nodeId}/commands` 代理；
- 不把损坏记录当空状态；
- 不自动把无法证明一致的历史 Run 标成成功；
- 不在 Launcher 仍有 active work 时切换。

### 14.2 迁移状态

durable data root 保存：

```text
research_workflows/migration/
  workflow-ledger-v1-manifest.json
  workflow-ledger-v1-audit.json
  workflow-ledger-v1-apply.json
  workflow-ledger-v1-verify.json
  backups/<timestamp>/...
```

manifest 状态：

```text
not_started -> audited -> backup_verified -> imported -> verified -> activated
```

任一未知错误进入 `failed`，Runtime 返回 `workflow_migration_required`，不 fallback。

### 14.3 CLI

```powershell
.venv\Scripts\python.exe scripts\audit_research_workflow_runtime.py `
  --data-root <path> --output <audit.json>

.venv\Scripts\python.exe scripts\migrate_research_workflow_ledger.py dry-run `
  --data-root <path> --report <dry-run.json>

.venv\Scripts\python.exe scripts\migrate_research_workflow_ledger.py apply `
  --data-root <path> --backup-root <path> --report <apply.json>

.venv\Scripts\python.exe scripts\migrate_research_workflow_ledger.py verify `
  --data-root <path> --report <verify.json>
```

CLI 必须显式参数化 data root；测试不得触碰正式用户目录。

### 14.4 validator 分类

每个旧 Run 只能进入以下一类：

```text
migratable
archivable_terminal
reconciliation_required
corrupt
duplicate_identity
scope_mismatch
```

`migratable` 必须通过：

- `teamId/workflowId/questionId/runId` 完整；
- runVersion、event sequence 单调；
- edgeId Handoff 唯一且 lineage 可解释；
- checkpoint thread 可解析；
- Artifact ref 可 read-back 或明确为历史归档；
- Agent session/task/turn anchor 对 running/succeeded attempt 完整；
- budget reservation/settlement 可对账；
- parent/child fork 无环。

其他类别进入报告，不自动修复语义。

### 14.5 apply

1. 要求 runtime stopped、active work=0；
2. 创建完整 data-root backup；
3. 校验 backup 可读与 hash；
4. 创建临时 Ledger 数据库；
5. 导入可迁移记录；
6. `integrity_check`、FK check、计数/hash/lineage 对账；
7. 原子 rename 激活数据库；
8. 写 activation marker；
9. 启动新版本；
10. 跑只读 runtime canary；
11. 通过后才删除旧 writer 代码引用，旧数据备份按治理策略保留。

### 14.6 rollback

回滚单位是“旧版本二进制 + 整个迁移前数据目录”。禁止新版本运行时动态回读旧 JSON。若新版本已产生正式新 command，必须先停止并保全新 Ledger，再由 Owner 决定是否允许整包回滚。

## 15. 实施任务图

```text
T0 基线冻结与迁移审计
  -> T1 contracts + Workflow Ledger
      -> T2 NodeReadiness
      -> T3 Command transaction + outbox
          -> T4 LangGraph interrupt/resume Runner
              -> T5 Adapters + receipts + Agent anchors
      -> T6 Query/Snapshot/Event/SSE
T5 + T6
  -> T7 Frontend hard cutover
T0 + T1..T7
  -> T8 Data migration + legacy deletion
T8
  -> T9 Launcher pure-click acceptance + cleanup
```

允许 T2 与 T3 在 T1 合同冻结后并行，但不得同时改同一 contract 文件。T7 不得在 T6 DTO 未冻结时先造前端第二套类型。

## 16. 开发任务卡

### T0 · 基线冻结与审计

**目标：** 证明当前 writer、route、数据和运行对象的真实范围。

**允许路径：** `scripts/audit_research_workflow_runtime.py`、focused tests、审计报告模板。

**RED：** fixture 含重复 Handoff、损坏 JSON、scope mismatch、缺 anchor 时审计必须失败并分类。

**GREEN：** 输出旧 Run 数、event/handoff/task/binding 数、checkpoint 数、领域 ref 可读性、orphan Session/Task/reservation、旧 route/import inventory。

**停止条件：** 正式数据中出现无法分类的记录或 active work 非零；不得开始 apply。

### T1 · Contracts 与 Workflow Ledger

**目标：** 建立 schema、repository、single writer 和纯领域合同。

**允许路径：** `core/research/workflow/contracts/`、`core/research/workflow/ledger/`、新 focused tests。

**RED tests：**

```text
test_research_workflow_ledger_schema.py
test_research_workflow_ledger_writer.py
test_research_workflow_ledger_idempotency.py
test_research_workflow_ledger_concurrency.py
test_research_workflow_contract_serialization.py
```

必须覆盖：migration checksum、FK、corruption fail-closed、队列 backpressure、并发 expectedVersion、同 key 同响应、同 key 异请求冲突、commit 前不发布。

**GREEN：** focused tests + Ruff + compileall；不接生产 route。

### T2 · NodeReadiness

**目标：** 16 个节点全量 registry 和同源 blocker。

**允许路径：** `research_runtime/readiness/`、contracts、focused fakes/tests。

**RED tests：**

```text
test_research_workflow_readiness_common.py
test_research_workflow_readiness_source_collection.py
test_research_workflow_readiness_experiment.py
test_research_workflow_readiness_iteration.py
test_research_workflow_readiness_registry.py
test_research_workflow_readiness_no_side_effects.py
```

**GREEN：** definition node set == evaluator key set；SCI-096 缺 candidate 时 Canvas 与 command 同时给 `source_candidates_missing`，所有副作用计数零增长。

### T3 · Command transaction 与 outbox

**目标：** 单命令入口、typed handler、lease worker primitives。

**允许路径：** `command_service.py`、Ledger repository/outbox、route DTO、focused tests。

**RED tests：**

```text
test_research_workflow_command_transaction.py
test_research_workflow_command_idempotency.py
test_research_workflow_outbox_leasing.py
test_research_workflow_command_team_scope.py
test_research_workflow_command_version_conflict.py
```

**GREEN：** command/status/outbox/event 同事务；crash 注入不产生半提交；`teamId` 缺失/不匹配显式失败。

### T4 · LangGraph 正式 Runner

**目标：** 16 节点 interrupt/resume、human interrupt、迭代分支、fork。

**允许路径：** `core/research/workflow/challenge_cup_graph.py`、新的 coordinator、graph dispatch worker、tests。

**RED tests：**

```text
test_research_workflow_graph_interrupt_resume.py
test_research_workflow_graph_human_interrupt.py
test_research_workflow_graph_iteration_routes.py
test_research_workflow_graph_fork_lineage.py
test_research_workflow_graph_crash_recovery.py
```

**GREEN：** checkpoint restart 后相同 actionId；节点函数 interrupt 前无副作用；生产 grep 不再使用 `update_state(as_node)` 推进业务节点。

### T5 · Adapter、收据与 Agent 锚点

**目标：** 真实业务 adapter 通过 outbox 执行并生成可验证 receipt。

**允许路径：** `action_registry.py`、adapter worker、现有各领域 adapter 的小范围重构、focused tests。

**RED tests：**

```text
test_research_workflow_adapter_readback.py
test_research_workflow_adapter_idempotency.py
test_research_workflow_agent_anchor.py
test_research_workflow_budget_ordering.py
test_research_workflow_artifact_receipt.py
test_research_workflow_reconciliation.py
```

**GREEN：** readiness 通过前无 reservation；Agent running 前完整 anchor；Artifact 不可读/hash 不符时 Handoff 不 accepted；外部成功/本地 crash 可 reconcile。

### T6 · Query、Snapshot、Event、SSE

**目标：** 统一读取面和可恢复 event transport。

**允许路径：** query/projection/event service、read routes、Python/TS contracts。

**RED tests：**

```text
test_research_workflow_snapshot_projection.py
test_research_workflow_event_sequence.py
test_research_workflow_sse_replay.py
test_research_workflow_sse_commit_visibility.py
researchWorkflow.contract.test.ts
researchWorkflowEventReducer.test.ts
```

**GREEN：** Snapshot 可由 Ledger+Domain Store 重建；SSE 重连无丢失/重复；gap 强制 snapshot reload；跨 run 慢请求不覆盖。

### T7 · 前端硬切换

**目标：** Toolbar、Canvas、Inspector、Agent/Session、Timeline 全部消费新 Snapshot/Offer。

**允许路径：** `web/src/api/research-workflow/`、types、现有 research-workflow route/components、必要 VUI design。

**RED tests：**

```text
ResearchWorkflowToolbar.test.tsx
useResearchWorkflowSnapshot.test.tsx
useResearchWorkflowCommand.test.tsx
ResearchProcessNodeInspector.test.tsx
researchWorkflowNavigation.test.ts
researchWorkflowEventReducer.test.ts
vuiShadcnRouteContract.test.ts
vuiComponentDesignContract.test.ts
```

**GREEN：** 已选 Run 仍能创建新 Run；运行标签用户可读；command error 随 run/node 切换清空；Agent 节点可精确进入 task/turn；按钮与后端 Offer 完全一致；无旧 API import。

### T8 · 数据迁移与 legacy 删除

**目标：** 一次性硬切换，删除第二写入路径。

**允许路径：** migration package/scripts、启动 wiring、旧 writer/route 删除、legacy contract tests。

**RED tests：**

```text
test_research_workflow_migration_inventory.py
test_research_workflow_migration_apply.py
test_research_workflow_migration_corruption.py
test_research_workflow_migration_scope.py
test_research_workflow_legacy_cleanup.py
researchLegacySurfaceInventory.test.ts
```

**GREEN：** dry-run 零 unknown；apply/verify 计数/hash/lineage 一致；旧 writer、node command route、session binding route、旧页面入口无生产引用；新 Ledger 不可用时 503 而非 fallback。

### T9 · Runtime 验收与清理

**目标：** Launcher 环境纯点击跑完 SCI-096，并清理任务产生的临时状态。

**前置：** 所有代码已在任务分支提交并通过 merge gate；active work=0；前端 `tsc -b`/build 已绿；Launcher refresh 经 Owner 执行。

**验收：** 见第 18 节。

**清理：** 测试 Run、orphan Session/Task/reservation、迁移临时文件、旧 design 注册、未连接 route、过期文档；不删除正式验收 artifact/evidence。

## 17. 自动化验证命令

执行 Agent 应按任务先 focused，再相邻回归，最后完整交付门禁。命令中的新测试文件在对应任务创建。

### 17.1 Backend focused

```powershell
.venv\Scripts\python.exe -m pytest `
  tests/test_research_workflow_ledger_schema.py `
  tests/test_research_workflow_ledger_writer.py `
  tests/test_research_workflow_command_transaction.py `
  tests/test_research_workflow_readiness_no_side_effects.py `
  tests/test_research_workflow_graph_interrupt_resume.py `
  tests/test_research_workflow_adapter_readback.py `
  tests/test_research_workflow_snapshot_projection.py -q
```

### 17.2 Existing adjacent regression

```powershell
.venv\Scripts\python.exe -m pytest `
  tests/test_research_workflow_challenge_cup_graph.py `
  tests/test_research_workflow_langgraph_vertical_slice.py `
  tests/test_research_workflow_v21_contract.py `
  tests/test_research_workflow_v21_team_scope_version.py `
  tests/test_research_workflow_v21_agent_execution.py `
  tests/test_research_workflow_v21_handoff_recovery.py `
  tests/test_research_workflow_v21_stream_result_package.py `
  tests/test_research_workflow_v21_legacy_cleanup.py -q
```

旧 vertical slice test 在 T8 必须被改写为正式 Runner contract 或删除；不能长期验证已移除行为。

### 17.3 Frontend

```powershell
cd web
npm run test -- --run `
  src/api/types/researchWorkflow.contract.test.ts `
  src/routes/teams/research-workflow/useResearchWorkflowSnapshot.test.tsx `
  src/routes/teams/research-workflow/useResearchWorkflowCommand.test.tsx `
  src/routes/teams/research-workflow/researchWorkflowEventReducer.test.ts `
  src/routes/teams/research-workflow/ResearchProcessNodeInspector.test.tsx `
  src/routes/teams/research-workflow/researchWorkflowNavigation.test.ts `
  src/components/vui/vuiShadcnRouteContract.test.ts `
  src/components/vui/vuiComponentDesignContract.test.ts
npx tsc -b --pretty false
npm run build
```

### 17.4 Static guards

```powershell
rg -n "update_state\(.*as_node|WorkflowRunStore|DurableWorkflowIndex" core web tests
rg -n "nodes/\{node_id\}/commands|session-binding|human-tasks/.*/resolve" core web
rg -n "team_id|research-team" core/web/routes/team_workflows/research_runtime.py web/src/routes/teams/research-workflow
git diff --check
```

结果必须按 allowlist 审查；生产运行路径不得命中旧 writer/route/fallback。

### 17.5 交付门禁

- Ruff/compileall；
- focused + adjacent backend；
- focused frontend + VUI contracts；
- `npx tsc -b --pretty false`；
- `npm run build`；
- migration dry-run/verify fixtures；
- local quality gate/manifest；
- task worktree clean；
- 当前 main 仍是 task HEAD 祖先或已重放并复验。

## 18. SCI-096 纯点击实机验收

验收必须在正式 Launcher Workbench 中进行，验收员只能使用可见鼠标和键盘。

### 18.1 启动

1. 打开 Teams → 挑战杯科研团队；
2. 选择 `SCI-096`；
3. 点击“创建运行”；
4. 验证新 Run 出现在用户可读选择器中；
5. 验证题目、三阶段、Agent 分工和安全预算快照一致。

### 18.2 知识搜集

1. 进入“资料寻找”，点击后端 Offer 对应动作；
2. 打开 Agent 会话，验证定位到本节点 task/turn，再返回原节点；
3. 完成资料寻找，确认候选资料 Artifact 出现；
4. 逐个完成资料提炼、证据关系、知识入库；
5. 在知识包交接人工接受；
6. 验证实验设计只在 accepted Handoff 后解锁。

### 18.3 实验设计

1. 完成假设设计、协议设计、协议评审；
2. 人工冻结协议；
3. 运行 Smoke 并查看真实日志/指标/Artifact；
4. 人工放行；
5. 验证受控运行只在 frozen protocol + smoke release 都有效时可执行。

### 18.4 执行迭代

1. 启动受控运行；
2. 完成结果评价；
3. 执行一次 `rerun_same_protocol`，验证同协议新 attempt；
4. 再执行 promote/stop 路径；
5. 经过版本治理和必要人工确认；
6. 生成结果包并打开全部必需 Artifact。

### 18.5 恢复

1. 运行中关闭并重开 Workbench；
2. 返回同一 Run；
3. 验证节点状态、Timeline、Artifact、Agent 会话锚点、Handoff、预算和 lineage 一致；
4. 断网/重连后事件不重复、不丢失；
5. 重复点击同一个动作只得到同一 CommandReceipt，不创建重复任务。

### 18.6 明确禁止

- 直接调用 HTTP API；
- 浏览器 DevTools/DOM script；
- 直接编辑 URL 跳过门禁；
- 修改 JSON/SQLite；
- 注入测试 fixture；
- 在命令行替用户完成节点；
- 通过默认 team、兼容 route 或旧页面继续。

任一步只能用上述方式绕过即验收失败。

## 19. 故障注入矩阵

| 注入点 | 预期 |
| --- | --- |
| readiness 后、command transaction 前依赖版本改变 | command 重算后拒绝；零副作用 |
| command transaction commit 前 crash | command/attempt/outbox/event 全无 |
| commit 后、worker 唤醒前 crash | restart 后 outbox 被领取 |
| graph interrupt 后、adapter outbox 前 crash | reconciler 从 checkpoint 恢复并创建同 actionId outbox |
| budget reserved 后、TaskBundle 前 crash | reconcile 释放或继续同 reservation |
| Session 创建后、Turn 前 crash | anchor 不 running；reconcile 同 session attempt |
| Agent 完成后、ArtifactReceipt 前 crash | domain read-back 生成 receipt，不重复执行 Agent |
| receipt 后、graph resume 前 crash | graph_dispatch 重试，resume 幂等 |
| event commit 后、SSE 推送前 crash | Last-Event-ID 从 Ledger 重放 |
| checkpoint 与 Ledger active node 不一致 | Run=`reconciliation_required`，禁止猜测 |
| SQLite corruption | startup/route 503，禁止 JSON fallback |

## 20. 执行 Agent 主提示词

将以下内容连同上位架构文档和本文交给执行 Agent：

```text
你负责在 Vibelution 中完整实现“挑战杯科研工作流正式运行时”。

权威文档：
1. docs/prds/2026-08-12-challenge-cup-research-workflow-runtime-architecture.md
2. docs/prds/2026-08-12-challenge-cup-research-workflow-runtime-implementation-spec.md
3. docs/adr/0006-challenge-cup-workflow-runtime-and-single-canvas.md
4. docs/adr/0007-research-workflow-handoff-and-agent-session-binding.md

不可变目标：LangGraph 是唯一控制流；Workflow Ledger 是 Run/Attempt/Command/Event/Handoff/Anchor/Receipt 唯一写入者；NodeReadiness 是命令校验与前端按钮的唯一能力来源；各领域 Store 保留业务事实；teamId 唯一且失败显式；不保留兼容运行层、双写、fallback 或第二页面；Agent 节点必须绑定真实 sessionId+taskId+turnId；纯点击跑通 SCI-096。

工作方式：
- 不在根 main 开发。先从最新本地 main 创建独立 codex/<task-slug> worktree/branch，并按项目 guard 建立 claim。
- 先读 AGENTS.md、docs/guides、development standard、VUI README 和两个权威文档。
- 严格按 T0→T9 任务图执行；每个任务先写能证明合同的 RED test，再做最小 GREEN 实现，再跑相邻回归并提交一个内聚 commit。
- 一个功能一个文件/模块。禁止把 schema、repository、readiness、command、outbox、projection、event、React hooks 堆回 service.py、route 或单个页面。
- 发现当前代码与文档存在会改变数据、API、迁移、安全或用户行为的冲突，立即停止受影响写入并汇报证据/推荐，不自行发明兼容逻辑。
- 不删除、还原或覆盖其他 Agent/用户改动；遇到 overlap/dirty target/active claim 先协调。
- 不 push、不开 PR、不刷新 Launcher、不合 main，除非用户或 integration owner 单独授权。

关键实现纪律：
- 所有 command mutation 经 APSW/WAL single writer + BEGIN IMMEDIATE；command/status/outbox/event 同事务。
- 幂等命中先于 expectedVersion 检查；相同 key+hash 返回原结果，不同 hash 409。
- 不在 DB transaction 内进行 LangGraph、网络、文件领域读写、Agent、模型或预算调用。
- readiness 拒绝时预算、TaskBundle、Session、Turn、Attempt、accepted Handoff 和 external outbox 全部零增长。
- LangGraph 节点在 interrupt 前无副作用，resume 只消费 typed ExecutionReceipt；生产路径不得 update_state(as_node) 冒充完成。
- 外部 adapter 先 read-back 输入，预算 reservation 后才创建任务；完成后再次 read-back 领域 Artifact，hash/version 通过才写 receipt/accept Handoff。
- UI 只渲染后端 CommandOffer，统一 Snapshot+Event reducer；run/node 切换必须重置 cursor、pending 和 error。
- 前端只使用 VUI 产品 API；新增 VUI 元素必须有 design 文档和 INDEX 登记。
- 后台进程必须无可见控制台，使用项目 no-console helper/windowsHide/CREATE_NO_WINDOW。

每个任务交付报告：
Task / Worktree / Branch / Commit / Changed files / RED evidence / GREEN evidence / Adjacent regression / Risks / Migration impact / Launcher refresh / Next task。

最终完成门禁：
- T0-T8 全部 contract tests、故障注入、迁移 dry-run/verify 绿；
- backend focused + adjacent 回归绿；
- frontend tests、VUI contracts、npx tsc -b --pretty false、npm run build 绿；
- static grep 无旧 writer/route/fallback 生产引用；
- local quality manifest 绿，worktree clean；
- 由 integration owner 合入后，在 activeWork=0 时刷新 Launcher；
- 验收员只用鼠标/键盘完成 SCI-096、重启恢复、会话深链和结果包检查；
- 最后清理测试 Run、orphan Task/Session/reservation、迁移临时文件、旧页面和过期 design/文档入口。

不要用“测试通过”替代正式 Launcher 纯点击验收，也不要用 dev server/build 证据冒充运行态完成。
```

## 21. 完成定义

只有同时满足以下条件，执行 Agent 才能声明实现完成：

- 16 节点全部由正式 LangGraph interrupt/resume 控制；
- Workflow Ledger 是唯一运行写模型，旧 JSON writer 无生产引用；
- NodeReadiness 同时驱动命令校验和 CommandOffer；
- command/outbox/event/attempt 事务与幂等合同有故障注入证据；
- 所有领域产物都以 verified ArtifactReceipt 交接；
- Agent attempt 都有真实 session/task/turn anchor；
- 前端只有一个运行命令入口、一个状态读取模型和一套 VUI 页面；
- `teamId` 缺失/不一致显式失败，无默认或静默兼容；
- migration 报告无 unknown，历史异常已归档或标记 reconciliation；
- 自动化门禁全绿；
- Launcher 中 SCI-096 纯点击全流程和重启恢复通过；
- 收尾清理完成，worktree/claim/Git 状态可审计。
