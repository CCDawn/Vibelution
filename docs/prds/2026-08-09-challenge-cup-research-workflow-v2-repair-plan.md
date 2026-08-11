# 挑战杯科研工作流 v2.1 完整修复、科研效能优化与验收方案

> 本文件是 v2.1 实施、审查和验收的统一交接合同；长期治理规则必须在 T0 提炼到可追踪的 ADR、现行标准和 owning README。

Status: **in-progress**

Approval baseline: **v2 修复边界已获用户确认；v2.1 科研效能优化来自本轮成熟项目调研，实施前需按本文件完成一次最终评审**

Planning owner: **Codex Challenge Workflow Plan**

Implementation owner: **Codex Challenge Workflow v2.1 Implementation**

Claim: **claim-1c38724370fa**（runtime）+ **claim-bc685d6ad7fa**（baseline/ignore）

Branch: **codex/challenge-cup-workflow-v2-implementation**

Worktree: **<project-root-parent>\Vibelution-worktrees\challenge-cup-workflow-v2-implementation**

Scope: **挑战杯 research-team 的科研工作流运行时、Agent/会话、Handoff、科研质量与预算门禁、三阶段单画布、旧页面收敛与正式验收**

Supersedes:

- docs/plans/2026-08-09-research-workflow-legacy-function-migration.md 的完成声明；
- docs/archive/plans/2026-08-07/challenge-cup-workflow-implementation-plan.md 的未闭合实施部分；
- 所有把局部测试、静态画布或兼容跳转视为正式闭环的历史结论。

Implementation link: **local branch `codex/challenge-cup-workflow-v2-implementation`；起点 `bcc9577c`**

Validation: **本文件完成后执行 Markdown 结构、内部路径、索引、关键决策锚点与 git diff 检查；业务行为验证按第 15 节执行**

Close condition: **T0–T9 全部满足，第 16 节完成定义全部为真，Launcher 实际运行版本与验收提交一致；随后将本文件标记 implemented 并迁入 docs/archive/**

---

## 1. 文档目的

本文件是挑战杯科研团队工作流 v2.1 的正式实施合同，用于把当前：

> 单画布流程外壳 + 可持久化编排骨架 + 旧工作台能力入口

修复为：

> 真实 Agent、HumanTask、System Adapter 和 LangGraph checkpoint 共同驱动，并受证据、预算、复现与竞赛评分门禁约束的可执行、可恢复、可审计科研工作流

开发 Agent 不得把本文件降级为视觉优化清单，也不得用局部测试、占位 Artifact、静态演示数据或旧页面兼容跳转代替真实闭环。

本文件同时锁定：

- 产品流程；
- 单一事实源；
- Agent 与会话身份；
- Handoff 与返工语义；
- 前后端 API；
- 文件职责；
- 迁移和删除边界；
- 科研质量、成本和停止策略；
- 测试与 Launcher 实机验收；
- 合并、回滚和收尾条件。

---

## 2. 审计基线

### 2.1 当前仓库与运行时

审计基线：

- local main HEAD：b9b324d4b537fbde4a1629f90f4e059bb1bedd85；
- Launcher 运行代码 fingerprint 与该提交一致；
- backend health 返回 routesReady=true；
- research-team 当前 WorkflowRun 数量为 0；
- research-team 有 9 个 active 团队成员；
- effective binding API 返回 9 条节点绑定，覆盖 7 个唯一 Agent；
- 后端 research-workflow 聚焦测试：105 passed；
- 前端 research-workflow 聚焦测试：119 passed；
- 真实浏览器仍能复现 React #310、绑定显示错误、工具栏面板切换失效和画布有效宽度不足。
- ADR 0006 当前只存在于根工作区的 ignored 本地文件，干净 checkout 中缺失；在 T0 恢复 tracked 权威前不得把它当作可交接依据。

测试通过只证明局部契约，不证明真实业务闭环。

### 2.2 当前实现中必须修复的问题

P1：

1. Teams workbench 在加载分支变化时违反 Rules of Hooks，能够触发 React #310。
2. effective binding API 已返回 Agent，但 ELK 布局缓存丢失 primaryAgentId，画布显示“未绑定”。
3. create_run 会直接 invoke 图并自动推进 Agent/System 节点。
4. challenge_cup_graph 和 handoff_builder 会生成 hash:... 占位 Artifact。
5. 资料寻找、资料提炼、证据关系和知识入库没有完整真实任务适配器。
6. 节点重新绑定后，任务系统仍可能按 roleKey 重新选中旧 Agent。
7. reject/revise 会把 Run 留在 blocked，但不创建可恢复修订任务和真实 checkpoint。
8. revise child run 只有记录，没有可恢复 LangGraph checkpoint。
9. Canvas nodeRuns 没有完整反映实际 completed node。
10. Handoff lineage 已存储但缺少完整查询和节点详情投影。
11. result package 在非完整终态也可能生成。
12. WorkflowRun 没有冻结具体赛题、研究合同、数据和指标。
13. 前端仍存在 teamId 静默回退与 legacy route resolver。
14. SessionBinding 的 returnTo 没有完整编码，也没有稳定携带 teamId。

P2：

1. 工作流模式下左团队栏和右 Inspector 同时常驻，1280×720 时画布过窄。
2. Agent、时间线、团队面板没有形成可用工作台。
3. “科研协调”和“版本治理”两个团队角色没有完整流程落点。
4. 挑战杯主表面虽然只保留一个画布，但旧资料、实验和 Research Loop 状态仍是平行事实源。
5. ResearchProcessWorkspace、useTeamsWorkbenchShellPhase 和 runtime service 混合多个独立职责。

### 2.3 已存在但尚未合入的候选

commit 4aac6b434 fix(teams): stabilize workbench hook order 位于独立 worktree，尚未进入 local main。

它只能作为 T1 候选补丁：

- 必须基于 T1 的最终路由和 hook 结构重新审查；
- 必须重跑 loading 分支切换回归；
- 不得把“存在候选提交”当作问题已修复。

### 2.4 当前主工作区保护边界

审计时 local main 有未提交 WIP，涉及：

- 挑战杯迁移计划；
- TeamsRoute layout 测试；
- ChallengeMvpProgressPanel；
- EvidenceGraphView；
- IterationDecisionPanel；
- 对应 styles 文件。

实施前必须确认其 owner、是否已提交和是否应吸收。不得清理、覆盖或自动带入新 worktree。

---

## 3. 目标与非目标

### 3.1 目标

1. 三个科研阶段在同一连续画布中可理解、可导航、可执行。
2. WorkflowRun、NodeRun、Checkpoint、HumanTask、Handoff、ArtifactRef 和 SessionBinding 形成单一事实链。
3. 每个 Agent 节点都能启动指定 Agent 的真实任务并绑定精确会话。
4. 接受、拒绝、重试、修订、重跑、晋升、回滚和停止都有明确可恢复语义。
5. 每个节点都能打开定义、Agent、会话、交接、产物、历史和命令详情。
6. 旧挑战杯页面、旧运行写入口和 teamId fallback 完整删除。
7. Launcher 重启后运行、人工任务、交接和版本谱系保持一致。
8. 结果包只能由真实、完整、可审计的终态运行生成。
9. 假设、实验和交付物由统一竞赛评分合同约束，能够追踪到证据、协议、运行和 Artifact。
10. 用任务租约、幂等副作用、内容寻址复用和分级模型路由降低重复工作，并用同题基线对照证明改善。

### 3.2 非目标

- 不实现通用低代码工作流编辑器。
- 不允许用户运行时修改固定拓扑。
- 不支持移动端，本轮只验收桌面。
- 不建立第二套设计系统。
- 不引入另一种图运行引擎。
- 不为了兼容旧页面保留第二状态机。
- 不把完整 Prompt、密钥或大 Artifact 内容放入事件、日志或 checkpoint。

### 3.3 成熟项目调研与复用决策

本轮只采用官方仓库、官方文档或论文。结论是：**保留现有 LangGraph 作为唯一运行时，复用项目已有领域资产；外部项目只提供机制参照，不引入第二套编排引擎或第二事实源。**

| 项目 | 成熟机制 | 本项目决策 |
| --- | --- | --- |
| [LangGraph Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)、[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | task 持久化、checkpoint、interrupt/resume、time travel；重放前副作用必须幂等 | **REUSE**：继续使用现有 runtime/checkpoint，把外部调用和副作用收口到可重试 task |
| [Temporal Architecture](https://github.com/temporalio/temporal/blob/main/docs/architecture/README.md)、[Python Samples](https://github.com/temporalio/samples-python) | workflow 与 activity 分离、task queue、retry、heartbeat、durable execution | **ADAPT**：借用任务租约、heartbeat、幂等 effect 和 outbox/receipt；**不安装 Temporal** |
| [OpenHands Architecture](https://github.com/OpenHands/OpenHands/blob/main/openhands/README.md) | AgentController、EventStream、Action → Runtime → Observation、sandbox 边界 | **ADAPT**：采用 typed action/observation/event，不复用其运行时 |
| [Dify HITL](https://github.com/langgenius/dify/discussions/32245)、[n8n Execution History](https://docs.n8n.io/workflows/executions/all-executions/) | 显式 paused/human-input、动作路由、执行历史、带来源的 retry | **ADAPT**：用于 HumanTask、Timeline、retry provenance；不建立低代码编辑器 |
| [AI Scientist v2](https://arxiv.org/abs/2504.08066)、[Source License](https://github.com/SakanaAI/AI-Scientist-v2/blob/main/LICENSE) | 可行性、基线调优、研究议程、消融四阶段；停止条件、复现、均值/方差 | **REFERENCE_ONLY**：吸收实验阶段和评估门禁；其许可证非本项目默认可复用许可证，不复制代码 |
| [Google AI co-scientist](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/) | 生成、反思、排名、演化、meta-review 与 supervisor 资源分配 | **ADAPT**：只在假设设计/协议评审使用有界候选组合，不部署无限 Agent swarm |
| [STORM](https://github.com/stanford-oval/storm) | 多视角问题规划、来源扎根对话、动态知识策展 | **ADAPT**：用于来源视角规划和 evidence-gap map，不增加新运行时依赖 |
| [PaperQA2](https://github.com/Future-House/paper-qa) | 科学文献检索、元数据、引用和 evidence critique | **REUSE**：扩展现有可选 adapter；继续保持候选证据、人工复核、不得直写正式知识的边界 |
| [Open Deep Research](https://github.com/langchain-ai/open_deep_research)、[Async Deep Agents](https://github.com/langchain-ai/async-deep-agents) | supervisor-researcher、并行子任务、隔离上下文、任务追踪和取消 | **ADAPT**：节点内部使用有界 ResearchTaskBundle，协调 Agent 不亲自执行领域任务 |
| [R&D-Agent](https://github.com/microsoft/RD-Agent)、[Agent Laboratory](https://github.com/SamuelSchmidgall/AgentLaboratory) | idea → implementation → feedback 演化；文献、实验、报告阶段检查点；按任务使用不同模型 | **ADAPT**：统一假设—实现—反馈闭环和模型分级路由 |
| [Nextflow cache/process](https://github.com/nextflow-io/nextflow/blob/master/docs/reference/process.md)、[MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/) | 内容关联缓存、运行 lineage、参数/指标/Artifact/数据集对比 | **ADAPT**：建立 ArtifactManifest 与运行对照；默认不要求外部 MLflow 服务 |

### 3.4 v2.1 架构原则

1. **单运行时**：LangGraph 负责控制流和 checkpoint，不得并存 Temporal、Dify、n8n、AutoGen 或 CrewAI runtime。
2. **单一事实源**：ClaimEvidenceStore、Knowledge、ExperimentContract、NodeRun/Handoff/Artifact/Result 继续由各领域 owner 写入；ResearchLedger 只能是只读投影。
3. **推理与副作用分离**：LLM 可以提出结构化 Action，但只有确定性 command adapter 能改变运行状态或写入 canonical store。
4. **有界多 Agent**：只在可并行、可独立验收的 ResearchTaskBundle 内并行；假设辩论和评审受候选数、轮数、预算和截止时间约束。
5. **质量优先于吞吐**：任何缓存、轻量模型或并行策略不得绕过来源、证据、复现、统计和人工门禁。
6. **可测量改进**：不预设提升百分比；先冻结基线，再用同题、同数据、同评分合同和同预算比较质量、时间、成本与人工干预。

### 3.5 v2.1 责任边界

~~~mermaid
flowchart LR
  UX["VUI 单画布<br/>Canvas · Inspector · Timeline"]
  API["Command / Query / SSE API"]
  LG["LangGraph 控制面<br/>Checkpoint · HumanTask · Supervisor"]
  EXEC["确定性执行面<br/>TaskLease · Agent Task · System Adapter · Outbox"]
  TRUTH["领域事实层<br/>NodeRun · Handoff · ClaimEvidence · Knowledge · Experiment · Artifact · Result"]
  READ["只读科研投影<br/>ResearchLedger · Budget · Evaluation"]

  UX -->|command| API --> LG --> EXEC --> TRUTH
  LG -->|state/checkpoint/event| TRUTH
  TRUTH --> READ -->|query/stream| API --> UX
  EXEC -->|receipt/heartbeat/budget| LG
~~~

责任结论：LangGraph 决定“下一步能否执行”，TaskLease/adapter 决定“副作用如何安全发生”，领域 store 决定“什么是真实”，ResearchLedger 决定“如何查看和评分”，VUI 只负责操作与解释。

---

## 4. 强制产品决策

### 4.1 teamId 是唯一团队作用域

所有公共请求、URL、Run、SessionBinding、Handoff 和权限检查只认 teamId。

禁止：

- team_id；
- selected team fallback；
- requested agent team fallback；
- 默认 research-team fallback；
- legacy resolver 自动补 team；
- 缺少 teamId 时继续查询或创建 Run。

缺失、无效或不匹配必须显式失败。

### 4.2 WorkflowRun 输入不可变

创建 Run 必须冻结：

~~~text
teamId
projectId
questionId
workflowVersionId
researchBriefHash
datasetRefs
metricContract
constraintSnapshot
competitionRuleRef
competitionRuleVersion
trackAndRubricSnapshot
researchObjectiveContract
sourcePolicy
budgetPolicy
stopPolicy
environmentSnapshotRef
modelRoutingPolicy
evaluationContract
agentBindingSnapshot
createdBy
createdAt
~~~

缺少 questionId、研究合同、指标合同、竞赛规则/评分快照、预算/停止策略、环境快照或绑定快照时不得创建 Run。规则更新只影响后续 Run；已创建 Run 的评分与停止语义不得漂移。

### 4.3 新运行硬切换到 WorkflowVersion v2

- research-team 当前没有 Run，v2 可以直接成为新运行唯一入口。
- v1 历史数据只读保留。
- v1 不再接受命令、重试、修订或新 Handoff。
- 不保留旧执行兼容路径。
- 历史读取不等于兼容写入。

### 4.4 禁止伪执行和占位产物

创建 Run 只能创建运行记录和首个 ready NodeRun，不得自动把 Agent 节点视为成功。

禁止：

- create_run 直接跑完整个资料阶段；
- f"hash:{kind}:{run_id}"；
- 没有 Agent task/session 的 Agent 节点成功；
- 没有实际 plan/result 的 System 节点成功；
- 缺少 required Artifact 时自动补空 ArtifactRef；
- 前端自行推导下一个节点状态。

### 4.5 Agent 与角色安排

团队现有 9 个角色继续保留。

科研协调：

- 是工作流级协调角色；
- 固定显示在 Team 面板；
- 可打开团队讨论、查看全局阻塞和当前责任人；
- 只负责分解 ResearchTaskBundle、资源分配、进度汇总和升级阻塞；
- 不执行检索、实验、评估等领域任务，不直接写 canonical store；
- 不伪装成有输入输出的执行节点。

版本治理：

- 在 v2 中成为真实 Agent 节点 version_governance；
- 负责 candidate version、supersedes、derived_from、rejection archive 和最终交付版本；
- terminal decision 进入结果包前必须经过该节点。

节点内部并行：

- 只有输入、输出和验收可独立的子任务才能组成 ResearchTaskBundle；
- 每个子任务使用隔离上下文、独立 taskId、预算和取消状态；
- 最大并行数、截止时间和最大重试次数由 budgetPolicy 冻结；
- supervisor 只能聚合结构化结果，不能把共享可变 Prompt/blackboard 当作事实源；
- 假设与协议评审最多使用受策略限制的候选数和讨论轮数，最终晋升仍由 HumanTask 决定。

模型路由：

- 高推理模型用于假设生成/排名、协议评审、失败分析和最终综合；
- 轻量模型用于抽取、分类、去重、格式校验和低风险摘要；
- 每次调用记录 modelRef、purpose、token/cost/time 和输出 hash；
- 质量门失败时可以显式升级模型，不得静默切换后覆盖原 attempt。

### 4.6 返工语义

同一节点失败重试：

- 同一 WorkflowRun；
- 新 NodeRun attempt；
- 原失败 attempt 永久保留；
- 幂等键包含 runId + nodeId + attempt。

改变已接受输入的修订：

- 创建 child WorkflowRun；
- 从正确 sourceCheckpointId fork；
- parent Run 不修改历史；
- child 保存 parentRunId、supersedesRunId、supersedesHandoffId；
- parent 进入 blocked 或 superseded；
- child 从修订源节点进入 ready。

### 4.7 科研质量、预算与停止策略

每个 Run 必须冻结三类门禁：

1. **质量门**：来源覆盖、主来源比例、反证、假设可证伪性、协议完整性、复现与竞赛评分覆盖。
2. **预算门**：按阶段限制 token、工具调用、墙钟时间、实验次数和计算资源；区分 reserved、consumed 与 remaining。
3. **停止门**：达到成功阈值、连续无改进、预算耗尽、证据不足、运行风险或人工终止时，产生明确 stop reason。

预算不足时不得制造低质量 Artifact 维持流程前进；必须进入 blocked/waiting_human，并给出可审计的缩减范围、追加预算或终止选项。

---

## 5. v2 流程拓扑

### 5.1 三阶段

~~~text
knowledge_collection
  source_finding
  -> source_extraction
  -> evidence_relations
  -> knowledge_ingestion
  -> knowledge_handoff

experiment_design
  hypothesis_design
  -> protocol_design
  -> protocol_review
  -> protocol_freeze
  -> smoke_gate

execution_iteration
  controlled_run
  -> result_evaluation
  -> iteration_decision
  -> version_governance
  -> candidate_promotion
  -> result_package
~~~

### 5.2 节点类型

| 节点 | 类型 | 责任 |
| --- | --- | --- |
| source_finding | Agent | 生成检索问题、发现并登记来源 |
| source_extraction | Agent | 提炼、质量复核、保留/排除 |
| evidence_relations | Agent | 建立证据关系与缺口 |
| knowledge_ingestion | Agent | 审核并写入 Team Knowledge |
| knowledge_handoff | Human | 接受或拒绝 Knowledge Package |
| hypothesis_design | Agent | 形成可检验假设 |
| protocol_design | Agent | 数据集、指标、baseline、变量与预算 |
| protocol_review | Agent | 协议审查和风险核对 |
| protocol_freeze | Human | 冻结不可变实验协议 |
| smoke_gate | Human + System action | 执行真实 Smoke 并人工放行 |
| controlled_run | System | 执行真实受控实验 |
| result_evaluation | Agent | 对比 baseline、指标和证据 |
| iteration_decision | Agent | rerun/revise/promote/rollback/stop |
| version_governance | Agent | 候选版本、谱系和拒绝归档 |
| candidate_promotion | Human | 仅 promote 分支需要人工批准 |
| result_package | System | 构建最终可审计交付包 |

### 5.3 分支

| 决策 | 目标 | 语义 |
| --- | --- | --- |
| rerun | controlled_run | 同一协议、同一 Run，新受控运行 attempt |
| revise | protocol_design | child Run，从协议修订 checkpoint fork |
| promote | version_governance → candidate_promotion | 建立候选版本并人工批准 |
| rollback | version_governance | 回退到明确 candidate/version |
| stop | version_governance → result_package | 记录停止原因并打包当前结论 |

前端只绘制当前 Run 真实存在的边。不得为了视觉完整伪造 revise 边。

---

## 6. 单一事实源与数据模型

### 6.1 事实层级

~~~text
WorkflowDefinition + WorkflowVersion
  -> WorkflowRunInputSnapshot
  -> LangGraph Checkpoint / active task
  -> NodeRun / TaskLease / HumanTask / Handoff / ArtifactRef / SessionBinding
  -> ClaimEvidence / Knowledge / ExperimentContract / Result
  -> Domain Event
  -> ResearchLedger / Canvas / Node Detail Projection
  -> VUI
~~~

ResearchLedger、Canvas 和前端 projection 只能读取领域事实，不得成为第二写入者。禁止再建立通用可变 blackboard。

### 6.2 WorkflowRun

~~~text
runId
workflowId
workflowVersionId
teamId
projectId
questionId
inputSnapshot
bindingSnapshot
threadId
status
runtimeCurrentNodeIds
parentRunId
sourceCheckpointId
terminalReason
createdAt
updatedAt
~~~

WorkflowRunStatus：

~~~text
queued
running
waiting_human
blocked
succeeded
failed
cancelled
superseded
~~~

### 6.3 NodeRun

~~~text
nodeRunId
runId
nodeId
attempt
actorType
agentId
taskId
sessionId
status
inputSnapshotHash
idempotencyKey
modelRef
budgetLedgerRef
artifactRefs
checkpointId
startedAt
finishedAt
failureCode
failureSummary
supersedesNodeRunId
~~~

NodeRunStatus：

~~~text
pending
ready
running
waiting_human
succeeded
failed
blocked
skipped
cancelled
~~~

### 6.4 Handoff

~~~text
handoffId
edgeId
runId
fromNodeId
fromNodeRunId
toNodeId
toNodeRunId
status
inputSnapshotHash
artifactRefs
acceptedBy
acceptedAt
rejectionReason
supersedesHandoffId
humanTaskId
~~~

Handoff 只能引用真实 ArtifactRef。contentHash 必须可验证且不得使用占位前缀。

### 6.5 SessionBinding

~~~text
teamId
runId
nodeId
nodeRunId
agentId
sessionId
focusTaskId
focusTurnId
returnTo
boundAt
~~~

Run binding snapshot 与实际 task Agent 不一致时，启动必须失败，不允许静默重新选 Agent。

### 6.6 NodeExecutionEnvelope 与 TaskLease

每次可执行节点都必须产生确定的执行信封：

~~~text
runId
nodeRunId
nodeId
attempt
actorType
agentId
taskId
sessionId
inputSnapshotHash
idempotencyKey
leaseOwner
leaseExpiresAt
heartbeatAt
deadlineAt
budgetReservationRef
status
commandReceiptRef
~~~

语义：

- 允许 at-least-once 调度，但副作用必须通过 idempotencyKey + command receipt 实现 exactly-once effect；
- worker 只可执行自己持有且未过期的 lease；
- heartbeat 超时后由调度器标记 stuck，先核对 receipt/外部状态，再决定续租或新 attempt；
- retry 继承相同逻辑输入 hash，使用新 attempt，不得覆盖历史；
- checkpoint 恢复不得绕过 lease、预算和副作用核对。

### 6.7 ResearchTaskBundle

~~~text
bundleId
runId
parentNodeRunId
objective
inputArtifactRefs
subtasks[] {
  subtaskId, role, acceptanceContract, budgetReservationRef,
  deadlineAt, status, taskId, sessionId, outputArtifactRefs
}
maxConcurrency
aggregationContract
status
~~~

只有 aggregationContract 可验证的结构化输出才能回到父节点。协调者不得把子 Agent 的完整上下文拼接为新的隐式事实；取消父节点必须传播到尚未结束的 subtask。

### 6.8 ResearchBudgetLedger

~~~text
budgetLedgerId
runId
stageId
policySnapshotHash
tokenLimit / tokenReserved / tokenConsumed
toolCallLimit / toolCallConsumed
wallClockLimit / wallClockConsumed
experimentLimit / experimentConsumed
computeLimit / computeConsumed
remaining
stopReason
updatedAt
~~~

所有 Agent、工具和实验调用先预留再结算；释放、超额和人工追加必须形成事件。预算投影不能反向修改 Run 策略。

### 6.9 HypothesisPortfolio

~~~text
portfolioId
runId
candidateId
claim
noveltyScore
competitionFitScore
falsifiabilityScore
evidenceSupportScore
feasibilityScore
counterEvidenceRefs
derivedFromCandidateIds
status
reviewRef
~~~

- 候选数量、演化轮数和评审预算有上限；
- Generation/Reflection/Ranking 只生成建议和评分，不直接晋升；
- HumanTask 选择进入协议设计的候选；
- 淘汰候选保留原因和 lineage，避免下一轮重复生成。

### 6.10 ExperimentCampaign

实验活动必须按以下阶段推进：

~~~text
feasibility/smoke
  -> stable baseline and bounded tuning
  -> core research agenda
  -> ablation and replication
~~~

这些是实验节点内部的活动阶段，不是第四个画布阶段；产品仍保持“知识搜集 / 实验设计 / 执行迭代”同一画布三分区。

核心字段：

~~~text
campaignId
runId
hypothesisCandidateId
protocolHash
environmentSnapshotHash
datasetSnapshotRefs
baselineRefs
metricContractRef
stage
seedSet
replicationCount
budgetLedgerRef
stopCriteria
experimentRunRefs
resultArtifactRefs
decision
~~~

不能把单次最佳结果视为结论；适用时必须报告多 seed/replication 的 mean、std 或置信区间，并保留失败与负结果。

### 6.11 ArtifactManifest 与可验证复用

~~~text
artifactId
contentHash
schemaVersion
producerNodeRunId
producerAttempt
inputSnapshotHash
configHash
environmentSnapshotHash
toolVersionHash
sourceArtifactIds
cacheDisposition
createdAt
~~~

只有 input/config/environment/tool version 全部匹配且质量门仍有效时才能复用；复用必须产生 ArtifactReused 事件并指向原 Artifact，不得复制为新“成果”。

### 6.12 ResearchLedger 与 CompetitionEvaluationSnapshot

ResearchLedger 是下列现有事实的只读索引：ClaimEvidenceStore、Team Knowledge、ExperimentContract、NodeRun、Handoff、ArtifactManifest 和 Result Package。它提供 claim → evidence → protocol → experiment → result → deliverable 的可追踪查询，不拥有写权限。

CompetitionEvaluationSnapshot 冻结：

~~~text
evaluationId
runId
rubricVersion
dimensionScores
claimCoverage
evidenceCoverage
experimentCoverage
deliverableCoverage
blockingWarnings
reviewerRefs
evaluatedAt
~~~

评分只是决策输入；有 blocking warning 时不得由总分掩盖，必须回到对应节点或人工终止。

---

## 7. 状态与执行语义

### 7.1 Agent 节点

~~~text
ready
  -> reserve budget and acquire TaskLease
  -> dispatch exact agent task with idempotencyKey
  -> running(taskId, sessionId, lease, heartbeat)
  -> task writeback
  -> validate command receipt and ArtifactManifest
  -> settle budget
  -> succeeded
  -> activate downstream
~~~

任务失败：

~~~text
running
  -> failed/stuck
  -> reconcile receipt and external state
  -> retry command
  -> new NodeRun attempt
~~~

所有 API 调用、文件写入、任务创建、知识写入和实验提交必须位于可持久化 task/command adapter 内；节点纯推理不得直接产生副作用。可重试 task 必须幂等，随机数、当前时间和模型采样等非确定输入必须在 task 内产生并持久化。

### 7.2 Human 节点

~~~text
ready
  -> waiting_human(HumanTask)
  -> accept
  -> succeeded
~~~

或：

~~~text
waiting_human
  -> reject/revise
  -> rejected Handoff
  -> child Run from checkpoint
  -> parent blocked/superseded
~~~

### 7.3 System 节点

System Adapter 必须消费真实领域对象。

- smoke：真实 planId、frozen protocol、Smoke result；
- controlled run：真实 experiment run；
- result package：真实终态、版本、证据和 ArtifactRef。

任何依赖缺失都必须失败并产生有界 runtime-scene 证据。

### 7.4 Projection

- runtimeCurrentNodeIds 从 active LangGraph tasks、pending HumanTask 和 checkpoint 推导；
- nodeRuns 从真实 NodeRun 记录投影；
- completedNodeIds 不得被忽略；
- nodeAttempts 不再独立拥有状态；
- Canvas 缓存不能持有过期 Agent 或运行状态。

### 7.5 Typed Action / Observation / Event

运行时至少提供以下类型化事件，并沿用统一 eventId、sequence、runId、nodeRunId、attempt：

- ActionIssued；
- ObservationRecorded；
- LeaseAcquired / LeaseHeartbeat / LeaseExpired；
- BudgetReserved / BudgetSettled / BudgetExceeded；
- ArtifactProduced / ArtifactReused；
- QualityGateEvaluated；
- HumanInputRequired / HumanDecisionRecorded；
- CommandReceiptRecorded；
- NodeRunTransitioned。

事件只记录有界摘要和引用，不包含完整 Prompt、密钥或大 Artifact。SSE、Timeline 和恢复逻辑消费同一事件源，不创建前端专用事件事实。

---

## 8. API 契约

### 8.1 创建 Run

~~~http
POST /api/research/workflows/{workflowId}/runs
~~~

请求：

~~~json
{
  "teamId": "research-team",
  "projectId": "project-...",
  "questionId": "question-...",
  "researchBriefHash": "sha256:...",
  "datasetRefs": [],
  "metricContract": {},
  "constraintSnapshot": {},
  "competitionRuleRef": "artifact-...",
  "competitionRuleVersion": "...",
  "trackAndRubricSnapshot": {},
  "researchObjectiveContract": {},
  "sourcePolicy": {},
  "budgetPolicy": {},
  "stopPolicy": {},
  "environmentSnapshotRef": "artifact-...",
  "modelRoutingPolicy": {},
  "evaluationContract": {},
  "idempotencyKey": "..."
}
~~~

响应必须包含完整 inputSnapshot、bindingSnapshot 和首个 ready NodeRun，不得包含伪完成节点。

### 8.2 查询

~~~text
GET /api/research/workflows/{workflowId}/definition
GET /api/research/workflows/{workflowId}/runs?teamId=
GET /api/research/workflow-runs/{runId}?teamId=
GET /api/research/workflow-runs/{runId}/canvas?teamId=
GET /api/research/workflow-runs/{runId}/nodes/{nodeId}?teamId=
GET /api/research/workflow-runs/{runId}/handoffs?teamId=
GET /api/research/workflow-runs/{runId}/handoffs/{handoffId}?teamId=
GET /api/research/workflow-runs/{runId}/research-ledger?teamId=
GET /api/research/workflow-runs/{runId}/budget?teamId=
GET /api/research/workflow-runs/{runId}/hypotheses?teamId=
GET /api/research/workflow-runs/{runId}/experiment-campaigns?teamId=
GET /api/research/workflow-runs/{runId}/evaluation?teamId=
GET /api/research/workflow-runs/{runId}/events?teamId=&afterSequence=
GET /api/research/workflow-runs/{runId}/stream?teamId=
~~~

### 8.3 命令

~~~text
POST /api/research/workflow-runs/{runId}/commands
POST /api/research/workflow-runs/{runId}/nodes/{nodeId}/commands
POST /api/research/workflow-runs/{runId}/human-tasks/{taskId}/resolve
PUT  /api/research/workflow-runs/{runId}/nodes/{nodeId}/session-binding
~~~

每个命令包含：

~~~text
teamId
idempotencyKey
expectedRunVersion
payload
~~~

### 8.4 错误语义

| HTTP | 语义 |
| --- | --- |
| 404 | team、Run、Node、Task 或 Handoff 不存在 |
| 409 | 非法状态转换、幂等键冲突、已解决任务重复处理 |
| 412 | required artifact、checkpoint 或输入快照缺失 |
| 422 | teamId 或命令 payload 缺失/无效 |
| 429 | 冻结预算已耗尽且需要人工缩减范围、追加预算或终止 |
| 503 | runtime/checkpointer/Agent task service 不可用 |

禁止在这些错误后返回空成功对象或回退到另一团队。

### 8.5 SSE

SSE 必须支持：

- 单调 sequence；
- Last-Event-ID；
- snapshot + delta；
- 重复事件幂等；
- Run 切换清空旧 cursor；
- 慢请求不能覆盖新 Run；
- 连接失败显示明确状态；
- 不静默退回无界轮询。

### 8.6 权限、审计与内容边界

- teamId 必须参与 Run、Node、Handoff、SessionBinding 和命令权限检查；
- createdBy、resolvedBy、acceptedBy 从可信操作者上下文产生，不信任客户端自由填写；
- 只有具备团队配置权限的操作者可以修改 workflow/stage/node binding；
- Agent 只能写回自己当前 nodeRunId 和 taskId 对应的结果；
- rebind、retry、fork、promote、rollback 和 result package 都写有界审计事件；
- 预算追加、模型升级、Artifact 复用和质量门覆盖都要求操作者身份与理由；
- imported source、网页、PDF 和知识文本继续按不可信内容清洗；
- API、SSE、runtime-scene 和日志不得包含完整 Prompt、secret 或无界 Artifact payload。

---

## 9. 后端文件责任

现有 pack 继续使用，不新建平行顶级 service tree。

建议目标：

~~~text
core/research/workflow/
  models.py
  definition.py
  challenge_cup_graph.py
  runtime.py
  checkpoint_store.py
  projection.py

core/web/services/team_workflow/research_runtime/
  service.py
  run_lifecycle.py
  run_projection.py
  node_execution.py
  agent_node_execution.py
  human_task_resolution.py
  event_stream.py
  binding_config.py
  session_binding_bridge.py
  handoff_builder.py
  handoff_lineage.py
  run_fork.py
  iteration_transition.py
  result_package.py
  evidence_graph_projection.py
~~~

责任：

| 文件 | 唯一职责 |
| --- | --- |
| service.py | 依赖装配和稳定 facade，不承载大段业务 |
| run_lifecycle.py | create/list/get/cancel |
| run_projection.py | Canvas、Run、Node 读模型 |
| node_execution.py | start/complete/fail/retry 与 NodeRun |
| agent_node_execution.py | exact agent task dispatch/writeback |
| human_task_resolution.py | HumanTask accept/reject/revise |
| event_stream.py | event query、SSE、replay |
| handoff_builder.py | 构造并校验单个 Handoff |
| handoff_lineage.py | lineage 查询、去重和 supersession |
| run_fork.py | checkpoint fork 和 child Run |
| result_package.py | 终态结果包门禁与构建 |

结构要求：

- 一个独立功能/变化边界一个文件；
- 不按行数机械拆 helper；
- 不建立无职责转发层；
- route 保持薄；
- 公共 DTO 有明确 Pydantic response model；
- projection 不写 canonical state。

---

## 10. 前端工作台与文件责任

### 10.1 目标结构

~~~text
web/src/routes/teams/research-workflow/
  ResearchProcessWorkspace.tsx
  useResearchWorkflowWorkspace.ts
  useResearchWorkflowRun.ts
  ResearchWorkflowToolbar.tsx
  ResearchWorkflowCanvasPane.tsx
  ResearchRunTimeline.tsx
  ResearchTeamPanel.tsx
  ResearchProcessNodeInspector.tsx
  NodeAgentSection.tsx
  NodeSessionSection.tsx
  NodeHandoffSection.tsx
  NodeArtifactSection.tsx
  NodeCommandSection.tsx
  researchProcessGraphModel.ts
  researchWorkflowNavigation.ts
  researchWorkflowEventReducer.ts
  researchWorkflowPollingController.ts
~~~

### 10.2 责任

| 文件 | 唯一职责 |
| --- | --- |
| ResearchProcessWorkspace.tsx | 页面组合，不持有完整业务状态机 |
| useResearchWorkflowWorkspace.ts | URL、selection、panel 本地状态 |
| useResearchWorkflowRun.ts | Run 查询、SSE、snapshot 校准 |
| ResearchWorkflowToolbar.tsx | Run 选择、创建、panel 切换 |
| ResearchWorkflowCanvasPane.tsx | Canvas 区域、加载/错误/空态 |
| ResearchRunTimeline.tsx | 领域事件时间线 |
| ResearchTeamPanel.tsx | 科研协调、成员、讨论入口 |
| ResearchProcessNodeInspector.tsx | 节点详情组合 |
| Node*Section | Agent、会话、交接、产物、命令独立功能 |

### 10.3 VUI 边界

- Route 只消费 VUI 产品 API；
- @xyflow/react 和 ELK 只在 VUI shadcn renderer；
- 不允许 route 导入 renderers/shadcn；
- 不允许 HeroUI；
- 新 VUI 元素必须登记 designs/INDEX.md；
- styles 与组件同步；
- 补充说明进入 hover、tooltip 或 Inspector，不堆叠卡片灰字。

### 10.4 ELK 与运行 overlay

布局缓存只保存 geometry：

~~~text
nodeId
x
y
width
height
ports
edge sections
~~~

以下字段必须在 geometry 之后实时合并：

~~~text
primaryAgentId
status
nodeRunId
taskId
sessionId
pendingHumanTask
artifact count
handoff status
~~~

definition/version 变化触发 relayout；普通状态或 Agent binding 更新不得丢失数据，也不得无意义 relayout。

### 10.5 桌面布局合同

不验收移动端。

1280×720：

- 工作流模式左团队栏默认折叠；
- 右 Inspector 可折叠，展开约 360px；
- Canvas 有效宽度目标不小于约 800px；
- 工具栏不遮挡画布；
- 状态图例不遮挡控制器；
- Inspector 关闭后 Canvas 自动扩展。

模式：

- 全图概览：三个阶段同时可见；
- 聚焦阶段：单阶段节点可读；
- 聚焦节点：选中节点居中并打开 Inspector。

三个模式仍使用同一个 Canvas 和同一 Run。

### 10.6 Header、Timeline 与 Team 面板

WorkspaceHeader 必须只保留一条主要操作路径：

- 当前团队；
- 当前 project/question；
- 当前 Run 与状态；
- 当前主要下一步；
- Run 切换与创建；
- Agent、Timeline、Team 面板入口。

项目或题目切换不得偷偷复用旧 Run；必须选择已有匹配 Run 或显式创建新 Run。

RunTimeline 使用领域事件语言，按 NodeRun attempt、TaskLease、Handoff、HumanTask、checkpoint、Artifact reuse 和 child Run 分组；不得只展示原始“sequence + type + nodeId”调试文本。

Team 面板必须展示科研协调 Agent、成员绑定覆盖率、当前阻塞责任人、团队讨论入口和版本治理状态；不得只显示占位说明。

科研效能信息不新增第四阶段，也不占据画布主体。它作为同一 Workspace 的 Inspector/Timeline 读模型提供：

- 质量门：来源、证据、反证、协议、复现和竞赛评分；
- 预算：各阶段 reserved/consumed/remaining 和停止原因；
- 执行：lease/heartbeat/stuck、重试、关键路径与并行任务；
- 复用：Artifact cache 命中、原产物、复用原因和节省量；
- 假设：候选组合、评分、淘汰原因与人工晋升；
- 实验：feasibility、baseline、agenda、ablation/replication 阶段。

### 10.7 Query、SSE 与缓存收敛

Query identity 至少包含：

~~~text
definition(workflowId)
runs(workflowId, teamId)
run(runId, teamId)
canvas(runId, teamId)
node(runId, nodeId, teamId)
handoffs(runId, teamId)
bindings(workflowId, teamId)
researchLedger(runId, teamId)
budget(runId, teamId)
hypotheses(runId, teamId)
experimentCampaigns(runId, teamId)
evaluation(runId, teamId)
~~~

规则：

- 命令只能设置本地 pending，不乐观伪造服务端成功状态；
- SSE 事件先经 reducer 幂等归并，再由 snapshot 校准；
- Run 切换必须取消旧请求、旧 cursor 和旧 Node detail；
- 慢响应不得覆盖新 Run；
- command 成功只 invalidates 受影响 Run、Node、Handoff 和 runs list；
- command 失败回收 pending 并显示真实 domain error；
- Route 和组件不得拥有 endpoint 字符串或第二套查询 key。

---

## 11. Agent、会话与配置交互

### 11.1 绑定层级

~~~text
workflow default
  -> stage override
  -> node override
  -> immutable run binding snapshot
~~~

运行开始后，普通配置修改只影响后续 Run。

活动 Run 换 Agent 必须执行显式 replace-agent 命令：

- 关闭或取消当前未完成 attempt；
- 创建新 NodeRun attempt；
- 保存 supersedesNodeRunId；
- 使用新 Agent 创建任务；
- 历史 SessionBinding 保留。

### 11.2 Agent 卡片

节点操作点复用会话栏成熟 Agent 卡片语义，至少显示：

- Agent 名称和稳定 ID；
- 角色；
- active/unavailable；
- 当前 task/session；
- 配置；
- 打开精确会话；
- 正式重试或替换 Agent。

无 Run 时允许配置默认绑定；有 Run 时默认显示 snapshot，不伪装为实时可变。

### 11.3 精确会话返回

returnTo 必须正确编码：

~~~text
/teams?teamId=...&researchView=workflow&runId=...&node=...&panel=node
~~~

从 Chat 返回后：

- 团队不变；
- Run 不变；
- 节点不变；
- Inspector 保持打开；
- 不依赖 selected team fallback。

---

## 12. Handoff、证据与结果包

### 12.1 Handoff 校验

创建 Handoff 前必须证明：

1. from NodeRun 已 succeeded；
2. required ArtifactRef 存在；
3. contentHash 可验证且非占位；
4. inputSnapshotHash 可重算；
5. from/to edge 属于当前 WorkflowVersion；
6. 同一 edge + attempt 没有重复有效 Handoff；
7. supersedes 链不存在环。

### 12.2 节点详情

Inspector 必须展示：

- 输入快照摘要；
- 输出 ArtifactRef；
- Handoff 状态；
- 接受/拒绝人和时间；
- rejection reason；
- supersedes/derived_from；
- parent/child Run；
- checkpoint；
- NodeRun attempts；
- task/session 锚点；
- TaskLease、heartbeat、deadline 和 stuck/retry provenance；
- 当前阶段预算、模型路由与消耗；
- ArtifactManifest、cache/reuse 来源；
- 质量门、竞赛评分维度与 blocking warning；
- HypothesisPortfolio 和 ExperimentCampaign lineage。

这些信息进入 Inspector/Timeline 的分区视图，不堆入默认节点卡。节点卡只保留名称、actor、主状态、当前责任人和一个主操作；详情通过选中、hover 或 Inspector 展开。

### 12.3 结果包门禁

Result Package 只有同时满足以下条件才能生成：

- Run 处于合法终态；
- terminalReason 非空；
- pending HumanTask 为 0；
- required ArtifactRef 全部存在；
- 不包含占位 hash；
- question、dataset、metric、protocol 已冻结；
- iteration decision 与 candidate version 一致；
- version_governance 已完成；
- ResearchLedger 能完整追踪 claim → evidence → protocol → experiment → result；
- 证据质量门、协议完整性、复现/统计门和 CompetitionEvaluationSnapshot 均通过；
- blocking warning 为 0，预算结算完整，失败与负结果未被删除；
- builtAt、版本、来源和 lineage 完整。

结果包必须幂等；相同终态输入得到相同内容 hash，不重复写候选。

结果包不是单一报告文件，至少包含：

- 正文结构与逐节 claim/evidence 引用；
- 答辩 PPT 的评分维度—证据映射；
- 演示脚本与可复现路径；
- claim—evidence—experiment 对照表；
- 实验协议、环境、seed、指标、消融与复现附录；
- 失败、限制、风险和未解决问题；
- 版本、来源、ArtifactManifest 与 lineage 清单。

所有交付物由同一事实链编译，不允许报告、PPT 和演示各自维护互相漂移的结论。

---

## 13. 旧页面和旧事实源处置

### 13.1 强制处置表

| 旧能力 | v2 处置 |
| --- | --- |
| Source collection 领域 service | 由 source Agent adapter 复用 |
| Experiment plan/smoke/full run | 由 Agent/System adapter 复用 |
| Research Loop 领域 service | 由 iteration decision 复用 |
| Team Knowledge 写入 | 由 knowledge_ingestion adapter 复用 |
| 旧三阶段主页面 | 删除 |
| 旧 stage rail/步骤条 | 删除 |
| researchLegacyRouteResolver | 删除 |
| TeamsLegacyResearchBoundary | 删除 |
| challengeTeamSurface | 删除 |
| 独立旧运行 writer | 删除 |
| 题目/MVP 状态 | 只读投影 WorkflowRun |
| 无入口组件 | 接入正式 Inspector 或删除 |

### 13.2 禁止的“迁移”

以下不算完成迁移：

- 把完整旧工作台塞进 drawer；
- 旧工作台操作后不写回 NodeRun；
- Workflow 自动推进但旧面板没有真实数据；
- 保留旧 route 以免测试失败；
- 用兼容 resolver 隐藏 teamId 缺失；
- 保留不可达页面或组件等待以后清理。

### 13.3 删除门

只有满足以下条件后才能删除旧 surface：

1. 用户能力已映射到 v2 节点、Inspector 或 adapter；
2. 真实写入已进入唯一领域 owner；
3. contract test 证明没有第二入口和第二 writer；
4. rg 证明没有生产引用；
5. 浏览器从 canonical Teams 入口可完成同等操作。

---

## 14. 实施任务图

~~~text
T0 基线与契约冻结
 ├─> T1 页面稳定性与 teamId 硬切换
 └─> T2 真实运行状态机
       └─> T3 Agent 任务与会话闭环
             └─> T4 Handoff、拒绝、重试与 checkpoint fork
                   └─> T5 科研效能、假设组合与实验活动
                         └─> T6 System Adapter、SSE、结果包和证据门禁
                               └─> T7 前端工作台与节点详情重构
                                     └─> T8 旧页面、旧 writer 和兼容代码清理
                                           └─> T9 Launcher 真实全链与同题基线验收
~~~

### Task T0：可实施基线

- Owner/Boundary：ADR、当前本文件、WorkflowDefinition 契约、测试基线。
- Dependency：当前 main WIP owner 已确认；新 worktree 和 claim 无重叠。
- Mode：BDD_TDD。
- Deliverable：
  - 冻结 v2.1 topology、RunInputSnapshot、状态和 API；
  - 冻结竞赛规则/赛道/评分、ResearchObjective、source/budget/stop/model/evaluation contract；
  - 选择一组不污染正式数据的代表性挑战杯题目，记录当前质量、时间、成本和人工干预基线；
  - 恢复 tracked ADR 0006，移除使其仅存在于本机的 obsolete ignore，并更新 ADR 0006/0007 与索引；
  - 为伪推进、占位 Artifact、Hook 崩溃、绑定丢失、返工死路、重复副作用和质量门绕过建立 RED。
- Verification/Stop：
  - RED 必须在未修代码上失败；
  - ADR、PRD、API、状态表和竞赛评分合同无矛盾；
  - 基线题目、数据、预算、模型策略和评分 rubric 可重放；
  - WIP/claim 重叠立即停止。

### Task T1：页面稳定与 teamId 硬切换

- Owner/Boundary：Teams shell、Router、navigation、team scope resolver。
- Dependency：T0。
- Mode：BDD_TDD。
- Deliverable：
  - Hook 无条件调用；
  - loading/success/error 分支稳定；
  - canonical URL 只认 teamId；
  - 删除旧 redirect/fallback。
- Verification/Stop：
  - React #310 复现用例转绿；
  - URL matrix、TeamsRoute layout、teamId contract 全绿；
  - 不允许用新的 fallback 修测试。

### Task T2：真实运行状态机

- Owner/Boundary：core/research/workflow + research_runtime lifecycle/projection。
- Dependency：T0。
- Mode：BDD_TDD。
- Deliverable：
  - create_run 只创建 queued Run + ready NodeRun；
  - 删除 placeholder Artifact；
  - NodeRun/Checkpoint/Event 成为唯一运行事实链；
  - NodeExecutionEnvelope、TaskLease、heartbeat、deadline、command receipt 和 outbox；
  - 所有外部副作用进入幂等 task/adapter；
  - service.py 拆为职责模块。
- Verification/Stop：
  - Run 创建后完成节点数为 0；
  - 缺少 Artifact 明确失败；
  - 重放/重试不产生重复 task、知识写入、实验提交或 Artifact；
  - heartbeat 超时可诊断并恢复；
  - restart 后 queued/running 状态一致。

### Task T3：Agent 任务与精确会话

- Owner/Boundary：node command adapter、research project task/session、binding bridge、Agent UI。
- Dependency：T2。
- Mode：BDD_TDD。
- Deliverable：
  - 四个资料 Agent 真实 adapter；
  - task API 接受显式 agentId；
  - Run snapshot 与实际 Agent 一致；
  - 精确 SessionBinding 和 returnTo；
  - 科研协调仅分解/分配/升级，不执行领域任务；
  - 独立子任务形成有界 ResearchTaskBundle，具备隔离上下文、追踪、取消和并行上限；
  - modelRoutingPolicy 记录 purpose、modelRef、成本和升级原因。
- Verification/Stop：
  - 每个 Agent 节点至少一条真实 task/session 测试；
  - rebind mismatch 必须失败；
  - 同 attempt 不重复 task/session；
  - supervisor 不得写 canonical domain record；
  - 并行取消、超时和预算耗尽可恢复。

### Task T4：Handoff 与恢复

- Owner/Boundary：handoff、human task、fork、iteration transition。
- Dependency：T2、T3。
- Mode：BDD_TDD。
- Deliverable：
  - Handoff query/detail API；
  - reject/revise child Run；
  - retry 新 NodeRun；
  - 真实 checkpoint fork；
  - parent/child/supersedes lineage。
- Verification/Stop：
  - 接受后有效 Handoff 恰好一条；
  - 拒绝后 child checkpoint 可恢复；
  - restart 后 lineage 不变；
  - 不允许只修改 queued/blocked 字段。

### Task T5：科研效能、假设组合与实验活动

- Owner/Boundary：research quality projection、hypothesis portfolio、experiment contract/campaign、budget、artifact manifest、competition evaluation。
- Dependency：T3、T4。
- Mode：BDD_TDD。
- Deliverable：
  - ResearchLedger 只读聚合现有 ClaimEvidenceStore、Knowledge、ExperimentContract、NodeRun/Handoff/Artifact/Result；
  - source perspective plan、evidence-gap、反证和 citation locator 质量门；
  - 有界 HypothesisPortfolio，保留候选评分、淘汰理由、lineage 和人工晋升；
  - ExperimentCampaign 按 feasibility → baseline → agenda → ablation/replication 推进；
  - ResearchBudgetLedger、停止条件、ArtifactManifest、内容寻址 cache/reuse；
  - CompetitionEvaluationSnapshot 和 blocking warning。
- Verification/Stop：
  - ResearchLedger 无写 API，不能成为第二事实源；
  - 质量门失败时节点不能晋升；
  - 同 hash Artifact 可验证复用，任一输入/配置/环境/tool version 改变则不得命中；
  - 候选数、辩论轮数、并行数和预算均有上限；
  - 单次最佳结果不能绕过复现/统计门。

### Task T6：System Adapter、SSE 与结果包

- Owner/Boundary：Smoke、controlled run、evaluation、version governance、result package、events。
- Dependency：T3、T4、T5。
- Mode：BDD_TDD。
- Deliverable：
  - System 节点消费真实领域记录；
  - version_governance 节点；
  - 真实 SSE；
  - typed Action/Observation/lease/budget/artifact/quality events；
  - 严格终态结果包门禁；
  - 从同一事实链编译报告、PPT 证据图、演示脚本、实验附录和限制清单。
- Verification/Stop：
  - 非终态、缺 Artifact、有 pending HumanTask、质量门失败或 blocking warning 时拒绝打包；
  - SSE 重放无丢失/重复；
  - 不同交付物中的 claim、数字、版本和证据一致；
  - 无静默 polling fallback。

### Task T7：前端工作台和节点详情

- Owner/Boundary：research-workflow Route、VUI Workflow renderer、API DTO/query key。
- Dependency：T1、T3、T4、T5、T6 的公共契约稳定。
- Mode：BDD_TDD。
- Deliverable：
  - Workspace/controller/panels 按职责拆分；
  - ELK geometry 与 runtime overlay 分离；
  - Agent/Timeline/Team/Node panel 可用；
  - Agent 卡片、精确会话和 Handoff 详情；
  - Inspector/Timeline 显示质量门、预算、lease、critical path、Artifact reuse、HypothesisPortfolio 和 ExperimentCampaign；
  - 默认节点卡保持紧凑，科研详情不压入画布主体；
  - 桌面 Canvas 布局合同。
- Verification/Stop：
  - 绑定异步更新不丢；
  - 面板 URL 与 UI 一致；
  - 1280×720 可读；
  - VUI contract、tsc、build 全绿。

### Task T8：旧 surface 与旧 writer 清理

- Owner/Boundary：legacy routes、legacy resolver、旧 stage surface、旧状态写入口、孤儿组件。
- Dependency：T7 达到功能等价。
- Mode：BDD_TDD。
- Deliverable：
  - 完成处置表；
  - 删除旧 route、fallback、writer 和 orphan；
  - 历史 Run 保持只读。
- Verification/Stop：
  - no-duplicate-surface contract；
  - rg 无生产引用；
  - canonical 入口功能等价；
  - 未迁移能力存在时不得删除。

### Task T9：真实验收、效能对照、集成和收尾

- Owner/Boundary：全栈、Launcher、runtime-scene、浏览器、Git/claim。
- Dependency：T0–T8。
- Mode：BDD_TDD + live acceptance。
- Deliverable：
  - 真实完整 Run；
  - Launcher restart 恢复；
  - 同题、同数据、同 rubric、同模型预算的 v2 baseline 与 v2.1 对照；
  - 适用的随机决策/实验至少 3 个 seed，报告质量 mean/std 与时间/成本 median/p95；
  - 可行时由不知道 run label 的人工评审按冻结 rubric 评分；
  - 三种桌面尺寸验收；
  - 合并、claim release、文档归档和 memory proposal。
- Verification/Stop：
  - 第 15、16 节全部满足；
  - 科研严谨性不得退化，且时间、成本、复用率、人工干预四项中至少两项出现可测改善；
  - 运行 fingerprint 不匹配提交时不得验收；
  - 任一 fallback/degraded 路径存在时不得声明完成。

### 14.1 串并行边界

可并行：

- T1 页面稳定与 T2 后端状态机可在不同 worktree 并行；
- T3 的 source adapter 子项在 API 合同冻结后可拆为独立职责；
- T5 中 HypothesisPortfolio、BudgetLedger 与 ArtifactManifest 可在公共 DTO 冻结后由不同 owner 实现，但最终 ResearchLedger 组合根只能由一个 owner 修改。

必须串行：

- WorkflowDefinition、公共 DTO、service facade、ResearchProcessWorkspace 组合根；
- T4 必须消费 T2/T3 的真实 NodeRun 和 task contract；
- T5 必须消费现有 canonical domain stores，不能先造新的 blackboard；
- T6 必须消费 T5 的质量、预算和 Artifact 合同；
- T7 必须消费稳定 API；
- T8 只能在功能等价后执行；
- T9 只能基于已合入 local main 的实际提交。

没有用户明确授权时，不主动创建并行开发 Agent。

---

## 15. 测试与验收矩阵

### 15.1 后端回归

必须覆盖：

1. create_run 后没有 Agent 节点自动成功；
2. 缺少 required Artifact 时失败；
3. 不产生 hash: 占位值；
4. binding snapshot Agent 等于 task Agent；
5. 同 attempt 不重复 task/session；
6. reject 创建真实 child checkpoint；
7. retry 创建新 NodeRun；
8. Handoff 接受幂等；
9. restart 后 waiting_human、blocked 和 lineage 不变；
10. result package 严格门禁；
11. teamId 缺失/不匹配失败；
12. SSE sequence、Last-Event-ID、replay；
13. corrupt store 显式诊断，不创建空索引；
14. TaskLease/heartbeat/stuck/reconcile/retry；
15. command receipt 保证重放不重复副作用；
16. BudgetLedger 预留、结算、释放、超限和人工追加；
17. ResearchLedger 无写入口且投影可重建；
18. HypothesisPortfolio 候选/轮数/预算上限和人工晋升；
19. ExperimentCampaign 四阶段、seed/replication、停止条件；
20. Artifact cache 命中与失效矩阵；
21. 质量门和 CompetitionEvaluation blocking warning；
22. 报告/PPT/演示/附录来自同一事实链。

建议命令：

~~~powershell
.\.venv\Scripts\python.exe tests\select_tests.py --from-git main --commands-only
.\.venv\Scripts\python.exe -m pytest tests\test_research_workflow_agent_binding.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_research_workflow_challenge_cup_graph.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_research_workflow_durable_runtime.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_research_workflow_iteration_decisions.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_research_workflow_langgraph_vertical_slice.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_research_workflow_result_package_evidence_graph.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_research_workflow_runtime_service.py -q
~~~

### 15.2 前端回归

必须覆盖：

1. Shell loading 分支变化不触发 Hook 错误；
2. 异步 binding 加载后 Agent 不丢失；
3. panel toolbar 改变 URL 和内容；
4. returnTo 保留 team/run/node；
5. teamId 无 fallback；
6. legacy resolver 不存在；
7. 1280×720 layout contract；
8. Node Inspector 各功能区可达；
9. loading/empty/error/running/waiting/blocked/failed/succeeded；
10. Route 不直连 shadcn renderer；
11. 预算、质量、lease、Artifact reuse、假设和实验只出现在 Inspector/Timeline，不挤压默认节点卡；
12. Run 切换后旧预算、假设、实验和 evaluation query 不泄漏；
13. blocking warning、预算耗尽、stuck task 都有明确可操作状态。

建议命令：

~~~powershell
cd web
npm.cmd test -- --run src/routes/teams/research-workflow
npm.cmd test -- --run src/routes/TeamsRoute.layout.test.ts
npm.cmd test -- --run src/components/vui/renderers/shadcn/workflow
npm.cmd test -- --run src/components/vui/vuiShadcnRouteContract.test.ts
npm.cmd test -- --run src/components/vui/vuiComponentDesignContract.test.ts
npx.cmd tsc -b --pretty false
npm.cmd run build
npm.cmd run check:bundle
npm.cmd run check:elk-worker-handshake
~~~

### 15.3 Launcher 真实链路

使用独立 acceptance project/question，避免污染正式研究数据。

必须完成：

1. 指定 teamId/projectId/questionId 创建 Run；
2. source_finding 创建真实 task/session；
3. 四个资料 Agent 产生真实 ArtifactRef；
4. 接受 Knowledge Package；
5. 生成有界 HypothesisPortfolio，并由人工晋升候选；
6. 协议、评审和冻结；
7. feasibility/smoke；
8. stable baseline；
9. core research agenda；
10. ablation/replication；
11. 人工拒绝一次；
12. 验证 child Run 与 checkpoint fork；
13. 修订后重新放行；
14. controlled run；
15. result evaluation 与 CompetitionEvaluationSnapshot；
16. 自动测试五种 iteration decision；
17. 真实浏览器至少验收 revise 与 promote/stop；
18. version governance；
19. result package 与多交付物一致性；
20. 从 Agent 会话返回原 team/run/node；
21. waiting_human 时 Launcher restart，恢复后状态不变；
22. running task 心跳中断后可诊断并安全恢复，外部副作用不重复。

尺寸：

- 1280×720；
- 1440×900；
- 1920×1080。

不包含移动端。

### 15.4 科研效果与效率对照

T0 先记录基线，T9 再在以下控制条件下对照：

- 同一冻结 question、dataset、competition rules/rubric；
- 同一模型可用集合与总预算；
- 同一 source policy、metric contract 和环境快照；
- 适用的随机 Agent/实验决策至少 3 个 seed；
- 可行时人工评分者不知道结果来自 baseline 还是 v2.1。

效果指标：

| 指标 | 定义 |
| --- | --- |
| primary-source ratio | 正式证据中主来源/权威来源占比 |
| claim-evidence coverage | 可交付 claim 中存在有效 EvidenceRef 的占比 |
| counter-evidence coverage | 关键 claim 中已检索并处置反证的占比 |
| viable hypothesis rate | 通过新颖性、可证伪性、可行性与竞赛契合门的候选占比 |
| protocol completeness | baseline、指标、seed、资源、停止条件、消融与复现字段完整度 |
| replication completeness | 要求复现的结论中已完成 replication 和统计摘要的占比 |
| traceability | claim → evidence → protocol → experiment → result → deliverable 可追踪率 |
| competition rubric score | 冻结 rubric 下的总分与各维度分，不允许总分掩盖 blocking warning |

效率指标：

| 指标 | 定义 |
| --- | --- |
| time to first viable hypothesis | 从 Run 创建到首个通过质量门并经人工晋升的候选 |
| time to first valid experiment | 从 Run 创建到首个满足协议的有效实验结果 |
| duplicate side effects | 重试/恢复造成的重复 task、知识写入、实验提交或 Artifact，目标为 0 |
| cache reuse rate | 符合复用条件的任务中命中已验证 Artifact 的比例 |
| human interventions | 完成单个 Run 所需人工决策次数及原因分布 |
| stage cost | 各阶段 token、工具、计算、实验次数与墙钟时间 |
| stuck recovery time | 从 heartbeat 超时到恢复/终止的时长 |
| parallel efficiency | 有效并行完成量与重复/取消浪费量 |
| result-package lead time | 合法终态到完整交付物包生成的时长 |

验收门：科研严谨性相关指标不得下降；不提前承诺固定提升百分比，T0 冻结基线后设数值阈值；T9 至少证明时间、成本、复用率、人工干预四项中的两项改善，并同时满足 duplicate side effects=0。

### 15.5 证据包

完成报告必须分别给出：

- source HEAD；
- local main merge commit；
- Launcher running fingerprint；
- backend test；
- frontend test；
- tsc；
- production build；
- HTTP contract；
- runtime-scene；
- browser screenshots；
- exact Agent task/session；
- checkpoint restart；
- Handoff lineage；
- result package hash；
- baseline/v2.1 对照数据、评分表、seed、预算和统计摘要；
- BudgetLedger、TaskLease、Artifact reuse 和 quality gate 摘要；
- Git status、claim 和 worktree。

不得把测试通过等同于运行时通过，也不得把浏览器截图等同于后端契约通过。

---

## 16. 完成定义

以下必须全部为真：

- [x] 0 个占位 Artifact hash；
- [x] 0 个 Agent 节点缺少真实 task adapter；
- [x] 0 个静默 teamId fallback；
- [x] 0 个旧挑战杯执行 route；
- [x] 0 个旧状态 writer；
- [x] 0 个 API 已绑定但画布显示未绑定；
- [x] 0 个未连接页面和 orphan component；
- [x] 0 个条件 Hook 崩溃；
- [x] 每个节点都可打开详情；
- [x] 每个 Agent 节点都可进入精确会话；
- [x] Agent snapshot 与实际 task Agent 一致；
- [x] 科研协调 Agent 只协调，不执行领域任务或写 canonical store；
- [x] TaskLease、heartbeat、receipt 和幂等副作用通过重放/故障注入；
- [x] ResearchLedger 可重建且 0 个写入口；
- [x] 假设候选、讨论轮数、并行度和预算全部有界；
- [x] feasibility/baseline/agenda/ablation-replication 阶段和停止条件可审计；
- [x] Artifact cache 只在 input/config/environment/tool version 全匹配时复用；
- [x] claim → evidence → protocol → experiment → result → deliverable 全链可追踪；
- [x] 证据、协议、复现/统计和竞赛评分门均通过，0 个 blocking warning；
- [x] 报告、PPT、演示和实验附录来自同一结果包事实链；
- [x] accept/reject/retry/revise/fork 均可恢复；
- [x] parent/child/handoff/version lineage 可审计；
- [x] Result Package 只能从完整终态生成；
- [x] 三阶段保持同一 Canvas；
- [x] 1280×720 桌面可用；
- [x] VUI、tsc、build、bundle、ELK worker 全绿；
- [ ] Launcher restart 后状态一致（待 T9 实机）；
- [ ] 同题 baseline/v2.1 对照中科研严谨性无退化，至少两项效率指标改善且重复副作用为 0（待 T9 实机）；
- [ ] 运行 fingerprint 与验收提交一致（待 T9 实机）；
- [ ] local main 干净（待收尾）；
- [ ] claim 已 release（待收尾）；
- [ ] 本文件标记 implemented 并迁入 docs/archive/（待收尾）。

任一项不满足，任务状态只能是 in-progress 或 blocked，不得使用“基本完成”“局部完成”或“可先体验”替代。

---

## 17. 风险、失败检测与回滚

### 17.1 当前 WIP 冲突

风险：main 未提交 WIP 与 T7 同路径。

处置：

- 启动前确认 owner；
- 需要吸收时先提交并独立审查；
- 不需要时由 owner 明确处理；
- 不 stash、reset 或覆盖未知改动。

### 17.2 v2 持久化

风险：Run index 与 checkpoint 不一致。

处置：

- 迁移前备份；
- schema version；
- 原子迁移；
- 启动时 reconcile；
- 缺失/损坏显式失败；
- 不静默创建空存储。

### 17.3 兼容性

产品决定是不兼容旧执行入口。

回滚方式：

- Git 回滚对应任务提交；
- 恢复迁移备份；
- 保留 v1 历史只读数据；
- 不通过双写、旧 route 或 fallback 维持两套运行。

### 17.4 Agent 副作用

风险：重放、重试或 checkpoint resume 重复创建任务/写入 Knowledge。

处置：

- idempotency key；
- NodeRun attempt；
- task/session 唯一约束；
- Handoff 唯一 edge identity；
- 外部写入结果先核对再 resume。

### 17.5 UI 状态漂移

风险：布局、React Query、SSE 和 URL 同时持有运行事实。

处置：

- 服务端 projection 唯一；
- query cache 只缓存 projection；
- URL 只保存 selection/panel；
- geometry cache 不保存 runtime overlay；
- SSE 后用 snapshot 校准。

### 17.6 多 Agent、缓存与成本

风险：无限候选/辩论造成成本失控；共享上下文形成第二事实源；缓存隐藏输入变化；轻量模型降低科研质量。

处置：

- 候选数、讨论轮数、并行度、重试和截止时间全部由冻结策略限制；
- 子任务隔离上下文，只通过结构化 Artifact/Observation 合并；
- cache key 覆盖 input/config/environment/tool version，复用写入显式事件；
- 模型按 purpose 路由，质量门失败可显式升级；
- 预算耗尽进入 waiting_human/blocked，不自动降质继续。

### 17.7 科研指标投机

风险：Agent 只追求 rubric 总分或单次最佳实验，忽略反证、统计、负结果和可复现性。

处置：

- blocking warning 不可被总分抵消；
- 结论必须具有 EvidenceRef、反证处置和实验 lineage；
- 适用时必须多 seed/replication 并报告分布；
- 保留失败和负结果；
- 最终人工评审同时检查质量分与证据链。

### 17.8 合并与发布

- 每个 Task 独立提交；
- shared hot file 同时只允许一个 owner；
- 本地 main 脏时禁止 merge；
- merge 后运行 targeted validation；
- T9 前不 push、不发布；
- remote push 需要用户另行授权；
- Windows Launcher/后台子进程不得出现可见控制台。

---

## 18. 文档与项目记忆收尾

实施期间：

- 本文件状态从 active-plan → user-approved → in-progress；v2.1 调研增量未获确认前不得跳过 user-approved；
- Implementation link 指向实际 branch/commit；
- 每阶段只更新可验证结果；
- 不把测试日志全文写入文档。

完成后：

1. 设置 Status=implemented；
2. 写入最终 commit 和验证摘要；
3. 把本文件迁入 docs/archive/；
4. 从 docs/prds/README.md 移除 active-plan 入口或改为 archive 链接；
5. 将长期规则提炼到 ADR、standards 或 owning README；
6. 由 memory-sync owner 写入一次 project-memory durable delta；
7. release claim；
8. 清理已合入且干净的 task worktree。

---

## 19. 开发 Agent 开始前检查

~~~text
[ ] 已读 AGENTS.md 与 ccdawn-brt
[ ] 已读本文件、tracked ADR 0006/0007、Teams README、team_workflow README；若 ADR 0006 尚未 tracked，先完成 T0
[ ] 已确认当前 main HEAD 和 dirty WIP owner
[ ] 已建立独立 worktree/branch
[ ] preflight 通过
[ ] claim 无重叠
[ ] 已选择当前 Task，不跨 Task 扩写
[ ] RED 测试在修复前真实失败
[ ] 未引入兼容 route/fallback
[ ] 未在 service.py/Workspace 继续堆新职责
[ ] 已定义成功证据与停止条件
[ ] 已冻结代表性基线题目、竞赛 rubric、预算、模型策略与对照方法
[ ] 未引入第二编排 runtime、通用可变 blackboard 或无界 Agent swarm
~~~

开发 Agent 应从 T0 开始，按 Critical Path 连续执行；遇到会改变 teamId、Run 输入、拓扑、持久化或验收口径的新证据时停止受影响写入并重新对齐。

---

## 20. 验收记录（acceptance ledger）

> 由验收执行轮按 §15.5 证据包格式追加；只记录已验证事实，不复制测试日志全文。

### 2026-08-11 静态与自动化矩阵验收（T0–T8 覆盖）

- 基线：local main `aaab4b462`（验收 worktree `codex/challenge-v21-acceptance` 起点）；ADR 0006/0007 均已 tracked；
- 后端矩阵：`tests/test_challenge_cup_*.py`（排除 spike/predictive 实验线）+ `test_challenge_question_runs.py` + `test_challenge_program_projection.py` + `test_challenge_question_run_routes.py` + `tests/test_research_workflow_*.py` 共 28 文件 **159 passed**，含重复运行顺序稳定性验证；
- 前端矩阵：`vuiShadcnRouteContract` + `vuiComponentDesignContract` **11 passed**；`src/routes/teams/research-workflow` + `TeamsRoute.layout.test.ts` **179 passed**；`tsc -b` exit 0；生产 build exit 0；`check:bundle` passed；`check:elk-worker-handshake` passed；
- 静态扫描：无 `hash:` 占位 Artifact；`ResearchFlowCanvasRoute.tsx`/`.styles.ts` 已删除且无生产引用；无 orphan 组件（`ChallengeMvpProgressPanel`/`EvidenceGraphView` 均由 InspectorPane 引用）；`research.tailwind.css` 中 `@source` 指向已删文件的死引用 1 处（待 T8 收尾处理）；
- 修复（验收发现）：`core/web/routes/team_workflows/experiment.py` 缺失 `HTTPException` 导入导致 fails-closed 路径 NameError（500）；`tests/test_challenge_question_run_routes.py` monkeypatch 目标随 `1467cd407` 路由重构漂移；
- 未覆盖：T9 Launcher 真实链路、同题 baseline/v2.1 对照、1280×720 实机尺寸、Launcher restart 一致性、fingerprint 核对（待 T9）；实验线（spike/predictive coding）依赖隔离环境未在本轮运行。
- 环境说明：`tests/test_challenge_program_projection.py` 与 `tests/test_challenge_question_runs.py` 依赖 gitignored 本地数据目录 `挑战杯/`（`.gitignore:118`），该目录仅存在于根 main 工作区；验收 worktree 中此类测试因缺少该目录而无法收集，以根 main 工作区结果为准（159 passed 含上述文件）。
