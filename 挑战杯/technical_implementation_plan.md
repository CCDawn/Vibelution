# 挑战杯科研流程技术实施方案

## 1. 实施目标

本方案用于把当前“神经科学启发算法发现”科研流程从可视化规划推进到可运行 MVP。第一阶段只覆盖 01-09：资料进入工作区、生成 paper_note、提取 neuro_mechanism、机制到计算抽象、生成 algorithm_hypothesis、证据复核、知识治理入库、候选图谱预览、正式知识图谱同步。

第一阶段不实现真实训练 runner，不自动生成比赛交付材料，不绕过记忆平台审批门禁。

## 2. 总体架构

复用优先原则：

- 先复用 Vibelution 已有 Research Agent、research flow canvas、prompt-research-* 模板和研究组织治理工具。
- 先复用 Team Knowledge 的 SourceArtifact、RefinementProposal、IngestionPackage、review/apply、KnowledgeItem、Trace 能力。
- 先复用 agent-knowledge-steward 作为唯一知识治理 Agent，不新增平行知识管理员。
- 先复用 knowledge_rag_retrieve_tool、research_knowledge_query_tool 和 /api/memory/knowledge-graph。
- 只补当前缺口：候选数据基座、PDF 页码锚点、候选 schema 校验、候选图谱 JSON、挑战杯流程适配脚本。

系统分为 6 层：

1. 候选资料工作区：新增最小 knowledge_candidates，只保存正式平台尚不能表达的候选中间态。
2. 本地研究工作模型层：接入 `bossAGI-standard / qwen3.5-9b`（本地 OpenAI-compatible，32k），负责高吞吐候选生成、资料初筛、结构化草稿和预审。
3. 研究编排复用层：复用 research_service、research flow canvas、prompt-research-broad/deep/review/themes/card 和研究组织治理工具。
4. 候选状态机：新增轻量校验脚本，约束 draft 到 official_synced 的流转，不替代现有 runtime 状态系统。
5. 记忆平台复用层：复用 SourceArtifact、RefinementProposal、IngestionPackage、KnowledgeItem、Trace 和 agent-knowledge-steward。
6. 图谱展示层：候选图谱只补 candidate_graph.json；正式图谱复用 /api/memory/knowledge-graph。

## 3. 目录与数据落盘

建议在挑战杯目录下新增最小候选工作区：

```text
挑战杯/
  knowledge_candidates/
    source_manifest.json
    index.json
    candidate_graph.json
    official_sync_records/
    sources/
    paper_notes/
    neuro_mechanisms/
    mechanism_mappings/
    algorithm_hypotheses/
    review_records/
    steward_ingestion_packs/
    rejection_archive/
```

落盘原则：

- 原始文件不改写，只登记路径、hash、页码范围和来源可信度。
- 所有候选 JSON 都有 id、status、createdAt、updatedAt、sourceRefs、links、review、graphSync。
- 候选数据不直接进入 Team Knowledge 或正式 RAG。
- 正式入库只允许通过 Knowledge Steward Agent 提交 proposal/rating/ingestion pack，再经 Ingestion Approval Gate 通过。
- 能用 Team Knowledge 表达的正式内容，不在 knowledge_candidates 里重复建一套正式库。

## 4. 核心 JSON Schema

### 4.1 source_manifest.json

必填字段：

- id
- path
- type: pdf | paper | note | competition_doc
- title
- sourceTrust: high | medium | low | unknown
- allowedForAnalysis
- pageScope
- sha256
- notes

### 4.2 paper_note

必填字段：

- id
- sourceRefs
- summary
- keyFindings
- methods
- limitations
- citations
- uncertainty
- status: paper_note_draft | paper_note_needs_revision

### 4.3 neuro_mechanism

必填字段：

- id
- paperNoteIds
- description
- brainSystems
- cognitiveFunctions
- experimentalPhenomena
- authorInterpretation
- projectInterpretation
- evidenceRefs
- confidence
- riskFlags
- status: mechanism_candidate

### 4.4 mechanism_mapping

必填字段：

- id
- neuroMechanismIds
- computationalAbstraction
- factLayer
- inferenceLayer
- overAnalogyRisk
- engineeringImplication
- status: mechanism_mapping_candidate

第一版可以内嵌在 algorithm_hypothesis 中，后续再独立成文件。

### 4.5 algorithm_hypothesis

必填字段：

- id
- neuroMechanismIds
- mechanismMappingIds
- architectureChange
- trainingObjective
- optimizationOrInferenceProcess
- baseline
- expectedBenefit
- expectedComputeCost
- implementationHint
- experimentPlan
- status: hypothesis_candidate

### 4.6 review_record

必填字段：

- id
- candidateIds
- checklist
- comments
- requiredChanges
- needsDecision
- riskFlags
- reviewerAgent: Evidence Review Agent
- status: review_prefiltered | review_needs_revision

边界：

- `review_prefilter` 只能产出候选审稿记录，不写最终 `decision`。
- 最终 `decision: approve_for_steward | needs_revision | reject` 留给 Evidence Review Agent 门禁或 Ingestion Approval Gate。

### 4.7 steward_ingestion_pack

必填字段：

- id
- candidateIds
- targetDomain
- sourceTrace
- riskSummary
- proposalPayload
- ratingSuggestion
- approvalRequired: true
- status: steward_pack_draft | steward_needs_revision | steward_pending_knowledge_review | approved_to_ingest

边界：

- `steward_pack_draft` 第一版只进入 CandidateStore，候选类型沿用 `review_record`。
- 草稿包必须显式 `approvalRequired=true`。
- 草稿包不得包含 `officialSync`、`applyNow=true`、`writeOfficialGraph=true` 等立即正式写入意图。
- 合格草稿进入 `steward_pack_draft`；缺治理字段、审批字段不合规或试图写正式库时进入 `steward_needs_revision`。

### 4.8 official_sync_record

必填字段：

- id
- ingestionPackId
- officialKnowledgeItemId
- ragStatus
- graphStatus
- approvedBy
- approvedAt
- status: official_synced

## 5. 状态机

主状态链：

```text
source_registered
  -> paper_note_draft
  -> mechanism_candidate
  -> mechanism_mapping_candidate
  -> hypothesis_candidate
  -> review_ready
  -> ready_for_steward
  -> steward_pack_draft
  -> steward_pending_knowledge_review
  -> candidate_graph_visible
  -> approved_to_ingest
  -> official_synced
```

失败回退：

- source_needs_confirmation：资料路径、权限或来源不清。
- paper_note_needs_revision：摘要缺页码、缺 citation、过度推断。
- mechanism_needs_revision：机制证据弱、术语不稳。
- mapping_needs_revision：类比边界不清。
- hypothesis_needs_revision：缺 baseline、expectedBenefit 或 experimentPlan。
- steward_needs_revision：目标知识域或证据链不满足入库条件。
- rejected：进入 rejection_archive，不再自动推进。

流程转移原则：

- 所有非线性跳转都必须产生 transfer_request 或 transfer_record，不能只改 status。
- 转移必须写明 fromNode、fromState、toNode、toState、reasonCode、evidenceRefs、requestedByAgent、assignedToAgent、acceptance。
- 普通功能 Agent 可以提出 transfer_request，但不能直接写最终流程状态。
- Research Coordination Agent 是唯一流程状态写入者，负责裁决 transfer_request、分配 assignedToAgent、写入 state/index，并关闭 transfer_record。
- 资料不足、证据不足、实验计划缺失、图谱断链、入库退回等问题优先返工到最小上游节点，不默认回到流程起点。
- 涉及新增 Agent、工具权限、记忆权限或通信边变更时，不直接跳转执行节点，先进入 risk_escalation，由 Research Organization Agent / Capability Governance Agent 处理。
- rejected 不是普通返工状态；只有 Ingestion Approval Gate 或 Evidence Review Agent 给出 reopenReason，并由 Research Coordination Agent 写入 reopen transfer_record，才允许从 rejection_archive 重新进入候选流程。

推荐流程转移表：

| 场景 | 触发状态 | 目标节点/状态 | 负责接收 | 必要产物 |
|---|---|---|---|---|
| 资料不足 | paper_note_needs_revision / mechanism_needs_revision | 01 资料登记 source_needs_confirmation | Source Intake Agent | transfer_request、missing_source_list |
| 摘录缺页码或 citation | paper_note_needs_revision | 02 论文笔记 paper_note_draft | Paper Note Extraction Agent | transfer_record、citation_fix_list |
| 机制证据弱 | mechanism_needs_revision | 03 神经机制提取 mechanism_candidate | Neuro Mechanism Extraction Agent | evidence_request、weak_evidence_report |
| 机制到算法映射不稳 | mapping_needs_revision | 04 机制映射 mechanism_mapping_candidate | Mechanism Mapping Agent | analogy_risk_note、required_changes |
| 算法假设不可测 | hypothesis_needs_revision | 05 算法假设 hypothesis_candidate | Algorithm Hypothesis Agent | experiment_plan_fix |
| 审稿要求返工 | review_ready + needs_revision | 最近责任节点 | 原产出 Agent | review_record、requiredChanges |
| 图谱断链 | candidate_graph_visible + broken_links | 对应缺失节点状态 | Candidate Graph Preview Agent 协调原产出 Agent | broken_link_report |
| 入库治理退回 | steward_needs_revision | 06 审稿或 07 知识治理 | Evidence Review Agent / Knowledge Steward Agent | steward_feedback |
| 审批门禁拒绝 | approved_to_ingest + rejected_by_gate | rejection_archive 或 06 审稿 | Ingestion Approval Gate 指定 | ingestion_rejection_reason |
| 权限或能力缺口 | 任意状态 | risk_escalation | Research Coordination Agent | risk_record、proposal |

转移关闭条件：

- assignedToAgent 明确接收。
- 目标节点补齐 acceptance 中列出的缺口。
- 原始 blocker 或 risk_record 更新为 resolved、rejected 或 superseded。
- Research Coordination Agent 生成 status_digest，并把新的 state/index 写回候选工作区；其他功能 Agent 不直接写最终状态。
- 如果转移影响知识候选或图谱，Candidate Graph Preview Agent 重新生成候选图谱和断链报告。

## 5.1 TeamWorkflowOrchestration

经需求对齐，流程状态机编排应作为 Team 的通用能力，而不是挑战杯专用孤岛。Team 在这里不是单纯成员列表，而是科研信息流控制抽象。

当前挑战杯流程直接绑定 Vibelution 已有团队 `research-team`（团队名：科研团队），不另建新的挑战杯团队。该团队来自 Research Organization 自动同步，`teamCategory=科研组织团队`、`teamSource=research_organization`，并已关联团队群聊 `room-20260529-090009-757107-6a747d62`（purpose：`research_coordination`）。流程编排落盘在 `workspace/teams/research-team/workflow_orchestration.json`，候选知识仓库落盘在 `workspace/teams/research-team/candidate_store/index.json`。

### 5.1.1 已落地的前半段后端切片

本轮已先完成 Team 编排与知识搜集/筛选入库前置链路的最小后端能力，并补入本地 PDF `source-extraction` 页码锚点抽取，以及 `sourceExtraction` 到 `paper_note_draft` 的首版自动草稿桥；Team 页面已新增科研流程只读面板，用于查看 `research-team` 的 workflow、CandidateStore、校验摘要和最近候选；暂不处理长文自动分块，不直接接正式 Team Knowledge 入库。

新增文件：

- `core/web/services/team_workflow_orchestration_service.py`
- `core/web/routes/team_workflows.py`
- `tests/test_team_workflow_orchestration_service.py`
- `tests/test_team_workflow_routes.py`

路由注册：

- `core/web/app.py` 已挂载 `team_workflows_router` 到 `/api`。

已落地 API：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/teams/{team_id}/workflow-orchestration` | 读取或自动初始化 Team 编排视图 |
| PUT | `/api/teams/{team_id}/workflow-orchestration` | 确保 `challenge_cup_research` 编排与 `ownerAgentId` |
| POST | `/api/teams/{team_id}/workflow-orchestration/candidates/source` | 登记 `source_manifest` 候选 |
| POST | `/api/teams/{team_id}/workflow-orchestration/candidates/{candidate_id}/source-extraction` | 对本地 PDF `source_manifest` 计算 `sha256`、抽取 `metadata.sourceExtraction.pageAnchors` / `excerpt`，并重新校验候选；抽取失败停在 `source_needs_confirmation` |
| POST | `/api/teams/{team_id}/workflow-orchestration/candidates/{candidate_id}/paper-note-draft` | 将已完成的 `sourceExtraction.excerpt/pageAnchors` 转为本地研究模型 `paper_note_draft` 任务，记录 `paper_note` 候选，并回写 source candidate 的 `metadata.paperNoteDrafts` trace |
| GET | `/api/teams/{team_id}/workflow-orchestration/candidates` | 按 `candidateType`、`currentState`、`qualityStatus` 查询 CandidateStore，并返回 `validationSummary` |
| GET | `/api/teams/{team_id}/workflow-orchestration/candidates/validation` | 生成 CandidateStore 校验报告，统计 valid/invalid/error/warning 并列出每个候选的问题 |
| POST | `/api/teams/{team_id}/workflow-orchestration/transfers` | 功能 Agent 提交流程转移请求 |
| POST | `/api/teams/{team_id}/workflow-orchestration/transfers/{transfer_id}/decide` | `Research Coordination Agent` 裁决并写最终状态 |
| POST | `/api/teams/{team_id}/workflow-orchestration/local-research-model/tasks` | 构建本地研究模型任务包，不直接调用模型 |
| POST | `/api/teams/{team_id}/workflow-orchestration/local-research-model/outputs` | 校验并记录本地研究模型 JSON 草稿 |
| POST | `/api/teams/{team_id}/workflow-orchestration/local-research-model/invoke` | 构建任务包、调用 `bossAGI-standard / qwen3.5-9b`、解析 JSON 并写入 CandidateStore；解析失败不入库 |
| POST | `/api/teams/{team_id}/workflow-orchestration/steward-packs/{candidate_id}/knowledge-ingestion` | 把有效 `steward_pack_draft` 提交到指定 `knowledgeBaseId`，创建 `SourceArtifact`、pending `RefinementProposal` 和可选 pending `ratingSuggestion`；不创建正式 `KnowledgeItem`、RAG 或正式图谱 |
| POST | `/api/teams/{team_id}/workflow-orchestration/steward-packs/{candidate_id}/knowledge-ingestion/review` | 只审批 `steward_pending_knowledge_review`；`approved` 复用 Team Knowledge `review/apply` 创建正式 `KnowledgeItem`，把 proposal 级 pending `ratingSuggestion` 迁移为 KnowledgeItem 级 pending rating review，并把 `sourceTrace` / `candidateIds` 转成 `metadata.officialResearchGraph` 正式边后写 `officialSyncRecord`；`rejected` 退回 `steward_needs_revision` |

已落盘结构：

```text
workspace/teams/<teamId>/
  workflow_orchestration.json
  candidate_store/
    index.json
  transfer_records.jsonl
```

已实现行为：

- `workflowKind` 第一版只允许 `challenge_cup_research`。
- `transferPolicy.requiresUserConfirmation=false`。
- 功能 Agent 可提交 `transfer_request`。
- 只有 `ownerAgentId`，默认 `Research Coordination Agent`，能裁决转移并写候选最终状态。
- `transfer_record` 记录 `decidedByAgent`。
- 新增运行事件日志：`workflow.created`、`workflow.ensure`、`candidate.registered`、`candidate.source_extracted`、`transfer.requested`、`transfer.decided`；日志只记录轻量 ID、状态和类型，不记录大段正文。
- 候选资料先以最小 `source_manifest` 进入 CandidateStore；正式 Team Knowledge/RAG/知识图谱仍等待后续治理接线。
- 本地研究工作模型已落地任务包构建、32k 上下文预算、统一 `LLMClient` invoke、JSON 输出提取/校验和草稿记录；`bossAGI-standard / qwen3.5-9b` 通过临时 `model_ref` profile 调用，解析失败不写 CandidateStore。
- CandidateStore 已支持按候选类型、当前状态和质量状态查询；`source_manifest` 已支持 `sourcePath`、`sha256`、`allowedForAnalysis`、`pageScope` 字段。
- PDF `source_manifest` 的最小校验已落地：缺 PDF 路径、缺 `sha256` 或 `allowedForAnalysis=true` 时，候选会进入 `source_needs_confirmation` / `source_manifest_invalid`，等待 Source Intake Agent 补齐。
- 本地 PDF `source-extraction` 已落地：对已登记 `source_manifest` 读取本地 PDF，计算 `sha256`，抽取 `pageAnchors` 与 `excerpt` 写入 `metadata.sourceExtraction`，并把 `pageScope` 回写候选。
- `source-extraction` 不会自动修改原文，不会下载远程资料，不会创建正式 `KnowledgeItem`、RAG 或正式图谱；只有调用方显式传入 `allowedForAnalysis=true` 时才更新分析许可。
- 缺文件、非 PDF、PDF 解析器不可用、PDF 打不开或无可抽取文本时，`metadata.sourceExtraction.status=failed`，候选保持 `source_needs_confirmation` / `source_manifest_invalid`，并在校验中记录 `source_extraction_failed`。
- `paper-note-draft` 自动草稿桥已落地：读取完成状态的 `metadata.sourceExtraction`，把 `excerpt/pageAnchors` 组装为 `sourceRefs/evidenceRefs/excerpt`，复用 `invoke_local_research_model` 调用本地研究模型，并通过 `record_local_research_model_output` 写入 `paper_note` 候选。
- 成功或需修订的 `paper_note` 都停留在 CandidateStore，不写正式 Team Knowledge、RAG 或正式图谱；source candidate 会追加 `metadata.paperNoteDrafts` trace，保留 source -> paper_note 的可追溯关系。
- 新增运行事件日志：`candidate_store.validated`，只记录候选数、invalid 数、error/warning 数和 workflowId。
- `paper_note_draft` 输出契约已补齐 `keyFindings`、`methods`、`limitations`、`citations`；每条 `keyFinding` 必须带 `sourceRef` 和 `page` / `citation` / `evidenceRef` 锚点。
- 合格 `paper_note` 本地模型输出进入 `paper_note_draft`；缺 citation/page anchor 时进入 `paper_note_needs_revision`，不能自然推进到 `mechanism_candidate`。长文拆分、多 chunk 汇总和多草稿合并仍待接。
- `neuro_mechanism_extract` 输出契约已补齐 `paperNoteIds`、`description`、`brainSystems`、`cognitiveFunctions`、`experimentalPhenomena`、`authorInterpretation`、`projectInterpretation`。
- 合格 `neuro_mechanism` 本地模型输出进入 `mechanism_candidate`；缺机制证据或神经术语不确定但未标记 `terminology_uncertain` 时进入 `mechanism_needs_revision`，不能自然推进到机制映射。
- `mechanism_mapping` 输出契约已补齐 `neuroMechanismIds`、`computationalAbstraction`、`factLayer`、`inferenceLayer`、`overAnalogyRisk`、`engineeringImplication`。
- 合格 `mechanism_mapping` 本地模型输出进入 `mechanism_mapping_candidate`；缺事实/推断分层、工程含义，或高类比风险未标记 `over_analogy_risk` 时进入 `mapping_needs_revision`，不能自然推进到算法假设。
- `steward_pack_draft` 输出契约已补齐 `candidateIds`、`targetDomain`、`sourceTrace`、`riskSummary`、`proposalPayload`、`ratingSuggestion`、`approvalRequired`。
- 合格 `steward_pack_draft` 本地模型输出进入 `steward_pack_draft`，仍只写 CandidateStore；缺治理字段、`approvalRequired` 非 true，或包含 `officialSync`、`applyNow=true`、`writeOfficialGraph=true` 等正式写入意图时进入 `steward_needs_revision`。
- 有效 `steward_pack_draft` 可通过待审入库 API 映射为 Team Knowledge 的 `SourceArtifact`、pending `RefinementProposal`，并可选创建 pending `ratingSuggestion`；候选状态更新为 `steward_pending_knowledge_review`，metadata 记录 `knowledgeBaseId`、`sourceArtifactId`、`proposalId`、`ratingSuggestionId` 和 officialBoundary=false。
- 该步骤仍不创建正式 `KnowledgeItem`，不写正式 RAG，不写正式图谱。
- `steward_pending_knowledge_review` 可通过审批门禁 API 审批；`approved` 调用 Team Knowledge `review_refinement_proposal(status=applied)` 创建正式 `KnowledgeItem`，候选进入 `official_synced`；`rejected` 调用 `status=rejected`，候选进入 `steward_needs_revision`。
- 审批通过且存在 proposal 级 pending `ratingSuggestion` 时，系统会先把旧 suggestion 标记为 `applied`，再创建一个面向正式 `KnowledgeItem` 的 pending rating suggestion；不会自动把评分应用到 `KnowledgeItem`。
- 审批通过后，系统会把 `sourceTrace`、`candidateIds`、`reviewRecordIds` 等治理上下文翻译为 `supports`、`maps_to`、`inspires`、`approved_for_ingestion` 正式科研 trace，写入正式 `KnowledgeItem.metadata.officialResearchGraph`。
- 审批结果写入 `metadata.officialSyncRecord`，记录 `knowledgeBaseId`、`proposalId`、`batchId`、`knowledgeItemIds`、`ratingSuggestionMigration`、`officialResearchGraph`、`reviewedByAgentId`、`ragStatus`、`graphStatus` 和正式写入边界。

已验证：

- `.venv\Scripts\python.exe -m pytest tests/test_team_workflow_orchestration_service.py tests/test_team_workflow_routes.py`
- `python -m py_compile core\web\services\team_workflow_orchestration_service.py core\web\routes\team_workflows.py core\web\app.py`

第一版原则：

- Team 负责“流”：状态编排、转移裁决、Agent 路由、返工派发、沟通模式、消息契约。
- CandidateStore 负责“物”：source_manifest、paper_note、neuro_mechanism、mechanism_mapping、algorithm_hypothesis、review_record、candidate_graph 等候选资料本体。
- TeamWorkflowOrchestration 做成 Team 通用结构，但第一版只给 challenge_cup_research 模板启用。
- 普通功能 Agent 可以提出 transfer_request；Research Coordination Agent 作为 ownerAgent 统一裁决并写入状态。
- TeamWorkflowOrchestration 只保存候选对象引用，不直接保存大段资料正文或正式知识。

推荐结构：

```json
{
  "workflowId": "challenge-cup-research-v1",
  "teamId": "research-team",
  "workflowKind": "challenge_cup_research",
  "status": "active",
  "ownerAgentId": "research-coordination-agent",
  "stateMachine": {
    "states": [],
    "transitions": [],
    "gates": []
  },
  "routingPolicy": {
    "defaultMode": "directed_inbox",
    "chatRoomPurpose": "research_coordination",
    "coordinationAgentId": "research-coordination-agent"
  },
  "transferPolicy": {
    "requiresUserConfirmation": false,
    "finalStateWriter": "Research Coordination Agent",
    "records": []
  },
  "activeWorkflowItems": []
}
```

TeamWorkflowOrchestration 核心字段：

| 字段 | 作用 | 边界 |
|---|---|---|
| workflowId | 标识一个团队编排流程 | 可被多个候选对象引用 |
| workflowKind | 模板类型，如 challenge_cup_research | 用于复用到其他团队流程 |
| ownerAgentId | 最终状态写入者 | 第一版固定 Research Coordination Agent |
| stateMachine.states | 可用状态列表 | 不保存资料正文 |
| stateMachine.transitions | 允许跳转表 | 必须带 gate / reasonCode |
| stateMachine.gates | 通过/退回门禁 | 与 Evidence Review / Ingestion Gate 对齐 |
| routingPolicy | Agent 路由和沟通方式 | 对接 Research Organization / Agent Bus / ChatRoom |
| transferPolicy | 自动转移规则 | 不需要用户确认 |
| activeWorkflowItems | 当前活跃候选引用 | 只保存 candidateId / artifactRef / currentState |

与现有 Vibelution 能力对齐：

- Team registry：增加 workflowOrchestration 引用或配置块。
- Team canvas：继续展示成员、职责和 communication / reports_to 边，不承载候选资料正文。
- linkedChatRoom：继续承载 research_coordination 群聊轮次。
- Research Organization：继续管理组织通信边、权限和能力缺口升级。
- Agent Bus / Inbox：承接 transfer_request、status_report、risk_record 等定向消息。
- Team Knowledge：只接收审核后的 SourceArtifact / RefinementProposal / KnowledgeItem。
- CandidateStore：作为 TeamWorkflowOrchestration 操作的数据对象存储层。

## 6. 功能 Agent 与工具接线

Agent 创建策略：

- 第一版不直接新增真实 Agent。
- 本地 `bossAGI-standard / qwen3.5-9b` 不作为人格 Agent，而作为 Local Research Worker Model，被不同节点用不同任务模板调用。
- Source Intake Agent、Paper Note Extraction Agent 可先复用 prompt-research-broad。
- Neuro Mechanism Extraction Agent、Mechanism Mapping Agent、Algorithm Hypothesis Agent 可先复用 prompt-research-deep / prompt-research-card。
- Evidence Review Agent 复用 prompt-research-review。
- 如确需新增功能 Agent，走 research_agent_creation_proposal_tool -> 用户确认 -> research_proposal_apply_tool，不直接创建。

### Local Research Worker Model：bossAGI-standard / qwen3.5-9b / 32k

定位：

- 作为本地高吞吐候选生成模型。
- 负责资料初筛、paper_note 草稿、neuro_mechanism 候选、机制到计算抽象、algorithm_hypothesis 草稿和 review prefilter。
- 不作为最终科研裁决模型。
- 不直接写正式 Team Knowledge、正式 RAG 或正式知识图谱。
- 不替代 Evidence Review Agent、Knowledge Steward Agent 或 Ingestion Approval Gate。
- Vibelution 模型库 ID：`houmo_qwen35_9b_agent`。
- 服务地址：`http://192.168.20.30:8081/v1`。
- 模型文件：`HiModel_xh2_qwen3.5_9b_256_256k_b1_1chip_2cores_v1.3.0_20260429.gguf`。
- 已验证：`GET /v1/models`、`POST /v1/chat/completions`、Vibelution `LLMClient` probe。
- 注意：该后端会大量返回 `reasoning_content`，短输出预算可能导致 `content` 为空；科研任务应预留足够输出 tokens，并以最终 JSON 校验为准，必要时容错检查 reasoning 草稿。
- 图像能力：不支持图像输入，PDF/图片资料必须先由 source_parser 转成文本片段和页码锚点。

32k 上下文预算：

| 部分 | 建议比例 | 说明 |
|---|---:|---|
| 系统指令 / 输出 schema | 10%-15% | 固定 JSON 字段、禁止事项、证据规则 |
| 当前任务说明 | 5%-10% | 节点目标、输入类型、状态和验收条件 |
| 论文片段 / evidence | 55%-65% | 建议控制在 18k-22k tokens，保留页码、章节和 sourceRef |
| 已有候选上下文 | 10%-15% | paper_note、mechanism、hypothesis 等上游候选摘要 |
| 输出预留 | 10%-15% | 避免塞满上下文导致 JSON 漂移或注意力下降 |

任务分配：

| 节点 | 使用方式 |
|---|---|
| 01 资料进入工作区 | 标题、摘要、片段初筛，输出 relevanceScore、topicTags、excludeReason |
| 02 生成 paper_note | 按章节或 chunk 生成 paper_note 草稿，保留 keyFindings、methods、limitations、uncertainty |
| 03 提取 neuro_mechanism | 从 paper_note 和关键片段抽取机制候选，标记 evidenceRefs、confidence、riskFlags |
| 04 机制到计算抽象 | 生成多种计算抽象映射，强制区分 factLayer、inferenceLayer、overAnalogyRisk |
| 05 生成 algorithm_hypothesis | 生成算法假设草稿，补 baseline、expectedBenefit、expectedComputeCost、experimentPlan |
| 06 科研审稿 | 只做 review prefilter，给 riskFlags 和 requiredChanges，不做最终审稿裁决 |
| 07 知识治理入库 | 只生成 proposal/ingestion pack 草稿，正式建议仍由 Knowledge Steward Agent 检查 |

输出契约：

```json
{
  "candidateType": "",
  "sourceRefs": [],
  "evidenceRefs": [],
  "claims": [],
  "uncertainty": [],
  "riskFlags": [],
  "confidence": 0.0,
  "nextAction": "",
  "requiresReview": true
}
```

硬边界：

- 没有 `sourceRef`、页码或 citation 的结论必须标记 `weak_evidence`。
- 神经术语不确定时必须标记 `terminology_uncertain`。
- 机制到算法的类比必须拆成 `factLayer` 和 `inferenceLayer`。
- 自然语言解释只能放在 `comments` 或 `notes` 字段，不允许破坏 JSON 输出。
- 本地 9B 研究模型输出必须进入 CandidateStore 或 review prefilter，不得绕过 TeamWorkflowOrchestration 写最终状态。

### Source Intake Agent

职责：

- 建立 source_manifest。
- 校验文件路径、hash、页码范围、来源可信度。
- 可调用 research_knowledge_query_tool 做查重。

待接入能力：

- 长 PDF 分批、章节识别和非 PDF 资料解析。
- 本地 9B 研究模型负责标题、摘要和片段初筛，输出 relevanceScore、topicTags 和 excludeReason。

### Paper Note Extraction Agent

职责：

- 从 PDF/论文片段生成 paper_note。
- 抽取 summary、keyFindings、methods、limitations。
- 每条 finding 绑定 citation/page anchor。

待接入能力：

- 长文 chunk 合并。
- 本地 9B 研究模型负责按章节或 chunk 生成 paper_note 草稿，32k 内优先保留 18k-22k 原文证据和输出预留。

### Neuro Mechanism Extraction Agent

职责：

- 从 paper_note 抽取神经机制候选。
- 区分实验现象、作者解释、项目理解。
- 打 confidence 和 riskFlags。

可用工具：

- research_knowledge_query_tool
- knowledge_rag_retrieve_tool

本地模型用法：

- 本地 9B 研究模型负责抽取 neuro_mechanism 候选。
- 弱证据必须写入 `weak_evidence`。
- 术语不确定必须写入 `terminology_uncertain`。

### Mechanism Mapping Agent

职责：

- 把神经机制映射到计算抽象。
- 标记 factLayer、inferenceLayer 和 overAnalogyRisk。

本地模型用法：

- 本地 9B 研究模型负责生成多方案映射。
- 每个映射必须拆分论文事实、项目推断和过度类比风险。

### Algorithm Hypothesis Agent

职责：

- 生成可验证算法假设。
- 强制提供 baseline、expectedBenefit、expectedComputeCost、experimentPlan。

本地模型用法：

- 本地 9B 研究模型负责生成 algorithm_hypothesis 草稿。
- 缺 baseline 或 experimentPlan 时不能进入 review_ready。

### Evidence Review Agent

职责：

- 审查证据链、类比风险、可测性和计算成本。
- 产出 review_record。
- 决策 approve_for_steward、needs_revision 或 reject。

本地模型用法：

- 本地 9B 研究模型只做 review prefilter。
- 可输出 riskFlags、requiredChanges 和 needsDecision。
- 不写最终 review.decision。

### Knowledge Steward Agent

职责：

- 使用现有 agent-knowledge-steward。
- 只生成 proposal、rating suggestion 和 ingestion pack。
- 不直接写正式知识库。

本地模型用法：

- 本地 9B 研究模型只能生成 proposal/ingestion pack 草稿。
- 正式建议仍由 Knowledge Steward Agent 检查。

可用工具：

- knowledge_governance_tasks_tool
- knowledge_steward_workbench_tool
- knowledge_steward_recommendations_tool
- knowledge_proposal_tool
- knowledge_ingestion_tool
- knowledge_rating_suggestion_tool

### Ingestion Approval Gate

职责：

- 作为正式入库硬门。
- 将 approved_to_ingest 的 ingestion pack 同步到 Team Knowledge、RAG、正式知识图谱。

## 7. 记忆平台同步

候选阶段：

- 只写 knowledge_candidates。
- 不写 Team Knowledge。
- 不进入正式 RAG。

治理阶段：

- Knowledge Steward Agent 把 ready_for_steward 候选转为可审核 SourceArtifact、RefinementProposal、rating suggestion 或 ingestion pack。
- ingestion pack 记录 sourceTrace、riskSummary、targetDomain。
- 优先调用现有 knowledge_proposal_tool、knowledge_ingestion_tool、knowledge_rating_suggestion_tool，不新增挑战杯专用入库工具。

正式阶段：

- Ingestion Approval Gate 通过后创建或更新 KnowledgeItem。
- 生成 Trace，保留 sourceFiles、paper_note、review_record、ingestion_pack 链路。
- RAG 只索引 official_synced 内容。

## 8. 图谱同步

候选图谱：

- 当前后端/API 已从 CandidateStore candidates 生成 `candidate_graph` 候选快照，存入 CandidateStore，不写正式图谱。
- 图谱 payload 包含 `nodes`、`edges`、`missingLinks`、`unreviewedNodes`、`officialBoundary` 和 summary。
- 当前链接字段优先使用候选输出中的 `paperNoteIds`、`neuroMechanismIds`、`mechanismMappingIds`、`candidateIds`，避免把外部 sourceRef 误判成候选断链。
- 断链时 `candidate_graph.qualityStatus=broken_links`，未断链时为 `preview_ready`。
- 独立 `candidate_graph.json` 导出和前端图谱读取仍待接。

正式图谱：

- approved_to_ingest 后进入正式图谱。
- 复用 /api/memory/knowledge-graph 展示正式 KnowledgeItem 结构。
- official_sync_record 记录 graphStatus。

## 9. API 与服务建议

已落地第一段 Team workflow API，用于 Team 编排、候选资料登记和流程转移裁决。挑战杯专用 Web 页面仍暂缓新增，先复用 Team workflow API、本地脚本、现有 knowledge 工具和 Teams 工作台的科研流程只读面板。

复用优先的服务边界：

- team_workflow_orchestration_service：已新增，读写 Team 级 workflow_orchestration、CandidateStore 和 transfer_records。
- team_workflows API：已新增 `/api/teams/{team_id}/workflow-orchestration` 及 candidates/source、candidates/{candidate_id}/source-extraction、candidates/{candidate_id}/paper-note-draft、transfers、decide。
- Teams 工作台科研流程面板：已新增只读入口，选择 `research-team` 或科研组织团队后读取 workflow detail 与最近候选列表，展示当前阶段、候选数、activeWorkflowItems、validationSummary 和候选状态；非科研团队不触发 workflow 初始化。
- local_research_worker_model：已落地任务包构建、32k 上下文预算、统一 `LLMClient` invoke、JSON 输出提取/校验和 CandidateStore 草稿记录；解析失败不入库。
- candidate_store：已落地 Team 级 index、候选列表查询、按类型/状态过滤和 validationSummary，并接入 source_manifest、paper_note、neuro_mechanism、mechanism_mapping、algorithm_hypothesis、candidate_graph 最小校验。
- source_parser：已新增 Team Workflow 后端/API 能力，支持本地 PDF `source_manifest` 的 `sha256`、`pageAnchors`、`excerpt` 抽取；缺文件、非 PDF、解析器不可用或抽取无文本时写 failed extraction 并停在 `source_needs_confirmation`。
- candidate_validator：已落地 source_manifest/PDF 字段校验、sourceExtraction 失败校验、paper_note citation anchor 校验、neuro_mechanism 证据/术语风险校验、mechanism_mapping 类比风险校验、algorithm_hypothesis experimentPlan 校验、review_prefilter 最终 decision 禁止、steward_pack_draft 审批门禁、candidate_graph officialBoundary/断链状态校验和 CandidateStore 校验报告。
- candidate_graph_builder：已落地后端/API，生成 CandidateStore 内的 candidate_graph 候选快照、断链报告、未审节点清单和 candidate_only officialBoundary；前端图谱读取仍待接。
- research_agent_binding：复用 research_service、research flow canvas、prompt-research-* 和 research 组织治理工具。
- memory_ingestion_bridge：已复用现有 Team Knowledge `create_ingestion_package`、`review_refinement_proposal`、rating suggestion review/create 与 KnowledgeItem metadata patch，把 `steward_pack_draft` 映射到 pending proposal，并由 Ingestion Approval Gate 审批为正式 `KnowledgeItem`、承接待审评分建议、写入 officialResearchGraph 或退回修订。

已落地 API：

- GET `/api/teams/{team_id}/workflow-orchestration`
- PUT `/api/teams/{team_id}/workflow-orchestration`
- POST `/api/teams/{team_id}/workflow-orchestration/candidates/source`
- POST `/api/teams/{team_id}/workflow-orchestration/candidates/{candidate_id}/source-extraction`
- POST `/api/teams/{team_id}/workflow-orchestration/candidates/{candidate_id}/paper-note-draft`
- GET `/api/teams/{team_id}/workflow-orchestration/candidates`
- GET `/api/teams/{team_id}/workflow-orchestration/candidates/validation`
- POST `/api/teams/{team_id}/workflow-orchestration/transfers`
- POST `/api/teams/{team_id}/workflow-orchestration/transfers/{transfer_id}/decide`
- POST `/api/teams/{team_id}/workflow-orchestration/local-research-model/tasks`
- POST `/api/teams/{team_id}/workflow-orchestration/local-research-model/outputs`
- POST `/api/teams/{team_id}/workflow-orchestration/local-research-model/invoke`
- POST `/api/teams/{team_id}/workflow-orchestration/steward-packs/{candidate_id}/knowledge-ingestion`
- POST `/api/teams/{team_id}/workflow-orchestration/steward-packs/{candidate_id}/knowledge-ingestion/review`

已落地前端读取面：

- `/teams?team=research-team` 右侧 inspector 的“科研流程”面板。
- 读取 `/api/teams/{team_id}/workflow-orchestration`。
- 读取 `/api/teams/{team_id}/workflow-orchestration/candidates?limit=8`。
- 只读展示，不提交 transfer、不审批 steward pack、不写正式 Team Knowledge/RAG/知识图谱。

暂缓新增挑战杯专用 API。未来若进入 Web 工作台，再考虑：

- GET /api/challenge-cup/candidates
- GET /api/challenge-cup/candidates/{id}
- POST /api/challenge-cup/sources/register
- POST /api/challenge-cup/paper-notes/generate
- POST /api/challenge-cup/mechanisms/extract
- POST /api/challenge-cup/hypotheses/generate
- POST /api/challenge-cup/reviews/run
- POST /api/challenge-cup/steward/prepare-ingestion
- POST /api/challenge-cup/graph/build
- POST /api/challenge-cup/official-sync/apply

## 10. 实施里程碑

### M1：候选数据基座

交付：

- source_manifest 候选。
- candidate_store/index.json。
- sourceExtraction.pageAnchors / excerpt。
- 本地 schema 校验。
- 候选断链检测。

验收：

- 能登记一个 PDF。
- 能生成一个 source_registered 记录。
- 能对本地 PDF 计算 sha256 并生成页码锚点。
- 缺路径、缺 hash、缺 allowedForAnalysis 时校验失败。

### M2：paper_note 与 PDF 锚点

交付：

- paper_note 输出契约与 CandidateStore 校验已落地：`keyFindings`、`methods`、`limitations`、`citations` 为本地模型输出必填。
- 每条 `keyFinding` 必须回指 `sourceRef`，并提供 `page` / `citation` / `evidenceRef` 锚点。
- 缺 citation/page anchor 的 paper_note 会进入 `paper_note_needs_revision`。
- 本地 PDF 页码摘录已可由 `source-extraction` 提供，并已通过 `/paper-note-draft` 自动组装成本地模型调用输入。
- `paper_note` 候选写入后会在 source candidate 的 `metadata.paperNoteDrafts` 中留下 trace，便于后续候选图谱和治理入库追踪。

验收：

- 已覆盖：每条 keyFinding 能回指 sourceRef/page/citation anchor。
- 已覆盖：缺 citation 的 finding 不能进入 mechanism_candidate，只能停在 `paper_note_needs_revision`。
- 已覆盖：从本地 PDF `sourceExtraction.excerpt/pageAnchors` 自动生成 paper_note，并回写 source candidate trace。
- 待覆盖：长文 chunk、多草稿合并和真实 Qwen 模型质量评估。

### M3：机制与算法假设

交付：

- neuro_mechanism 最小输出契约和 CandidateStore 校验已落地：必须含 `paperNoteIds`、`description`、`brainSystems`、`cognitiveFunctions`、`experimentalPhenomena`、`authorInterpretation`、`projectInterpretation`、`evidenceRefs`、`confidence` 和 `riskFlags`。
- 合格机制进入 `mechanism_candidate`。
- 缺机制证据或术语不确定但未标记 `terminology_uncertain` 时进入 `mechanism_needs_revision`。
- mechanism_mapping 最小字段/schema 和类比风险门禁已接入 CandidateStore。
- algorithm_hypothesis 最小字段/schema 和可测性门禁已接入 CandidateStore：必须含 `mechanismMappingIds` 或 `neuroMechanismIds`、`hypothesis`、`baseline`、`expectedBenefit`、`expectedComputeCost`，且 `experimentPlan` 必须含 `dataset`、`metric`、`baseline`、`smokePlan`。
- prompt-research-deep / prompt-research-card 自动生成链路仍待接。

验收：

- 已覆盖：能登记一个带证据链、解释分层和风险标记的 neuro_mechanism 候选。
- 已覆盖：神经术语不确定但未标记 `terminology_uncertain` 时不能进入 `mechanism_candidate`。
- 已覆盖：能登记一个带 `neuroMechanismIds`、计算抽象、fact/inference 分层和工程含义的 `mechanism_mapping` 候选。
- 已覆盖：高类比风险未标记 `over_analogy_risk` 时不能进入 `mechanism_mapping_candidate`。
- 已覆盖：能登记一个带上游 mechanism 引用、baseline、预期收益、计算成本和完整 experimentPlan 的 `algorithm_hypothesis` 候选。
- 已覆盖：algorithm_hypothesis 缺完整 `experimentPlan` 时进入 `hypothesis_needs_revision`，不能进入科研审稿/知识治理。

### M4：证据复核与候选图谱

交付：

- candidate_graph builder 后端/API：`POST /api/teams/{team_id}/workflow-orchestration/candidate-graph`。
- CandidateStore 内新增 `candidate_graph` 候选快照，包含 `nodes`、`edges`、`missingLinks`、`unreviewedNodes`、`officialBoundary`。
- 断链报告和未审节点清单。
- `candidate_graph` officialBoundary 明确不写正式 Team Knowledge/RAG/Graph。
- review_prefilter 后端门禁：本地模型可生成 `review_record` 候选，必须含 `candidateIds`、`checklist`、`comments`、`requiredChanges`、`needsDecision`，且不能写最终 `decision`。

验收：

- 已覆盖：完整 paper_note -> neuro_mechanism -> mechanism_mapping -> algorithm_hypothesis 候选链可生成 `candidate_graph_visible`，且 `officialBoundary.writesOfficialGraph=false`。
- 已覆盖：候选链接指向不存在对象时生成 `missingLinks`，`candidate_graph.qualityStatus=broken_links`。
- 已覆盖：合格 review prefilter 进入 `review_prefiltered`。
- 已覆盖：review prefilter 输出最终 `decision` 时进入 `review_needs_revision`。
- 待覆盖：reject 进入 rejection_archive。
- 待覆盖：needs_revision 回到对应上游节点。

### M5：知识治理与正式同步

交付：

- steward_ingestion_pack / steward_pack_draft schema 已接入 TeamWorkflowOrchestration 的本地模型输出契约。
- CandidateStore 已能记录合格 `steward_pack_draft` 草稿包。
- 草稿包门禁已强制 `approvalRequired=true`，并禁止 `officialSync`、`applyNow=true`、`writeOfficialGraph=true`。
- 待审入库桥已复用 Team Knowledge：有效 `steward_pack_draft` 可提交为 `SourceArtifact` + pending `RefinementProposal`，并可选生成 pending `ratingSuggestion`。
- 提交后候选进入 `steward_pending_knowledge_review`，并记录 `metadata.knowledgeIngestion`。
- Ingestion Approval Gate 已接入：`approved` 复用 Team Knowledge review/apply 创建正式 `KnowledgeItem`，并把 proposal 级 pending `ratingSuggestion` 迁移为 KnowledgeItem 级 pending rating review，同时把正式科研边写入 `KnowledgeItem.metadata.officialResearchGraph`；`rejected` 退回 `steward_needs_revision`。
- `official_sync_record` 已以 `metadata.officialSyncRecord` 形式记录正式同步证据、`ratingSuggestionMigration` 和 `officialResearchGraph`；RAG 通过正式 KnowledgeItem 的现有读取面可检索，Memory Graph 通过 `include=officialResearchGraph` 显式展开正式科研 trace。

验收：

- 已覆盖：合格 steward pack 草稿进入 `steward_pack_draft`，且只写 CandidateStore。
- 已覆盖：`approvalRequired` 非 true 时进入 `steward_needs_revision`。
- 已覆盖：包含 `officialSync`、`applyNow=true` 或 `writeOfficialGraph=true` 等立即正式写入意图时进入 `steward_needs_revision`。
- 已覆盖：Knowledge Steward Agent 可将草稿包映射为 Team Knowledge 待审 SourceArtifact / pending RefinementProposal / pending ratingSuggestion。
- 已覆盖：未通过授权审批门禁不能创建正式 KnowledgeItem、RAG 或正式图谱。
- 已覆盖：Ingestion Approval Gate 批准后创建正式 `KnowledgeItem`，候选进入 `official_synced`，并记录 `officialSyncRecord`。
- 已覆盖：Ingestion Approval Gate 拒绝后不创建正式 `KnowledgeItem`，候选进入 `steward_needs_revision`。
- 已覆盖：pending proposal 级 `ratingSuggestion` 在批准后关闭为 `applied`，并迁移为正式 `KnowledgeItem` 的 pending rating review，不自动应用评分。
- 已覆盖：正式 `supports` / `maps_to` / `inspires` / `approved_for_ingestion` 图谱边以 `officialResearchGraph` 写入正式 `KnowledgeItem.metadata` 和 `officialSyncRecord`。
- 已覆盖：Memory Graph 画布请求 `include=officialResearchGraph` 后显式展开 `officialResearchGraph` 的正式科研引用节点和 `official_*` 边。

## 11. 测试计划

单元测试：

- schema 校验。
- 状态机流转。
- candidate_graph 断链检测。
- source_manifest 路径/hash 校验。

集成测试：

- source -> paper_note -> mechanism -> hypothesis -> review。
- ready_for_steward -> steward_ingestion_pack。
- approved_to_ingest -> official_sync_record。

人工验收：

- 打开 research_team_flow_design.html。
- 检查 01-09 节点页与技术方案一致。
- 检查候选图谱与正式图谱边界。

## 12. 日志与审计

每个关键状态变化都应记录：

- candidateId
- previousStatus
- nextStatus
- trigger
- agentRole
- validationResult
- sourceRefs
- errorCode

不记录：

- 完整论文正文。
- 大段 prompt。
- secret 或凭证。
- 未脱敏用户隐私。

## 13. 优先级建议

最短可跑通路径：

1. 先实现 M1 + M2，确保资料和 paper_note 可追溯。
2. 再实现 M3，形成算法假设候选。
3. 再实现 M4，确保候选不会污染正式记忆。
4. 最后接 M5，进入记忆平台和正式图谱。

当前最关键技术缺口是候选数据基座和 schema 校验；没有这个基座，Agent 输出会很快变成不可维护的自由文本。

## 14. 复用优先实施边界

本方案当前不建议优先改动：

- core/web/routes 新增 challenge-cup 专用路由。
- web/src 新增挑战杯专用页面。
- Team Knowledge 数据模型。
- agent-knowledge-steward 的核心治理边界。
- knowledge_rag_retrieve_tool、knowledge_proposal_tool、knowledge_ingestion_tool 的正式契约。

优先新增或调整：

- 挑战杯目录下的候选数据文件。
- 挑战杯本地脚本：登记、校验、图谱生成、摄取包映射。
- research_service 的功能 Agent 绑定配置，必要时通过 proposal 工具创建。
- 流程 HTML 与技术方案文档。

这样可以先跑通科研资料到候选知识再到正式入库的链路，同时最大限度复用现有 Vibelution 能力，降低维护成本。

## 15. 团队沟通与组织设计

### 15.1 当前可复用能力

Vibelution 已经具备团队沟通基础能力，不需要为挑战杯从零实现群聊系统。

可复用能力：

- Team registry：支持创建团队、成员、角色、团队画布和 linkedChatRoom。
- Team canvas：支持 role、agent、group、user、external 节点，以及 reports_to、communication、collaborates_with、delegates_to、observes、supports 边。
- ChatRoom：支持多 Agent 群聊、round_robin / opportunistic 调度、research_coordination purpose、SSE 事件流、停止/重置轮次。
- Research Organization：已有受保护核心组织岗位、通信边、收件箱、wake policy、proposal/apply 审批链。
- Research organization tools：支持 research_agent_creation_proposal_tool、research_communication_edge_proposal_tool、research_proposal_apply_tool。
- Team Knowledge：支持从团队群聊 sourceRef 进入 SourceArtifact / RefinementProposal 的正式知识治理链路。

### 15.2 挑战杯团队结构

挑战杯科研团队应分为 3 类功能岗位：

组织协调层：

- Research Coordination Agent：负责会议议题、任务拆分、跨节点排期、状态汇总和风险升级。
- Research Organization Agent：负责团队结构、成员职责、沟通边、汇报关系和新增 Agent 提案。
- Capability Governance Agent：负责工具权限、记忆权限、prompt/template 适配和能力缺口审查。

科研执行层：

- Source Intake Agent
- Paper Note Extraction Agent
- Neuro Mechanism Extraction Agent
- Mechanism Mapping Agent
- Algorithm Hypothesis Agent
- Evidence Review Agent
- Candidate Graph Preview Agent

知识治理层：

- Knowledge Steward Agent / agent-knowledge-steward
- Ingestion Approval Gate
- Knowledge Platform

### 15.3 推荐沟通拓扑

推荐用 Research Organization 管控通信边，用 Team linkedChatRoom 承接群聊讨论。

汇报边：

- Research Coordination Agent reports_to Research Organization Agent。
- 科研执行层 reports_to Research Coordination Agent。
- Knowledge Steward Agent reports_to Capability Governance Agent。
- Ingestion Approval Gate 作为正式审批门禁，不参与普通任务派发。

通信边：

- Research Coordination Agent -> 所有执行 Agent：task_assignment、evidence_request、validation_plan。
- 执行 Agent -> Research Coordination Agent：status_report、risk_escalation、final_report。
- Evidence Review Agent <-> Knowledge Steward Agent：knowledge_update、permission_review、decision_request。
- Research Organization Agent <-> Capability Governance Agent：organization_design、capability_policy、tool_policy、memory_policy。

群聊用途：

- Team linkedChatRoom purpose 使用 research_coordination。
- 默认 mode 使用 round_robin。
- 需要优先协调时可使用 opportunistic，并通过 priorityAgentIds 把 Research Coordination Agent 放在首位。

### 15.4 入库到团队共享记忆

团队沟通内容可以进入共享记忆，但不能直接成为正式知识。

推荐链路：

```text
Team linkedChatRoom round
  -> team_chat_refinement SourceArtifact
  -> RefinementProposal
  -> Knowledge Steward Agent 审查
  -> Ingestion Approval Gate 审批
  -> Team Knowledge / RAG / 正式知识图谱
```

适合进入共享记忆的内容：

- 最终研究结论。
- 证据复核结果。
- 算法假设版本。
- 决策记录。
- 风险和拒绝原因。
- 实验计划或实验结果摘要。

不应直接入库的内容：

- 普通寒暄。
- 重复状态确认。
- 未审查的搜索片段。
- 未脱敏的大段原文。
- 未经过 Evidence Review Agent 的算法灵感。

### 15.5 最小实施建议

第一版不新增对话系统，只做配置和映射：

1. 使用现有 `research-team / 科研团队` 作为挑战杯科研流程团队，不新增平行团队。
2. 保持 Research Organization 对该团队的成员、功能岗位和通信边同步。
3. 使用 Team 已关联的 linkedChatRoom `room-20260529-090009-757107-6a747d62` 承载团队群聊。
4. 群聊 round 使用 `research_coordination` purpose。
5. Research Coordination Agent 负责发起轮次、收敛结论和生成任务摘要。
6. 需要新增功能 Agent 或通信边时，走 proposal -> 用户确认 -> apply。
7. 会议结论通过 Team Knowledge 现有 SourceArtifact / RefinementProposal / review 链路进入团队共享记忆。

### 15.6 高效沟通协议

目标不是让所有 Agent 更频繁地发言，而是让信息按职责、证据和决策状态流动。

推荐沟通原则：

- 默认异步，少开全员轮次：普通状态、证据请求、缺口追问优先走定向通信边和收件箱。
- 协调先行，执行后发言：Research Coordination Agent 先发布议题包、输入范围、预期产物和截止条件，避免执行 Agent 在上下文不齐时重复讨论。
- 小范围闭环，必要时升级：能在执行层解决的问题不进入组织层；涉及工具权限、记忆权限、Agent 新增或通信边变更时再升级到 Research Organization Agent / Capability Governance Agent。
- 结论结构化，过程轻量化：群聊正文只保留必要讨论；可复用结论必须沉淀为 decision_record、review_record、algorithm_hypothesis 或 ingestion package。
- 候选和正式分层：团队讨论可以生成候选记忆，但正式 Team Knowledge/RAG/图谱仍必须经过 Evidence Review Agent、Knowledge Steward Agent 和 Ingestion Approval Gate。

推荐轮次类型：

| 类型 | 触发 | 参与者 | ChatRoom 模式 | 产物 |
|---|---|---|---|---|
| agenda_brief | 新阶段、新资料批次、新实验方向 | Research Coordination Agent + 必要执行 Agent | opportunistic，协调 Agent 优先 | agenda_packet、task_assignment |
| status_sync | 阶段内例行同步 | 当前活跃执行 Agent | round_robin | status_digest、blocker_list |
| evidence_closure | 证据冲突、引用不足、结论待复核 | Evidence Review Agent + 相关执行 Agent | round_robin | review_record、decision_request |
| decision_gate | 准备入库或同步正式图谱 | Knowledge Steward Agent + Evidence Review Agent + Ingestion Approval Gate | opportunistic，门禁相关 Agent 优先 | ingestion_decision、official_sync_record |
| risk_escalation | 权限、数据可信度、工具缺口、流程阻塞 | Research Coordination Agent + Organization/Governance Agent | opportunistic | risk_record、proposal 或 rollback_request |

消息契约：

- task_assignment：必须包含 goal、inputRefs、expectedArtifact、acceptance、ownerAgent、deadline、dependency。
- status_report：必须包含 currentState、progress、blockers、nextAction、evidenceRefs、needsDecision。
- evidence_request：必须包含 claimId、sourceRef、question、urgency、requiredBy。
- decision_record：必须包含 decision、optionsRejected、reason、impact、followUp、knowledgeCandidateRefs。
- risk_record：必须包含 riskType、severity、affectedNode、evidence、proposedMitigation、escalationTarget。

降噪规则：

- 一个任务线程只允许一个 ownerAgent 汇总，其他 Agent 回复给 ownerAgent，不并行向全员广播。
- 每轮 ChatRoom 结束必须由 Research Coordination Agent 生成 status_digest 或 decision_record，否则该轮不能进入记忆候选。
- 重复问题先查 Team Knowledge/RAG、candidate_graph 和上一轮 status_digest，再发起 evidence_request。
- 大段原文、未脱敏资料、未经复核的灵感不进入群聊摘要，只保留 sourceRef、pageAnchor 和简短理由。
- 超过一轮仍无法解决的 blocker 必须转成 risk_record，不继续在普通群聊里循环讨论。

效率指标：

- decision_round_count：一个节点从提出问题到形成 decision_record 的群聊轮次数。
- unresolved_blocker_age：阻塞项停留在 blocker_list 的时长。
- duplicate_question_count：同一 claim/sourceRef 被重复追问的次数。
- chat_to_memory_conversion_rate：群聊轮次中成功转成 SourceArtifact / RefinementProposal 的比例。
- rejected_due_to_evidence_gap：因证据不足被 Knowledge Steward 或审批门禁退回的数量。
