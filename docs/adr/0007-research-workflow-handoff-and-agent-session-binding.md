# ADR 0007 · 科研工作流节点交接与 Agent 会话锚点

## Status

Accepted（v2.1 复审，2026-08-09）。

## Context

[ADR 0006](0006-challenge-cup-workflow-runtime-and-single-canvas.md) 已确定 LangGraph 运行事实源和三阶段单画布，但只定义了 `AgentBinding`，尚未锁定：

- 上游节点以什么条件把什么产物交给下游；
- 下游如何确认自己消费的是不可变输入快照；
- Agent 配置如何从流程、阶段和节点逐级覆盖；
- 节点运行如何落到一个可继续的具体 Agent 会话位置；
- 重试、换 Agent 和跨阶段回退是否会污染历史运行。

现有实现提供了可复用基础：

- `researchStageAgentBindings.ts` 从组织画布和团队成员投影阶段角色；
- `research_project_agent_sessions.py` 维护“研究项目 + Agent”的稳定会话，并在正式重试时创建新 attempt；
- source collection 和 experiment / iteration task 已记录 `agentId`、`sessionId`、`taskId` 与 `turnId`；
- Chat 当前只支持 `/chat?session=<id>`，还不能聚焦节点对应的 task / turn；
- `ChallengeCupStageAgentConfigurationPanel` 只能跳到通用 Agent 配置，无法表达本节点的有效绑定、运行快照和会话锚点。

因此不需要再造一套 Agent 会话系统，但必须在工作流领域中建立显式交接记录和会话锚点。

## Decision

### 1. 节点先声明执行主体

每个固定节点必须声明 `actorKind`：

```text
agent
system
human
```

v2.1 固定分工：

| 节点 | actorKind | 主责 |
| --- | --- | --- |
| `source_finding` | agent | `source_finder` |
| `source_extraction` | agent | `source_extractor` |
| `evidence_relations` | agent | `source_relation_mapper` |
| `knowledge_ingestion` | agent | `source_ingestor` |
| `knowledge_handoff` | human | research owner / reviewer |
| `hypothesis_design` | agent | `experiment_planner` |
| `protocol_design` | agent | `experiment_planner` |
| `protocol_review` | agent | `experiment_ledger` |
| `protocol_freeze` | human | research owner / reviewer 确认，service 固化 artifact |
| `smoke_gate` | human | 只在 system runner 证据完整后人工放行 |
| `controlled_run` | system | formal runner；不得由 Agent 会话自动启动训练 |
| `result_evaluation` | agent | `experiment_ledger` |
| `iteration_decision` | agent | `iteration_planner` |
| `version_governance` | agent | `iteration_versioning`；版本、谱系、拒绝归档 |
| `candidate_promotion` | human | 仅确认已经过版本治理的 promote proposal |
| `result_package` | system | package builder |

`research_coordination` 是 workflow-level coordinator，不占用每个业务节点的主责位置；它可作为协作 Agent 或人工升级对象。

### 2. Agent 配置采用四层解析，运行时保存快照

配置层级：

```text
WorkflowDefaultBinding
  -> StageBindingOverride
    -> NodeBindingOverride
      -> RunAgentBindingSnapshot
```

解析规则：

1. `NodeBindingOverride` 优先于 `StageBindingOverride`；
2. 阶段未配置时使用 `WorkflowDefaultBinding`；
3. 创建 `WorkflowRun` 时解析并保存 `RunAgentBindingSnapshot`；
4. 当前 Agent 显示名、头像、模型配置变化不得改写历史快照；
5. 运行中的换 Agent 必须执行受控 `rebind_node` 命令，创建新的 `NodeRun` attempt 和绑定事件，不允许静默替换；
6. `researchStageAgentBindings` 仅作为迁移输入和当前配置投影，不是历史运行事实源。

绑定使用稳定 `agentId`。显示名、头像、角色文案不参与授权。

### 3. 一个项目 Agent 保持连续会话，节点绑定到会话内的具体 task / turn

不为每个节点机械创建新会话。沿用现有“研究项目 + Agent + attempt”的连续会话，避免一个项目被拆成大量无上下文会话。

每次 Agent 节点执行必须保存：

```text
NodeAgentSessionBinding
  bindingId
  workflowId
  workflowVersionId
  runId
  nodeId
  nodeRunId
  nodeAttempt
  agentId
  roleKey
  sessionId
  sessionAttempt
  taskId
  turnId
  checkpointId
  status
  boundAt
  supersedesBindingId?
```

具体会话点由 `sessionId + taskId + turnId` 共同标识：

- `sessionId` 保持项目级上下文连续；
- `taskId` 标识本节点责任；
- `turnId` 标识本次提交和运行位置；
- `nodeRunId` 与 checkpoint 连接工作流 lineage。

目标深链：

```text
/chat
  ?session=<session-id>
  &focusTask=<task-id>
  &focusTurn=<turn-id>
  &returnTo=<canonical-workflow-node-url>
  &returnLabel=<short-label>
```

Chat 必须：

- 打开指定 session；
- 定位或高亮对应 task / turn；
- task / turn 尚未加载时按锚点分页加载；
- 锚点失效时保留 session 并显示“该节点会话位置不可用”，不得跳到 Agent 默认会话；
- 返回动作回到原 `runId + node`，不回到笼统 Teams 首页。

普通继续执行复用当前 session attempt。只有正式重试、会话损坏或受控换 Agent 才创建新 attempt，并保留 `retryOfSessionId` / `supersedesBindingId`。

### 4. 每条运行边都有显式交接记录

定义：

```text
NodeHandoffRecord
  handoffId
  workflowId
  workflowVersionId
  runId
  fromNodeId
  fromNodeRunId
  toNodeId
  toNodeRunId?
  gateKind
  outputArtifactRefs[]
  inputSnapshotHash
  status
  offeredAt
  acceptedAt?
  acceptedBy?
  rejectionReason?
  supersedesHandoffId?
```

状态：

```text
pending
ready
waiting_human
accepted
rejected
superseded
failed
```

规则：

- 上游成功不等于下游已接收；下游 `NodeRun` 只能消费 `accepted` handoff；
- `inputSnapshotHash` 绑定具体 artifact version，禁止下游读取仍在变化的“当前数据”；
- 交接失败或拒绝不得把下游标成 ready；
- 修订会生成新 artifact version 和新 handoff，旧记录标记 `superseded`，不覆盖；
- 跨阶段 handoff 必须有关联 `HumanTask`；
- 同阶段自动交接也必须持久记录，不能只靠前端连线推断。

### 5. 两个阶段边界消费不可变包

| 边界 | 必须输入 | 放行条件 | 拒绝后的去向 |
| --- | --- | --- | --- |
| 知识搜集 → 实验设计 | `KnowledgePackageRef` | 入库完成、来源/证据关系完整、人工接受 | 回到对应知识节点并生成新 package version |
| 实验设计 → 执行迭代 | `FrozenProtocolRef` + smoke artifacts | 协议冻结、smoke gate 通过、人工放行 | 回到协议设计/评审并生成新 protocol version |

禁止：

- 仅因“存在资料批次”就解锁实验设计；
- 仅因“存在实验计划”就解锁正式执行；
- 下游直接读取可变草稿；
- UI 按钮自行决定跨阶段成功。

### 6. 固定节点边契约

| from → to | 交接 artifact | 最小接收条件 |
| --- | --- | --- |
| `source_finding` → `source_extraction` | `SourceManifestRef` | 来源、获取时间、URL/文件引用和 provenance 完整 |
| `source_extraction` → `evidence_relations` | `ExtractedEvidenceSetRef` | 主张、方法、指标、限制和排除原因结构化 |
| `evidence_relations` → `knowledge_ingestion` | `EvidenceGraphRef` | 节点/边可解析，阻塞级 missing links 为零或有人工作为 waiver |
| `knowledge_ingestion` → `knowledge_handoff` | `KnowledgePackageDraftRef` | 正式知识写回完成，重复/冲突/来源审计完成 |
| `knowledge_handoff` → `hypothesis_design` | `KnowledgePackageRef` | 人工 accepted；artifact version/hash 固定 |
| `hypothesis_design` → `protocol_design` | `HypothesisSetRef` | 假设可证伪、变量和失败条件明确 |
| `protocol_design` → `protocol_review` | `ProtocolDraftRef` | dataset、baseline、变量、metric、seed、预算、停止条件齐全 |
| `protocol_review` → `protocol_freeze` | `ReviewedProtocolRef` | 阻塞问题为零；waiver 有操作者和理由 |
| `protocol_freeze` → `smoke_gate` | `FrozenProtocolRef` | 人工确认后由 service 生成不可变版本/hash |
| `smoke_gate` → `controlled_run` | `SmokeEvidenceRef` + `FrozenProtocolRef` | smoke 通过且 HumanTask accepted |
| `controlled_run` → `result_evaluation` | `RunArtifactSetRef` | runner 已终止，日志/metric/artifact 完整性可验证 |
| `result_evaluation` → `iteration_decision` | `EvaluationReportRef` | baseline 对比、失败、置信边界和 artifact 引用完整 |
| `iteration_decision` → `controlled_run` | `IterationDecisionRef` | `rerun_same_protocol`；绑定同一 `FrozenProtocolRef` 和新 run attempt |
| `iteration_decision` → `protocol_design` | `IterationDecisionRef` | `revise_protocol`；从实验设计 checkpoint fork 新 run |
| `iteration_decision` → `version_governance` | `IterationDecisionRef` | promote/rollback/stop；评价、版本目标和理由完整 |
| `version_governance` → `candidate_promotion` | `VersionGovernanceRef` | 仅 promote；候选版本和 lineage 完整 |
| `version_governance` → `result_package` | `VersionGovernanceRef` | 仅 stop；终止原因和当前版本完整 |
| `candidate_promotion` → `result_package` | `PromotionProposalRef` | 人工 accepted 或明确 no-promotion 终止 |

`result_package` 生成终端 `ResearchResultPackageRef`，不再通过隐藏自动边继续运行。

### 7. 迭代回边具有单一、可审计语义

`iteration_decision` 只能产生以下结构化决策：

| 决策 | 行为 |
| --- | --- |
| `rerun_same_protocol` | 同一 `WorkflowRun` 中创建新的 `controlled_run` attempt，复用同一 `FrozenProtocolRef` |
| `revise_protocol` | 从实验设计 checkpoint fork 新 `WorkflowRun`，生成新的 protocol artifact lineage |
| `rollback_candidate` | 进入 `version_governance`，引用既有 baseline/candidate，不进入 promotion gate，不覆盖历史 artifact |
| `stop` | 经 `version_governance` 记录终止版本后进入 `result_package` |

`candidate_promotion` 只生成 promotion proposal。人工接受后才更新正式候选引用，且不得直接覆盖 baseline。

`result_package` 只有在必需 artifact 完整、未决 HumanTask 为零且终止原因明确时才能成功。

### 8. Agent 配置入口只有一个编辑事实源

工作流页面提供两个视图，但只有一个配置写入口：

1. 节点检查器的 **Agent** 区：
   - 显示有效绑定、来源层级、运行快照和会话状态；
   - “继续会话”进入精确 task / turn；
   - “配置 Agent”进入 Agent Center，并携带当前节点 `returnTo`；
   - 运行中绑定默认只读，换绑走 `rebind_node`。
2. WorkspaceHeader 的 **Agent 分工** 抽屉：
   - 汇总全流程节点的有效绑定和缺口；
   - 复用同一 binding model；
   - 不复制 Agent 表单，不成为第二编辑器。

Agent Center 仍是身份、模型、Prompt、工具和内存配置事实源。工作流 binding service 只管理“哪个稳定 Agent 承担哪个节点”。

### 9. API 增量

在 ADR 0006 API 上增加：

```text
GET  /api/research/workflows/{workflowId}/agent-bindings/effective
PUT  /api/research/workflows/{workflowId}/agent-bindings
POST /api/research/workflow-runs/{runId}/nodes/{nodeId}/rebind

GET  /api/research/workflow-runs/{runId}/nodes/{nodeId}/session-binding
GET  /api/research/workflow-runs/{runId}/handoffs
GET  /api/research/workflow-runs/{runId}/handoffs/{handoffId}
POST /api/research/workflow-runs/{runId}/handoffs/{handoffId}/resolve
```

工作流投影中的 Agent 卡片必须消费 run snapshot / session binding，不能用当前 Agent 目录状态替代历史绑定。

### 10. 与 ADR 0002 的关系

[ADR 0002](0002-agent-collaboration-session-addressing.md) 继续规定协作消息以目标 Session 为 body SSOT。

本 ADR 只增加：

- 工作流节点到 session 内 task / turn 的锚点；
- node run、checkpoint 与 Agent session 的 lineage；
- 工作流内换绑、正式重试和返回路径。

它不引入第二份会话正文，也不把 inbox 变成节点输出事实源。

## Consequences

正向：

- 每个节点都能回答“由哪个 Agent、在哪个会话的哪次任务完成”；
- 阶段交接消费不可变包，不会把“有进度”误判为“可进入下一阶段”；
- Agent 配置入口唯一，运行历史不受当前配置漂移影响；
- 同项目 Agent 保持连续上下文，同时可精确回到节点对应位置；
- 迭代回边、重试和晋升都有 lineage。

成本：

- Chat 需要支持 task / turn 锚点定位；
- workflow DTO、binding service 和投影需要新增实体；
- 现有 stage-level binding 必须迁移成 node-effective binding；
- 当前前端的进度式解锁模型需要改为 handoff/gate 投影；
- 缺少 `taskId` 或 `turnId` 的历史记录保持只读且明确不可精确跳转；不得回退到 Agent 默认会话或伪造兼容锚点。

## Related

- [单画布运行架构 ADR 0006](0006-challenge-cup-workflow-runtime-and-single-canvas.md)
- [协作会话寻址 ADR 0002](0002-agent-collaboration-session-addressing.md)
- [产品 PRD](../prds/2026-08-07-research-process-flow-single-page-workspace.md)
- [旧页面处置表](../archive/plans/2026-08-07/challenge-cup-legacy-surface-disposition.md)
