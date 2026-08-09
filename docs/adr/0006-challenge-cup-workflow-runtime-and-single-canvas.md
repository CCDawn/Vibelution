# ADR 0006 · 挑战杯科研工作流使用 LangGraph 运行权威与单画布三阶段投影

## Status

Accepted — v2.1 revision, 2026-08-09

## Context

挑战杯科研功能包含知识搜集、实验设计、执行迭代、Agent 绑定、证据、版本与交付物，但历史页面曾分别维护进度、旧阶段状态和画布状态。只增加节点图不能解决运行事实分裂，也不能提供可靠的人工门禁、恢复、重试和审计。

项目已经使用 LangGraph。产品确认三个阶段必须处于一个连续画布中，并以固定科研流程为主，不建设自由低代码编辑器。

## Decision

### 1. LangGraph 是唯一控制流运行时

- `WorkflowDefinition` 与不可变 `WorkflowVersion` 定义固定拓扑；
- `WorkflowRun.threadId` 对应 LangGraph thread；
- persistent checkpointer 保存可恢复 checkpoint；
- `interrupt()` 与 `Command(resume=...)` 表达人工作业；
- checkpoint fork 表达改变已接受输入后的 child run；
- 不引入 Temporal、Dify、n8n、AutoGen、CrewAI 或浏览器状态机作为第二运行时。

### 2. 领域事实是唯一业务事实源

权威链为：

```text
WorkflowDefinition / WorkflowVersion
  -> WorkflowRunInputSnapshot
  -> Checkpoint / NodeRun / TaskLease / HumanTask
  -> Handoff / SessionBinding / ArtifactManifest
  -> ClaimEvidence / Knowledge / Experiment / Result
  -> Domain Event
  -> ResearchLedger / Canvas / Inspector projection
```

LangGraph 决定控制流；确定性 command adapter 执行副作用；领域 store 决定业务真实；投影和前端只读。禁止可变 blackboard、旧页面 writer、占位 Artifact 或前端推导下一节点。

### 3. v2.1 固定拓扑

三个阶段在同一画布中投影，定义共 16 个节点：

```text
knowledge_collection
  source_finding -> source_extraction -> evidence_relations
  -> knowledge_ingestion -> knowledge_handoff

experiment_design
  hypothesis_design -> protocol_design -> protocol_review
  -> protocol_freeze -> smoke_gate

execution_iteration
  controlled_run -> result_evaluation -> iteration_decision
  -> version_governance -> candidate_promotion -> result_package
```

条件语义：

- `rerun_same_protocol`：同一 run、同一冻结协议，新 `controlled_run` attempt；
- `revise_protocol`：从协议设计 checkpoint 创建 child run，不绘制本 run 内伪边；
- `promote_candidate`：`version_governance -> candidate_promotion -> result_package`；
- `rollback_candidate`：`version_governance` 回退明确版本，不进入 promotion gate；
- `stop`：`version_governance -> result_package`。

`version_governance` 是真实 Agent 节点，负责 candidate version、`supersedes`、`derived_from`、拒绝归档和最终交付版本。

### 4. Run 创建和执行必须分离

`create_run` 只能：

1. 校验并冻结完整 `WorkflowRunInputSnapshot`；
2. 创建 `queued` WorkflowRun；
3. 创建首个 `ready` NodeRun；
4. 保存初始 checkpoint 与事件。

创建接口不得自动完成 Agent/System 节点，不得生成 `hash:...` 占位 Artifact。执行必须通过 `NodeExecutionEnvelope + TaskLease + command receipt/outbox` 进入真实 Agent task 或 System adapter。

### 5. Run 输入不可变

Run 至少冻结：`teamId`、竞赛规则/赛道/评分、ResearchObjective、source policy、dataset refs、metric contract、budget policy、stop policy、model routing、evaluation rubric、Agent binding snapshot、createdBy 和 createdAt，并生成稳定 `snapshotHash`。

缺少 `teamId` 或任何必需输入时明确失败；禁止 selected-team、默认 research-team、`team_id` 或 Agent team fallback。

### 6. 状态、重试与恢复

- WorkflowRun：`queued/running/waiting_human/blocked/succeeded/failed/cancelled`；
- NodeRun：`pending/ready/running/waiting_human/succeeded/failed/blocked/skipped/stale/cancelled`；
- 同节点重试创建新 attempt，旧 attempt 不覆盖；
- 改变已接受输入创建 child run，parent 历史不修改；
- 副作用幂等身份包含 `runId + nodeId + attempt`；
- restart 后 checkpoint、lease、task、handoff 和 lineage 必须恢复一致。

`selectedNodeId` 仅是 URL/UI 状态，不属于服务端运行状态。

### 7. API 与事件

采用 typed HTTP command/query 与真实 SSE：

- command 负责 create/start/cancel/retry/rebind/fork/resolve；
- query 返回 definition、run、node detail、handoff、task、Artifact 和只读 ResearchLedger；
- SSE 使用单调 sequence、`Last-Event-ID`、snapshot + delta；
- 不允许静默 polling fallback；
- 日志和事件不得包含 secrets、完整 Prompt 或大 Artifact 内容。

### 8. 单画布 VUI 投影

- 业务 Route 只使用 VUI 产品 API；
- `@xyflow/react` 与 ELK 仅位于 VUI shadcn renderer；
- ELK geometry 与 runtime overlay 分离；
- 三阶段使用 compound region，当前 run 只显示真实存在的边；
- Canvas、Inspector、Timeline、Agent、Team 面板消费同一 query/SSE projection；
- 运行状态不得由 React local state 或旧 route 推导。

### 9. 迁移策略

本次采用 hard cutover：

1. 新 runtime、adapter、query、VUI 达到功能等价；
2. canonical Teams workflow URL 成为唯一入口；
3. 删除旧 stage route、legacy resolver、fallback、writer 和 orphan；
4. 历史 run 仅保留只读迁移；
5. 任一旧能力未迁移时停止删除，不建立兼容执行层。

## Consequences

正向：控制流、Agent task、人工门、交接、证据、版本和交付物可以沿同一事实链恢复与审计；三个科研阶段保持连续可见；前端不再伪造流程。

成本：需要拆分现有 runtime facade、建立 task lease/outbox、补齐真实 adapter、重构工作台并执行 Launcher 全链验收。

不允许的结果：第二编排引擎、第二 writer、placeholder Artifact、team fallback、polling fallback、未绑定 Agent 静默执行、非终态结果打包或 degraded 兼容展示。

## Related

- [ADR 0007 · 节点交接与 Agent 会话锚点](0007-research-workflow-handoff-and-agent-session-binding.md)
- [v2.1 实施与验收方案](../prds/2026-08-09-challenge-cup-research-workflow-v2-repair-plan.md)
- [VUI 架构 ADR 0004](0004-product-ui-uses-vui-shadcn-only.md)
