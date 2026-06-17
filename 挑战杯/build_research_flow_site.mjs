import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.dirname(fileURLToPath(import.meta.url));
const pagesDir = path.join(rootDir, "research_flow_pages");
const indexPath = path.join(rootDir, "research_team_flow_design.html");

const nodes = [
  {
    id: "01",
    slug: "source-workspace",
    title: "资料进入工作区",
    status: "第一轮资料搜集已跑通",
    statusKind: "active",
    role: "Source Intake Agent",
    summary: "建立稳定证据源，并把本地 PDF 转成可引用的页码锚点。",
    objective: "把用户提供的论文、PDF、赛题文件和补充资料登记为可追溯输入。",
    inputs: ["用户提供的论文/PDF", "赛题 PDF", "补充资料", "挑战杯工作区路径"],
    actions: [
      "登记文件路径、资料类型、页码范围和来源可信度。",
      "对本地 PDF source_manifest 运行 source-extraction，计算 sha256 并生成 pageAnchors 与 excerpt。",
      "区分允许分析、暂不分析、需要用户确认的资料。",
      "执行 source collection 搜索时写入 source_collection_run work-run 快照，让顶部全局运行状态栏显示知识搜集正在运行。",
      "保留原始文件，不在资料入口阶段改写内容。",
    ],
    outputs: ["资料清单", "sourceFiles 引用", "sourceExtraction.pageAnchors", "source_collection_run 运行快照", "Paper 原始来源节点"],
    memory: "不进入正式记忆库；只作为后续 paper_note 的 sourceFiles。",
    graph: "可作为候选图谱的 Paper source 节点，不进入正式知识图谱。",
    risks: ["资料来源不明", "PDF 抽取失败", "联网搜索结果混入第一版"],
    openQuestions: ["章节识别仍待补；当前先按 pageAnchors 生成 paper_note 分块计划。"],
  },
  {
    id: "02",
    slug: "paper-note",
    title: "生成 paper_note",
    status: "自动草稿桥与分块计划已接入",
    statusKind: "active",
    role: "Paper Note Extraction Agent",
    summary: "把资料转成可审查的论文/资料笔记候选。",
    objective: "从资料中提取背景、方法、关键发现、局限和引用位置。",
    inputs: ["资料清单", "sourceExtraction.pageAnchors", "PDF 页码", "论文片段", "补充备注"],
    actions: [
      "从 sourceExtraction.excerpt/pageAnchors 组装 sourceRefs、evidenceRefs 和 excerpt。",
      "对长 PDF / 长论文先生成 paperNoteChunkPlan，把 pageAnchors 切成可追踪 chunk seeds。",
      "调用 Local Research Worker Model 生成 summary、keyFindings、methods、limitations。",
      "通过 CandidateStore 校验 citation/page anchor，合格时进入 paper_note_draft。",
      "paper-note-draft 可带 chunkId 只处理目标 chunk，并回写 source candidate 的 paperNoteDrafts trace 与 chunk 进度。",
    ],
    outputs: ["paperNoteChunkPlan", "paper_note_YYYYMMDD_NNN.json", "候选状态 draft", "Paper -> PaperNote 关系"],
    memory: "仍属于候选知识，不进入正式 RAG。",
    graph: "进入候选图谱，可被 neuro_mechanism links 引用。",
    risks: ["摘要过度压缩", "缺页码", "把作者假设当成实验结论"],
    openQuestions: ["多个 chunk draft 的合并/去重策略仍待规划。"],
  },
  {
    id: "03",
    slug: "neuro-mechanism",
    title: "提取 neuro_mechanism",
    status: "已规划",
    statusKind: "done",
    role: "Neuro Mechanism Extraction Agent",
    summary: "把论文事实整理为神经机制候选，而不是直接跳到算法灵感。",
    objective: "形成带证据链的神经机制卡片。",
    inputs: ["paper_note", "支持 claim", "实验现象", "脑区/认知功能线索"],
    actions: [
      "提取 mechanism.description、brainSystems、cognitiveFunctions。",
      "把 experimentalPhenomena 和作者解释分开记录。",
      "为每个 mechanism evidence 绑定 paperNoteId 和 confidence。",
    ],
    outputs: ["neuro_mechanism_YYYYMMDD_NNN.json", "PaperNote supports NeuroMechanism"],
    memory: "候选机制必须经过证据复核 Agent 和知识治理 Agent 治理后才能入库。",
    graph: "候选图谱边：paper_note supports neuro_mechanism。",
    risks: ["弱证据泛化", "神经术语误读", "缺少不确定性说明"],
    openQuestions: ["是否需要外部神经科学专家复核机制名称。"],
  },
  {
    id: "04",
    slug: "mechanism-mapping",
    title: "机制到计算抽象",
    status: "首版候选映射已生成",
    statusKind: "active",
    role: "Mechanism Mapping Agent",
    summary: "把神经机制转为工程上能讨论的抽象层。",
    objective: "建立从神经科学机制到神经网络设计空间的可审查映射。",
    inputs: ["neuro_mechanism", "证据等级", "算法相关性说明"],
    actions: [
      "映射到注意力、记忆、反馈、预测误差、稀疏激活、动态路由等抽象。",
      "明确哪些是论文事实，哪些是本项目算法推断。",
      "为每个映射标记 over_analogy 风险。",
    ],
    outputs: ["mechanism_mapping_YYYYMMDD_NNN.json", "NeuroMechanism maps_to MechanismMapping"],
    memory: "只进入 CandidateStore 草稿区；正式 Team Knowledge/RAG/知识图谱仍等待后续证据复核和知识治理。",
    graph: "候选图谱可展示 NeuroMechanism maps_to MechanismMapping，正式图谱同步仍由审批门禁控制。",
    risks: ["过度类比", "抽象过宽", "不可转为实验计划"],
    openQuestions: ["后续是否补独立 mechanism_mapping.schema.json 文件。"],
  },
  {
    id: "05",
    slug: "algorithm-hypothesis",
    title: "生成 algorithm_hypothesis",
    status: "首版算法假设已生成",
    statusKind: "active",
    role: "Algorithm Hypothesis Agent",
    summary: "把机制启发收束为可验证算法假设。",
    objective: "生成包含 baseline、实验计划、风险和计算成本的算法候选。",
    inputs: ["mechanism_mapping ids", "neuro_mechanism ids", "computationalAbstraction", "机制证据链"],
    actions: [
      "定义 architectureChange、trainingObjective、optimizationOrInferenceProcess。",
      "填写 baseline、expectedBenefit、implementationHint 和 expectedComputeCost。",
      "强制保留 experimentPlan，即使第一版只填占位。",
    ],
    outputs: ["algorithm_hypothesis_YYYYMMDD_NNN.json", "NeuroMechanism inspires AlgorithmHypothesis"],
    memory: "只进入 CandidateStore 草稿区；缺完整 experimentPlan 的算法假设不得提交科研审稿或知识治理 Agent。",
    graph: "候选图谱边：mechanism_mapping inspires algorithm_hypothesis，占位保留 neuro_mechanism inspires algorithm_hypothesis。",
    risks: ["无实验计划", "预期收益不可测", "计算成本过高"],
    openQuestions: ["后续是否接真实训练 runner。"],
  },
  {
    id: "06",
    slug: "research-review",
    title: "科研审稿",
    status: "prefilter 与协调队列已落地",
    statusKind: "done",
    role: "Evidence Review Agent",
    summary: "在交给记忆平台前先做领域与工程风险过滤，并把返工/拒绝/待转移纳入团队协调队列和沟通建议。",
    objective: "先用 review_record 候选记录证据、类比、可测性和成本风险；返工走 transfer returned，拒绝进入 rejection_archive。",
    inputs: ["paper_note", "neuro_mechanism", "algorithm_hypothesis"],
    actions: [
      "填写 candidateIds、checklist、comments、requiredChanges、riskFlags、needsDecision。",
      "标记 weak_evidence、missing_citation、over_analogy、not_testable 等风险。",
      "禁止本地模型写最终 decision；高争议候选进入人工/门禁决策。",
      "Research Coordination Agent 可将 needs_revision 转移回最小上游节点，或将 rejected 候选归档到 rejection_archive。",
      "GET coordination/status 只读聚合 pendingTransfers、needsRework、blocked、stewardship 和 active 队列，并为每个队列项生成 communicationBrief。",
    ],
    outputs: ["review_record 候选", "review_prefiltered 状态", "review_needs_revision 状态", "transfer returned/rejected 记录", "rejection_archive", "coordination_status"],
    memory: "审稿记录仍是候选工作区内容；rejected 候选只保留归档证据，不进入正式记忆。",
    graph: "候选图谱可展示 reviewed_by、needs_revision 边；rejected 归档候选从可推进图谱中隔离，并在 summary 中计数。",
    risks: ["证据复核 Agent 只做形式审核", "缺少明确退回项", "风险标记不可复用"],
    openQuestions: ["是否需要为 Evidence Review Agent 增加专用 decision API，而不是继续复用通用 transfer decide。"],
  },
  {
    id: "07",
    slug: "steward-ingestion",
    title: "知识治理入库",
    status: "待知识治理审查",
    statusKind: "active",
    role: "Knowledge Steward Agent · agent-knowledge-steward",
    summary: "steward_pack_draft 可提交到 Team Knowledge 待审队列，且团队可读取知识入库状态漏斗。",
    objective: "把待治理候选整理为可审查的 SourceArtifact、pending RefinementProposal 和可选 pending ratingSuggestion。",
    inputs: ["review_record 候选", "algorithm_hypothesis 候选", "candidate_graph 快照", "目标知识域"],
    actions: [
      "校验 candidateIds、targetDomain、sourceTrace、riskSummary、proposalPayload、ratingSuggestion。",
      "强制 approvalRequired=true，禁止 officialSync、applyNow 或 writeOfficialGraph 等立即正式写入意图。",
      "合格草稿先进入 steward_pack_draft；提交待审队列后进入 steward_pending_knowledge_review。",
      "Ingestion Approval Gate 批准后进入 official_synced；拒绝后回到 steward_needs_revision。",
      "审批通过且创建正式 KnowledgeItem 后，将 proposal 级 pending ratingSuggestion 迁移为 KnowledgeItem 级 pending ratingSuggestion。",
      "审批通过后把 sourceTrace / candidateIds 转为 KnowledgeItem metadata.officialResearchGraph 中的 supports、maps_to、inspires、approved_for_ingestion 正式边。",
      "GET knowledge-ingestion/status 聚合 CandidateStore、校验报告、候选图摘要和 Team Knowledge stats，输出 stages、actionItems、officialBoundary。",
      "Teams 工作台同时读取 coordination/status，把待转移、待返工、待治理和阻塞候选集中显示，并展示目标功能 Agent 与建议通道；不提供自动调转或自动发送按钮。",
    ],
    outputs: ["steward_pack_draft 候选", "SourceArtifact", "pending RefinementProposal", "proposal ratingSuggestion", "KnowledgeItem ratingSuggestion", "officialResearchGraph", "official_sync_record", "knowledge_ingestion_status", "coordination_status_panel"],
    memory: "待审阶段不创建正式 KnowledgeItem；审批通过后复用 Team Knowledge review/apply 创建正式 KnowledgeItem；状态总览只读聚合 formalKnowledgeItemCount 和 pendingProposalCount。",
    graph: "审批通过后正式 KnowledgeItem metadata 记录 officialResearchGraph；状态总览明确 candidate_graph_preview_only 与 official_research_trace_synced 的边界。",
    risks: ["绕过审批门禁", "目标知识域错误", "把 ingestion pack 草稿误当正式入库记录"],
    openQuestions: ["是否把 knowledge-ingestion/status 接到 Teams 前端状态漏斗与告警徽标。"],
  },
  {
    id: "08",
    slug: "candidate-graph",
    title: "候选图谱预览",
    status: "Teams 可视化已接入",
    statusKind: "done",
    role: "Candidate Graph Preview Agent",
    summary: "让团队先看到研究链路，但不污染正式知识图谱。",
    objective: "可视化候选中的 Paper、Mechanism、Mapping、Hypothesis、Review 链路。",
    inputs: ["CandidateStore candidates", "paperNoteIds / neuroMechanismIds / mechanismMappingIds", "候选状态"],
    actions: [
      "读取 candidate_only、ready_for_candidate_graph、excluded 状态。",
      "展示 supports、maps_to、inspires、reviewed_by 等候选边。",
      "突出缺失链接和断裂证据链。",
      "Teams 工作台科研流程面板可读取 latest candidate_graph，并用 SVG 小图展示节点、边、断链和未审节点。",
      "刷新图谱按钮复用 POST candidate-graph，只生成 candidate_only 快照，不写正式 Team Knowledge、RAG 或正式图谱。",
    ],
    outputs: ["candidate_graph 候选快照", "Teams 候选图谱面板", "missingLinks 断链报告", "unreviewedNodes 未审节点清单"],
    memory: "候选图谱只进入 CandidateStore 草稿区，不进入正式 RAG。",
    graph: "只展示候选图谱；正式图谱同步必须等 ingested。",
    risks: ["候选图谱被误读为正式知识", "links 指向不存在对象"],
    openQuestions: ["是否仍需要导出独立 candidate_graph.json，或保持前端直接读取 CandidateStore graph payload。"],
  },
  {
    id: "09",
    slug: "official-graph",
    title: "正式知识图谱同步",
    status: "状态边界已接入",
    statusKind: "done",
    role: "Knowledge Platform",
    summary: "只有审核入库后的知识进入正式图谱 trace 与 RAG；状态 API 可观察同步是否完成。",
    objective: "将 ingested 知识同步到 Team Knowledge、正式 RAG 和 KnowledgeItem officialResearchGraph。",
    inputs: ["approved_to_ingest 候选", "正式 KnowledgeItem", "知识治理建议"],
    actions: [
      "将 official_pending 转为 official_synced。",
      "生成正式 supports、maps_to、inspires、approved_for_ingestion 边。",
      "保留 sourceFiles 和 review 追溯链。",
      "通过 knowledge-ingestion/status 区分 writesOfficialKnowledge、writesOfficialRag、writesOfficialGraph、ragStatus 和 graphStatus。",
    ],
    outputs: ["正式知识图谱 trace", "正式 RAG 可检索上下文", "officialKnowledgeItemId", "officialResearchGraph", "officialBoundary status"],
    memory: "只同步 ingested 内容，正式图谱 trace 挂在 KnowledgeItem metadata 上；RAG 状态通过 reviewed Team Knowledge 可读。",
    graph: "正式图谱 trace 必须能追溯到 sourceTrace、candidateIds、reviewRecordIds 和正式 KnowledgeItem；候选图快照不等于正式图谱。",
    risks: ["候选误同步", "sourceFiles 丢失", "正式图谱缺审核记录", "状态聚合误把下游未到达当失败"],
    openQuestions: ["是否在 Memory Graph 详情栏和 Teams 工作台同时显示 officialBoundary 摘要。"],
  },
  {
    id: "10",
    slug: "experiment-loop",
    title: "实验验证闭环",
    status: "待规划",
    statusKind: "pending",
    role: "Experiment Planning Agent / ML Run Service",
    summary: "未来把算法假设从方案推进到小规模验证。",
    objective: "规划 baseline/candidate 算法实验、指标、消融和结果回写。",
    inputs: ["algorithm_hypothesis", "experimentPlan", "候选实现提示"],
    actions: ["待规划：训练 runner。", "待规划：指标与数据集。", "待规划：实验结果回写。"],
    outputs: ["experiment_result", "实验报告", "promotion/reject 决策"],
    memory: "实验结果是否入库取决于证据复核 Agent 和知识治理 Agent。",
    graph: "未来边：AlgorithmHypothesis evaluated_by ExperimentResult。",
    risks: ["实验成本过高", "指标不能验证假设", "baseline 不公平"],
    openQuestions: ["是否先做轻量 toy benchmark。"],
  },
  {
    id: "11",
    slug: "iteration-versioning",
    title: "持续迭代与版本化",
    status: "待规划",
    statusKind: "pending",
    role: "Iteration Versioning Agent",
    summary: "防止研究假设失控堆积，保留可追溯版本。",
    objective: "管理候选修订、拒绝原因、同类假设合并和挑战杯材料摘要视图。",
    inputs: ["候选 index", "review_record", "experiment_result", "ingested 知识"],
    actions: ["待规划：versionHistory。", "待规划：supersededBy。", "待规划：rejectionArchive。"],
    outputs: ["版本链", "拒绝归档", "可复用总结"],
    memory: "版本化记录应保留但不默认进入正式知识。",
    graph: "未来边：supersedes、derived_from、rejected_because。",
    risks: ["同类假设重复", "拒绝原因丢失", "正式知识与候选版本混淆"],
    openQuestions: ["是否需要独立 version policy。"],
  },
  {
    id: "12",
    slug: "challenge-cup-delivery",
    title: "挑战杯交付计划",
    status: "待规划",
    statusKind: "pending",
    role: "Challenge Cup Delivery Agent",
    summary: "把研究流程产物转为比赛材料。",
    objective: "将候选知识、算法假设和实验计划转成技术方案、演示和提交材料。",
    inputs: ["ingested 知识", "algorithm_hypothesis", "experiment_result", "赛题要求", "赛题对齐方案"],
    actions: ["待规划：技术方案 PDF。", "待规划：演示视频脚本。", "待规划：前端演示与源代码包。", "已补充：赛题对齐方案作为赛道选择、评分映射和提交闭环依据。"],
    outputs: ["技术方案大纲", "演示脚本", "材料清单", "赛题对齐方案"],
    memory: "交付材料可引用正式知识，但不把材料草稿反向污染知识库。",
    graph: "未来边：KnowledgeItem supports DeliverableSection。",
    risks: ["比赛材料与正式知识不一致", "缺阿里云百炼凭证", "时间节点遗漏"],
    openQuestions: ["是否把报名 Excel 和技术方案生成纳入同一流程。"],
  },
  {
    id: "13",
    slug: "flow-html-maintenance",
    title: "流程 HTML 维护门禁",
    status: "已规划",
    statusKind: "done",
    role: "Flow Site Maintenance Agent",
    summary: "把科研流程 HTML 作为挑战杯开发的可视化索引与长期维护入口。",
    objective: "确保以后所有挑战杯开发、设计、schema、数据、记忆平台、图谱同步、实验和交付变化，都在同一轮同步进科研流程 HTML。",
    inputs: ["AGENTS.md 规则", "本轮挑战杯改动", "build_research_flow_site.mjs", "research_team_flow_design.html"],
    actions: [
      "优先修改 build_research_flow_site.mjs，而不是手工改生成后的页面。",
      "每个新增流程步骤都新增或更新索引节点，并提供对应独立计划页。",
      "尚未完整规划的步骤必须以占位页显式保留，避免流程断点隐形化。",
      "结束挑战杯相关任务前，重新生成 HTML 并验证页面链接。",
    ],
    outputs: ["更新后的总索引", "更新后的节点计划页", "HTML 链接验证记录", "final 中的 HTML 更新说明"],
    memory: "这是挑战杯流程维护规则，不等同于正式知识入库；若涉及项目级记忆，还需同步 .docs/project-memory。",
    graph: "不直接写入候选图谱或正式图谱；它约束图谱相关开发变化必须更新对应流程节点。",
    risks: ["只改代码不改流程页", "手工改生成页面导致下次覆盖", "新增节点没有独立计划页", "未报告 HTML 是否更新"],
    openQuestions: ["未来是否把链接验证脚本固化为单独 npm/script 入口。"],
  },
];

const knowledgeRunbook = {
  scope: "只跑通知识搜集、筛选、候选入库、知识治理 Agent 和图谱同步设计；不进入训练实验、算法实现或比赛交付。",
  minimalPath: [
    ["01", "资料登记", "source_manifest"],
    ["02", "生成笔记", "paper_note"],
    ["03", "提取机制", "neuro_mechanism"],
    ["04", "计算映射", "mechanism_mapping"],
    ["05", "形成假设", "algorithm_hypothesis"],
    ["06", "科研审稿", "review_record"],
    ["07", "知识治理", "ingestion_pack"],
    ["08", "候选图谱", "candidate_graph"],
    ["09", "正式同步", "official_sync"],
  ],
  stateFlow: [
    ["source_registered", "资料已登记", "资料来源可追溯，允许进入笔记生成。"],
    ["paper_note_draft", "论文笔记候选", "有摘要、发现、方法、局限和来源页码。"],
    ["mechanism_candidate", "神经机制候选", "机制和实验现象分开，证据链可追踪。"],
    ["mechanism_mapping_candidate", "计算抽象候选", "把机制映射成工程可讨论的计算抽象，并标明类比风险。"],
    ["hypothesis_candidate", "算法假设候选", "包含计算抽象、算法设想和 experimentPlan 占位。"],
    ["review_ready", "待科研审稿", "候选字段完整，等待风险筛选。"],
    ["ready_for_steward", "可交知识治理 Agent", "审稿通过或需要治理建议。"],
    ["steward_pack_draft", "治理草稿包", "CandidateStore 中已有 proposalPayload、ratingSuggestion、sourceTrace，且 approvalRequired=true。"],
    ["steward_pending_knowledge_review", "待审入库对象", "已创建 SourceArtifact、pending RefinementProposal，可选 pending ratingSuggestion；等待审批门禁。"],
    ["knowledge_ingestion_needs_review", "入库状态待审", "状态总览显示 pendingProposalCount、actionItems 和 officialBoundary，便于团队协调员分派审核。"],
    ["candidate_graph_visible", "候选图谱可见", "只进入候选图谱，不能当正式事实。"],
    ["official_synced", "正式同步完成", "授权审批门禁通过后进入 Team Knowledge、RAG、officialResearchGraph，并保留 KnowledgeItem 级待审评分建议。"],
  ],
  artifacts: [
    ["source_manifest.json", "资料索引", "记录文件路径、来源类型、可信度、页码范围和允许分析状态。"],
    ["paper_note_YYYYMMDD_NNN.json", "资料笔记", "从资料中抽取可审查的论文/资料笔记。"],
    ["neuro_mechanism_YYYYMMDD_NNN.json", "神经机制", "把论文事实整理成带证据链的神经机制候选。"],
    ["algorithm_hypothesis_YYYYMMDD_NNN.json", "算法假设", "把机制映射为可验证算法假设，必须含 experimentPlan。"],
    ["review_record_YYYYMMDD_NNN.json", "审稿记录", "记录通过、退回、拒绝和风险标记。"],
    ["steward_ingestion_pack_YYYYMMDD_NNN.json", "知识治理摄取包", "治理建议、评级建议、目标知识域和正式入库申请；审批通过后评分建议承接到正式 KnowledgeItem。"],
    ["candidate_graph.json", "候选图谱预览", "展示候选链路、断链和未审节点。"],
    ["official_sync_record_YYYYMMDD_NNN.json", "正式同步记录", "记录审批门禁、正式 KnowledgeItem、RAG 和图谱同步状态。"],
    ["knowledge_ingestion_status", "入库状态总览", "只读聚合 CandidateStore、候选图摘要、Team Knowledge stats、stages、actionItems 和 officialBoundary。"],
  ],
  gates: [
    ["资料门", "资料路径、来源和页码范围存在", "source_registered", "退回补 source_manifest"],
    ["证据门", "关键发现绑定 paper_note 和页码", "mechanism_candidate", "退回补 citation / page"],
    ["映射门", "机制映射区分论文事实、项目推断和过度类比风险", "mechanism_mapping_candidate", "退回补 fact / inference 边界"],
    ["假设门", "算法假设有 baseline、预期收益和 experimentPlan", "review_ready", "退回补实验计划"],
    ["审稿门", "review.decision 不是 rejected，风险可解释", "ready_for_steward", "退回 revision 或 rejectionArchive"],
    ["治理草稿门", "steward_pack_draft 必须 approvalRequired=true，且不得请求 officialSync/applyNow/writeOfficialGraph", "steward_pack_draft", "退回 steward_needs_revision"],
    ["治理门", "知识治理 Agent 只创建 SourceArtifact + pending RefinementProposal + 可选 pending ratingSuggestion，不直接创建 KnowledgeItem", "steward_pending_knowledge_review", "退回 steward_needs_revision"],
    ["入库门", "授权审批门禁确认正式摄取；approved 创建正式 KnowledgeItem，rejected 回到 steward_needs_revision", "official_synced", "停在候选图谱，不进正式图谱"],
  ],
  transferPrinciples: [
    "所有非线性跳转都必须产生 transfer_request 或 transfer_record，不能只改 status。",
    "普通功能 Agent 可以提出 transfer_request，但不能直接写最终流程状态。",
    "Research Coordination Agent 是唯一流程状态写入者，负责裁决、分配、写入 state/index 并关闭 transfer_record。",
    "返工优先跳到最小上游节点，不默认回到流程起点。",
    "涉及新增 Agent、工具权限、记忆权限或通信边变更时，先进入 risk_escalation。",
    "rejected 不是普通返工状态；只有内部门禁给出 reopenReason，并由 Research Coordination Agent 写入 reopen transfer_record，才能重新进入候选流程。",
    "流程转移关闭后必须更新 status_digest、候选 index 和必要的候选图谱断链报告。",
  ],
  transferMatrix: [
    ["资料不足", "paper_note_needs_revision / mechanism_needs_revision", "01 source_needs_confirmation", "Source Intake Agent", "transfer_request、missing_source_list"],
    ["摘录缺页码或 citation", "paper_note_needs_revision", "02 paper_note_draft", "Paper Note Extraction Agent", "transfer_record、citation_fix_list"],
    ["机制证据弱", "mechanism_needs_revision", "03 mechanism_candidate", "Neuro Mechanism Extraction Agent", "evidence_request、weak_evidence_report"],
    ["机制到算法映射不稳", "mapping_needs_revision", "04 mechanism_mapping_candidate", "Mechanism Mapping Agent", "analogy_risk_note、required_changes"],
    ["算法假设不可测", "hypothesis_needs_revision", "05 hypothesis_candidate", "Algorithm Hypothesis Agent", "experiment_plan_fix"],
    ["审稿要求返工", "review_ready + needs_revision", "最近责任节点", "原产出 Agent", "review_record、requiredChanges"],
    ["图谱断链", "candidate_graph_visible + broken_links", "对应缺失节点状态", "Candidate Graph Preview Agent 协调原产出 Agent", "broken_link_report"],
    ["入库治理退回", "steward_needs_revision", "06 审稿或 07 知识治理", "Evidence Review Agent / Knowledge Steward Agent", "steward_feedback"],
    ["审批门禁拒绝", "approved_to_ingest + rejected_by_gate", "rejection_archive 或 06 审稿", "Ingestion Approval Gate 指定", "ingestion_rejection_reason"],
    ["权限或能力缺口", "任意状态", "risk_escalation", "Research Coordination Agent", "risk_record、proposal"],
  ],
  transferRecordFields: [
    "fromNode",
    "fromState",
    "toNode",
    "toState",
    "reasonCode",
    "evidenceRefs",
    "requestedByAgent",
    "assignedToAgent",
    "decidedByAgent",
    "acceptance",
  ],
  teamWorkflowOrchestration: {
    target: "Team 作为信息流控制抽象，已新增通用 workflowOrchestration 后端切片；第一版只给 challenge_cup_research 模板启用。",
    principles: [
      "Team 负责流：状态编排、转移裁决、Agent 路由、返工派发、沟通模式和消息契约。",
      "CandidateStore 负责物：资料、笔记、机制、假设、审稿记录和候选图谱。",
      "workflowOrchestration 做成 Team 通用能力，但第一版只启用 challenge_cup_research。",
      "Research Coordination Agent 是 ownerAgent 和最终状态写入者。",
      "编排层只保存 candidateId、artifactRef、currentState 等引用，不保存大段正文。",
    ],
    fields: [
      ["workflowId", "团队编排流程标识，可被多个候选对象引用。"],
      ["workflowKind", "模板类型，第一版为 challenge_cup_research。"],
      ["ownerAgentId", "最终状态写入者，第一版固定 Research Coordination Agent。"],
      ["stateMachine", "states、transitions、gates 的组合。"],
      ["routingPolicy", "对接 Research Organization、Agent Bus、ChatRoom 的路由规则。"],
      ["transferPolicy", "自动转移规则，requiresUserConfirmation=false。"],
      ["activeWorkflowItems", "当前活跃候选引用，只保存 candidateId/artifactRef/currentState。"],
    ],
    landedApis: [
      ["GET", "/api/teams/{team_id}/workflow-orchestration", "读取或自动初始化 Team 编排视图。"],
      ["PUT", "/api/teams/{team_id}/workflow-orchestration", "确保 challenge_cup_research 编排与 ownerAgent。"],
      ["POST", "/api/teams/{team_id}/workflow-orchestration/candidates/source", "登记 source_manifest 候选。"],
      ["POST", "/api/teams/{team_id}/workflow-orchestration/candidates/{candidate_id}/source-extraction", "对本地 PDF source_manifest 计算 sha256、抽取 pageAnchors/excerpt，并回写候选校验状态；失败时停在 source_needs_confirmation。"],
      ["GET", "/api/teams/{team_id}/workflow-orchestration/paper-note-chunks/status", "只读聚合 sourceExtraction 就绪、paperNoteChunkPlan、open/drafted/needsRevision chunk 和 actionItems；不写正式知识/RAG/图谱。"],
      ["POST", "/api/teams/{team_id}/workflow-orchestration/candidates/{candidate_id}/paper-note-chunks/plan", "把已完成 sourceExtraction 的 source_manifest 切成可追踪 paper_note chunk seeds，并写回 CandidateStore metadata.paperNoteChunkPlan。"],
      ["POST", "/api/teams/{team_id}/workflow-orchestration/candidates/{candidate_id}/paper-note-draft", "把已完成的 sourceExtraction.excerpt/pageAnchors 或指定 chunkId 组装成本地模型 paper_note_draft 任务，落 CandidateStore，并回写 source candidate 的 paperNoteDrafts trace 与 chunk 进度。"],
      ["POST", "/api/teams/{team_id}/workflow-orchestration/transfers", "功能 Agent 提交流程转移请求。"],
      ["POST", "/api/teams/{team_id}/workflow-orchestration/transfers/{transfer_id}/decide", "Research Coordination Agent 裁决并写最终状态。"],
      ["POST", "/api/teams/{team_id}/workflow-orchestration/local-research-model/tasks", "构建本地研究模型任务包，不直接调用模型。"],
      ["POST", "/api/teams/{team_id}/workflow-orchestration/local-research-model/outputs", "校验并记录本地研究模型 JSON 草稿。"],
      ["POST", "/api/teams/{team_id}/workflow-orchestration/local-research-model/invoke", "构建任务包、调用 bossAGI-standard / qwen3.5-9b、解析 JSON 并写入 CandidateStore；解析失败不入库。"],
      ["POST", "/api/teams/{team_id}/workflow-orchestration/steward-packs/{candidate_id}/knowledge-ingestion", "把有效 steward_pack_draft 提交为 SourceArtifact + pending RefinementProposal，可选 pending ratingSuggestion；不创建 KnowledgeItem/RAG/正式图谱。"],
      ["POST", "/api/teams/{team_id}/workflow-orchestration/steward-packs/{candidate_id}/knowledge-ingestion/review", "审批 pending steward pack；approved 复用 Team Knowledge review/apply 创建正式 KnowledgeItem、迁移评分建议、写 officialResearchGraph 并写 officialSyncRecord，rejected 退回 steward_needs_revision。"],
      ["GET", "/api/teams/{team_id}/workflow-orchestration/knowledge-ingestion/status", "只读聚合知识入库漏斗：stages、summary、actionItems、CandidateGraphSummary、Team Knowledge stats 和 officialBoundary；不会生成新的 candidate_graph 快照。"],
    ],
    integrations: [
      ["Team registry", "增加 workflowOrchestration 引用或配置块。"],
      ["Team canvas", "继续展示成员、职责、communication/reports_to 边。"],
      ["linkedChatRoom", "承载 research_coordination 群聊轮次。"],
      ["Research Organization", "管理组织通信边、权限和能力缺口升级。"],
      ["Agent Bus / Inbox", "承接 transfer_request、status_report、risk_record 等定向消息。"],
      ["CandidateStore", "保存候选资料本体和候选图谱。"],
      ["Team Knowledge", "只接收审核后的正式知识对象。"],
    ],
  },
  roles: [
    ["Source Intake Agent", "登记资料，不做正式入库。"],
    ["Source Quality Assessment Agent", "筛选 source_manifest 的可靠性、可访问性、相关性和抽取风险，只写 CandidateStore。"],
    ["Paper Note Extraction Agent", "生成 paper_note，保留页码、引用和不确定性。"],
    ["Neuro Mechanism Extraction Agent", "提取神经机制，标注证据和不确定性。"],
    ["Mechanism Mapping Agent", "把机制转成计算抽象，明确类比风险。"],
    ["Algorithm Hypothesis Agent", "生成算法假设和 experimentPlan 占位。"],
    ["Evidence Review Agent", "筛选风险，决定通过、退回或拒绝。"],
    ["Knowledge Steward Agent / agent-knowledge-steward", "生成治理建议、评级建议和摄取包，不绕过审核。"],
    ["Ingestion Approval Gate", "批准正式入库和正式图谱同步。"],
  ],
  featureMatrix: [
    ["知识搜集一级工作台", "顶部展示当前判断、未完成任务、候选资料、搜索问题、缓存状态；5 个阶段卡用颜色区分进行中/完成/失败/待处理/未进行；步骤卡只保留状态和主操作，当前步骤 Agent 配置跟随右侧详情底部展示", "已接入前端"],
    ["资料与候选存储", "source_manifest、knowledge_candidates/index、候选 JSON 命名与状态流", "需新设计"],
    ["PDF/资料解析", "读取本地 PDF、页码锚点、摘录范围和 sourceFiles 绑定", "已接入后端/API"],
    ["科研知识只读查询", "research_knowledge_query_tool 用于查历史科研资料、claims、evidence、gaps", "已有能力"],
    ["正式知识查询/RAG", "knowledge_query_tool、knowledge_rag_retrieve_tool 只读检索已审核知识", "已有能力"],
    ["知识候选提交", "knowledge_proposal_tool / knowledge_ingestion_tool 只提交待审 proposal", "已有能力"],
    ["知识治理工作台", "knowledge_governance_tasks_tool、knowledge_steward_workbench_tool、recommendations", "已有能力"],
    ["入库状态总览", "knowledge-ingestion/status 聚合 CandidateStore、校验报告、候选图摘要、pending proposals、formal KnowledgeItem 和 officialBoundary；Teams 科研流程面板已可视化展示状态漏斗/actionItems/officialBoundary", "已接入前端/API"],
    ["团队协调队列", "coordination/status 聚合 pendingTransfers、needsRework、stewardship、blocked、active 队列，并输出 communicationBrief；Teams 科研流程面板已显示协调状态、目标 Agent、建议通道与只读策略边界", "已接入前端/API"],
    ["资料质量筛选", "source-quality/status 与 source-quality/assess 聚合/写回 source_manifest 质量评估；Teams 候选资料页可通过筛选或退回补资料", "已接入前端/API"],
    ["paper_note 分块计划", "paper-note-chunks/status 与 paper-note-chunks/plan 聚合/生成长论文 chunk seeds；Teams 候选资料页可生成或重建分块计划", "已接入前端/API"],
    ["阶段 Agent 配置面板", "知识搜集、实验、迭代阶段页从 Team canvas / Team members / Agent config workspace 推导本阶段功能 Agent，并跳转复用 Agent 管理配置", "已接入前端"],
    ["评级建议", "knowledge_rating_suggestion_tool 只提交 reviewable rating suggestion", "已有能力"],
    ["候选图谱预览", "CandidateStore candidate_graph payload、断链报告、候选/正式边界显示；Teams 工作台已接入首版 SVG 读取面，现有 Memory Graph 只承接正式知识结构视图", "已接入首版"],
    ["正式图谱同步", "approved 后进入 Team Knowledge/RAG，并把正式科研边写入 KnowledgeItem metadata.officialResearchGraph；Memory Graph 请求 include=officialResearchGraph 后显式展开", "已接线"],
  ],
  projectAlignment: [
    ["Research Agent 池", "prompt-research-broad/deep/review/themes/card 模板存在；research_service 可确保实例", "可复用+需绑定", "当前 active research pool 是 CEO/组织顾问/能力管家，不是挑战杯执行型功能岗位；需把 Source Intake Agent、Neuro Mechanism Extraction Agent、Evidence Review Agent 等绑定到模板或新建 Agent。"],
    ["科研组织治理", "research_agent_creation_proposal_tool、research_communication_edge_proposal_tool、research_proposal_apply_tool 已存在", "已有能力", "新增 Mechanism Mapping Agent / Algorithm Hypothesis Agent 等岗位应走 proposal + 用户确认，不直接创建。"],
    ["知识治理 Agent", "agent-knowledge-steward 固定存在；ToolPolicy 含 knowledge proposal/ingestion/governance/rating 工具；边界 proposal_and_rating_suggestion_only", "高度匹配", "07 节点已对齐 Team Knowledge 待审摄取包；该 Agent 不能直接应用正式知识，只能提交建议和待审对象。"],
    ["正式知识平台", "knowledge routes 支持 source-artifacts、refinement-proposals、ingestion-packages、review、items、trace、rating suggestions", "已有能力", "07/09 可以对齐 SourceArtifact -> RefinementProposal -> Review -> KnowledgeItem -> Trace。"],
    ["正式 RAG", "knowledge_rag_retrieve_tool 与 /api/knowledge/rag/retrieve 已存在，且只读正式知识", "已有能力", "03-06 可用它查正式背景知识；不能用它读取 pending proposal 或候选图谱。"],
    ["科研知识库", "ResearchKnowledgeBase 支持 entries/claims/evidence/gaps，research_knowledge_query_tool 显式授权后可查", "已有能力", "可用于查重和背景检索；它不是本轮候选 JSON 的落库位置。"],
    ["记忆知识图谱", "/api/memory/knowledge-graph 和 MemoryRoute 知识图谱视图已存在", "部分匹配", "适合展示正式 Team/Agent/KnowledgeBase/KnowledgeItem 结构；候选图谱首版在 Teams 工作台读取 CandidateStore 快照，不混入正式 Memory Graph。"],
    ["入库状态聚合", "Team Workflow 新增 knowledge-ingestion/status；读取 CandidateStore + Team Knowledge overview，不写正式知识、不写候选图快照", "已接入首版", "适合作为团队协调面板和后续状态机转移判断输入。"],
    ["团队协调聚合", "Team Workflow 的 coordination/status 读取 CandidateStore + transfer_records，按 pendingTransfers/needsRework/stewardship/blocked/active 分队列，并为每个队列项生成 communicationBrief", "已接入首版", "适合作为组织人员和协调人员的只读工作面；本轮不做自动调转、不自动发送消息、不写正式知识。"],
    ["PDF/本地资料解析", "Team Workflow 已新增 source-extraction API；知识 ingestion 工具仍要求传入已有 excerpt/source_ref，不负责解析 PDF", "已接入首版", "01 已能把本地 PDF 解析成 sourceExtraction.pageAnchors/excerpt；02 已能基于 pageAnchors 生成 paperNoteChunkPlan，并允许 paper-note-draft 按 chunkId 草稿化。"],
    ["候选 schema 与工作区", "paper_note/neuro_mechanism/algorithm_hypothesis/review_record/candidate_graph 尚未作为项目原生 schema 落地", "需新设计", "这是把流程跑通前的主要工程缺口。"],
  ],
};

const implementationBlueprint = {
  doc: "technical_implementation_plan.md",
  alignmentDoc: "赛题对齐方案.md",
  target: "复用 Vibelution 现有 Research、Team Knowledge、RAG、Knowledge Steward 和 Memory Graph 能力，把 01-09 做成可运行 MVP。",
  activeTeam: {
    teamId: "research-team",
    teamName: "ai科学研究团队",
    teamCategory: "科研组织团队",
    teamSource: "research_organization",
    linkedChatRoomId: "room-20260529-090009-757107-6a747d62",
    chatRoomPurpose: "research_coordination",
    workflowPath: "workspace/teams/research-team/workflow_orchestration.json",
    candidateStorePath: "workspace/teams/research-team/candidate_store/index.json",
    note: "挑战杯科研流程直接绑定当前 Vibelution ai科学研究团队，不另建新团队；Teams 页顶部只保留 AI 搜索范围团队和 ai科学研究团队两个固定入口，左侧栏删除，不再展示创建团队、模板创建或完整团队列表；选择 ai科学研究团队后直接进入团队专属科研工作台，默认只显示科研控制台：知识搜集、实验、迭代三张阶段卡各保留一个主操作和阶段详情入口；资料搜集已折叠进知识搜集阶段页，组织画布仅保留为附属结构视图；知识搜集一级工作台只展示当前判断、关键数量、阶段颜色和下一步按钮，详细追踪放入详情区。",
    workspaceEntry: "/teams?team=research-team",
    sourceCollectionEntry: "/teams?team=research-team&researchView=knowledge_collection",
    defaultView: "选中 ai科学研究团队后，团队内容区显示科研控制台：研究主题、当前阶段、知识搜集/实验/迭代三张阶段卡、每卡一个主按钮和一个阶段详情入口；知识搜集卡会按未开始、待继续搜索、搜索中、待筛选、可进入实验、等待回写显示状态，并提供“新一轮搜集”；点击知识搜集主按钮会创建/续用阶段轮次，并立即排队第一批后台资料搜索；知识搜集独立页的资料搜集、资料筛选、候选入库、候选图谱、共享记忆前审五张步骤卡只承载状态和主操作，当前步骤的功能 Agent 名称、模型、状态和配置入口集中显示在右侧详情底部；资料筛选主按钮会让资料质量评估 Agent 批量执行待筛候选；若已筛完，则显示 Agent 重新筛选并 force 复审已筛候选；批次列表按 teamId/startedFrom 在服务端过滤，后台 activeWorkRun 会持续显示正在团队搜索，AppShell 顶部优先显示知识搜集而不是团队群聊；知识搜集页不再把本阶段 Agent 统一堆在顶部，点击每张步骤卡才查看该步骤内容和操作；资料搜集子页把当前动作和原始资料记录分开：过程区只显示当前正在执行的一条动作，结果区只展示本轮 DataRecord 原始记录，并明确标出已入候选多少、还有多少待导入候选；候选入库子页单独展示本轮 source_manifest 候选资料，避免把原始记录数和候选数混在一起；资料结果统计使用原始记录、已入候选、可点击来源和本地文件，列表内 DOI 单独显示为 DOI 链接，网页显示可点击来源，本地文件显示路径，缺少来源直接标出；每条资料卡片可点击选中，右侧详情把资料来源和搜集证据分开：主操作只打开论文 DOI、网页来源或本地文件，Crossref/OpenAlex 等机器 API 放入“查看搜索证据”折叠区，并保留打开批次目录、搜索步骤、搜集记录和候选镜像入口；知识搜集启动不再依赖旧的 houmo_qwen35_9b_agent 固定 ID，而是由后端从当前模型库解析可用 KV 模型；模型证据、候选、路径、校验和内部状态默认移到阶段详情页或高级信息中。",
    canvasView: "组织画布保留可编辑能力，但不再出现在科研三阶段一级索引中；普通团队仍保持画布优先布局。",
  },
  architecture: [
    ["通用数据处理底座", "新增 data_processing_service 首切，提供 profile/run/record/collection assignment/output/status；用于资料搜集与筛选前置，不绑定科研特定 schema。"],
    ["Team 编排状态机", "已新增 TeamWorkflowOrchestration 后端切片，首期启用 challenge_cup_research。"],
    ["科研阶段轮次层", "新增 ResearchStageRound / stage-rounds/status / stage-rounds/start，统一承接知识搜集、实验和迭代三阶段启动、续做、新一轮与上游轮次追踪。"],
    ["候选资料工作区", "已新增 Team 级 CandidateStore 最小索引，保存正式平台尚不能表达的候选中间态。"],
    ["本地研究工作模型层", "接入 bossAGI-standard / qwen3.5-9b（OpenAI-compatible，32k）作为候选生成和预审模型，不作为最终裁决或正式入库模型。"],
    ["团队沟通复用层", "复用 Team registry、Team canvas、linkedChatRoom、ChatRoom round 和 research_coordination purpose；Teams 团队页顶部固定切换 AI 搜索范围团队 / ai科学研究团队，左侧栏删除以释放 research-team 主工作区，组织画布作为附属结构视图保留。"],
    ["研究编排复用层", "复用 research_service、research flow canvas、prompt-research-* 和研究组织治理工具。"],
    ["候选状态机", "新增轻量校验脚本约束 source_registered -> official_synced，不替代现有 runtime 状态系统。"],
    ["记忆平台复用层", "复用 SourceArtifact、RefinementProposal、IngestionPackage、KnowledgeItem、Trace 和 agent-knowledge-steward。"],
    ["图谱展示层", "候选图谱首版由 Teams 工作台读取 CandidateStore candidate_graph payload；正式图谱复用 /api/memory/knowledge-graph。"],
  ],
  milestones: [
    ["M0", "Team 编排后端切片", "已新增 workflow_orchestration.json、candidate_store/index.json、transfer_records.jsonl 和 API。", "能创建 challenge_cup_research 编排、登记资料候选、提交转移请求，并由 Research Coordination Agent 裁决。"],
    ["M0.1", "Team 页面科研流程入口", "已在 Teams 工作台为 research-team / 科研组织团队读取 TeamWorkflowOrchestration、最近 CandidateStore 候选和知识入库状态；当前入口统一为知识搜集、实验、迭代三阶段，旧的协调、入库、候选图谱、候选资料、团队沟通和组织画布不再作为一级索引。", "只读展示，不触发状态转移、审批、正式 Team Knowledge/RAG/图谱写入；普通非科研团队保持原画布优先布局，不被动初始化挑战杯 workflow。"],
    ["M0.2", "Teams 科研三阶段入口", "科研索引不再与团队同级，也不再混放流程模块，进入 ai科学研究团队后默认展示知识搜集、实验、迭代三张阶段控制卡。", "用户先选团队，首页只做当前阶段判断和一键主操作；知识搜集页承载原资料搜集对话流和技术控制台，实验/迭代页先提供规划启动、轮次状态、模块边界和返回团队页；监督进化/自进化画布已拆到各自模式页，以只读系统团队画布展示。"],
    ["M0.5", "本地研究工作模型接线", "已新增 Local Research Worker Model 任务包、32k 上下文预算、JSON 输出校验、草稿记录和 invoke API；bossAGI-standard / qwen3.5-9b 通过临时 model_ref profile 调用，解析失败不写 CandidateStore。", "能为资料初筛、paper_note 草稿、neuro_mechanism 候选、algorithm_hypothesis 草稿和 review prefilter 构建任务包，调用本地模型，并把合格 JSON 草稿写入 CandidateStore。"],
    ["M1", "候选数据基座", "已新增 CandidateStore 列表查询、校验报告、source_manifest/PDF 最小字段校验和本地 PDF source-extraction API；PDF 缺路径、sha256、allowedForAnalysis=true 或抽取失败会进入 source_needs_confirmation。", "能登记 PDF source_manifest，按 candidateType/currentState/qualityStatus 查询候选，抽取 sha256/pageAnchors/excerpt，并查看 invalid/error/warning 统计；仍不写正式 Team Knowledge/RAG/知识图谱。"],
    ["M2", "paper_note 与 PDF 锚点", "已新增 paper_note 输出契约与 Citation Anchor 校验，并接入 sourceExtraction -> paper_note_draft 自动草稿桥：本地 PDF pageAnchors/excerpt 会被转为 sourceRefs/evidenceRefs/excerpt 后调用本地模型；paperNoteChunkPlan 可把长文切成可追踪 chunk seeds。", "合格本地模型输出进入 paper_note_draft；缺 citation/page anchor 时进入 paper_note_needs_revision，不能自然推进到 mechanism_candidate；多 chunk 草稿合并仍待接。"],
    ["M3", "机制与算法假设", "已新增 neuro_mechanism、mechanism_mapping、algorithm_hypothesis 三段候选门禁；algorithm_hypothesis 必须含 mechanismMappingIds 或 neuroMechanismIds、hypothesis、baseline、expectedBenefit、expectedComputeCost 和含 dataset/metric/baseline/smokePlan 的 experimentPlan。", "合格机制进入 mechanism_candidate，合格映射进入 mechanism_mapping_candidate，合格算法假设进入 hypothesis_candidate；缺机制证据/术语风险、类比风险未标记或实验计划不完整时分别进入 mechanism_needs_revision / mapping_needs_revision / hypothesis_needs_revision。"],
    ["M4", "证据复核与候选图谱", "candidate_graph builder 后端/API 已落地；Teams 科研流程面板已接入 latest candidate_graph SVG 预览；review_prefilter 已补 review_record 候选门禁，必须含 candidateIds、checklist、comments、requiredChanges、needsDecision，且禁止写最终 decision；returned/rejected 转移闭环已接入。", "candidate_graph_visible 和 review_prefiltered 都只进入 CandidateStore；断链进入 broken_links，带最终 decision 的 prefilter 进入 review_needs_revision；returned 可回到最小上游修订节点，rejected 进入 rejection_archive 并从候选图谱推进视图隔离。"],
    ["M5", "知识治理与正式同步", "steward_pack_draft 门禁、待审入库桥、Ingestion Approval Gate、评分建议迁移、officialResearchGraph 正式边和 Memory Graph 展开已落地：有效草稿批准后创建正式 KnowledgeItem、承接待审评级并可视化正式科研 trace，拒绝后退回修订。", "正式 RAG 通过已审核 KnowledgeItem 检索；正式图谱边落在 KnowledgeItem metadata，并由 Memory Graph 只读展开。"],
    ["M6", "知识入库状态总览", "knowledge-ingestion/status 只读聚合 API 和 Teams 工作台可视化状态漏斗已接入，把 CandidateStore、候选校验、候选图摘要、Team Knowledge stats 和 officialBoundary 汇成 stages/actionItems。", "团队协调员可在 /teams?team=research-team 看到 source_collection、candidate_screening、steward_pack、knowledge_review、official_sync 的 ready/needs_review/blocked 状态；查询不会创建 KnowledgeItem、不会写 RAG、不会生成 candidate_graph 快照。"],
    ["M6.1", "团队协调状态队列", "coordination/status 只读聚合 API 和 Teams 工作台协调队列已接入，把 pendingTransfers、needsRework、stewardship、blocked、active 汇成队列、summary、actionItems、coordinationPolicy 和 communicationBrief。", "Research Coordination Agent/组织层可集中看到待决转移、返工候选、治理待审、阻塞项、目标功能 Agent 与建议通道；本轮不自动调转，不自动发送消息，不提供审批按钮。"],
    ["M6.2", "通用数据处理底座首切", "新增 /api/data-processing profiles/runs/list/records/collection-assignments/outputs/status，以及 workspace/data_processing/runs/<runId> 文件落库。", "资料搜集 Agent 可以先创建/查询 DataProcessingRun、领取 CollectionAssignment、提交 CollectionOutput 并生成 DataRecord；该层不写正式 Team Knowledge、不写 RAG、不写知识图谱，后续由挑战杯流程把 DataRecord 转为候选知识。"],
    ["M6.3", "DataRecord 导入 source_manifest", "新增 Team workflow 导入桥：/api/teams/{teamId}/workflow-orchestration/data-processing/runs/{runId}/records/{recordId}/source-candidate。", "通用 DataRecord 可被幂等导入 CandidateStore source_manifest，并保留 importedFromDataRecord、dataProcessingQualitySignals、collectionTrace 和 data_record/data_processing_run evidenceRefs；仍不写正式知识/RAG/正式图谱。"],
    ["M6.4", "资料搜集批次启动入口", "新增 /api/teams/{teamId}/workflow-orchestration/source-collection-runs，一次创建 DataProcessingRun 和功能 Agent CollectionAssignment。", "Research Coordination Agent 可以启动可追踪资料搜集批次，默认分配 data_discovery、source_acquisition、content_extraction；功能 Agent 回写 DataRecord 后再导入 source_manifest。"],
    ["M6.5", "数据搜索计划契约", "source-collection-runs 会生成 searchPlan、querySeeds、queries、roleAssignmentInputs 和 resultWritebackContract，并把 assignedQueries 写入各功能 Agent assignment scope。", "Research Coordination Agent 可基于 topic/goal/scope 启动可追踪搜索计划；本轮只生成 contract_only planned 查询，不触发外部搜索，不写正式 Team Knowledge/RAG/official graph。"],
    ["M6.6", "Teams 知识搜集执行台", "research-team 页面将原资料搜集索引折叠进知识搜集阶段页，可启动 source collection run、查看最近批次、run status、assignment、assignedQueries，并手工提交 CollectionOutput。", "启动批次会从 Team canvas 读取 data_discovery/source_acquisition/content_extraction/source_quality 等角色绑定的团队 agentId；手工回写会先写入 DataRecord，再通过 Team workflow 导入桥转成 source_manifest 候选；仍不触发真实外部搜索，不写正式 Team Knowledge/RAG/official graph。"],
    ["M6.7", "科研三阶段启动台", "research-team / ai科学研究团队右侧顶部新增三阶段启动台，提供知识搜集、实验、迭代三个启动按钮；后端新增 stage-rounds/status 和 stage-rounds/start。", "知识搜集会创建或续用 ResearchStageRound 并复用 source-collection run；实验与迭代先创建 planning 轮次和 coordinationContract，不自动执行实验/迭代；阶段记录写入 Team workflow runtime memory，不创建正式 KnowledgeItem/RAG/official graph。"],
    ["M6.8", "阶段协调改为显式启动", "stage-rounds/start 只记录 coordinationContract 和 manual_only startResult，不再自动拉起 linkedChatRoom 群聊。", "需要团队讨论时，由用户通过 coordination/retry 或团队讨论入口显式启动轻量协调 round；显式启动成功后再写回 coordinationRoomId/coordinationRoundId。"],
    ["M6.9", "模型调用证据链", "新增 official-model-evidence status/register API 和 Teams 科研总览证据面板；本地 qwen3.5 invoke 会自动登记 invocation_log，已有 local_model_output 也会只读折算为候选输出证据。", "团队可以看到 source_screening、paper_note、neuro_mechanism、mechanism_mapping、algorithm_hypothesis、review_prefilter 的 Qwen/百炼/本地模型证据覆盖；证据 store 不写正式 Team Knowledge/RAG/official graph。"],
    ["M6.10", "长论文 paper_note 分块计划", "新增 paper-note-chunks/status 与 paper-note-chunks/plan；Teams 候选资料页可对已完成 sourceExtraction 的 source_manifest 生成/重建 paperNoteChunkPlan。", "分块计划只写 CandidateStore metadata，按 pageAnchors 生成 chunk seeds；paper-note-draft 可带 chunkId 逐块草稿化并回写 chunk 进度，不写正式 Team Knowledge/RAG/official graph。"],
    ["M6.11", "资料质量筛选执行台", "新增 source-quality/status 与 source-quality/assess；Teams 候选资料页可由 Source Quality Assessment Agent 对 source_manifest 标记通过筛选或退回补资料。", "评估结果写入 CandidateStore metadata.sourceQualityAssessment/sourceQualityAssessments，并更新 source_quality_approved/source_quality_needs_revision/source_quality_rejected；不写正式 Team Knowledge/RAG/official graph。"],
    ["M6.12", "知识搜集独立阶段页与对话流", "新增 /teams?team=research-team&researchView=knowledge_collection 独立阶段页，承载原资料搜集对话流、状态摘要和技术控制台；旧 source_collection 参数兼容映射到知识搜集。", "对话流从现有 run/query/assignment/CollectionOutput/DataRecord/source_manifest/source_quality 状态合成，展示谁做了什么、结果是什么、存到哪里；仍不触发真实外部搜索，不写正式 Team Knowledge/RAG/official graph。"],
    ["M6.13", "科研三阶段索引统一", "Teams research-team 一级索引统一为知识搜集、实验、迭代三阶段；每个阶段点击进入独立页面并提供返回团队页。旧候选图谱、候选资料、团队沟通、知识入库和组织画布转为阶段内部能力或附属视图，不再与阶段同级展示。", "知识搜集阶段复用现有 source collection 对话式链路；实验和迭代阶段先提供规划页、启动按钮、轮次状态、模块边界和正式知识/RAG/official graph 写入边界。"],
    ["M6.14", "知识搜集 KV/prompt cache 启动门禁", "source-collection-runs 启动前生成 source_collection_prompt_cache_policy，默认要求本地研究模型 prompt_cache.mode 为 automatic 或 explicit_cache_control；不满足时 422 阻断，不创建 DataProcessingRun。", "run scope/metadata、searchPlan、query execution 和 CollectionAssignment scope 均写入 promptCachePolicyRef/promptCachePartition/conversationTraceRequired，后续对话式搜集 Agent 可复用稳定前缀，避免把全量历史和网页正文反复塞进模型。"],
    ["M6.15", "知识搜集缓存命中对话流", "Teams 知识搜集阶段页把 KV/prompt cache policy/ref 显示为搜集对话流中的独立步骤，并在摘要栏展示 KV 门禁状态。", "页面会说明稳定前缀承载团队规则、schema 和回写边界，动态增量只传当前 query、结果引用和存储位置；每个功能 Agent assignment 同时展示 promptCachePartition，方便后续真实搜索执行器复用对话链路并减少 token 消耗。"],
    ["M6.16", "知识搜集启动反馈修复", "stage-rounds/start 复用 active knowledge_collection 时返回 continuedSourceRunRef、run 和 assignments；Teams 知识搜集页显示“已复用已有搜集批次”和“等待功能 Agent 回写，未触发外部搜索”的可见提示。", "解决点击启动后像没有反应的问题；本轮仍不接真实外部搜索执行器，不写正式 Team Knowledge/RAG/official graph。"],
    ["M6.17", "知识搜集搜索执行最小闭环", "新增 source-collection-runs/{runId}/search/execute，知识搜集页提供“搜索下一批”按钮；系统可按 assignment/query 调用 Crossref 元数据搜索，生成执行事件、DataRecord，并自动导入 source_manifest 候选。", "这是 metadata-only 最小执行器：只下载来源元数据和引用，不抓取全文网页/PDF；结果仍停在候选资料仓库，不写正式 Team Knowledge、不写 RAG、不写 official graph。"],
    ["M6.18", "知识搜集工作台可视化降噪", "Teams 知识搜集页默认只展示当前轮状态、下一步动作、候选/待处理/查询/KV 摘要和对话式搜集过程；assignment、query、存储路径、KV 分区和手工回写收进可展开详情。", "用户第一眼能判断当前是否在搜、搜到什么、存到哪里和下一步怎么做；技术细节仍保留给维护者追溯，但不再挤占主路径。"],
    ["M6.19", "固定团队入口下拉", "Teams 左侧团队管理区替换为固定团队下拉，只暴露 AI 搜索范围团队和 ai科学研究团队；选择项会更新 team URL 并进入对应团队页面。", "当前页面不再显示创建团队表单、模板创建或完整团队列表，避免自定义团队入口挤占科研团队主工作区；后端团队创建和模板 API 不删除，仍可由其它管理面承接。"],
    ["M6.20", "顶部团队切换条", "Teams 固定团队入口从左侧栏移到 summary 下方的顶部横向切换条，左侧栏删除，主工作区改为科研内容优先。", "点击 AI 搜索范围团队或 ai科学研究团队后直接进入对应团队内容；科研三阶段页面获得更多横向空间，不再被团队选择区挤压。"],
    ["M6.21", "搜集证据落盘与打开位置", "source collection run 固定生成 workspace/teams/research-team/source_collection_runs/<runId>/，写入 search_plan.json、search_events.jsonl、records.jsonl、candidates.jsonl 和 artifacts/，Teams 知识搜集页提供打开批次目录、搜索计划、搜索步骤、搜集记录、候选镜像和候选仓库按钮。", "打开接口只接受白名单 target，不允许前端传任意路径；本轮仍只保存候选搜集证据，不绕过资料筛选、正式 Team Knowledge、RAG 或 official graph 门禁。"],
    ["M6.22", "科研总览控制台降噪", "Teams research-team 总览页移除旧三阶段索引和默认科研流程/模型证据详情，只保留研究主题、当前阶段、三张阶段卡、每阶段一个主操作和一个阶段详情入口。", "首页用于一键启动/续做和判断下一步；模型调用证据、候选数量、仓库路径、校验、KV 分区、query 和内部执行细节进入知识搜集/实验/迭代阶段页或可展开高级信息，不再默认挤占总览。"],
    ["M6.23", "控制台状态驱动操作卡", "知识搜集卡接入 source collection run 状态，显示未开始、待继续搜索、搜索中、待筛选、可进入实验、等待回写，并展示当前批次、待处理、候选和查询数。", "主按钮不再叫笼统的继续搜集，而是按状态变为开始知识搜集、搜索下一批、进入资料筛选或进入搜集工作台；旁边保留新一轮搜集和阶段详情，方便在总览操控流程、在详情查看内容。"],
    ["M6.24", "知识搜集中文控制台", "知识搜集阶段页新增中文展示映射层，把 processing/open/planned、Agent 英文角色、DataRecord/source_manifest/Query seeds 等内部字段转成中文业务表述。", "右侧控制台默认只保留一个主操作、本轮配置折叠、最近批次和一个批次目录按钮；更多证据文件、查询分工和手工回写进入详情，减少重复统计和技术噪声。"],
    ["M6.25", "知识搜集默认层去说明化", "知识搜集阶段页默认可见层移除解释性小字，只保留批次状态、阶段名称、关键数量、主操作、搜集过程和产物入口。", "本轮配置、查询分工、证据文件、路径和兜底回写继续保留在折叠详情；默认层不再依靠提示句解释页面怎么用。"],
    ["M6.26", "搜索状态收口", "通用 DataProcessingRun 在所有采集 assignment 关闭且已有记录后进入 reviewing；科研控制台把“搜索中”限定为真实请求执行中，把有待处理 assignment 的状态显示为“待继续搜索”。", "用户能区分后台正在执行、下一批可手动触发、以及已进入资料筛选；这不写正式 Team Knowledge、不写 RAG、不写 official graph。"],
    ["M6.27", "知识搜集控制台客观状态", "知识搜集独立页首屏提升为流程控制台：左上角显示正在团队搜索/待继续搜索/待筛选/失败等运行态，关键按钮直接展示搜索下一批、新一轮搜集、打开结果目录和刷新状态。", "五个步骤按进行中、已完成、失败、未进行、待处理映射为边框/绿色/红色/灰色/提示色；对话流继续承载证据与存放位置，后端搜索、筛选、正式知识/RAG/图谱边界不改变。"],
    ["M6.28", "全局运行状态接入", "source collection 搜索执行前写入 source_collection_run active work-run，结束或失败时写入终态；/api/runtime/status 会把它纳入 workRuns.active/activeItems，AppShell 顶部“正在进行”弹层显示“知识搜集”。", "用户不在知识搜集详情页时，也能从顶部状态栏看到 AI 科研团队正在搜集资料；完成后自动退出全局运行态，历史结果仍回到知识搜集阶段页查看。"],
    ["M6.29", "资料筛选入口常驻", "知识搜集独立页顶部操作条和右侧下一步面板固定显示资料筛选按钮；有 source_manifest 候选时点击进入候选资料筛选页，没有候选时保持禁用并显示暂无候选。", "资料筛选不再藏在模块数字或候选页深处；真实筛选仍复用 source-quality/assess 的通过筛选/退回补资料链路，不自动写正式 Team Knowledge、RAG 或 official graph。"],
    ["M6.30", "步骤卡主操作入口", "知识搜集独立页移除顶部操作条和右侧下一步面板的重复按钮，把资料搜集、资料筛选、候选入库、候选图谱、共享记忆前审五个步骤卡改成主操作入口。", "点击资料筛选不再跳回通用候选页，而是在知识搜集工作台内打开页内筛选详情；每个步骤继续按进行中、已完成、失败、未进行、待处理显示客观状态，正式知识/RAG/official graph 写入边界不变。"],
    ["M6.31", "资料筛选页内反馈修复", "资料筛选步骤卡点击后会展开本页筛选详情、滚动右侧控制台并短暂高亮目标区域；按钮文案从开始资料筛选改为打开资料筛选，避免误解为后台批量筛选。", "本轮只修复前端可见反馈和页内导航，不新增自动筛选执行器；通过筛选、退回补资料和生成分块仍复用已有 source-quality/assess 与 paper-note-chunks/plan 链路。"],
    ["M6.32", "资料筛选 Agent 一键执行", "新增 source-quality/assess-batch：资料筛选步骤卡点击后由资料质量评估 Agent 批量处理待筛 source_manifest，复用单条 source-quality/assess 的默认评分与候选写入逻辑。", "批量筛选只写 CandidateStore 的 sourceQualityAssessment/sourceQualityAssessments 和候选状态；仍不写正式 Team Knowledge、不写 RAG、不写 official graph，人工单条通过/退回保留为覆盖修正入口。"],
    ["M6.33", "候选库可视化二级索引", "知识搜集阶段的资料搜集、资料筛选、候选入库、候选图谱、共享记忆前审五张步骤卡都可点击进入对应页内详情；候选入库主按钮改为查看可视化候选库，不再直接打开 candidate_store/index.json。", "底层 candidate_store/index.json 仍保留在“更多证据文件”中作为维护入口；用户主路径只看到候选卡片、筛选状态、图谱预览和共享记忆前审，不再被 JSON 文件打断。"],
    ["M6.35", "知识搜集阶段子页控制台", "知识搜集阶段的五张步骤卡升级为页内子页索引，点击资料搜集、资料筛选、候选入库、候选图谱或共享记忆前审时，底部只显示该阶段内容。", "右侧控制台按当前阶段切换主操作按钮和关键数量；资料搜集保留配置/批次/回写折叠区，其余阶段只显示对应查看、筛选、刷新或前审动作，避免所有阶段信息同屏堆叠。"],
    ["M6.36", "资料筛选 Agent 复审入口", "资料筛选已完成时，步骤卡和右侧控制台主按钮不再只显示查看结果，而是显示 Agent 重新筛选，并通过 source-quality/assess-batch force=true 重新审查已筛候选。", "资料筛选详情页保留查看结果入口，同时新增显眼的 Agent 批量审查按钮；复审仍只写 CandidateStore 的 sourceQualityAssessment，不写正式 Team Knowledge、RAG 或 official graph。"],
    ["M6.37", "阶段 Agent 配置面板", "科研总览卡显示阶段 Agent 可用数；知识搜集、实验和迭代阶段页展示本阶段功能 Agent、绑定状态、模型摘要和配置入口。", "绑定来源复用 Team canvas / Team members / Agent config workspace；点击配置跳转 Agent 管理，不复制第二套 Agent 配置表单；缺绑定时显示待绑定或引用失效。"],
    ["M6.38", "知识搜集运行闭环根治", "data-processing run 列表支持按 profileId、teamId 和 startedFrom 服务端过滤，Teams 知识搜集页不再先取全局最近批次后本地过滤；后台搜索 accepted 后把 activeWorkRun 合成到控制台和对话流，资料搜集卡保持进行中直到 runStatus 收口。", "五个知识搜集子步骤的右侧控制台展示当前步骤相关功能 Agent，并复用 Agent 管理页进行配置；这轮只修复批次可见性、后台状态可见性和 Agent 绑定可操作性，不写正式 Team Knowledge、RAG 或 official graph。"],
    ["M6.39", "知识搜索启动模型解析根治", "修复知识搜集启动闪退：source collection prompt-cache policy 不再硬依赖已不存在的 houmo_qwen35_9b_agent；后端把前端传入的 modelId 视为偏好，从当前 operator config 模型库选择支持 automatic/explicit_cache_control 的文本模型。", "如果没有任何可用 KV 模型，接口仍明确阻断并返回可读原因；Teams 控制台把阶段启动错误纳入失败态，避免按钮闪一下后用户不知道原因。本轮不改 operator config，不写正式知识/RAG/official graph。"],
    ["M6.40", "知识搜集一键执行闭环", "stage-rounds/start 创建知识搜集轮次后立即调用既有 source-collection 后台搜索入口，并在响应中返回 sourceCollectionSearchExecution.activeWorkRun；前端把该快照合成到控制台和对话流。", "用户点击知识搜集后不再只看到计划和任务分配，而是能直接看到第一批资料搜索已排队/正在执行；AppShell 顶部运行态优先显示知识搜集，资料搜集步骤只展示 data_discovery、source_acquisition、content_extraction 等功能 Agent，不再把协调人误作执行 Agent。仍只写 DataRecord/CandidateStore 候选，不写正式 Team Knowledge、RAG 或 official graph。"],
    ["M6.41", "步骤 Agent 右侧配置槽", "知识搜集页移除顶部统一“本阶段 Agent”面板，也不再把 Agent 列表塞进五张步骤卡；资料搜集、资料筛选、候选入库、候选图谱、共享记忆前审的功能 Agent 跟随当前步骤显示在右侧详情底部。", "用户操作某个步骤时，只在对应详情里看到该步骤 Agent 的职责、Agent 名称、模型、状态和配置入口；顶部步骤卡只保留状态、数量和主按钮，避免重复信息挤占流程阅读空间。"],
    ["M6.42", "资料搜集过程与结果分层", "知识搜集页的资料搜集子页改为两块：当前搜集动作只显示一条正在进行或最近完成的动作，结果区集中展示本轮 DataRecord 原始记录。", "原始记录与候选资料分账展示：资料搜集子页显示原始记录、已入候选和待导入候选，候选入库子页单独展示本轮 source_manifest；顶部阶段卡和总览指标使用中文业务词，避免把 record/query/assignment 等内部计数混在一处。"],
    ["M6.43", "搜集结果状态徽标适配", "资料搜集结果列表中的资料状态独立为横向徽标，避免“需补资料”“已通过”等中文状态在窄列里被挤成单字。", "状态标签保留在结果卡右侧，但按内容撑开并禁止竖排；长状态最多省略，不再影响标题、摘要和来源时间的阅读。"],
    ["M6.44", "搜索运行态与后续任务拆分", "source collection work-run 和 Teams 控制台拆分 searchOpenAssignmentCount、downstreamOpenAssignmentCount；只有资料发现/来源获取这类真实搜索任务运行时才显示“正在团队搜索”。", "内容提炼、资料筛选、候选图谱和共享记忆前审的待处理不再把顶部状态误置为搜索中；控制台展示可搜索任务、后续任务和搜集结果，用户能判断当前是否真的有 Agent 在跑。"],
    ["M6.45", "知识搜集信息架构降噪", "知识搜集页顶部五张步骤卡删除重复 Agent 槽，右侧详情底部集中展示当前步骤 Agent 配置；搜集结果区改名为已收集资料，并把统计拆成已搜到、可点击来源、本地文件和待 Agent 筛选。", "用户不需要理解 DataRecord、query、source_manifest 等内部术语，也能判断哪些是流程步骤、哪些是实际资料结果、当前步骤由哪个 Agent 和模型承接。"],
    ["M6.46", "搜集结果来源可溯源", "资料搜集结果卡新增来源展示规则：DOI 统一显示为 DOI 并链接 doi.org，网页来源显示为可点击链接，本地资料显示文件路径，缺少 DOI/链接/本地路径时用缺少来源标出。", "用户能一眼区分论文 DOI、网页元数据和本地文件；不可溯源候选不会和正常结果长得一样，后续筛选 Agent 也能把来源缺失作为退回补资料依据。"],
    ["M6.47", "资料卡片点击追溯", "资料搜集、资料筛选和候选入库列表中的资料卡片可点击选中，右侧详情展示当前资料的 DOI/网页/本地路径、搜索问题、资料记录、批次、分工和搜索源。", "外部来源直接打开 DOI 或网页；本地来源通过既有 source-collection storage 白名单入口打开批次目录、搜索步骤、搜集记录和候选镜像，不允许前端传任意本地路径。"],
    ["M6.48", "资料来源与搜集证据分层", "右侧资料详情把用户可读来源和机器搜索证据分开：主按钮只打开论文 DOI、网页来源或本地文件，Crossref/OpenAlex API 查询放入“查看搜索证据”折叠区。", "用户不会再把 api.crossref.org JSON 当成论文页面；开发者仍可在证据区打开 API 原文、批次目录、搜索步骤、搜集记录和候选镜像追溯 Agent 搜集过程。"],
    ["M6.49", "五阶段完整结果与来源过滤", "资料搜集、资料筛选、候选入库、候选图谱、共享记忆前审五个子页统一接入来源类型过滤：全部、PDF、论文网页/DOI、数据集、本地文件、缺少来源。", "资料筛选和候选入库不再只显示少量预览；候选图谱按过滤条件裁剪节点/边并补节点列表；共享记忆前审显示候选资料和前审问题，所有卡片保留 DOI、网页、本地文件或候选详情追溯入口。"],
    ["M6.50", "知识搜集可读操作台根治", "知识搜集独立页改为实体工作台：主题背景不再穿透正文，顶部五阶段卡只承担导航、状态和主按钮，不再展示输入/输出小框。", "当前阶段子页固定为“结果”和“Agent过程”；阶段交接只在子页头部展示输入、输出、下一步，右侧控制区固定宽度，只保留下一步操作、当前资料详情和当前步骤 Agent 配置。"],
    ["M6.51", "阶段分页点击稳定", "知识搜集阶段结果面板的数量标识和分页控件只作为状态/翻页入口，不再触发 details summary 折叠或外层布局重排。", "点击 1-8/20、上一页、下一页或阶段标题右侧数量时，页面保持当前阶段布局；只有明确的阶段卡、结果/Agent过程 tab 和分页按钮会改变内容。"],
  ],
  schemas: [
    "DataProcessingRun",
    "DataRecord",
    "DataSearchPlan",
    "SearchQuerySeed",
    "CollectionAssignment",
    "CollectionOutput",
    "source_manifest",
    "paper_note",
    "neuro_mechanism",
    "mechanism_mapping",
    "algorithm_hypothesis",
    "review_record",
    "candidate_graph",
    "steward_ingestion_pack",
    "official_sync_record",
    "official_model_evidence",
    "source_quality_assessment",
    "source_collection_prompt_cache_policy",
  ],
  services: [
    ["data_processing_service", "已落地首切：通用 profile/run/record/collection assignment/output/status，数据落到 workspace/data_processing/runs/<runId>；只做通用资料处理，不直接写正式知识。"],
    ["data_processing API", "已落地：/api/data-processing/profiles、runs 创建/列表/详情、records、collection-assignments、outputs、status；供数据搜集类 Agent 领取任务和回写结果。"],
    ["team_workflow_orchestration_service", "已落地：Team 级 workflowOrchestration、ResearchStageRound、CandidateStore、transfer request/decision、source-collection run 启动、DataSearchPlan/query seed 契约、prompt cache/KV 启动门禁、DataRecord -> source_manifest 幂等导入桥、source_quality assessment、paper_note chunk planning，以及 official_model_evidence 证据登记/status。"],
    ["team_workflows API", "已落地：/api/teams/{team_id}/workflow-orchestration、stage-rounds/status、stage-rounds/start、stage-rounds/{stageRoundId}/coordination/retry、stage-rounds/{stageRoundId}/memory-record/retry、source-collection-runs（含 searchPlan/querySeeds/assignedQueries/resultWritebackContract）、candidates/source、data-processing/runs/{runId}/records/{recordId}/source-candidate、candidates/{candidate_id}/source-extraction、source-quality/status、candidates/{candidate_id}/source-quality/assess、paper-note-chunks/status、candidates/{candidate_id}/paper-note-chunks/plan、candidates/{candidate_id}/paper-note-draft（支持 chunkId）、candidates、candidates/validation、candidate-graph、transfers、decide、knowledge-ingestion/status、coordination/status、official-model-evidence/status、official-model-evidence；coordination/status 返回 communicationBrief。"],
    ["TeamsRoute workflow workspace", "已落地入口：Teams 页顶部固定横向切换条只暴露 AI 搜索范围团队和 ai科学研究团队，左侧栏已删除；监督进化/自进化模式页各自读取系统 Team 并展示只读团队画布；选择 ai科学研究团队后直接进入 research-team 专属科研控制台；总览只显示知识搜集、实验、迭代三张阶段卡，每张卡一个主操作和一个阶段详情入口。知识搜集卡会显示当前批次、待处理、候选和查询数，主按钮按状态执行开始、下一批搜索、筛选入口或打开工作台，另有新一轮搜集入口。知识搜集页位于 /teams?team=research-team&researchView=knowledge_collection，默认展示高价值状态摘要、状态驱动主操作和对话式 source collection 过程流；点击知识搜集主按钮会通过 stage-rounds/start 创建轮次并立即排队第一批后台 source collection 搜索；执行 source collection 搜索时会写入 source_collection_run 运行快照，让 AppShell 顶部“正在进行”优先显示知识搜集；资料搜集 run 列表通过 data-processing 服务端 teamId/startedFrom 过滤，避免被其它团队批次挤掉；后台 accepted 后 activeWorkRun 会进入控制台和对话流，直到 runStatus 收口；资料搜集、资料筛选、候选入库、候选图谱、共享记忆前审五张步骤卡各自带主按钮并作为页内子页索引，顶部卡片只保留状态、关键数量和主操作，不再显示输入/输出小框；底部只显示当前阶段内容，并拆成结果与 Agent过程；右侧只显示当前步骤操作、当前资料详情、关键数量和当前步骤 Agent 配置；资料筛选会调用资料质量评估 Agent 批量执行，完成后展开、滚动并高亮页内筛选详情；KV/prompt cache 由后端从当前模型库解析，不再依赖旧固定模型 ID；稳定前缀、动态增量、assignment、query、存储路径和手工回写保留在可展开详情中；默认层移除解释性小字且使用实体工作台背景，避免主题壁纸压住正文；实验/迭代页先提供规划启动、轮次状态和边界说明；旧 source_collection 参数兼容映射到知识搜集。"],
    ["local_research_worker_model", "已落地任务包构建、32k 上下文预算、统一 LLMClient invoke、JSON 提取/校验和 CandidateStore 草稿记录；解析失败不入库。"],
    ["team_communication_binding", "复用 Research Organization 通信边、Team linkedChatRoom、round_robin/opportunistic 群聊轮次。"],
    ["candidate_store", "已落地 Team 级 index、候选列表查询、按类型/状态过滤、validationSummary，并接入 source_manifest、paper_note、neuro_mechanism、mechanism_mapping、algorithm_hypothesis、candidate_graph 最小校验；rejected 候选保留在 CandidateStore metadata.rejectionArchive，但不进入候选图谱推进节点。"],
    ["source_parser", "已接入后端/API：本地 PDF source_manifest 可计算 sha256、抽取 pageAnchors/excerpt 并回写 CandidateStore；缺文件、非 PDF、解析器不可用或无文本时记录 failed extraction。"],
    ["source_quality_assessment", "已接入后端/API/Teams 候选资料页：对 source_manifest 记录 relevance/reliability/accessibility/extractionReadiness/overall 分数和 approved/needs_revision/rejected 决策。"],
    ["paper_note_chunk_planner", "已接入后端/API/Teams 候选资料页：对已完成 sourceExtraction 的 source_manifest 生成 paperNoteChunkPlan，并支持按 chunkId 调用 paper-note-draft。"],
    ["candidate_validator", "已落地 source_manifest/PDF 字段校验、sourceExtraction 失败校验、paper_note citation anchor 校验、neuro_mechanism 证据/术语风险校验、mechanism_mapping fact/inference/overAnalogyRisk 校验、algorithm_hypothesis experimentPlan 校验、candidate_graph 边界校验和 CandidateStore 校验报告。"],
    ["candidate_graph_builder", "已落地后端/API：生成 candidate_graph 候选快照、断链报告、未审节点清单、archivedCandidateCount 和 candidate_only officialBoundary；Teams 工作台已接入首版候选图谱读取、刷新和 SVG 预览。"],
    ["research_agent_binding", "复用 research_service、research flow canvas、prompt-research-* 和研究组织治理工具。"],
    ["memory_ingestion_bridge", "已复用 Team Knowledge create_ingestion_package、review_refinement_proposal、rating suggestion review/create 和 KnowledgeItem metadata patch；steward_pack_draft 可进入 pending proposal，审批通过后创建正式 KnowledgeItem、迁移待审评分建议，并写入 officialResearchGraph 正式科研边。"],
    ["knowledge_ingestion_status", "已新增只读状态聚合：输出 summary/stages/actionItems/candidateBreakdown/candidateGraphSummary/knowledgeBases/officialBoundary，并记录 knowledge_ingestion.status_viewed 运行事件计数。"],
    ["official_model_evidence_status", "已新增只读模型证据聚合：读取 official_model_evidence store 和 CandidateStore 派生模型输出，汇总 coverage/providerCounts/actionItems/officialBoundary，并记录 official_model_evidence.status_viewed。"],
  ],
  communicationRoles: [
    ["Research Coordination Agent", "会议议题、任务拆分、状态汇总、风险升级和跨节点排期。"],
    ["Research Organization Agent", "团队结构、成员职责、通信边、汇报关系和新增 Agent 提案。"],
    ["Capability Governance Agent", "工具权限、记忆权限、prompt/template 适配和能力缺口审查。"],
  ],
  communicationProtocols: [
    ["agenda_brief", "新阶段、新资料批次、新实验方向", "opportunistic，Research Coordination Agent 优先", "agenda_packet、task_assignment"],
    ["status_sync", "阶段内例行同步", "round_robin", "status_digest、blocker_list"],
    ["evidence_closure", "证据冲突、引用不足、结论待复核", "round_robin", "review_record、decision_request"],
    ["decision_gate", "准备入库或同步正式图谱", "opportunistic，门禁相关 Agent 优先", "ingestion_decision、official_sync_record"],
    ["risk_escalation", "权限、数据可信度、工具缺口、流程阻塞", "opportunistic", "risk_record、proposal 或 rollback_request"],
  ],
  messageContracts: [
    ["task_assignment", "goal、inputRefs、expectedArtifact、acceptance、ownerAgent、deadline、dependency"],
    ["status_report", "currentState、progress、blockers、nextAction、evidenceRefs、needsDecision"],
    ["evidence_request", "claimId、sourceRef、question、urgency、requiredBy"],
    ["decision_record", "decision、optionsRejected、reason、impact、followUp、knowledgeCandidateRefs"],
    ["risk_record", "riskType、severity、affectedNode、evidence、proposedMitigation、escalationTarget"],
  ],
  communicationNoiseRules: [
    "普通状态和证据追问优先走定向通信边和收件箱，不默认全员广播。",
    "每个任务线程只允许一个 ownerAgent 汇总，其他 Agent 回复给 ownerAgent。",
    "每轮 ChatRoom 结束必须生成 status_digest 或 decision_record，否则不能进入记忆候选。",
    "重复问题先查 Team Knowledge/RAG、candidate_graph 和上一轮 status_digest。",
    "超过一轮仍无法解决的 blocker 必须转成 risk_record 并升级。",
  ],
  communicationMetrics: [
    ["decision_round_count", "一个节点从提出问题到形成 decision_record 的群聊轮次数。"],
    ["unresolved_blocker_age", "阻塞项停留在 blocker_list 的时长。"],
    ["duplicate_question_count", "同一 claim/sourceRef 被重复追问的次数。"],
    ["chat_to_memory_conversion_rate", "群聊轮次中成功转成 SourceArtifact / RefinementProposal 的比例。"],
    ["rejected_due_to_evidence_gap", "因证据不足被知识治理或审批门禁退回的数量。"],
  ],
  localModel: {
    name: "bossAGI-standard / qwen3.5-9b",
    role: "Local Research Worker Model",
    contextWindow: "约 32k tokens",
    positioning: "本地 OpenAI-compatible 研究工作模型，模型 ID 为 houmo_qwen35_9b_agent；适合高吞吐候选生成、资料初筛、结构化草稿和预审；不做最终科研裁决，不直接写正式 Team Knowledge/RAG/知识图谱。",
    runtimeNotes: [
      ["服务地址", "http://192.168.20.30:8081/v1"],
      ["模型文件", "HiModel_xh2_qwen3.5_9b_256_256k_b1_1chip_2cores_v1.3.0_20260429.gguf"],
      ["已验证", "GET /v1/models、POST /v1/chat/completions、Vibelution LLMClient probe 和 Team workflow invoke 测试均通过。"],
      ["推理输出", "该后端会大量返回 reasoning_content；科研任务要预留输出预算，并从最终 content/草稿 JSON 做校验，必要时容错检查 reasoning 草稿。"],
      ["图像能力", "不支持图像输入；PDF/图片资料需要先由解析器转成文本和页码锚点。"],
      ["入库边界", "invoke 成功后只写 CandidateStore 草稿；不会写正式 Team Knowledge/RAG/知识图谱，解析失败不入库。"],
    ],
    contextBudget: [
      ["系统指令/输出 schema", "10%-15%", "稳定 JSON、字段定义、禁止事项和证据规则。"],
      ["当前任务说明", "5%-10%", "节点目标、输入类型、状态和验收条件。"],
      ["论文片段/evidence", "55%-65%", "建议控制在 18k-22k tokens，保留页码、章节和 sourceRef。"],
      ["已有候选上下文", "10%-15%", "paper_note、mechanism、hypothesis 等上游候选摘要。"],
      ["输出预留", "10%-15%", "避免塞满上下文导致 JSON 漂移或后半段注意力下降。"],
    ],
    nodeAssignments: [
      ["01 资料进入工作区", "标题/摘要/片段初筛，输出 relevanceScore、topicTags、excludeReason。"],
      ["02 生成 paper_note", "按章节或 chunk 生成 paper_note 草稿，保留 keyFindings、methods、limitations、citations、uncertainty；缺 citation/page anchor 会退回修订。"],
      ["03 提取 neuro_mechanism", "从 paper_note 和关键片段抽取机制候选，必须区分实验现象、作者解释和项目理解，并标记 evidenceRefs、confidence、riskFlags。"],
      ["04 机制到计算抽象", "生成多种计算抽象映射，强制区分 neuroMechanismIds、computationalAbstraction、factLayer、inferenceLayer、overAnalogyRisk、engineeringImplication；高类比风险必须标记 over_analogy_risk。"],
      ["05 生成 algorithm_hypothesis", "生成算法假设草稿，补 baseline、expectedBenefit、expectedComputeCost、experimentPlan。"],
      ["06 科研审稿", "只做 review prefilter，给 riskFlags 和 requiredChanges，不做最终审稿裁决。"],
      ["07 知识治理入库", "只生成 steward_pack_draft 草稿；approvalRequired 必须为 true，且不得请求 officialSync/applyNow/writeOfficialGraph。"],
    ],
    hardBoundaries: [
      "不得直接写正式 Team Knowledge、正式 RAG 或正式知识图谱。",
      "不得替代 Evidence Review Agent、Knowledge Steward Agent 或 Ingestion Approval Gate 的最终裁决。",
      "没有 sourceRef/page/citation 的结论必须标记 weak_evidence。",
      "神经术语不确定时必须标记 terminology_uncertain。",
      "机制到算法的类比必须拆成 factLayer 和 inferenceLayer。",
      "输出必须是可校验 JSON；自然语言解释只能放入 comments/notes 字段。",
    ],
    outputContract: [
    "candidateType",
    "sourceRefs",
    "evidenceRefs",
    "claims",
    "keyFindings",
    "methods",
    "limitations",
    "citations",
    "paperNoteIds",
    "description",
    "brainSystems",
    "cognitiveFunctions",
    "experimentalPhenomena",
    "authorInterpretation",
    "projectInterpretation",
    "neuroMechanismIds",
    "computationalAbstraction",
    "factLayer",
    "inferenceLayer",
    "overAnalogyRisk",
    "engineeringImplication",
    "mechanismMappingIds",
    "hypothesis",
    "baseline",
    "expectedBenefit",
    "expectedComputeCost",
    "experimentPlan",
    "candidateIds",
    "checklist",
    "comments",
    "requiredChanges",
    "needsDecision",
    "targetDomain",
    "sourceTrace",
    "riskSummary",
    "proposalPayload",
    "ratingSuggestion",
    "approvalRequired",
    "uncertainty",
    "riskFlags",
      "confidence",
      "nextAction",
      "requiresReview",
    ],
  },
  deliveredSlice: [
    ["通用数据处理服务", "core/web/services/data_processing_service.py", "新增 DataProcessingRun、DataRecord、CollectionAssignment、CollectionOutput 文件落库和安全运行事件计数。"],
    ["通用数据处理路由", "core/web/routes/data_processing.py", "提供 /api/data-processing profiles/runs 创建/列表/详情/records/collection-assignments/outputs/status；供 Agent 领取资料搜集任务和提交输出。"],
    ["资料搜集批次启动", "/api/teams/{teamId}/workflow-orchestration/source-collection-runs", "Research Coordination Agent 可一次创建 DataProcessingRun、searchPlan 和 data_discovery/source_acquisition/content_extraction 等功能 Agent assignments。"],
    ["科研阶段轮次启动", "/api/teams/{teamId}/workflow-orchestration/stage-rounds/start", "统一启动/续做/开启新一轮知识搜集、实验、迭代；知识搜集复用 source-collection run，实验和迭代先生成 planning 轮次；阶段启动只记录显式协商契约，不自动启动群聊。"],
    ["科研阶段状态", "/api/teams/{teamId}/workflow-orchestration/stage-rounds/status", "只读聚合三阶段状态、activeRound、latestRound、readiness、primary/secondary actions 和正式知识/RAG/图谱写入边界。"],
    ["阶段协调显式启动", "/api/teams/{teamId}/workflow-orchestration/stage-rounds/{stageRoundId}/coordination/retry", "用户明确需要团队讨论时启动团队协调 round；如果群聊缺失、忙碌或没有可发言成员，会把失败原因写回 coordinationContract；成功后写回 coordinationRoomId/coordinationRoundId。"],
    ["数据搜索计划契约", "DataSearchPlan / assignedQueries", "基于 topic/goal/scope/querySeeds 生成 planned 查询、角色分配输入和 resultWritebackContract；只做 contract_only 搜索计划，不触发真实外部搜索。"],
    ["DataRecord 导入桥", "/api/teams/{teamId}/workflow-orchestration/data-processing/runs/{runId}/records/{recordId}/source-candidate", "把通用 DataRecord 幂等导入为 source_manifest 候选，保留 run/record/quality/collection trace；不写正式知识。"],
    ["模型调用证据链", "/api/teams/{teamId}/workflow-orchestration/official-model-evidence/status", "只读聚合 Qwen/百炼/本地模型调用证据覆盖；本地模型 invoke 自动登记 invocation_log，已有 local_model_output 可折算为候选输出证据；不写正式知识/RAG/图谱。"],
    ["模型证据登记", "/api/teams/{teamId}/workflow-orchestration/official-model-evidence", "允许登记 invocation_log、sample_output、screenshot、config 或 manual_attestation，要求绑定 taskType/workflowNode/candidateId 之一，用于审计而非自动入库。"],
    ["资料质量筛选状态", "/api/teams/{teamId}/workflow-orchestration/source-quality/status", "只读聚合 source_manifest 的 assessed/approved/needs_revision/rejected/unassessed、actionItems、screeningContract 和 officialBoundary。"],
    ["资料质量筛选写回", "/api/teams/{teamId}/workflow-orchestration/candidates/{candidateId}/source-quality/assess", "Source Quality Assessment Agent 对 source_manifest 写入 metadata.sourceQualityAssessment，并更新 source_quality_approved/source_quality_needs_revision/source_quality_rejected；不写正式知识/RAG/图谱。"],
    ["paper_note 分块状态", "/api/teams/{teamId}/workflow-orchestration/paper-note-chunks/status", "只读聚合 sourceExtraction 就绪来源、paperNoteChunkPlan、chunk draft 进度、缺计划来源和 actionItems；不写正式知识/RAG/图谱。"],
    ["paper_note 分块计划", "/api/teams/{teamId}/workflow-orchestration/candidates/{candidateId}/paper-note-chunks/plan", "对已完成 sourceExtraction 的 source_manifest 生成或重建 page_anchor_window chunk seeds，写回 CandidateStore metadata.paperNoteChunkPlan。"],
    ["服务文件", "core/web/services/team_workflow_orchestration_service.py", "Team 编排、资料搜集批次启动、候选登记、DataRecord 导入、资料质量筛选、paper_note 分块计划、模型证据登记、转移请求、协调 Agent 裁决和轻量运行事件日志。"],
    ["路由文件", "core/web/routes/team_workflows.py", "提供工作流查询/确保、资料搜集批次启动、候选资料登记、DataRecord 导入、资料质量筛选状态/写回、paper_note 分块状态/计划、模型证据状态/登记、转移提交、转移裁决 API。"],
    ["路由注册", "core/web/app.py", "新增 team_workflows_router，挂载到 /api。"],
    ["存储位置", "workspace/teams/<teamId>/workflow_orchestration.json", "保存 Team 编排结构与 activeWorkflowItems。"],
    ["阶段轮次索引", "workspace/teams/<teamId>/research_stage_rounds/index.json", "保存 ResearchStageRound、sourceRunIds、upstreamRoundIds、teamMemoryRecord、coordinationContract，以及显式协调启动后的 coordinationRoomId/coordinationRoundId。"],
    ["候选索引", "workspace/teams/<teamId>/candidate_store/index.json", "保存 source_manifest 等候选对象的最小元数据。"],
    ["模型证据索引", "workspace/teams/<teamId>/official_model_evidence/index.json", "保存模型调用证据、artifact/log/screenshot 引用、覆盖节点和 officialBoundary；只做证据审计，不做正式知识写入。"],
    ["候选查询", "/api/teams/{teamId}/workflow-orchestration/candidates", "按 candidateType、currentState、qualityStatus 查询 CandidateStore，并返回 validationSummary。"],
    ["候选校验", "/api/teams/{teamId}/workflow-orchestration/candidates/validation", "统计 CandidateStore valid/invalid/error/warning，并报告每个候选的结构化校验问题。"],
    ["Team 前端入口", "/teams?team=research-team", "读取 /workflow-orchestration、/stage-rounds/status、/official-model-evidence/status、/candidates?limit=8、/knowledge-ingestion/status 和通用 data-processing run/status/assignment；顶部横向切换条只允许选择 AI 搜索范围团队或 ai科学研究团队，点击 research-team 后直接进入团队专属科研控制台，内容区只展示知识搜集、实验、迭代三张阶段卡和状态驱动主操作；非这两个团队不在当前入口暴露。"],
    ["知识搜集阶段页", "TeamsRoute knowledge collection stage", "可在 /teams?team=research-team&researchView=knowledge_collection 独立打开知识搜集页，启动 source collection run、查看 DataSearchPlan/querySeeds/assignment/assignedQueries，并手工提交一条含 rawLocation 的 CollectionOutput；启动时优先使用 Team canvas 中各功能角色绑定的团队 agentId，提交后自动导入 source_manifest 候选；页面会把 KV 门禁状态、promptCacheMode、稳定前缀、promptCachePartition 和 source_collection_runs/<runId> 证据落盘位置放入搜集对话流，并可通过 storage/open 白名单接口打开对应位置。"],
    ["转移记录", "workspace/teams/<teamId>/transfer_records.jsonl", "记录 transfer_request 和 decidedByAgent。"],
    ["本地模型 API", "/api/teams/{teamId}/workflow-orchestration/local-research-model/*", "构建任务包、调用 9B 本地模型、校验并记录 JSON 草稿；不直接写正式知识。"],
    ["paper_note 门禁", "CandidateStore paper_note validation", "paper_note_draft 必须含 keyFindings/methods/limitations/citations，关键发现缺 sourceRef/page/citation 时进入 paper_note_needs_revision；可通过 chunkId 限定长文分块草稿范围。"],
    ["neuro_mechanism 门禁", "CandidateStore neuro_mechanism validation", "mechanism_candidate 必须含 paperNoteIds、description、brainSystems/cognitiveFunctions、experimentalPhenomena、解释分层、evidenceRefs 和 confidence；术语不确定未标记 terminology_uncertain 时进入 mechanism_needs_revision。"],
    ["mechanism_mapping 门禁", "CandidateStore mechanism_mapping validation", "mechanism_mapping_candidate 必须含 neuroMechanismIds、computationalAbstraction、factLayer、inferenceLayer、overAnalogyRisk、engineeringImplication；高类比风险未标记 over_analogy_risk 时进入 mapping_needs_revision。"],
    ["algorithm_hypothesis 门禁", "CandidateStore algorithm_hypothesis validation", "hypothesis_candidate 必须含 mechanismMappingIds 或 neuroMechanismIds、hypothesis、baseline、expectedBenefit、expectedComputeCost，以及 dataset/metric/baseline/smokePlan 完整的 experimentPlan；否则进入 hypothesis_needs_revision。"],
    ["review_record prefilter", "CandidateStore review_record validation", "review_prefiltered 必须含 candidateIds、checklist、comments、requiredChanges、needsDecision；输出包含最终 decision 时进入 review_needs_revision。"],
    ["review 返工/拒绝闭环", "/api/teams/{teamId}/workflow-orchestration/transfers/{transferId}/decide", "decision=returned 会把候选移动到目标上游节点并设为目标修订状态；decision=rejected 会写 metadata.rejectionArchive、进入 rejection_archive，并从 candidate_graph 推进节点中隔离。"],
    ["steward_pack_draft 门禁", "CandidateStore review_record validation", "steward_pack_draft 必须含 candidateIds、targetDomain、sourceTrace、riskSummary、proposalPayload、ratingSuggestion 且 approvalRequired=true；包含 officialSync/applyNow/writeOfficialGraph 时进入 steward_needs_revision。"],
    ["steward_pack 待审入库", "/api/teams/{teamId}/workflow-orchestration/steward-packs/{candidateId}/knowledge-ingestion", "有效 steward_pack_draft 可提交到指定 knowledgeBaseId，创建 SourceArtifact、pending RefinementProposal 和可选 pending ratingSuggestion；候选进入 steward_pending_knowledge_review。"],
    ["steward_pack 审批门禁", "/api/teams/{teamId}/workflow-orchestration/steward-packs/{candidateId}/knowledge-ingestion/review", "只审批 steward_pending_knowledge_review；approved 创建正式 KnowledgeItem、迁移 proposal 级评分建议为 KnowledgeItem 级 pending 评级并进入 official_synced，rejected 退回 steward_needs_revision。"],
    ["知识入库状态总览", "/api/teams/{teamId}/workflow-orchestration/knowledge-ingestion/status", "只读聚合 source_collection、candidate_screening、steward_pack、knowledge_review、official_sync 状态；Teams 工作台已展示漏斗、actionItems 与 officialBoundary；不写正式知识、不写 RAG、不生成候选图快照。"],
    ["candidate_graph 预览", "CandidateStore candidate_graph snapshot", "POST candidate-graph 会从当前未归档候选重建 candidate_only 图谱，输出 nodes/edges/missingLinks/unreviewedNodes/archivedCandidateCount/officialBoundary；断链时 qualityStatus=broken_links。"],
    ["验证", "tests/test_data_processing_service.py + tests/test_data_processing_routes.py + tests/test_team_workflow_orchestration_service.py + tests/test_team_workflow_routes.py + TeamsRoute.layout.test.ts", "覆盖通用数据处理首切、ResearchStageRound 三阶段启动/续做/新一轮、source-collection run 启动、DataSearchPlan/query seed 契约、DataRecord 导入 source_manifest、Teams 知识搜集独立页/对话流契约、主路径、非 ownerAgent 不能写最终状态、本地模型任务包、输出校验、知识入库状态总览、模型证据链、资料质量筛选和 paper_note 分块计划前端契约。"],
  ],
};

const currentResearchRun = {
  title: "神经学启发神经网络算法 第一轮知识搜集",
  runId: "dprun-20260608011547474702-cd912a0c",
  searchPlanId: "searchplan-20260608011547-b004500d",
  status: "候选搜集与首轮提炼已完成，等待筛选/治理",
  updatedAt: "2026-06-08 09:30 CST",
  team: "ai科学研究团队 / research-team",
  flowState: [
    ["DataProcessingRun", "4 个 assignment 完成", "data_discovery、source_acquisition、content_extraction、source_quality 均已提交输出。"],
    ["DataRecord", "10 条 collected", "全部带 sourceRef、summary、qualitySignals、collectionTrace。"],
    ["source_manifest", "10 个 source_registered / source_quality_*", "全部为 candidate-only；可由 Source Quality Assessment Agent 写回 sourceQualityAssessment。"],
    ["mechanism_mapping", "1 个 mechanism_mapping_candidate", "服务层校验通过，qualityStatus=prefiltered。"],
    ["algorithm_hypothesis", "1 个 hypothesis_candidate", "PER-NN v0 草稿，含 baseline、成本、实验计划。"],
    ["candidate_graph", "1 个 candidate_graph_visible", "12 nodes / 1 edge / 6 missing links，qualityStatus=broken_links。"],
    ["knowledge_ingestion_status", "needs_review", "正式知识、RAG、正式图谱均未写入。"],
  ],
  sources: [
    ["Predictive coding in the visual cortex", "predictive_coding", "https://www.nature.com/articles/nn0199_79"],
    ["Regulation of synaptic efficacy by coincidence of postsynaptic APs and EPSPs", "STDP", "https://pure.mpg.de/pubman/faces/ViewItemFullPage.jsp?itemId=item_2095157_1"],
    ["Dendritic cortical microcircuits approximate the backpropagation algorithm", "dendritic_credit_assignment", "https://papers.nips.cc/paper/8089-dendritic-cortical-microcircuits-approximate-the-backpropagation-algorithm"],
    ["Prioritized memory access explains planning and hippocampal replay", "hippocampal_replay", "https://www.nature.com/articles/s41593-018-0232-z"],
    ["A solution to the learning dilemma for recurrent networks of spiking neurons", "spiking_recurrent_eligibility", "https://www.nature.com/articles/s41467-020-17236-y"],
    ["SuperSpike: Supervised Learning in Multilayer Spiking Neural Networks", "surrogate_gradient_spiking_learning", "https://pmc.ncbi.nlm.nih.gov/articles/PMC6118408/"],
    ["Metalearning and neuromodulation", "neuromodulation_metalearning", "https://www.sciencedirect.com/science/article/pii/S0893608002000448"],
    ["Random synaptic feedback weights support error backpropagation for deep learning", "feedback_alignment", "https://www.nature.com/articles/ncomms13276"],
    ["Predictive Coding Theories of Cortical Function", "predictive_coding_review", "https://arxiv.org/abs/2112.10048"],
    ["Neuroscience-Inspired Artificial Intelligence", "neuroscience_to_ai_review", "https://www.cell.com/neuron/abstract/S0896-6273(17)30509-3"],
  ],
  extractedDrafts: [
    ["local-model-output-20260608013004-519ff308", "神经机制到算法计算抽象候选映射 v0.1", "mechanism_mapping_candidate"],
    ["local-model-output-20260608013004-ee7b3a0e", "PER-NN 神经启发网络算法假设草稿 v0.1", "hypothesis_candidate"],
    ["candidate-graph-20260608013548-7a180786", "First source collection candidate graph preview", "candidate_graph_visible / broken_links"],
  ],
  officialBoundary: [
    "candidateStoreOfficialState=candidate_only_until_steward_approval",
    "formalKnowledgeItemCreated=false",
    "writesOfficialKnowledge=false",
    "writesOfficialRag=false",
    "writesOfficialGraph=false",
    "graphStatus=candidate_graph_preview_only",
  ],
  nextActions: [
    "Source Quality Assessment Agent 对 source_manifest 做可靠性、可访问性、相关性和抽取风险筛选。",
    "内容抽取 Agent 为 source_quality_approved 来源补 page/citation anchors；Paper Note Extraction Agent 先生成 paperNoteChunkPlan，再按 chunkId 生成 paper_note 草稿。",
    "候选图谱需要修复 missing links；当前 status actionItems 指向 repair_candidate_graph_links 与 run_review_prefilter。",
    "知识治理 Agent 只能在 review/steward pack 完成后生成待审入库包，不能直接正式入库。",
  ],
};

const knowledgeNodeRunbook = {
  "01": {
    state: "source_registered",
    agent: "Source Intake Agent",
    agentStatus: "可复用通用 data-processing assignment / source-extraction / source-quality 后端已接入；Teams 资料搜集执行台、候选资料筛选台、科研总览控制台、KV 缓存对话轨迹、启动复用反馈、metadata-only 搜索执行闭环、高价值信息层、中文控制台、默认层去说明化、步骤卡主操作入口、右侧当前步骤 Agent 配置、资料筛选页内反馈、资料筛选 Agent 批量执行、候选库可视化二级索引、知识搜集阶段子页控制台、资料筛选 Agent 复审入口、一键排队首批后台搜索、资料搜集当前动作和已收集资料分层、搜集结果状态徽标完整显示、搜集结果 DOI/网页/本地文件来源可溯源、五阶段完整列表、来源类型过滤、阶段结果/Agent过程双页、阶段输入输出交接、Agent 执行过程流水、结果分页、实体可读工作台、阶段卡降噪、阶段协调显式启动已接入",
    features: ["ResearchStageRound 建立", "科研控制台一键进入知识搜集", "总览页只显示三阶段主操作", "知识搜集状态驱动按钮", "知识搜集中文展示映射", "默认层去说明化", "右侧主操作唯一化", "资料筛选入口常驻", "步骤卡主操作入口", "右侧当前步骤 Agent 配置", "步骤卡二级索引", "阶段子页控制台", "阶段结果/Agent过程双页", "实体可读工作台", "阶段卡降噪", "阶段输入输出交接", "Agent 执行过程流水", "五阶段结果分页", "资料搜集当前动作", "已收集资料结果区", "搜集结果来源溯源", "搜集结果状态徽标", "资料筛选 Agent 复审", "候选库可视化面板", "资料筛选页内详情", "资料筛选展开高亮反馈", "资料筛选 Agent 批量执行", "source-quality/assess-batch", "source-quality force 重筛", "新一轮搜集入口", "active 知识搜集轮次复用反馈", "一键排队首批搜索", "全局运行态知识搜集优先", "步骤功能 Agent 聚焦", "五阶段完整列表", "来源类型过滤", "阶段协调显式启动", "DataProcessingRun 建立", "DataProcessingRun reviewing 收口", "DataSearchPlan/querySeeds 搜索计划", "KV/prompt cache 启动门禁", "稳定前缀/动态增量契约", "CollectionAssignment 资料搜集任务", "assignedQueries 角色分配", "promptCachePartition 角色分区", "Teams 启动搜集批次", "Teams 查看 run/assignment/query/KV 状态", "Teams 高价值摘要层", "Teams 搜索下一批", "Crossref 元数据搜索执行器", "搜索执行事件进入搜集对话流", "DataRecord 通用记录", "DataRecord 自动导入 source_manifest", "metadata-only 下载边界", "手工 CollectionOutput 回写", "本地资料登记", "source_manifest 写入", "文件路径/页码/来源可信度记录", "本地 PDF sha256/pageAnchors/excerpt 抽取", "sourceQualityAssessment 筛选", "可选 research_knowledge_query_tool 查重"],
    tools: ["/api/teams/{teamId}/workflow-orchestration/stage-rounds/status", "/api/teams/{teamId}/workflow-orchestration/stage-rounds/start", "/api/teams/{teamId}/workflow-orchestration/stage-rounds/{stageRoundId}/coordination/retry", "/api/teams/{teamId}/workflow-orchestration/stage-rounds/{stageRoundId}/memory-record/retry", "/api/teams/{teamId}/workflow-orchestration/source-collection-runs", "/api/teams/{teamId}/workflow-orchestration/source-collection-runs/{runId}/search/execute", "/api/data-processing/runs", "/api/data-processing/runs/{runId}/collection-assignments", "/api/data-processing/runs/{runId}/collection-assignments/{assignmentId}/outputs", "/api/teams/{teamId}/workflow-orchestration/data-processing/runs/{runId}/records/{recordId}/source-candidate", "/api/teams/{teamId}/workflow-orchestration/official-model-evidence/status", "research_knowledge_query_tool", "/api/teams/{teamId}/workflow-orchestration/candidates/{candidateId}/source-extraction"],
    localModelUse: "本地 9B 模型适合做标题/摘要/片段初筛，输出 relevanceScore、topicTags、excludeReason；调用证据进入 official_model_evidence 状态面板，不直接决定正式纳入。",
    humanGate: "确认资料允许分析、来源可信度和是否纳入本轮。",
    gap: "科研总览控制台、资料搜集阶段轮次、资料搜集批次启动、active 轮次复用反馈、DataSearchPlan/query seed 契约、KV/prompt cache 启动门禁、缓存分区对话轨迹、通用资料搜集 assignment/output、Teams 高价值摘要层、metadata-only 搜索执行器、DataRecord 到 source_manifest 导入桥和 source-quality 筛选台已接入；全文网页/PDF 下载、长 PDF 自动分批、章节识别和非 PDF 资料解析仍待补。",
    entry: "用户提供 PDF、论文、赛题或补充资料；文件可在挑战杯工作区定位。",
    operation: "用户在 ai科学研究团队科研控制台点击知识搜集主按钮，stage-rounds/start 创建或续用 ResearchStageRound，并复用 source-collection run 建立 DataProcessingRun；新建知识搜集轮次会立即调用后台 source collection 搜索入口，把第一批 metadata-only 搜索排队并在响应中返回 sourceCollectionSearchExecution.activeWorkRun。总览页只提示当前阶段、下一步和阶段详情入口，不默认展示模型证据、路径、query、KV 分区或校验详情。知识搜集卡会显示未开始、待继续搜索、搜索中、待筛选、可进入实验或等待回写，并显示当前批次、待处理、候选和查询数；主按钮按状态变为开始知识搜集、搜索下一批、进入资料筛选或进入搜集工作台，旁边可点“新一轮搜集”强制补充一轮。如果已有 active knowledge_collection，接口返回 continuedSourceRunRef、run 和 assignments，知识搜集阶段页直接显示 runId、记录数、待回写任务数和搜索执行状态。资料搜集 run 列表由 /api/data-processing/runs 使用 teamId + startedFrom 服务端过滤，不再先取全局最近批次再本地筛选，避免其它任务把当前科研批次挤出 UI。阶段启动只记录显式协商契约，不会自动打开团队群聊；需要协商时再由用户显式启动 coordination/retry。系统基于 topic/goal/scope/querySeeds 生成 searchPlan、queries、roleAssignmentInputs 和 resultWritebackContract，让 data_discovery/source_acquisition/content_extraction/source_quality 等功能 Agent 领取带 assignedQueries 的 CollectionAssignment。知识搜集页首屏作为流程控制台：左上角显示正在团队搜索、待继续搜索、待筛选或失败；后台搜索 accepted 后 activeWorkRun 会合成到控制台和对话流，AppShell 顶部运行态在知识搜集与团队群聊并发时优先显示知识搜集，资料搜集卡保持进行中直到 runStatus 进入 reviewing 或终态。资料搜集、资料筛选、候选入库、候选图谱、共享记忆前审五张步骤卡只展示状态、关键数量和主按钮；点击卡片本体切换页内子页，底部只显示当前阶段内容，右侧保留当前阶段主操作、关键数量和当前步骤细节，并在详情底部展示该步骤功能 Agent 的职责、Agent 名称、模型、状态和配置入口。当前阶段子页拆成“结果”和“过程”两个视图：结果页只展示该阶段产物并按 8 条分页，过程页把 Agent 的输入、输出、下一步、状态和证据位置按时间线展示；阶段标题区同步显示本阶段输入、输出和下一步，帮助用户理解从前一步到后一步传递了什么。五个子页统一提供来源类型过滤：全部、PDF、论文网页/DOI、数据集、本地文件、缺少来源；过滤只改变当前页结果列表，不改变候选状态。资料搜集子页左侧主内容拆成当前搜集动作和已收集资料：当前动作只保留正在执行或最近完成的一条，已收集资料集中展示进入候选仓库的资料清单，让用户一眼区分流程和结果；每条结果必须显示可溯源入口：DOI 以 DOI 标签和 doi.org 链接展示，网页以可点击来源展示，本地资料显示文件路径，缺少 DOI/链接/路径时标为缺少来源；候选资料状态以横向徽标显示，避免“需补资料”“已通过”等中文状态在窄列中只露出单字。资料搜集步骤聚焦 data_discovery、source_acquisition、content_extraction，不把协调人显示成执行 Agent；Agent 配置入口复用 Agent 管理页，不复制第二套配置表。点击资料筛选会调用 source-quality/assess-batch，由资料质量评估 Agent 批量处理待筛 source_manifest；当资料筛选已经完成时，主按钮变为 Agent 重新筛选，调用同一接口并传 force=true 让 Agent 重新审查已筛候选。资料筛选详情页展示完整 source_manifest 候选列表，不再限制为少量预览，同时保留查看结果入口和 Agent 批量审查按钮。点击候选入库只打开可视化候选库，不直接打开 candidate_store/index.json；候选入库子页展示本轮完整候选资料、来源追溯和筛选状态，底层 JSON 留在更多证据文件作为维护入口。候选图谱子页按来源过滤裁剪节点/边，并补充节点列表；共享记忆前审子页展示可进入前审的候选资料和前审问题。人工通过筛选、退回补资料和生成分块保留为覆盖修正入口；五个步骤按进行中、已完成、失败、未进行、待处理显示为不同颜色。processing/reviewing/open/planned、Agent 角色、DataRecord/source_manifest/Query seeds 等内部字段通过中文展示映射转成业务表述；assignment、query、KV 分区、存储路径、更多证据文件和手工回写收进可展开详情，默认层不再放解释性小字。用户可点击“搜索下一批”，通过 source-collection-runs/{runId}/search/execute 继续执行 metadata-only Crossref 查询，生成 search.executed、storage.data_record_written、storage.source_manifest_imported 等对话式事件，把结果写成 DataRecord 并幂等导入 source_manifest 候选；执行台仍支持手工回写一条 CollectionOutput。所有采集 assignment 关闭且已有资料记录后，通用 DataProcessingRun 收口到 reviewing，表示后台搜索已停止、下一步进入资料筛选。资料筛选批量执行/复审复用 source-quality/assess 写入 sourceQualityAssessment/sourceQualityAssessments，并标记通过筛选、退回补资料或拒绝。对本地 PDF 运行 source-extraction，计算 sha256、生成 pageAnchors/excerpt，不改写原文，不自动混入联网全文。",
    exit: "每个知识搜集轮次有 stageRoundId、roundNumber、teamMemoryRecord、coordinationContract.startResult(manual_only 或显式启动结果)、显式协调后的可选 coordinationRoomId/coordinationRoundId、sourceRunIds、dataSearchPlanRef、planned queries、assignedQueries 和 resultWritebackContract；每个资料项先有 DataRecord/sourceRef/rawLocation/title/qualitySignals/collectionTrace，再有 source_manifest 的 id、path、type、allowedForAnalysis、sha256、pageScope、sourceExtraction.pageAnchors 和 sourceQualityAssessment。",
    fallback: "资料不足、路径缺失、来源不明、权限不清、抽取失败或解析器不可用时，assignment 标记 returned/partial，挑战杯候选停在 source_needs_confirmation；显式启动群聊时若群聊缺失、忙碌或没有可发言成员，只把失败原因写入 coordinationContract，不影响资料搜集主流程。",
  },
  "02": {
    state: "paper_note_draft",
    agent: "Paper Note Extraction Agent",
    agentStatus: "自动草稿桥已接入 / 长文 chunk plan 已接入",
    features: ["PDF/资料摘录", "paperNoteChunkPlan", "paper_note 候选 JSON 生成", "citation anchors", "uncertainty 字段", "chunkId 草稿追踪"],
    tools: ["research_knowledge_query_tool", "sourceExtraction.excerpt", "本地研究模型 task/output API", "/api/teams/{teamId}/workflow-orchestration/official-model-evidence/status", "/api/teams/{teamId}/workflow-orchestration/paper-note-chunks/status", "/api/teams/{teamId}/workflow-orchestration/candidates/{candidateId}/paper-note-chunks/plan", "/api/teams/{teamId}/workflow-orchestration/candidates/{candidateId}/paper-note-draft"],
    localModelUse: "本地 9B 模型适合按章节或 chunk 生成 paper_note 草稿；32k 内保留 18k-22k 原文证据和输出预留；invoke 会自动登记模型调用证据。",
    humanGate: "必要时确认摘要是否保守、是否遗漏关键章节。",
    gap: "paper_note schema 与页码引用校验已接入 CandidateStore；本地 PDF 页码摘录已可由 source-extraction 提供，并已接入自动 paper_note 草稿桥；长文 page_anchor_window 分块计划已接入，多个 chunk draft 的合并/去重仍待接。",
    entry: "资料已登记且 allowedForAnalysis=true。",
    operation: "先对已完成 sourceExtraction 的 source_manifest 生成 paperNoteChunkPlan；长文可按 chunkId 逐块调用 paper-note-draft，抽取 summary、keyFindings、methods、limitations 和 citation anchors。",
    exit: "每个 chunk seed 能回指 sourceFiles、页码或章节；paper_note 关键发现能回指 sourceFiles/page anchors；uncertainty 不为空时显式保留。",
    fallback: "缺页码、缺来源或摘要过度推断时退回 paper_note_needs_revision。",
  },
  "03": {
    state: "mechanism_candidate",
    agent: "Neuro Mechanism Extraction Agent",
    agentStatus: "需要专门神经机制分析 Agent 或 research_deep 绑定该职责",
    features: ["神经机制抽取", "实验现象/作者解释/项目理解分离", "evidenceRefs", "confidence"],
    tools: ["research_knowledge_query_tool", "knowledge_rag_retrieve_tool（只查正式背景知识）"],
    localModelUse: "本地 9B 模型适合抽取 neuro_mechanism 候选和风险标记；弱证据必须写 weak_evidence。",
    humanGate: "遇到神经术语不确定或证据弱时进入领域复核门禁。",
    gap: "neuro_mechanism 最小 schema 与术语风险门禁已接入 CandidateStore；脑区/认知功能词表和证据强度评分规则仍待补。",
    entry: "paper_note 至少有一个可追溯 keyFinding。",
    operation: "提取 neuro_mechanism，把实验现象、作者解释和本项目理解分开。",
    exit: "每个 mechanism 有 evidenceRefs、confidence、brainSystems/cognitiveFunctions 或明确 unknown。",
    fallback: "证据弱或术语不确定时必须标记 weak_evidence / terminology_uncertain；缺失风险标记时进入 mechanism_needs_revision，不进入机制映射。",
  },
  "04": {
    state: "mechanism_mapping_candidate",
    agent: "Mechanism Mapping Agent",
    agentStatus: "建议新增专门 Agent；也可先由 Neuro Mechanism Extraction Agent + Algorithm Hypothesis Agent 串联承担",
    features: ["机制到计算抽象映射", "fact/inference 分层", "over_analogy 风险标记", "映射链路 links"],
    tools: ["knowledge_rag_retrieve_tool", "research_knowledge_query_tool"],
    localModelUse: "本地 9B 模型适合做多方案机制映射；必须拆分 factLayer、inferenceLayer 和 overAnalogyRisk。",
    humanGate: "确认映射没有把类比包装成论文事实。",
    gap: "mechanism_mapping 最小输出契约与类比风险门禁已接入 CandidateStore；跨候选断链检测和独立 schema 文件仍待补。",
    entry: "neuro_mechanism 已有证据链和不确定性说明。",
    operation: "映射到注意力、记忆、反馈、稀疏激活、动态路由等计算抽象。",
    exit: "每个映射标出 fact、inference 和 over_analogy 风险。",
    fallback: "缺 factLayer/inferenceLayer/engineeringImplication，或高类比风险未标记 over_analogy_risk 时进入 mapping_needs_revision，不进入 algorithm_hypothesis。",
  },
  "05": {
    state: "hypothesis_candidate",
    agent: "Algorithm Hypothesis Agent",
    agentStatus: "需要算法假设设计 Agent；可从 research_themes / research_card 扩展",
    features: ["algorithm_hypothesis 生成", "baseline/expectedBenefit/cost", "experimentPlan 占位", "可测性约束"],
    tools: ["knowledge_rag_retrieve_tool", "research_knowledge_query_tool"],
    localModelUse: "本地 9B 模型适合生成 algorithm_hypothesis 草稿；缺 baseline 或 experimentPlan 时不能进入审稿。",
    humanGate: "确认假设是否值得进入审稿，且 experimentPlan 足够可评审。",
    gap: "algorithm_hypothesis 最小输出契约和 experimentPlan 门禁已接入 CandidateStore；真实训练 runner 和 research card 自动生成仍待接。",
    entry: "至少一个机制映射可转成模型结构、训练目标或推理过程变化。",
    operation: "生成 algorithm_hypothesis，保留 baseline、expectedBenefit、cost 和 experimentPlan。",
    exit: "experimentPlan 字段存在；即使未实现，也有 dataset、metric、baseline 和 smokePlan 占位。",
    fallback: "缺上游 mechanism 引用、hypothesis、baseline、expectedBenefit、expectedComputeCost，或 experimentPlan 缺 dataset/metric/baseline/smokePlan 时退回 hypothesis_needs_revision。",
  },
  "06": {
    state: "review_ready",
    agent: "Evidence Review Agent",
    agentStatus: "review prefilter 与返工/拒绝 transfer 闭环已接入；最终裁决仍复用通用转移裁决",
    features: ["证据审查", "类比风险审查", "可测性/成本审查", "review_record 生成", "返工转移", "拒绝归档"],
    tools: ["research_knowledge_query_tool", "knowledge_rag_retrieve_tool"],
    localModelUse: "本地 9B 模型只做 review prefilter，产出 riskFlags、requiredChanges 和 needsDecision，不写最终 review.decision。",
    humanGate: "高争议候选、拒绝重要候选或放行弱证据候选时进入审核门禁确认。",
    gap: "rejectionArchive 规则和 returned/rejected 转移已接入；后续可补 Evidence Review Agent 专用 decision API 和 riskFlags 枚举。",
    entry: "paper_note、neuro_mechanism、algorithm_hypothesis 字段完整。",
    operation: "证据复核 Agent 检查证据、类比、可测性、成本和重复假设。",
    exit: "review_record 候选含 candidateIds、checklist、comments、requiredChanges、needsDecision，状态为 review_prefiltered。",
    fallback: "缺 checklist/comments/needsDecision，或本地模型写最终 decision 时进入 review_needs_revision；审稿要求返工时 Research Coordination Agent 通过 transfer returned 回到最小上游节点；明确拒绝时 transfer rejected 进入 rejection_archive。",
  },
  "07": {
    state: "steward_pending_knowledge_review",
    agent: "Knowledge Steward Agent / agent-knowledge-steward",
    agentStatus: "后端草稿包门禁、Team Knowledge 待审入库桥、审批门禁和入库状态总览已接入",
    features: ["sourceTrace 校验", "proposalPayload", "ratingSuggestion", "approvalRequired=true", "SourceArtifact", "pending RefinementProposal", "KnowledgeItem rating suggestion migration", "knowledge_ingestion_status", "officialResearchGraph", "officialSyncRecord", "official write 禁止项"],
    tools: ["knowledge_governance_tasks_tool", "knowledge_steward_workbench_tool", "knowledge_steward_recommendations_tool", "knowledge_proposal_tool", "knowledge_ingestion_tool", "knowledge_rating_suggestion_tool", "/api/teams/{teamId}/workflow-orchestration/knowledge-ingestion/status"],
    localModelUse: "本地 9B 模型只能生成 steward_pack_draft 草稿，正式建议仍由 Knowledge Steward Agent 检查；禁止在输出中请求正式写入。",
    humanGate: "必须经 Knowledge Steward Agent / Ingestion Approval Gate 确认，不能由科研执行 Agent 或本地模型直接入库。",
    gap: "pending ratingSuggestion 到正式 KnowledgeItem rating review 的承接已接入；正式边已写入 officialResearchGraph；status API 和 Teams 前端状态漏斗已能显示 pending/ready/actionItems。后续可补按候选/知识库筛选。",
    entry: "review_record 或候选图谱已给出可追溯 candidateIds，且具备目标知识域。",
    operation: "生成带 sourceTrace、riskSummary、proposalPayload、ratingSuggestion、approvalRequired=true 的 CandidateStore 草稿包，并可提交到指定 knowledgeBaseId 的待审入库队列；status API 汇总 pendingProposalCount、formalKnowledgeItemCount、actionItems 和 officialBoundary。",
    exit: "合格草稿提交后进入 steward_pending_knowledge_review；批准后进入 official_synced、记录 officialSyncRecord 和 officialResearchGraph，并创建 KnowledgeItem 级 pending ratingSuggestion；status=ready 表示入库链路已跑通。",
    fallback: "缺必填治理字段、approvalRequired 非 true，或包含 officialSync/applyNow/writeOfficialGraph 时返回 steward_needs_revision。",
  },
  "08": {
    state: "candidate_graph_visible",
    agent: "Candidate Graph Preview Agent",
    agentStatus: "后端/API 已可生成候选图谱快照；Teams 工作台科研流程面板已接入首版 SVG 可视化读取",
    features: ["candidate_graph 候选快照生成", "候选节点/边预览 payload", "断链报告", "未审节点清单", "候选/正式边界标识", "Teams SVG 候选图谱面板", "手动刷新 candidate_only 快照"],
    tools: ["/api/teams/{teamId}/workflow-orchestration/candidate-graph", "CandidateStore", "TeamsRoute 候选图谱渲染"],
    humanGate: "确认候选图谱只作预览，不作为正式知识证据使用。",
    gap: "独立 candidate_graph.json 导出仍待接；首版前端直接读取 CandidateStore graph payload。",
    entry: "CandidateStore 中存在 paper_note / neuro_mechanism / mechanism_mapping / algorithm_hypothesis 等候选。",
    operation: "从 paperNoteIds、neuroMechanismIds、mechanismMappingIds 重建候选链路；Teams 面板可请求最新 candidate_graph 并渲染 evidence -> candidate 的阅读向箭头。",
    exit: "candidate_graph 候选快照能列出 nodes、edges、missingLinks、unreviewedNodes 和 officialBoundary，并能在 Teams 科研流程面板可视化查看。",
    fallback: "候选链接指向不存在对象时输出 missingLinks，并把质量状态标记为 broken_links，不允许进入正式同步。",
  },
  "09": {
    state: "official_synced",
    agent: "Ingestion Approval Gate + Knowledge Platform",
    agentStatus: "授权审批门禁已接入 Team Knowledge review/apply、KnowledgeItem metadata patch 和 officialBoundary 状态聚合",
    features: ["正式审核确认", "正式 KnowledgeItem 创建/同步", "KnowledgeItem rating review", "officialResearchGraph", "RAG 可检索", "official_sync_record", "Memory Graph 可见", "officialBoundary status"],
    tools: ["knowledge_query_tool", "knowledge_rag_retrieve_tool", "Team Knowledge 审核/应用流程（平台能力）", "/api/teams/{teamId}/workflow-orchestration/knowledge-ingestion/status"],
    humanGate: "必须通过授权审批门禁批准 ingestion pack。",
    gap: "ratingSuggestion 自动迁移到 KnowledgeItem 待审评级已接入；正式边已接入 officialResearchGraph；status API 与 Teams 面板已区分 candidate_graph_preview_only 与 official_research_trace_synced。后续可补正式图谱详情筛选。",
    entry: "授权审批门禁已批准 pending RefinementProposal。",
    operation: "复用 Team Knowledge review/apply 创建 KnowledgeItem；sourceTrace/candidateIds 被翻译为 officialResearchGraph 正式边；status API 返回 writesOfficialKnowledge=false/true、writesOfficialRag=false、writesOfficialGraph=false/true。",
    exit: "knowledgeItemIds、ratingSuggestionMigration、officialResearchGraph、ragStatus、graphStatus、reviewedByAgentId 和 officialSyncRecord 均已记录；status=ready 时 actionItems 只剩 operational 提示。",
    fallback: "未批准时停留在 candidate_graph_visible，不进入正式知识库。",
  },
};

const css = `
:root {
  color-scheme: light;
  --ink: #1f2728;
  --muted: #66706c;
  --paper: #f7f4ed;
  --panel: #fffdf7;
  --line: #d7d0c2;
  --line-strong: #a59c8a;
  --green: #246b54;
  --green-soft: #dceee5;
  --amber: #b98122;
  --amber-soft: #f3e1bd;
  --red: #b5483c;
  --red-soft: #f3d5ce;
  --blue: #315f7d;
  --blue-soft: #d9e8ee;
  --violet: #65518b;
  --violet-soft: #e7e0f0;
  --shadow: 0 18px 48px rgba(68, 57, 39, 0.14);
  --mono: "Cascadia Mono", "SFMono-Regular", Consolas, monospace;
  --sans: "Aptos", "Segoe UI", "Microsoft YaHei UI", sans-serif;
  --serif: "Georgia", "SimSun", serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  color: var(--ink);
  font-family: var(--sans);
  background:
    linear-gradient(90deg, rgba(49, 95, 125, 0.045) 1px, transparent 1px),
    linear-gradient(180deg, rgba(49, 95, 125, 0.035) 1px, transparent 1px),
    var(--paper);
  background-size: 34px 34px;
}
a { color: inherit; }
.shell { width: min(1500px, calc(100vw - 34px)); margin: 0 auto; padding: 26px 0 46px; }
.top {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr);
  gap: 16px;
  margin-bottom: 16px;
}
.hero, .panel, .node-card, .plan-card, .flow-cell, .nav-rail, .status-panel {
  background: rgba(255, 253, 247, 0.95);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
}
.hero { min-height: 250px; padding: 28px; display: flex; flex-direction: column; justify-content: space-between; }
.kicker { color: var(--green); font: 12px var(--mono); text-transform: uppercase; }
h1 { margin: 8px 0 14px; max-width: 980px; font: 700 clamp(36px, 5vw, 70px)/1.02 var(--serif); letter-spacing: 0; }
.subtitle { max-width: 900px; color: var(--muted); font-size: 17px; line-height: 1.75; }
.tag-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.tag { display: inline-block; padding: 4px 8px; border: 1px solid var(--line); background: #f9f4e9; color: var(--muted); font: 11px var(--mono); }
.tag.done { color: #174b39; background: var(--green-soft); border-color: #9bc3ad; }
.tag.draft { color: #755013; background: var(--amber-soft); border-color: #d1ab68; }
.tag.pending { color: #7c332b; background: var(--red-soft); border-color: #d69a91; }
.panel { padding: 18px; }
.fact-grid { display: grid; gap: 10px; }
.fact { display: grid; grid-template-columns: 110px 1fr; gap: 10px; padding: 11px 12px; border: 1px solid var(--line); background: #fbf7ee; }
.fact b, .label { color: var(--muted); font: 600 12px var(--mono); }
.fact span { font-size: 13px; line-height: 1.55; }
.section { margin-top: 16px; padding: 20px; background: rgba(255, 253, 247, 0.94); border: 1px solid var(--line); box-shadow: var(--shadow); }
.section-head { display: flex; justify-content: space-between; align-items: end; gap: 18px; padding-bottom: 13px; margin-bottom: 16px; border-bottom: 1px solid var(--line); }
h2 { margin: 0; font: 700 29px/1.15 var(--serif); }
.hint { max-width: 680px; margin: 0; color: var(--muted); font-size: 13px; line-height: 1.6; }
.node-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.node-card { min-height: 172px; padding: 14px; text-decoration: none; border-left: 5px solid var(--green); transition: transform 160ms ease, border-color 160ms ease; }
.node-card:hover { transform: translateY(-2px); border-color: var(--line-strong); }
.node-card:nth-child(2n) { border-left-color: var(--blue); }
.node-card:nth-child(3n) { border-left-color: var(--amber); }
.node-card:nth-child(5n) { border-left-color: var(--violet); }
.num { display: inline-grid; place-items: center; width: 34px; height: 28px; margin-bottom: 12px; color: #fff; background: var(--green); font: 12px var(--mono); }
.node-card h3 { margin: 0 0 8px; font-size: 16px; line-height: 1.35; }
.node-card p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.6; }
.map-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; }
.flow-cell { min-height: 112px; padding: 13px; }
.flow-cell strong { display: block; margin-bottom: 6px; color: var(--green); font-size: 14px; }
.flow-cell span { color: var(--muted); font-size: 12px; line-height: 1.5; }
.flow-board {
  position: relative;
  height: min(52vh, 520px);
  min-height: 420px;
  overflow: auto;
  background:
    linear-gradient(90deg, rgba(36, 107, 84, 0.06) 1px, transparent 1px),
    linear-gradient(180deg, rgba(36, 107, 84, 0.045) 1px, transparent 1px),
    #fbfaf5;
  background-size: 28px 28px;
  border: 1px solid var(--line);
  cursor: grab;
  overscroll-behavior: contain;
  scrollbar-color: var(--line-strong) #f1eadf;
  scrollbar-width: thin;
}
.flow-board.dragging {
  cursor: grabbing;
  user-select: none;
}
.flow-board-shell {
  position: relative;
}
.flow-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
  margin-bottom: 8px;
}
.flow-toolbar button {
  min-width: 36px;
  height: 32px;
  padding: 0 10px;
  color: var(--ink);
  background: #fbf7ee;
  border: 1px solid var(--line);
  font: 12px var(--mono);
  cursor: pointer;
}
.flow-toolbar button:hover {
  border-color: var(--line-strong);
  background: #fffdf7;
}
.zoom-readout {
  min-width: 58px;
  padding: 7px 9px;
  color: var(--green);
  background: #eef6f1;
  border: 1px solid #a9cbb7;
  font: 12px var(--mono);
  text-align: center;
}
.flow-stage {
  position: relative;
  width: 1900px;
  height: 640px;
}
.flow-graph {
  position: relative;
  width: 1900px;
  height: 640px;
  min-height: 640px;
  transform: scale(var(--zoom, 1));
  transform-origin: 0 0;
}
.graph-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
.graph-svg > path {
  fill: none;
  stroke: rgba(49, 95, 125, 0.68);
  stroke-width: 4;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.graph-svg > path.dashed {
  stroke: rgba(185, 129, 34, 0.8);
  stroke-dasharray: 12 10;
}
.graph-node {
  position: absolute;
  left: var(--x);
  top: var(--y);
  width: 220px;
  min-height: 72px;
  transform: translate(-50%, -50%);
  padding: 12px 14px;
  color: var(--ink);
  text-decoration: none;
  background: rgba(255, 253, 247, 0.97);
  border: 1px solid var(--line);
  border-left: 5px solid var(--green);
  box-shadow: 0 12px 30px rgba(68, 57, 39, 0.13);
  transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
}
.graph-node:hover {
  transform: translate(-50%, -52%);
  border-color: var(--line-strong);
  box-shadow: 0 18px 38px rgba(68, 57, 39, 0.18);
}
.graph-node .graph-id {
  display: inline-grid;
  place-items: center;
  width: 32px;
  height: 24px;
  margin-right: 9px;
  color: #fff;
  background: var(--green);
  font: 11px var(--mono);
  vertical-align: middle;
}
.graph-node h3 {
  display: inline;
  margin: 0;
  font-size: 17px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.graph-node.draft { border-left-color: var(--amber); }
.graph-node.pending { border-left-color: var(--red); }
.graph-node.maintenance {
  width: 250px;
  border-left-color: var(--violet);
  background: #f7f2fb;
}
.graph-lane {
  position: absolute;
  left: 24px;
  padding: 5px 8px;
  color: var(--muted);
  background: rgba(255, 253, 247, 0.82);
  border: 1px solid var(--line);
  font: 11px var(--mono);
}
.graph-lane.top-lane { top: 36px; }
.graph-lane.mid-lane { top: 260px; }
.graph-lane.bottom-lane { top: 640px; }
.workbench-grid .graph-lane {
  left: 42px;
  z-index: 2;
  color: #21423c;
  background: rgba(255, 255, 252, 0.92);
  border-color: rgba(46, 63, 61, 0.18);
}
.workbench-grid .graph-lane.top-lane { top: 44px; }
.workbench-grid .graph-lane.mid-lane { top: 196px; }
.workbench-grid .graph-lane.bottom-lane { top: 354px; }
.compact-map .graph-lane.top-lane { top: 50px; }
.compact-map .graph-lane.mid-lane { top: 220px; }
.compact-map .graph-lane.bottom-lane { top: 384px; }
.graph-lane-band {
  position: absolute;
  left: 24px;
  right: 24px;
  height: 128px;
  background: rgba(235, 244, 240, 0.62);
  border: 1px solid rgba(46, 63, 61, 0.10);
  pointer-events: none;
}
.graph-lane-band.top-lane { top: 38px; }
.graph-lane-band.mid-lane { top: 190px; }
.graph-lane-band.bottom-lane { top: 348px; }
.compact-map .graph-lane-band.top-lane { top: 72px; height: 126px; }
.compact-map .graph-lane-band.mid-lane { top: 242px; height: 126px; }
.compact-map .graph-lane-band.bottom-lane { top: 404px; height: 176px; }
.graph-lane-band.bottom-lane {
  background: rgba(250, 243, 231, 0.72);
}
.graph-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 8px;
}
.legend-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  color: var(--muted);
  background: #fbfdf9;
  border: 1px solid var(--line);
  font: 11px var(--mono);
}
.legend-line {
  width: 28px;
  height: 0;
  border-top: 3px solid rgba(49, 95, 125, 0.68);
}
.legend-line.dashed { border-top-style: dashed; border-top-color: rgba(185, 129, 34, 0.8); }
.page-layout { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 14px; align-items: start; }
.nav-rail { position: sticky; top: 14px; padding: 12px; max-height: calc(100vh - 28px); overflow: auto; }
.nav-rail a { display: grid; grid-template-columns: 38px 1fr; gap: 8px; padding: 9px; margin-bottom: 6px; text-decoration: none; border: 1px solid transparent; }
.nav-rail a.active, .nav-rail a:hover { background: #fbf7ee; border-color: var(--line); }
.nav-rail .mini { color: #fff; background: var(--green); font: 11px var(--mono); display: inline-grid; place-items: center; height: 24px; }
.nav-rail span:last-child { font-size: 12px; line-height: 1.35; }
.plan-hero { padding: 24px; background: rgba(255,253,247,0.95); border: 1px solid var(--line); box-shadow: var(--shadow); }
.plan-hero h1 { font-size: clamp(34px, 4.6vw, 62px); }
.diagram { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 14px; }
.diagram .flow-cell { box-shadow: none; background: #fbfaf5; }
.plan-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }
.plan-card { padding: 16px; box-shadow: none; min-height: 170px; }
.plan-card h2 { font-size: 22px; margin-bottom: 9px; }
.plan-card ul { margin: 0; padding-left: 18px; color: var(--muted); font-size: 13px; line-height: 1.75; }
.status-panel { padding: 14px; box-shadow: none; }
.status-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.status-item { padding: 11px; background: #fbf7ee; border: 1px solid var(--line); }
.status-item b { display: block; color: var(--green); font: 12px var(--mono); margin-bottom: 5px; }
.status-item span { color: var(--muted); font-size: 12px; line-height: 1.5; }
.runbook-grid { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 12px; }
.state-ladder { display: grid; gap: 7px; }
.state-row {
  display: grid;
  grid-template-columns: 190px 150px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  padding: 10px;
  background: #fbf7ee;
  border: 1px solid var(--line);
}
.state-row b { color: var(--green); font: 12px var(--mono); }
.state-row strong { font-size: 13px; }
.state-row span { color: var(--muted); font-size: 12px; line-height: 1.5; }
.artifact-table { display: grid; gap: 7px; }
.artifact-row {
  display: grid;
  grid-template-columns: 220px 120px minmax(0, 1fr);
  gap: 8px;
  padding: 10px;
  background: #fbfaf5;
  border: 1px solid var(--line);
}
.artifact-row code { color: var(--green); font: 12px var(--mono); overflow-wrap: anywhere; }
.artifact-row b { font-size: 12px; }
.artifact-row span { color: var(--muted); font-size: 12px; line-height: 1.5; }
.gate-grid, .role-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.gate-card, .role-card {
  padding: 12px;
  min-height: 120px;
  background: #fbfaf5;
  border: 1px solid var(--line);
}
.gate-card h3, .role-card h3 { margin: 0 0 8px; font-size: 15px; }
.gate-card p, .role-card p { margin: 0 0 6px; color: var(--muted); font-size: 12px; line-height: 1.55; }
.agent-matrix { display: grid; gap: 8px; }
.agent-row, .feature-row, .alignment-row, .transfer-row {
  display: grid;
  gap: 8px;
  padding: 11px;
  background: #fbfaf5;
  border: 1px solid var(--line);
}
.agent-row { grid-template-columns: 54px 150px 170px minmax(0, 1fr) minmax(0, 1fr); }
.feature-row { grid-template-columns: 190px minmax(0, 1fr) 88px; }
.alignment-row { grid-template-columns: 170px minmax(0, 1fr) 110px minmax(0, 1fr); }
.transfer-row { grid-template-columns: 150px minmax(0, 1fr) 170px 180px minmax(0, 1fr); }
.blueprint-row { grid-template-columns: 84px 170px minmax(0, 1fr) minmax(0, 1fr); }
.service-row { grid-template-columns: 190px minmax(0, 1fr); }
.agent-row b, .feature-row b, .transfer-row b { color: var(--green); font: 12px var(--mono); }
.blueprint-row b, .service-row b { color: var(--green); font: 12px var(--mono); }
.alignment-row b { color: var(--green); font: 12px var(--mono); }
.agent-row strong, .feature-row strong, .alignment-row strong, .blueprint-row strong, .service-row strong, .transfer-row strong { font-size: 13px; line-height: 1.4; }
.agent-row span, .feature-row span, .alignment-row span, .blueprint-row span, .service-row span, .transfer-row span { color: var(--muted); font-size: 12px; line-height: 1.45; overflow-wrap: anywhere; }
.feature-row .status-pill {
  justify-self: start;
  padding: 3px 7px;
  color: #755013;
  background: var(--amber-soft);
  border: 1px solid #d1ab68;
  font: 11px var(--mono);
}
.feature-row .status-pill.ready {
  color: #174b39;
  background: var(--green-soft);
  border-color: #9bc3ad;
}
.feature-row .status-pill.partial, .alignment-row .status-pill.partial {
  color: #315f7d;
  background: var(--blue-soft);
  border-color: #9dbdce;
}
.runbook-card {
  padding: 14px;
  background: #fbfaf5;
  border: 1px solid var(--line);
}
.runbook-card h2 { font-size: 21px; margin-bottom: 8px; }
.runbook-card p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.65; }
.mvp-strip {
  display: grid;
  grid-template-columns: repeat(9, minmax(118px, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}
.mvp-step {
  position: relative;
  min-height: 96px;
  padding: 11px;
  background: #fbf7ee;
  border: 1px solid var(--line);
  border-top: 4px solid var(--green);
}
.mvp-step:not(:last-child)::after {
  content: "";
  position: absolute;
  right: -8px;
  top: 42px;
  width: 8px;
  border-top: 2px solid rgba(49, 95, 125, 0.65);
}
.mvp-step b {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 24px;
  margin-bottom: 8px;
  color: #fff;
  background: var(--green);
  font: 11px var(--mono);
}
.mvp-step strong { display: block; margin-bottom: 5px; font-size: 13px; }
.mvp-step span { color: var(--muted); font: 11px var(--mono); overflow-wrap: anywhere; }
.pager { display: flex; justify-content: space-between; gap: 10px; margin-top: 14px; }
.pager a { flex: 1; padding: 12px; text-decoration: none; background: #fbf7ee; border: 1px solid var(--line); color: var(--muted); }
.pager a:last-child { text-align: right; }
.placeholder { border-style: dashed; background: #f8efe1; }
@media (max-width: 1180px) {
  .top, .page-layout, .plan-grid { grid-template-columns: 1fr; }
  .node-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .map-grid, .diagram, .status-grid, .runbook-grid, .gate-grid, .role-grid, .mvp-strip { grid-template-columns: 1fr; }
  .state-row, .artifact-row, .agent-row, .feature-row, .alignment-row, .blueprint-row, .service-row { grid-template-columns: 1fr; }
  .mvp-step:not(:last-child)::after { display: none; }
  .nav-rail { position: static; max-height: none; }
  .flow-board { height: 520px; min-height: 420px; }
}
@media (max-width: 700px) {
  .shell { width: min(100vw - 18px, 1500px); padding-top: 12px; }
  .hero, .plan-hero { padding: 20px; }
  .node-grid, .map-grid, .diagram, .status-grid { grid-template-columns: 1fr; }
  .section-head { align-items: start; flex-direction: column; }
  h1 { font-size: 34px; }
}

/* Review workbench redesign for the Challenge Cup index page. */
body {
  background:
    linear-gradient(90deg, rgba(31, 39, 40, 0.045) 1px, transparent 1px),
    linear-gradient(180deg, rgba(31, 39, 40, 0.035) 1px, transparent 1px),
    #edf2f1;
  background-size: 28px 28px;
}
.shell {
  width: min(1520px, calc(100vw - 28px));
  padding: 18px 0 40px;
}
.section,
.hero,
.panel,
.plan-hero,
.plan-card,
.runbook-card,
.node-card,
.nav-rail,
.status-panel {
  border-color: rgba(46, 63, 61, 0.16);
  box-shadow: 0 16px 42px rgba(23, 37, 35, 0.10);
}
.section {
  margin-top: 12px;
  padding: 16px;
  background: rgba(253, 254, 250, 0.96);
}
.section-head {
  margin-bottom: 12px;
  padding-bottom: 10px;
  align-items: center;
}
.section-head h2,
.plan-card h2,
.runbook-card h2 {
  font-family: var(--sans);
  letter-spacing: 0;
}
.section-head h2 {
  font-size: 22px;
}
.hint,
.subtitle {
  color: #56615f;
}
.review-dashboard {
  display: grid;
  grid-template-columns: minmax(0, 1.16fr) minmax(360px, 0.84fr);
  gap: 12px;
  min-height: 310px;
}
.dashboard-hero {
  position: relative;
  overflow: hidden;
  padding: 18px;
  background:
    linear-gradient(135deg, rgba(21, 83, 72, 0.92), rgba(29, 54, 65, 0.95)),
    #1f3f43;
  color: #f7fbf6;
  border: 1px solid rgba(255, 255, 255, 0.16);
  box-shadow: 0 20px 46px rgba(18, 44, 42, 0.22);
}
.dashboard-hero::after {
  content: "";
  position: absolute;
  right: 22px;
  bottom: 22px;
  width: 340px;
  height: 150px;
  opacity: 0.18;
  background:
    linear-gradient(90deg, transparent 0 28px, #d9f5ea 28px 31px, transparent 31px 56px),
    linear-gradient(180deg, transparent 0 28px, #d9f5ea 28px 31px, transparent 31px 56px);
  background-size: 56px 56px;
  pointer-events: none;
}
.dashboard-hero > * {
  position: relative;
  z-index: 1;
}
.dashboard-hero h1 {
  max-width: 780px;
  margin: 8px 0 10px;
  font: 800 clamp(28px, 3.8vw, 46px)/1.04 var(--sans);
}
.dashboard-hero .subtitle {
  max-width: 820px;
  color: rgba(246, 251, 246, 0.78);
  font-size: 14px;
  line-height: 1.6;
}
.dashboard-hero .kicker {
  color: #9be3cd;
}
.dashboard-hero .tag {
  color: rgba(246, 251, 246, 0.82);
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.18);
}
.dashboard-hero .tag.done {
  color: #092c24;
  background: #a9ead5;
  border-color: #a9ead5;
}
.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.hero-actions a,
.quick-nav a,
.node-card .open-link,
.plan-drawer summary {
  text-decoration: none;
}
.hero-actions a {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 0 12px;
  color: #0d352c;
  background: #bff0df;
  border: 1px solid rgba(255, 255, 255, 0.2);
  font: 700 12px var(--sans);
}
.hero-actions a.secondary {
  color: #eefbf6;
  background: rgba(255, 255, 255, 0.10);
}
.dashboard-panel {
  padding: 14px;
  background: rgba(253, 254, 250, 0.98);
  border: 1px solid rgba(46, 63, 61, 0.16);
  box-shadow: 0 16px 42px rgba(23, 37, 35, 0.10);
}
.dashboard-panel h2 {
  margin: 0 0 10px;
  font: 800 18px/1.25 var(--sans);
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.kpi {
  min-height: 74px;
  padding: 10px;
  background: #f5f8f5;
  border: 1px solid rgba(46, 63, 61, 0.13);
}
.kpi b {
  display: block;
  margin-bottom: 6px;
  color: #62706c;
  font: 700 11px var(--mono);
  text-transform: uppercase;
}
.kpi strong {
  display: block;
  color: #173833;
  font: 800 20px/1.08 var(--sans);
}
.kpi span {
  display: block;
  margin-top: 5px;
  color: #60706b;
  font-size: 12px;
  line-height: 1.42;
}
.focus-list {
  display: grid;
  gap: 7px;
  margin-top: 10px;
}
.focus-item {
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr);
  gap: 7px;
  align-items: start;
  padding: 7px;
  background: #f8faf7;
  border: 1px solid rgba(46, 63, 61, 0.12);
}
.focus-item b {
  color: #1f6656;
  font: 700 11px var(--mono);
}
.focus-item span {
  color: #56615f;
  font-size: 11px;
  line-height: 1.45;
}
.quick-nav {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  gap: 6px;
  padding: 8px 0;
  background: linear-gradient(180deg, #edf2f1 70%, rgba(237, 242, 241, 0));
}
.quick-nav a {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 0 10px;
  color: #25433e;
  background: rgba(253, 254, 250, 0.88);
  border: 1px solid rgba(46, 63, 61, 0.16);
  font: 700 12px var(--sans);
}
.quick-nav a.primary {
  color: #f6fbf8;
  background: #155348;
}
.workbench-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}
.flow-board-shell {
  min-width: 0;
}
.flow-board-shell.compact-map {
  display: grid;
  gap: 10px;
}
.flow-toolbar {
  justify-content: space-between;
  margin-bottom: 8px;
}
.flow-toolbar-group {
  display: inline-flex;
  gap: 6px;
  align-items: center;
}
.flow-toolbar button {
  min-width: 34px;
  height: 30px;
  color: #24413c;
  background: #f8faf7;
  border-color: rgba(46, 63, 61, 0.16);
}
.zoom-readout {
  color: #155348;
  background: #e7f5ef;
  border-color: #a9d6c7;
}
.flow-board {
  min-height: 660px;
  padding: 14px;
  background:
    linear-gradient(90deg, rgba(21, 83, 72, 0.08) 1px, transparent 1px),
    linear-gradient(180deg, rgba(21, 83, 72, 0.06) 1px, transparent 1px),
    #fbfdf9;
  background-size: 24px 24px;
  border-color: rgba(46, 63, 61, 0.16);
  overflow: visible;
  cursor: default;
}
.flow-stage,
.flow-graph {
  width: 100%;
  min-height: 630px;
}
.flow-map {
  position: relative;
  min-height: 630px;
  background: rgba(255, 255, 252, 0.72);
  border: 1px solid rgba(46, 63, 61, 0.12);
  overflow: hidden;
}
.flow-map .graph-node {
  position: absolute;
  left: var(--x);
  top: var(--y);
  transform: translate(-50%, -50%);
}
.flow-map-lines {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 2;
}
.flow-map-lines path {
  fill: none;
  stroke: rgba(21, 83, 72, 0.54);
  stroke-width: 3.2;
  stroke-linecap: round;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
}
.flow-map-lines path.turn {
  stroke: rgba(21, 83, 72, 0.46);
}
.flow-map-lines path.dashed {
  stroke: rgba(184, 127, 35, 0.78);
  stroke-width: 2.8;
  stroke-dasharray: 8 7;
}
.flow-arrow-tip {
  position: absolute;
  left: var(--x);
  top: var(--y);
  z-index: 2;
  width: 0;
  height: 0;
  transform: translate(-50%, -50%);
  pointer-events: none;
}
.flow-arrow-tip.right {
  border-top: 7px solid transparent;
  border-bottom: 7px solid transparent;
  border-left: 12px solid rgba(21, 83, 72, 0.68);
}
.flow-arrow-tip.left {
  border-top: 7px solid transparent;
  border-bottom: 7px solid transparent;
  border-right: 12px solid rgba(21, 83, 72, 0.68);
}
.flow-arrow-tip.down {
  border-left: 7px solid transparent;
  border-right: 7px solid transparent;
  border-top: 12px solid rgba(21, 83, 72, 0.68);
}
.flow-arrow-tip.dashed.left {
  border-right-color: rgba(184, 127, 35, 0.82);
}
.graph-svg > path {
  stroke: rgba(21, 83, 72, 0.72);
  stroke-width: 3.5;
}
.graph-svg > path.dashed {
  stroke: rgba(184, 127, 35, 0.86);
}
.graph-node {
  width: 230px;
  min-height: 72px;
  padding: 13px 15px;
  border-left-width: 4px;
  border-color: rgba(46, 63, 61, 0.18);
  background: rgba(255, 255, 252, 0.98);
  box-shadow: 0 10px 24px rgba(25, 41, 38, 0.13);
}
.flow-map .graph-node {
  z-index: 3;
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  width: clamp(172px, 13.8vw, 210px);
  min-height: 76px;
}
.graph-node .graph-id {
  width: 32px;
  height: 24px;
  margin-right: 10px;
  background: #155348;
  font-size: 12px;
}
.flow-map .graph-node .graph-id {
  margin-right: 0;
}
.graph-node h3 {
  font-size: 17px;
  line-height: 1.34;
}
.flow-map .graph-node h3 {
  display: block;
  font-size: clamp(14px, 0.96vw, 16px);
  line-height: 1.28;
  word-break: keep-all;
  overflow-wrap: anywhere;
}
.graph-node.active {
  border-left-color: #155348;
}
.graph-node.done {
  border-left-color: #2f7e67;
}
.graph-node.pending {
  border-left-color: #b87922;
}
.graph-node.maintenance {
  width: clamp(184px, 14.5vw, 220px);
  border-left-color: #555e89;
  background: #f4f5fb;
}
.flow-review-panel {
  min-width: 0;
  padding: 12px;
  background: #f7faf6;
  border: 1px solid rgba(46, 63, 61, 0.16);
}
.flow-review-panel {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}
.flow-review-panel h3 {
  margin: 0 0 6px;
  font-size: 16px;
}
.flow-review-panel p {
  margin: 0;
  color: #56615f;
  font-size: 12px;
  line-height: 1.45;
}
.review-stack {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 7px;
}
.review-stack div {
  padding: 7px 8px;
  background: #fffefb;
  border: 1px solid rgba(46, 63, 61, 0.12);
}
.review-stack b {
  display: block;
  margin-bottom: 4px;
  color: #1f6656;
  font: 700 11px var(--mono);
}
.review-stack span {
  color: #56615f;
  font-size: 12px;
  line-height: 1.45;
}
.mobile-flow-list {
  display: none;
}
.plan-library {
  padding: 14px;
}
.plan-library-intro {
  display: grid;
  grid-template-columns: 1.2fr 0.8fr;
  gap: 10px;
  margin-bottom: 12px;
}
.plan-summary {
  display: grid;
  gap: 8px;
}
.plan-summary .service-row {
  background: #f8faf7;
}
.plan-drawer {
  margin-top: 8px;
  background: #f8faf7;
  border: 1px solid rgba(46, 63, 61, 0.15);
}
.plan-drawer summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 42px;
  padding: 0 12px;
  cursor: pointer;
  color: #183a34;
  font: 800 14px var(--sans);
}
.plan-drawer summary::after {
  content: "+";
  color: #1f6656;
  font: 800 18px var(--sans);
}
.plan-drawer[open] summary::after {
  content: "-";
}
.drawer-body {
  padding: 0 12px 12px;
}
.drawer-body > .section {
  margin-top: 8px;
  box-shadow: none;
}
.node-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
.node-card {
  min-height: 138px;
  padding: 12px;
  border-left-width: 4px;
}
.node-card p {
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.node-card .tag-row {
  margin-top: 10px;
}
.node-card .tag {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agent-row,
.feature-row,
.alignment-row,
.blueprint-row,
.service-row,
.transfer-row,
.artifact-row,
.state-row {
  min-width: 0;
  background: #fbfdf9;
  border-color: rgba(46, 63, 61, 0.13);
}
.runbook-grid,
.artifact-table,
.agent-matrix,
.status-grid,
.gate-grid,
.role-grid,
.plan-grid {
  min-width: 0;
}
.runbook-grid > *,
.artifact-table > *,
.agent-matrix > *,
.status-grid > *,
.gate-grid > *,
.role-grid > *,
.plan-grid > * {
  min-width: 0;
}
.artifact-row *,
.service-row *,
.blueprint-row *,
.transfer-row *,
.state-row *,
.agent-row *,
.feature-row *,
.alignment-row *,
.checklist span {
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.checklist {
  display: grid;
  gap: 7px;
}
.checklist span {
  display: block;
  padding: 8px 9px;
  color: #56615f;
  background: #fbfdf9;
  border: 1px solid rgba(46, 63, 61, 0.12);
  font-size: 12px;
  line-height: 1.45;
}
@media (max-width: 1180px) {
  .review-dashboard,
  .workbench-grid,
  .plan-library-intro {
    grid-template-columns: 1fr;
  }
  .flow-review-panel,
  .review-stack {
    grid-template-columns: 1fr;
  }
  .flow-board {
    min-height: 620px;
  }
  .node-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 760px) {
  .shell {
    width: min(100vw - 16px, 1520px);
    padding-top: 8px;
  }
  .quick-nav {
    overflow-x: auto;
    padding-bottom: 7px;
  }
  .quick-nav a {
    white-space: nowrap;
  }
  .dashboard-hero,
  .dashboard-panel,
  .section,
  .plan-library {
    padding: 12px;
  }
  .dashboard-hero h1 {
    font-size: 30px;
  }
  .kpi-grid,
  .node-grid {
    grid-template-columns: 1fr;
  }
  .workbench-grid {
    display: block;
  }
  .flow-board-shell,
  .flow-board-shell.compact-map,
  .graph-legend {
    display: none;
  }
  .mobile-flow-list {
    display: grid;
    gap: 8px;
  }
  .mobile-flow-list a {
    display: grid;
    grid-template-columns: 42px minmax(0, 1fr);
    gap: 8px;
    align-items: center;
    min-height: 46px;
    padding: 8px;
    color: #183a34;
    text-decoration: none;
    background: #fbfdf9;
    border: 1px solid rgba(46, 63, 61, 0.14);
    border-left: 4px solid #155348;
  }
  .mobile-flow-list a.pending {
    border-left-color: #b87922;
  }
  .mobile-flow-list a.maintenance {
    border-left-color: #555e89;
  }
  .mobile-flow-list b {
    display: grid;
    place-items: center;
    height: 28px;
    color: #fff;
    background: #155348;
    font: 700 11px var(--mono);
  }
  .mobile-flow-list span {
    min-width: 0;
    font-weight: 800;
    font-size: 13px;
    line-height: 1.3;
  }
  .flow-review-panel {
    margin-top: 10px;
  }
}
`;

function pageName(node) {
  return `${node.id}-${node.slug}.html`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function tag(node) {
  return `<span class="tag ${node.statusKind}">${escapeHtml(node.status)}</span>`;
}

function nav(currentId) {
  return `
    <nav class="nav-rail">
      <a href="../research_team_flow_design.html"><span class="mini">IDX</span><span>返回总索引</span></a>
      ${nodes
        .map((node) => {
          const active = node.id === currentId ? " active" : "";
          return `<a class="${active}" href="${pageName(node)}"><span class="mini">${node.id}</span><span>${escapeHtml(node.title)}</span></a>`;
        })
        .join("\n")}
    </nav>
  `;
}

function list(items) {
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("\n")}</ul>`;
}

function nodeAgentRows() {
  return nodes
    .filter((node) => knowledgeNodeRunbook[node.id])
    .map((node) => {
      const item = knowledgeNodeRunbook[node.id];
      return `<div class="agent-row">
        <b>${escapeHtml(node.id)}</b>
        <strong>${escapeHtml(item.agent)}</strong>
        <span>${escapeHtml(item.agentStatus)}</span>
        <span>${escapeHtml(item.features.join(" / "))}</span>
        <span>${escapeHtml(item.humanGate)}</span>
      </div>`;
    })
    .join("\n");
}

function featureMatrixHtml() {
  return knowledgeRunbook.featureMatrix
    .map(([feature, need, status]) => {
      const readyClass = status === "已有能力" ? " ready" : status.includes("复用") || status.includes("部分") ? " partial" : "";
      return `<div class="feature-row">
        <strong>${escapeHtml(feature)}</strong>
        <span>${escapeHtml(need)}</span>
        <b class="status-pill${readyClass}">${escapeHtml(status)}</b>
      </div>`;
    })
    .join("\n");
}

function projectAlignmentHtml() {
  return knowledgeRunbook.projectAlignment
    .map(([area, evidence, status, implication]) => {
      const readyClass = status === "已有能力" || status === "高度匹配" ? " ready" : status.includes("匹配") || status.includes("复用") ? " partial" : "";
      return `<div class="alignment-row">
        <strong>${escapeHtml(area)}</strong>
        <span>${escapeHtml(evidence)}</span>
        <b class="status-pill${readyClass}">${escapeHtml(status)}</b>
        <span>${escapeHtml(implication)}</span>
      </div>`;
    })
    .join("\n");
}

function currentResearchRunHtml() {
  return `
    <section id="run-state" class="section">
      <div class="section-head">
        <h2>当前运行状态</h2>
        <p class="hint">${escapeHtml(currentResearchRun.status)} · ${escapeHtml(currentResearchRun.updatedAt)}</p>
      </div>
      <div class="runbook-card" style="margin-bottom: 12px;">
        <h2>${escapeHtml(currentResearchRun.title)}</h2>
        <div class="artifact-table">
          <div class="service-row"><b>团队</b><span>${escapeHtml(currentResearchRun.team)}</span></div>
          <div class="service-row"><b>runId</b><span>${escapeHtml(currentResearchRun.runId)}</span></div>
          <div class="service-row"><b>searchPlanId</b><span>${escapeHtml(currentResearchRun.searchPlanId)}</span></div>
        </div>
      </div>
      <div class="agent-matrix">
        ${currentResearchRun.flowState
          .map(
            ([name, state, detail]) => `<div class="feature-row">
              <strong>${escapeHtml(name)}</strong>
              <b class="status-pill partial">${escapeHtml(state)}</b>
              <span>${escapeHtml(detail)}</span>
            </div>`,
          )
          .join("\n")}
      </div>
      <div class="runbook-grid" style="margin-top: 12px;">
        <div class="runbook-card">
          <h2>候选来源</h2>
          <div class="artifact-table">
            ${currentResearchRun.sources
              .map(
                ([title, mechanism, url]) => `<div class="artifact-row">
                  <code>${escapeHtml(mechanism)}</code>
                  <b>${escapeHtml(title)}</b>
                  <span>${escapeHtml(url)}</span>
                </div>`,
              )
              .join("\n")}
          </div>
        </div>
        <div class="runbook-card">
          <h2>候选提炼</h2>
          <div class="artifact-table">
            ${currentResearchRun.extractedDrafts
              .map(
                ([id, title, state]) => `<div class="artifact-row">
                  <code>${escapeHtml(id)}</code>
                  <b>${escapeHtml(title)}</b>
                  <span>${escapeHtml(state)}</span>
                </div>`,
              )
              .join("\n")}
          </div>
          <h2 style="margin-top: 14px;">正式边界</h2>
          <div class="checklist">
            ${currentResearchRun.officialBoundary.map((item) => `<span>${escapeHtml(item)}</span>`).join("\n")}
          </div>
          <h2 style="margin-top: 14px;">下一步</h2>
          <div class="checklist">
            ${currentResearchRun.nextActions.map((item) => `<span>${escapeHtml(item)}</span>`).join("\n")}
          </div>
        </div>
      </div>
    </section>
  `;
}

function implementationBlueprintHtml() {
  return `
    <section class="section">
      <div class="section-head">
        <h2>可实施技术蓝图</h2>
        <p class="hint">${escapeHtml(implementationBlueprint.target)} 详细方案见 <a href="${escapeHtml(implementationBlueprint.doc)}">${escapeHtml(implementationBlueprint.doc)}</a>。</p>
      </div>
      <div class="runbook-card" style="margin-bottom: 12px;">
        <h2>当前团队绑定</h2>
        <div class="artifact-table">
          <div class="service-row"><b>团队</b><span>${escapeHtml(implementationBlueprint.activeTeam.teamName)} / ${escapeHtml(implementationBlueprint.activeTeam.teamId)}</span></div>
          <div class="service-row"><b>分类</b><span>${escapeHtml(implementationBlueprint.activeTeam.teamCategory)} · ${escapeHtml(implementationBlueprint.activeTeam.teamSource)}</span></div>
          <div class="service-row"><b>团队群聊</b><span>${escapeHtml(implementationBlueprint.activeTeam.linkedChatRoomId)} · ${escapeHtml(implementationBlueprint.activeTeam.chatRoomPurpose)}</span></div>
          <div class="service-row"><b>流程文件</b><span>${escapeHtml(implementationBlueprint.activeTeam.workflowPath)}</span></div>
          <div class="service-row"><b>候选仓库</b><span>${escapeHtml(implementationBlueprint.activeTeam.candidateStorePath)}</span></div>
          <div class="service-row"><b>策略</b><span>${escapeHtml(implementationBlueprint.activeTeam.note)}</span></div>
        </div>
      </div>
      <div class="runbook-grid">
        <div class="runbook-card">
          <h2>实施架构</h2>
          <div class="artifact-table">
            ${implementationBlueprint.architecture
              .map(
                ([layer, note]) => `<div class="service-row">
                  <strong>${escapeHtml(layer)}</strong>
                  <span>${escapeHtml(note)}</span>
                </div>`,
              )
              .join("\n")}
          </div>
        </div>
        <div class="runbook-card">
          <h2>服务边界</h2>
          <div class="artifact-table">
            ${implementationBlueprint.services
              .map(
                ([service, note]) => `<div class="service-row">
                  <b>${escapeHtml(service)}</b>
                  <span>${escapeHtml(note)}</span>
                </div>`,
              )
              .join("\n")}
          </div>
        </div>
      </div>
      <div class="agent-matrix" style="margin-top: 12px;">
        ${implementationBlueprint.communicationRoles
          .map(
            ([role, note]) => `<div class="service-row">
              <strong>${escapeHtml(role)}</strong>
              <span>${escapeHtml(note)}</span>
            </div>`,
          )
          .join("\n")}
      </div>
      <div class="runbook-grid" style="margin-top: 12px;">
        <div class="runbook-card">
          <h2>高效沟通轮次</h2>
          <div class="artifact-table">
            ${implementationBlueprint.communicationProtocols
              .map(
                ([type, trigger, mode, output]) => `<div class="blueprint-row compact">
                  <b>${escapeHtml(type)}</b>
                  <span>${escapeHtml(trigger)}</span>
                  <span>${escapeHtml(mode)}</span>
                  <strong>${escapeHtml(output)}</strong>
                </div>`,
              )
              .join("\n")}
          </div>
        </div>
        <div class="runbook-card">
          <h2>消息契约</h2>
          <div class="artifact-table">
            ${implementationBlueprint.messageContracts
              .map(
                ([type, fields]) => `<div class="service-row">
                  <strong>${escapeHtml(type)}</strong>
                  <span>${escapeHtml(fields)}</span>
                </div>`,
              )
              .join("\n")}
          </div>
        </div>
      </div>
      <div class="runbook-grid" style="margin-top: 12px;">
        <div class="runbook-card">
          <h2>降噪规则</h2>
          <div class="checklist">
            ${implementationBlueprint.communicationNoiseRules
              .map((rule) => `<span>${escapeHtml(rule)}</span>`)
              .join("\n")}
          </div>
        </div>
        <div class="runbook-card">
          <h2>效率指标</h2>
          <div class="artifact-table">
            ${implementationBlueprint.communicationMetrics
              .map(
                ([metric, note]) => `<div class="service-row">
                  <b>${escapeHtml(metric)}</b>
                  <span>${escapeHtml(note)}</span>
                </div>`,
              )
              .join("\n")}
          </div>
        </div>
      </div>
      <div class="runbook-grid" style="margin-top: 12px;">
        <div class="runbook-card">
          <h2>本地研究模型定位</h2>
          <div class="artifact-table">
            <div class="service-row"><b>模型</b><span>${escapeHtml(implementationBlueprint.localModel.name)}</span></div>
            <div class="service-row"><b>角色</b><span>${escapeHtml(implementationBlueprint.localModel.role)}</span></div>
            <div class="service-row"><b>上下文</b><span>${escapeHtml(implementationBlueprint.localModel.contextWindow)}</span></div>
            <div class="service-row"><b>边界</b><span>${escapeHtml(implementationBlueprint.localModel.positioning)}</span></div>
            ${implementationBlueprint.localModel.runtimeNotes
              .map(([label, note]) => `<div class="service-row"><b>${escapeHtml(label)}</b><span>${escapeHtml(note)}</span></div>`)
              .join("\n")}
          </div>
        </div>
        <div class="runbook-card">
          <h2>32k 上下文预算</h2>
          <div class="artifact-table">
            ${implementationBlueprint.localModel.contextBudget
              .map(
                ([part, budget, note]) => `<div class="blueprint-row compact">
                  <b>${escapeHtml(part)}</b>
                  <strong>${escapeHtml(budget)}</strong>
                  <span>${escapeHtml(note)}</span>
                </div>`,
              )
              .join("\n")}
          </div>
        </div>
      </div>
      <div class="agent-matrix" style="margin-top: 12px;">
        ${implementationBlueprint.localModel.nodeAssignments
          .map(
            ([node, usage]) => `<div class="service-row">
              <strong>${escapeHtml(node)}</strong>
              <span>${escapeHtml(usage)}</span>
            </div>`,
          )
          .join("\n")}
      </div>
      <div class="tag-row" style="margin-top: 12px;">
        ${implementationBlueprint.localModel.outputContract.map((field) => `<span class="tag">${escapeHtml(field)}</span>`).join("\n")}
      </div>
      <div class="checklist" style="margin-top: 12px;">
        ${implementationBlueprint.localModel.hardBoundaries.map((rule) => `<span>${escapeHtml(rule)}</span>`).join("\n")}
      </div>
      <div class="agent-matrix" style="margin-top: 12px;">
        ${implementationBlueprint.deliveredSlice
          .map(
            ([surface, path, note]) => `<div class="blueprint-row compact">
              <b>${escapeHtml(surface)}</b>
              <strong>${escapeHtml(path)}</strong>
              <span>${escapeHtml(note)}</span>
            </div>`,
          )
          .join("\n")}
      </div>
      <div class="agent-matrix" style="margin-top: 12px;">
        ${implementationBlueprint.milestones
          .map(
            ([id, title, deliverable, acceptance]) => `<div class="blueprint-row">
              <b>${escapeHtml(id)}</b>
              <strong>${escapeHtml(title)}</strong>
              <span>${escapeHtml(deliverable)}</span>
              <span>${escapeHtml(acceptance)}</span>
            </div>`,
          )
          .join("\n")}
      </div>
      <div class="tag-row">
        ${implementationBlueprint.schemas.map((schema) => `<span class="tag">${escapeHtml(schema)}</span>`).join("\n")}
      </div>
    </section>
  `;
}

function knowledgeRunbookHtml() {
  return `
    <section class="section">
      <div class="section-head">
        <h2>知识搜集与筛选入库 MVP</h2>
        <p class="hint">${escapeHtml(knowledgeRunbook.scope)}</p>
      </div>
      <div class="mvp-strip">
        ${knowledgeRunbook.minimalPath
          .map(
            ([id, label, artifact]) => `<div class="mvp-step">
              <b>${escapeHtml(id)}</b>
              <strong>${escapeHtml(label)}</strong>
              <span>${escapeHtml(artifact)}</span>
            </div>`,
          )
          .join("\n")}
      </div>
      <div class="runbook-grid">
        <div class="runbook-card">
          <h2>状态流</h2>
          <div class="state-ladder">
            ${knowledgeRunbook.stateFlow
              .map(
                ([state, label, note]) => `<div class="state-row">
                  <b>${escapeHtml(state)}</b>
                  <strong>${escapeHtml(label)}</strong>
                  <span>${escapeHtml(note)}</span>
                </div>`,
              )
              .join("\n")}
          </div>
        </div>
        <div class="runbook-card">
          <h2>产物清单</h2>
          <div class="artifact-table">
            ${knowledgeRunbook.artifacts
              .map(
                ([file, label, note]) => `<div class="artifact-row">
                  <code>${escapeHtml(file)}</code>
                  <b>${escapeHtml(label)}</b>
                  <span>${escapeHtml(note)}</span>
                </div>`,
              )
              .join("\n")}
          </div>
        </div>
      </div>
      </section>

    <section class="section">
      <div class="section-head">
        <h2>功能岗位编排矩阵</h2>
        <p class="hint">每一步明确功能岗位、需要的能力和审核门禁。这里是规划，不会自动创建或授权 Agent。</p>
      </div>
      <div class="agent-matrix">
        ${nodeAgentRows()}
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>平台功能矩阵</h2>
        <p class="hint">区分 Vibelution 已有能力、待设计能力和待接入流程的能力，后续实现时按缺口逐项落地。</p>
      </div>
      <div class="agent-matrix">
        ${featureMatrixHtml()}
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>项目功能对齐矩阵</h2>
        <p class="hint">把当前规划和 Vibelution 已有功能逐项对齐，避免把模板、工具、正式知识库和候选工作区混为一谈。</p>
      </div>
      <div class="agent-matrix">
        ${projectAlignmentHtml()}
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>筛选门禁</h2>
        <p class="hint">每一步都要有通过条件和失败回退，避免候选知识直接污染正式记忆平台。</p>
      </div>
      <div class="gate-grid">
        ${knowledgeRunbook.gates
          .map(
            ([name, condition, nextState, fallback]) => `<article class="gate-card">
              <h3>${escapeHtml(name)}</h3>
              <p><b>通过：</b>${escapeHtml(condition)}</p>
              <p><b>进入：</b>${escapeHtml(nextState)}</p>
              <p><b>失败：</b>${escapeHtml(fallback)}</p>
            </article>`,
          )
          .join("\n")}
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>流程转移与返工</h2>
        <p class="hint">资料不足、证据不足、假设不可测、图谱断链或入库退回时，流程按转移记录跳到最小上游节点。</p>
      </div>
      <div class="runbook-grid">
        <div class="runbook-card">
          <h2>转移原则</h2>
          <div class="checklist">
            ${knowledgeRunbook.transferPrinciples
              .map((principle) => `<span>${escapeHtml(principle)}</span>`)
              .join("\n")}
          </div>
        </div>
        <div class="runbook-card">
          <h2>记录字段</h2>
          <div class="tag-row">
            ${knowledgeRunbook.transferRecordFields.map((field) => `<span class="tag">${escapeHtml(field)}</span>`).join("\n")}
          </div>
        </div>
      </div>
      <div class="agent-matrix" style="margin-top: 12px;">
        ${knowledgeRunbook.transferMatrix
          .map(
            ([scenario, trigger, target, owner, artifact]) => `<div class="transfer-row">
              <b>${escapeHtml(scenario)}</b>
              <span>${escapeHtml(trigger)}</span>
              <strong>${escapeHtml(target)}</strong>
              <span>${escapeHtml(owner)}</span>
              <span>${escapeHtml(artifact)}</span>
            </div>`,
          )
          .join("\n")}
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>Team 编排状态机</h2>
        <p class="hint">${escapeHtml(knowledgeRunbook.teamWorkflowOrchestration.target)}</p>
      </div>
      <div class="runbook-grid">
        <div class="runbook-card">
          <h2>边界原则</h2>
          <div class="checklist">
            ${knowledgeRunbook.teamWorkflowOrchestration.principles
              .map((principle) => `<span>${escapeHtml(principle)}</span>`)
              .join("\n")}
          </div>
        </div>
        <div class="runbook-card">
          <h2>核心字段</h2>
          <div class="artifact-table">
            ${knowledgeRunbook.teamWorkflowOrchestration.fields
              .map(
                ([field, note]) => `<div class="service-row">
                  <b>${escapeHtml(field)}</b>
                  <span>${escapeHtml(note)}</span>
                </div>`,
              )
              .join("\n")}
          </div>
        </div>
      </div>
      <div class="agent-matrix" style="margin-top: 12px;">
        ${knowledgeRunbook.teamWorkflowOrchestration.integrations
          .map(
            ([surface, note]) => `<div class="service-row">
              <strong>${escapeHtml(surface)}</strong>
              <span>${escapeHtml(note)}</span>
            </div>`,
          )
          .join("\n")}
      </div>
      <div class="agent-matrix" style="margin-top: 12px;">
        ${knowledgeRunbook.teamWorkflowOrchestration.landedApis
          .map(
            ([method, route, note]) => `<div class="blueprint-row compact">
              <b>${escapeHtml(method)}</b>
              <strong>${escapeHtml(route)}</strong>
              <span>${escapeHtml(note)}</span>
            </div>`,
          )
          .join("\n")}
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>角色边界</h2>
        <p class="hint">科研功能 Agent 只产出候选；知识治理 Agent 给治理建议；正式入库必须有审核确认。</p>
      </div>
      <div class="role-grid">
        ${knowledgeRunbook.roles
          .map(
            ([role, note]) => `<article class="role-card">
              <h3>${escapeHtml(role)}</h3>
              <p>${escapeHtml(note)}</p>
            </article>`,
          )
          .join("\n")}
      </div>
    </section>
  `;
}

function nodeRunbookHtml(node) {
  const item = knowledgeNodeRunbook[node.id];
  if (!item) return "";
  return `
    <section class="section">
      <div class="section-head">
        <h2>可跑通节点契约</h2>
        <p class="hint">这一块只覆盖知识搜集、筛选和入库 MVP，不涉及实验训练或交付实现。</p>
      </div>
      <div class="status-grid">
        <div class="status-item"><b>状态</b><span>${escapeHtml(item.state)}</span></div>
        <div class="status-item"><b>功能岗位</b><span>${escapeHtml(item.agent)}</span></div>
        <div class="status-item"><b>Agent 状态</b><span>${escapeHtml(item.agentStatus)}</span></div>
        <div class="status-item"><b>进入条件</b><span>${escapeHtml(item.entry)}</span></div>
        <div class="status-item"><b>退出条件</b><span>${escapeHtml(item.exit)}</span></div>
        <div class="status-item"><b>审核门禁</b><span>${escapeHtml(item.humanGate)}</span></div>
      </div>
      <div class="plan-grid">
        <article class="plan-card"><h2>本步操作</h2><p class="hint">${escapeHtml(item.operation)}</p></article>
        ${item.localModelUse ? `<article class="plan-card"><h2>本地研究模型用法</h2><p class="hint">${escapeHtml(item.localModelUse)}</p></article>` : ""}
        <article class="plan-card"><h2>所需功能</h2>${list(item.features)}</article>
        <article class="plan-card"><h2>工具/平台能力</h2>${list(item.tools)}</article>
        <article class="plan-card"><h2>功能缺口</h2><p class="hint">${escapeHtml(item.gap)}</p></article>
        <article class="plan-card"><h2>失败回退</h2><p class="hint">${escapeHtml(item.fallback)}</p></article>
      </div>
    </section>
  `;
}

function graphNode(id, x, y, extraClass = "") {
  const node = nodes.find((item) => item.id === id);
  const classes = ["graph-node", node.statusKind, extraClass].filter(Boolean).join(" ");
  return `<a class="${classes}" style="--x:${x}px; --y:${y}px;" href="research_flow_pages/${pageName(node)}">
    <span class="graph-id">${node.id}</span>
    <h3>${escapeHtml(node.title)}</h3>
  </a>`;
}

const mapPositions = {
  "01": ["10%", "19%"],
  "02": ["30%", "19%"],
  "03": ["50%", "19%"],
  "04": ["70%", "19%"],
  "05": ["90%", "19%"],
  "06": ["70%", "46%"],
  "07": ["50%", "46%"],
  "08": ["30%", "46%"],
  "09": ["10%", "46%"],
  "10": ["30%", "72%"],
  "11": ["50%", "72%"],
  "12": ["70%", "72%"],
  "13": ["70%", "88%"],
};

const flowMapLabels = {
  "01": "资料入工作区",
  "02": "生成论文笔记",
  "03": "提取机制",
  "04": "机制计算抽象",
  "05": "生成算法假设",
  "08": "候选图谱",
  "09": "正式图谱同步",
  "10": "实验验证",
  "11": "迭代与版本化",
  "12": "挑战杯交付",
  "13": "HTML 维护门禁",
};

function mapNode(id, extraClass = "") {
  const node = nodes.find((item) => item.id === id);
  const classes = ["graph-node", node.statusKind, extraClass].filter(Boolean).join(" ");
  const [x, y] = mapPositions[id];
  const label = flowMapLabels[id] || node.title;
  return `<a class="${classes}" style="--x:${x}; --y:${y};" href="research_flow_pages/${pageName(node)}">
    <span class="graph-id">${node.id}</span>
    <h3>${escapeHtml(label)}</h3>
  </a>`;
}

function arrowTip(kind, x, y) {
  return `<span class="flow-arrow-tip ${kind}" style="--x:${x}; --y:${y};"></span>`;
}

function mobileFlowList() {
  return `<div class="mobile-flow-list" aria-label="移动端科研流程索引">
    ${nodes
      .map((node) => {
        const extraClass = node.id === "13" ? " maintenance" : node.statusKind === "pending" ? " pending" : "";
        return `<a class="${node.statusKind}${extraClass}" href="research_flow_pages/${pageName(node)}">
          <b>${escapeHtml(node.id)}</b>
          <span>${escapeHtml(node.title)}</span>
        </a>`;
      })
      .join("\n")}
  </div>`;
}

function flowGraph() {
  return `<div class="flow-board-shell compact-map">
  <div class="flow-board" aria-label="科研流程图">
    <div class="flow-map" aria-label="一屏完整科研流程图结构">
    <svg class="flow-map-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <path d="M 18.2 19 H 21.8"></path>
      <path d="M 38.2 19 H 41.8"></path>
      <path d="M 58.2 19 H 61.8"></path>
      <path d="M 78.2 19 H 81.8"></path>
      <path class="turn" d="M 90 25 V 46 H 77.8"></path>
      <path d="M 62.2 46 H 57.8"></path>
      <path d="M 42.2 46 H 37.8"></path>
      <path d="M 22.2 46 H 17.8"></path>
      <path class="turn" d="M 10 52 V 72 H 21.8"></path>
      <path d="M 38.2 72 H 41.8"></path>
      <path d="M 58.2 72 H 61.8"></path>
      <path class="turn" d="M 70 78 V 82"></path>
      <path class="dashed" d="M 79 72 H 94 V 29"></path>
      <path class="dashed" d="M 92.5 29 H 82.8"></path>
    </svg>
    ${arrowTip("right", "21.8%", "19%")}
    ${arrowTip("right", "41.8%", "19%")}
    ${arrowTip("right", "61.8%", "19%")}
    ${arrowTip("right", "81.8%", "19%")}
    ${arrowTip("left", "77.8%", "46%")}
    ${arrowTip("left", "57.8%", "46%")}
    ${arrowTip("left", "37.8%", "46%")}
    ${arrowTip("left", "17.8%", "46%")}
    ${arrowTip("right", "21.8%", "72%")}
    ${arrowTip("right", "41.8%", "72%")}
    ${arrowTip("right", "61.8%", "72%")}
    ${arrowTip("down", "70%", "82%")}
    ${arrowTip("dashed left", "82.8%", "29%")}
    <span class="graph-lane-band top-lane"></span>
    <span class="graph-lane-band mid-lane"></span>
    <span class="graph-lane-band bottom-lane"></span>
    <span class="graph-lane top-lane">资料到假设</span>
    <span class="graph-lane mid-lane">治理与图谱</span>
    <span class="graph-lane bottom-lane">实验与交付</span>
    ${mapNode("01")}
    ${mapNode("02")}
    ${mapNode("03")}
    ${mapNode("04")}
    ${mapNode("05")}
    ${mapNode("09")}
    ${mapNode("08")}
    ${mapNode("07")}
    ${mapNode("06")}
    ${mapNode("10")}
    ${mapNode("11")}
    ${mapNode("12")}
    ${mapNode("13", "maintenance")}
  </div>
  </div>
  <div class="graph-legend">
    <span class="legend-chip"><span class="legend-line"></span>主流程依赖</span>
    <span class="legend-chip"><span class="legend-line dashed"></span>维护/迭代回写</span>
    <span class="legend-chip">一屏完整流程图，点击节点进入独立计划页</span>
  </div>
</div>`;
}

function pageFor(node, index) {
  const previous = nodes[index - 1];
  const next = nodes[index + 1];
  return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${node.id} ${escapeHtml(node.title)} · 科研流程计划页</title>
    <link rel="stylesheet" href="flow_pages.css" />
  </head>
  <body>
    <main class="shell page-layout">
      ${nav(node.id)}
      <div>
        <section class="plan-hero">
          <div class="kicker">Research Flow Node ${node.id}</div>
          <h1>${escapeHtml(node.title)}</h1>
          <p class="subtitle">${escapeHtml(node.summary)}</p>
          <div class="tag-row">${tag(node)}<span class="tag">${escapeHtml(node.role)}</span><span class="tag">独立计划页</span></div>
          <div class="diagram">
            <div class="flow-cell"><strong>输入</strong><span>${escapeHtml(node.inputs.slice(0, 2).join(" / "))}</span></div>
            <div class="flow-cell"><strong>动作</strong><span>${escapeHtml(node.actions[0] || "待规划")}</span></div>
            <div class="flow-cell"><strong>输出</strong><span>${escapeHtml(node.outputs.slice(0, 2).join(" / "))}</span></div>
            <div class="flow-cell"><strong>记忆/图谱</strong><span>${escapeHtml(node.graph)}</span></div>
          </div>
        </section>

        <section class="section">
          <div class="section-head">
            <h2>当前节点规划</h2>
            <p class="hint">本页只展示 ${node.id} 节点。通过左侧导航可进入其它节点页。</p>
          </div>
          <div class="plan-grid">
            <article class="plan-card"><h2>目标</h2><p class="hint">${escapeHtml(node.objective)}</p></article>
            <article class="plan-card"><h2>输入</h2>${list(node.inputs)}</article>
            <article class="plan-card"><h2>处理动作</h2>${list(node.actions)}</article>
            <article class="plan-card"><h2>输出物</h2>${list(node.outputs)}</article>
            <article class="plan-card"><h2>风险</h2>${list(node.risks)}</article>
            <article class="plan-card ${node.statusKind === "pending" ? "placeholder" : ""}"><h2>未决事项</h2>${list(node.openQuestions)}</article>
          </div>
        </section>

        <section class="section">
          <div class="section-head">
            <h2>记忆与图谱边界</h2>
            <p class="hint">区分候选工作区、知识治理 Agent、正式 Team Knowledge 和正式知识图谱。</p>
          </div>
          <div class="status-grid">
            <div class="status-item"><b>候选状态</b><span>${escapeHtml(node.status)}</span></div>
            <div class="status-item"><b>记忆平台</b><span>${escapeHtml(node.memory)}</span></div>
            <div class="status-item"><b>图谱同步</b><span>${escapeHtml(node.graph)}</span></div>
          </div>
        </section>

        ${nodeRunbookHtml(node)}

        <div class="pager">
          ${previous ? `<a href="${pageName(previous)}">上一节点：${previous.id} ${escapeHtml(previous.title)}</a>` : `<a href="../research_team_flow_design.html">返回总索引</a>`}
          ${next ? `<a href="${pageName(next)}">下一节点：${next.id} ${escapeHtml(next.title)}</a>` : `<a href="../research_team_flow_design.html">返回总索引</a>`}
        </div>
      </div>
    </main>
  </body>
</html>
`;
}

function indexHtml() {
  return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>神经学机制启发神经网络算法发现科研流程索引</title>
    <link rel="stylesheet" href="research_flow_pages/flow_pages.css" />
  </head>
  <body>
    <main class="shell">
      <nav class="quick-nav" aria-label="页面快速索引">
        <a class="primary" href="#overview">总览</a>
        <a href="#flow-board">流程图</a>
        <a href="#node-index">节点页</a>
        <a href="#run-state">运行状态</a>
        <a href="#plan-library">计划库</a>
      </nav>

      <section id="overview" class="review-dashboard">
        <div class="dashboard-hero">
          <div>
            <div class="kicker">Challenge Cup Research Flow Workbench</div>
            <h1>神经学机制启发神经网络算法发现科研流程审核台</h1>
            <p class="subtitle">首页只承载审核判断：现在能跑到哪里、哪些边界不能越过、哪些节点需要继续规划。完整说明仍保留在节点页和计划库中。</p>
          </div>
          <div class="tag-row">
            <span class="tag done">ai科学研究团队</span>
            <span class="tag">candidate-only until approval</span>
            <span class="tag">Knowledge Steward Agent</span>
            <span class="tag">Candidate Graph Preview</span>
          </div>
          <div class="hero-actions">
            <a href="#flow-board">查看流程图</a>
            <a class="secondary" href="research_flow_pages/01-source-workspace.html">进入 01 知识搜集</a>
            <a class="secondary" href="technical_implementation_plan.md">技术方案</a>
            <a class="secondary" href="${escapeHtml(implementationBlueprint.alignmentDoc)}">赛题对齐方案</a>
          </div>
        </div>
        <aside class="dashboard-panel">
          <h2>审核摘要</h2>
          <div class="kpi-grid">
            <div class="kpi"><b>当前阶段</b><strong>M6.39</strong><span>知识搜索启动已改为从当前模型库解析可用 KV 模型，避免旧固定 ID 阻断。</span></div>
            <div class="kpi"><b>流程节点</b><strong>${nodes.length}</strong><span>1-9 为知识入库主线，10-13 保留占位与维护节点。</span></div>
            <div class="kpi"><b>候选资料</b><strong>${currentResearchRun.sources.length}</strong><span>第一轮 source_manifest 已进入 candidate-only 工作区。</span></div>
            <div class="kpi"><b>正式写入</b><strong>0</strong><span>未写正式 Team Knowledge、RAG 或 official graph。</span></div>
          </div>
          <div class="focus-list">
            <div class="focus-item"><b>优先看</b><span>知识搜集页是否能一眼判断是否进行中、下一步按钮是什么、结果存在哪里，以及详情里能否追溯原始证据。</span></div>
            <div class="focus-item"><b>不能做</b><span>当前执行器只取元数据引用，不抓全文、不审批入库、不把候选图谱当作正式事实。</span></div>
            <div class="focus-item"><b>下一步</b><span>扩展全文下载/网页抽取、批量去重、质量评分和 cache hit/miss 运行证据。</span></div>
          </div>
        </aside>
      </section>

      <section id="flow-board" class="section">
        <div class="section-head">
          <h2>流程图结构</h2>
          <p class="hint">一屏展示 13 个节点、3 条泳道和返工/维护线；不需要缩放或横向拖动，点击节点进入独立计划页。</p>
        </div>
        <div class="workbench-grid">
          ${flowGraph()}
          ${mobileFlowList()}
          <aside class="flow-review-panel">
            <h3>图结构阅读方式</h3>
            <p>主路径先完成资料到假设，再进入审稿、知识治理和图谱同步；实验和交付先保持占位，维护节点负责把后续开发回写到本站。</p>
            <div class="review-stack">
              <div><b>01-05</b><span>资料搜集、笔记、机制、计算映射、算法假设。</span></div>
              <div><b>06-09</b><span>审稿、知识治理、候选图谱、正式同步边界。</span></div>
              <div><b>10-13</b><span>实验验证、版本化、挑战杯交付和 HTML 维护门禁。</span></div>
            </div>
          </aside>
        </div>
      </section>

      <section id="node-index" class="section">
        <div class="section-head">
          <h2>节点页面索引</h2>
          <p class="hint">已规划、半规划、待规划都保留为可点击页面，便于后续逐页补全。</p>
        </div>
        <div class="node-grid">
          ${nodes
            .map(
              (node) => `<a class="node-card" href="research_flow_pages/${pageName(node)}">
                <span class="num">${node.id}</span>
                <h3>${escapeHtml(node.title)}</h3>
                <p>${escapeHtml(node.summary)}</p>
                <div class="tag-row">${tag(node)}<span class="tag">${escapeHtml(node.role)}</span></div>
              </a>`,
            )
            .join("\n")}
        </div>
      </section>

      ${currentResearchRunHtml()}

      <section id="plan-library" class="section plan-library">
        <div class="section-head">
          <h2>完整计划库</h2>
          <p class="hint">下面保留全部规划内容，但默认折叠；审核时先看总览和流程图，需要细节时再展开。</p>
        </div>
        <div class="plan-library-intro">
          <div class="plan-summary">
            <div class="service-row"><strong>知识搜集主线</strong><span>${escapeHtml(knowledgeRunbook.scope)}</span></div>
            <div class="service-row"><strong>实施目标</strong><span>${escapeHtml(implementationBlueprint.target)}</span></div>
            <div class="service-row"><strong>团队入口</strong><span>${escapeHtml(implementationBlueprint.activeTeam.workspaceEntry)} · ${escapeHtml(implementationBlueprint.activeTeam.defaultView)}</span></div>
          </div>
          <div class="dashboard-panel">
            <h2>边界提醒</h2>
            <div class="focus-list">
              <div class="focus-item"><b>候选</b><span>科研功能 Agent 只能写 CandidateStore。</span></div>
              <div class="focus-item"><b>治理</b><span>Knowledge Steward Agent 只提交建议与待审对象。</span></div>
              <div class="focus-item"><b>正式</b><span>审批通过后才进入 Team Knowledge/RAG/official graph。</span></div>
            </div>
          </div>
        </div>
        <details class="plan-drawer">
          <summary>知识搜集与筛选入库 MVP 全量规划</summary>
          <div class="drawer-body">${knowledgeRunbookHtml()}</div>
        </details>
        <details class="plan-drawer">
          <summary>可实施技术蓝图</summary>
          <div class="drawer-body">${implementationBlueprintHtml()}</div>
        </details>
      </section>
    </main>
  </body>
</html>
`;
}

function cleanGeneratedHtml(content) {
  return content.replace(/[ \t]+$/gm, "");
}

await fs.mkdir(pagesDir, { recursive: true });
await fs.writeFile(path.join(pagesDir, "flow_pages.css"), css.trim(), "utf8");
await fs.writeFile(indexPath, cleanGeneratedHtml(indexHtml()), "utf8");
await Promise.all(nodes.map((node, index) => fs.writeFile(path.join(pagesDir, pageName(node)), cleanGeneratedHtml(pageFor(node, index)), "utf8")));

console.log(`Generated ${nodes.length} research flow pages in ${pagesDir}`);
