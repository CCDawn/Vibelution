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
    status: "source-extraction 已落地",
    statusKind: "done",
    role: "Source Intake Agent",
    summary: "建立稳定证据源，并把本地 PDF 转成可引用的页码锚点。",
    objective: "把用户提供的论文、PDF、赛题文件和补充资料登记为可追溯输入。",
    inputs: ["用户提供的论文/PDF", "赛题 PDF", "补充资料", "挑战杯工作区路径"],
    actions: [
      "登记文件路径、资料类型、页码范围和来源可信度。",
      "对本地 PDF source_manifest 运行 source-extraction，计算 sha256 并生成 pageAnchors 与 excerpt。",
      "区分允许分析、暂不分析、需要用户确认的资料。",
      "保留原始文件，不在资料入口阶段改写内容。",
    ],
    outputs: ["资料清单", "sourceFiles 引用", "sourceExtraction.pageAnchors", "Paper 原始来源节点"],
    memory: "不进入正式记忆库；只作为后续 paper_note 的 sourceFiles。",
    graph: "可作为候选图谱的 Paper source 节点，不进入正式知识图谱。",
    risks: ["资料来源不明", "PDF 抽取失败", "联网搜索结果混入第一版"],
    openQuestions: ["长 PDF 是否需要自动分批抽取与章节级拆分规则。"],
  },
  {
    id: "02",
    slug: "paper-note",
    title: "生成 paper_note",
    status: "自动草稿桥已接入",
    statusKind: "active",
    role: "Paper Note Extraction Agent",
    summary: "把资料转成可审查的论文/资料笔记候选。",
    objective: "从资料中提取背景、方法、关键发现、局限和引用位置。",
    inputs: ["资料清单", "sourceExtraction.pageAnchors", "PDF 页码", "论文片段", "补充备注"],
    actions: [
      "从 sourceExtraction.excerpt/pageAnchors 组装 sourceRefs、evidenceRefs 和 excerpt。",
      "调用 Local Research Worker Model 生成 summary、keyFindings、methods、limitations。",
      "通过 CandidateStore 校验 citation/page anchor，合格时进入 paper_note_draft。",
      "回写 source candidate 的 paperNoteDrafts trace，保留 uncertainty，避免把摘要写成确定事实。",
    ],
    outputs: ["paper_note_YYYYMMDD_NNN.json", "候选状态 draft", "Paper -> PaperNote 关系"],
    memory: "仍属于候选知识，不进入正式 RAG。",
    graph: "进入候选图谱，可被 neuro_mechanism links 引用。",
    risks: ["摘要过度压缩", "缺页码", "把作者假设当成实验结论"],
    openQuestions: ["长论文拆分为多个 paper_note 的 chunk 策略仍待规划。"],
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
    status: "半规划",
    statusKind: "draft",
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
    status: "已规划",
    statusKind: "done",
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
    status: "M6 状态总览与协调队列已落地",
    statusKind: "done",
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
    inputs: ["ingested 知识", "algorithm_hypothesis", "experiment_result", "赛题要求"],
    actions: ["待规划：技术方案 PDF。", "待规划：演示视频脚本。", "待规划：前端演示与源代码包。"],
    outputs: ["技术方案大纲", "演示脚本", "材料清单"],
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
    ["source_registered", "资料已登记", "原始资料可追溯，允许进入笔记生成。"],
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
      ["POST", "/api/teams/{team_id}/workflow-orchestration/candidates/{candidate_id}/paper-note-draft", "把已完成的 sourceExtraction.excerpt/pageAnchors 组装成本地模型 paper_note_draft 任务，落 CandidateStore，并回写 source candidate 的 paperNoteDrafts trace。"],
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
    ["Paper Note Extraction Agent", "生成 paper_note，保留页码、引用和不确定性。"],
    ["Neuro Mechanism Extraction Agent", "提取神经机制，标注证据和不确定性。"],
    ["Mechanism Mapping Agent", "把机制转成计算抽象，明确类比风险。"],
    ["Algorithm Hypothesis Agent", "生成算法假设和 experimentPlan 占位。"],
    ["Evidence Review Agent", "筛选风险，决定通过、退回或拒绝。"],
    ["Knowledge Steward Agent / agent-knowledge-steward", "生成治理建议、评级建议和摄取包，不绕过审核。"],
    ["Ingestion Approval Gate", "批准正式入库和正式图谱同步。"],
  ],
  featureMatrix: [
    ["资料与候选存储", "source_manifest、knowledge_candidates/index、候选 JSON 命名与状态流", "需新设计"],
    ["PDF/资料解析", "读取本地 PDF、页码锚点、摘录范围和 sourceFiles 绑定", "已接入后端/API"],
    ["科研知识只读查询", "research_knowledge_query_tool 用于查历史科研资料、claims、evidence、gaps", "已有能力"],
    ["正式知识查询/RAG", "knowledge_query_tool、knowledge_rag_retrieve_tool 只读检索已审核知识", "已有能力"],
    ["知识候选提交", "knowledge_proposal_tool / knowledge_ingestion_tool 只提交待审 proposal", "已有能力"],
    ["知识治理工作台", "knowledge_governance_tasks_tool、knowledge_steward_workbench_tool、recommendations", "已有能力"],
    ["入库状态总览", "knowledge-ingestion/status 聚合 CandidateStore、校验报告、候选图摘要、pending proposals、formal KnowledgeItem 和 officialBoundary；Teams 科研流程面板已可视化展示状态漏斗/actionItems/officialBoundary", "已接入前端/API"],
    ["团队协调队列", "coordination/status 聚合 pendingTransfers、needsRework、stewardship、blocked、active 队列，并输出 communicationBrief；Teams 科研流程面板已显示协调状态、目标 Agent、建议通道与只读策略边界", "已接入前端/API"],
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
    ["PDF/本地资料解析", "Team Workflow 已新增 source-extraction API；知识 ingestion 工具仍要求传入已有 excerpt/source_ref，不负责解析 PDF", "已接入首版", "01 已能把本地 PDF 解析成 sourceExtraction.pageAnchors/excerpt；02 已能基于该摘录自动生成 paper_note_draft，长文拆分仍待接。"],
    ["候选 schema 与工作区", "paper_note/neuro_mechanism/algorithm_hypothesis/review_record/candidate_graph 尚未作为项目原生 schema 落地", "需新设计", "这是把流程跑通前的主要工程缺口。"],
  ],
};

const implementationBlueprint = {
  doc: "technical_implementation_plan.md",
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
    note: "挑战杯科研流程直接绑定当前 Vibelution ai科学研究团队，不另建新团队；团队成员仍来自现有科研组织架构。",
  },
  architecture: [
    ["通用数据处理底座", "新增 data_processing_service 首切，提供 profile/run/record/collection assignment/output/status；用于资料搜集与筛选前置，不绑定科研特定 schema。"],
    ["Team 编排状态机", "已新增 TeamWorkflowOrchestration 后端切片，首期启用 challenge_cup_research。"],
    ["候选资料工作区", "已新增 Team 级 CandidateStore 最小索引，保存正式平台尚不能表达的候选中间态。"],
    ["本地研究工作模型层", "接入 bossAGI-standard / qwen3.5-9b（OpenAI-compatible，32k）作为候选生成和预审模型，不作为最终裁决或正式入库模型。"],
    ["团队沟通复用层", "复用 Team registry、Team canvas、linkedChatRoom、ChatRoom round 和 research_coordination purpose；Team 页面已新增科研流程只读面板。"],
    ["研究编排复用层", "复用 research_service、research flow canvas、prompt-research-* 和研究组织治理工具。"],
    ["候选状态机", "新增轻量校验脚本约束 source_registered -> official_synced，不替代现有 runtime 状态系统。"],
    ["记忆平台复用层", "复用 SourceArtifact、RefinementProposal、IngestionPackage、KnowledgeItem、Trace 和 agent-knowledge-steward。"],
    ["图谱展示层", "候选图谱首版由 Teams 工作台读取 CandidateStore candidate_graph payload；正式图谱复用 /api/memory/knowledge-graph。"],
  ],
  milestones: [
    ["M0", "Team 编排后端切片", "已新增 workflow_orchestration.json、candidate_store/index.json、transfer_records.jsonl 和 API。", "能创建 challenge_cup_research 编排、登记资料候选、提交转移请求，并由 Research Coordination Agent 裁决。"],
    ["M0.1", "Team 页面科研流程面板", "已在 Teams 工作台为 research-team / 科研组织团队读取 TeamWorkflowOrchestration、最近 CandidateStore 候选和知识入库状态，展示当前阶段、候选数、活跃项、校验摘要、最近候选、入库状态漏斗、actionItems 和 officialBoundary。", "只读展示，不触发状态转移、审批、正式 Team Knowledge/RAG/图谱写入；普通非科研团队不会被动初始化挑战杯 workflow。"],
    ["M0.5", "本地研究工作模型接线", "已新增 Local Research Worker Model 任务包、32k 上下文预算、JSON 输出校验、草稿记录和 invoke API；bossAGI-standard / qwen3.5-9b 通过临时 model_ref profile 调用，解析失败不写 CandidateStore。", "能为资料初筛、paper_note 草稿、neuro_mechanism 候选、algorithm_hypothesis 草稿和 review prefilter 构建任务包，调用本地模型，并把合格 JSON 草稿写入 CandidateStore。"],
    ["M1", "候选数据基座", "已新增 CandidateStore 列表查询、校验报告、source_manifest/PDF 最小字段校验和本地 PDF source-extraction API；PDF 缺路径、sha256、allowedForAnalysis=true 或抽取失败会进入 source_needs_confirmation。", "能登记 PDF source_manifest，按 candidateType/currentState/qualityStatus 查询候选，抽取 sha256/pageAnchors/excerpt，并查看 invalid/error/warning 统计；仍不写正式 Team Knowledge/RAG/知识图谱。"],
    ["M2", "paper_note 与 PDF 锚点", "已新增 paper_note 输出契约与 Citation Anchor 校验，并接入 sourceExtraction -> paper_note_draft 自动草稿桥：本地 PDF pageAnchors/excerpt 会被转为 sourceRefs/evidenceRefs/excerpt 后调用本地模型。", "合格本地模型输出进入 paper_note_draft；缺 citation/page anchor 时进入 paper_note_needs_revision，不能自然推进到 mechanism_candidate；长文拆分和多草稿合并仍待接。"],
    ["M3", "机制与算法假设", "已新增 neuro_mechanism、mechanism_mapping、algorithm_hypothesis 三段候选门禁；algorithm_hypothesis 必须含 mechanismMappingIds 或 neuroMechanismIds、hypothesis、baseline、expectedBenefit、expectedComputeCost 和含 dataset/metric/baseline/smokePlan 的 experimentPlan。", "合格机制进入 mechanism_candidate，合格映射进入 mechanism_mapping_candidate，合格算法假设进入 hypothesis_candidate；缺机制证据/术语风险、类比风险未标记或实验计划不完整时分别进入 mechanism_needs_revision / mapping_needs_revision / hypothesis_needs_revision。"],
    ["M4", "证据复核与候选图谱", "candidate_graph builder 后端/API 已落地；Teams 科研流程面板已接入 latest candidate_graph SVG 预览；review_prefilter 已补 review_record 候选门禁，必须含 candidateIds、checklist、comments、requiredChanges、needsDecision，且禁止写最终 decision；returned/rejected 转移闭环已接入。", "candidate_graph_visible 和 review_prefiltered 都只进入 CandidateStore；断链进入 broken_links，带最终 decision 的 prefilter 进入 review_needs_revision；returned 可回到最小上游修订节点，rejected 进入 rejection_archive 并从候选图谱推进视图隔离。"],
    ["M5", "知识治理与正式同步", "steward_pack_draft 门禁、待审入库桥、Ingestion Approval Gate、评分建议迁移、officialResearchGraph 正式边和 Memory Graph 展开已落地：有效草稿批准后创建正式 KnowledgeItem、承接待审评级并可视化正式科研 trace，拒绝后退回修订。", "正式 RAG 通过已审核 KnowledgeItem 检索；正式图谱边落在 KnowledgeItem metadata，并由 Memory Graph 只读展开。"],
    ["M6", "知识入库状态总览", "knowledge-ingestion/status 只读聚合 API 和 Teams 工作台可视化状态漏斗已接入，把 CandidateStore、候选校验、候选图摘要、Team Knowledge stats 和 officialBoundary 汇成 stages/actionItems。", "团队协调员可在 /teams?team=research-team 看到 source_collection、candidate_screening、steward_pack、knowledge_review、official_sync 的 ready/needs_review/blocked 状态；查询不会创建 KnowledgeItem、不会写 RAG、不会生成 candidate_graph 快照。"],
    ["M6.1", "团队协调状态队列", "coordination/status 只读聚合 API 和 Teams 工作台协调队列已接入，把 pendingTransfers、needsRework、stewardship、blocked、active 汇成队列、summary、actionItems、coordinationPolicy 和 communicationBrief。", "Research Coordination Agent/组织层可集中看到待决转移、返工候选、治理待审、阻塞项、目标功能 Agent 与建议通道；本轮不自动调转，不自动发送消息，不提供审批按钮。"],
    ["M6.2", "通用数据处理底座首切", "新增 /api/data-processing profiles/runs/list/records/collection-assignments/outputs/status，以及 workspace/data_processing/runs/<runId> 文件落库。", "资料搜集 Agent 可以先创建/查询 DataProcessingRun、领取 CollectionAssignment、提交 CollectionOutput 并生成 DataRecord；该层不写正式 Team Knowledge、不写 RAG、不写知识图谱，后续由挑战杯流程把 DataRecord 转为候选知识。"],
    ["M6.3", "DataRecord 导入 source_manifest", "新增 Team workflow 导入桥：/api/teams/{teamId}/workflow-orchestration/data-processing/runs/{runId}/records/{recordId}/source-candidate。", "通用 DataRecord 可被幂等导入 CandidateStore source_manifest，并保留 importedFromDataRecord、dataProcessingQualitySignals、collectionTrace 和 data_record/data_processing_run evidenceRefs；仍不写正式知识/RAG/正式图谱。"],
  ],
  schemas: [
    "DataProcessingRun",
    "DataRecord",
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
  ],
  services: [
    ["data_processing_service", "已落地首切：通用 profile/run/record/collection assignment/output/status，数据落到 workspace/data_processing/runs/<runId>；只做通用资料处理，不直接写正式知识。"],
    ["data_processing API", "已落地：/api/data-processing/profiles、runs 创建/列表/详情、records、collection-assignments、outputs、status；供数据搜集类 Agent 领取任务和回写结果。"],
    ["team_workflow_orchestration_service", "已落地：Team 级 workflowOrchestration、CandidateStore、transfer request/decision，以及 DataRecord -> source_manifest 幂等导入桥。"],
    ["team_workflows API", "已落地：/api/teams/{team_id}/workflow-orchestration、candidates/source、data-processing/runs/{runId}/records/{recordId}/source-candidate、candidates/{candidate_id}/source-extraction、candidates/{candidate_id}/paper-note-draft、candidates、candidates/validation、candidate-graph、transfers、decide、knowledge-ingestion/status、coordination/status；coordination/status 返回 communicationBrief 但不发送消息。"],
    ["TeamsRoute workflow panel", "已落地只读入口：research-team 右侧 inspector 展示 workflow 当前阶段、candidateStore 摘要、coordination queue、communicationBrief、knowledge ingestion status、validationSummary、候选图谱和最近候选，不做状态写操作。"],
    ["local_research_worker_model", "已落地任务包构建、32k 上下文预算、统一 LLMClient invoke、JSON 提取/校验和 CandidateStore 草稿记录；解析失败不入库。"],
    ["team_communication_binding", "复用 Research Organization 通信边、Team linkedChatRoom、round_robin/opportunistic 群聊轮次。"],
    ["candidate_store", "已落地 Team 级 index、候选列表查询、按类型/状态过滤、validationSummary，并接入 source_manifest、paper_note、neuro_mechanism、mechanism_mapping、algorithm_hypothesis、candidate_graph 最小校验；rejected 候选保留在 CandidateStore metadata.rejectionArchive，但不进入候选图谱推进节点。"],
    ["source_parser", "已接入后端/API：本地 PDF source_manifest 可计算 sha256、抽取 pageAnchors/excerpt 并回写 CandidateStore；缺文件、非 PDF、解析器不可用或无文本时记录 failed extraction。"],
    ["candidate_validator", "已落地 source_manifest/PDF 字段校验、sourceExtraction 失败校验、paper_note citation anchor 校验、neuro_mechanism 证据/术语风险校验、mechanism_mapping fact/inference/overAnalogyRisk 校验、algorithm_hypothesis experimentPlan 校验、candidate_graph 边界校验和 CandidateStore 校验报告。"],
    ["candidate_graph_builder", "已落地后端/API：生成 candidate_graph 候选快照、断链报告、未审节点清单、archivedCandidateCount 和 candidate_only officialBoundary；Teams 工作台已接入首版候选图谱读取、刷新和 SVG 预览。"],
    ["research_agent_binding", "复用 research_service、research flow canvas、prompt-research-* 和研究组织治理工具。"],
    ["memory_ingestion_bridge", "已复用 Team Knowledge create_ingestion_package、review_refinement_proposal、rating suggestion review/create 和 KnowledgeItem metadata patch；steward_pack_draft 可进入 pending proposal，审批通过后创建正式 KnowledgeItem、迁移待审评分建议，并写入 officialResearchGraph 正式科研边。"],
    ["knowledge_ingestion_status", "已新增只读状态聚合：输出 summary/stages/actionItems/candidateBreakdown/candidateGraphSummary/knowledgeBases/officialBoundary，并记录 knowledge_ingestion.status_viewed 运行事件计数。"],
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
    ["DataRecord 导入桥", "/api/teams/{teamId}/workflow-orchestration/data-processing/runs/{runId}/records/{recordId}/source-candidate", "把通用 DataRecord 幂等导入为 source_manifest 候选，保留 run/record/quality/collection trace；不写正式知识。"],
    ["服务文件", "core/web/services/team_workflow_orchestration_service.py", "Team 编排、候选登记、DataRecord 导入、转移请求、协调 Agent 裁决和轻量运行事件日志。"],
    ["路由文件", "core/web/routes/team_workflows.py", "提供工作流查询/确保、候选资料登记、DataRecord 导入、转移提交、转移裁决 API。"],
    ["路由注册", "core/web/app.py", "新增 team_workflows_router，挂载到 /api。"],
    ["存储位置", "workspace/teams/<teamId>/workflow_orchestration.json", "保存 Team 编排结构与 activeWorkflowItems。"],
    ["候选索引", "workspace/teams/<teamId>/candidate_store/index.json", "保存 source_manifest 等候选对象的最小元数据。"],
    ["候选查询", "/api/teams/{teamId}/workflow-orchestration/candidates", "按 candidateType、currentState、qualityStatus 查询 CandidateStore，并返回 validationSummary。"],
    ["候选校验", "/api/teams/{teamId}/workflow-orchestration/candidates/validation", "统计 CandidateStore valid/invalid/error/warning，并报告每个候选的结构化校验问题。"],
    ["Team 前端入口", "/teams?team=research-team", "读取 /workflow-orchestration、/candidates?limit=8 和 /knowledge-ingestion/status，展示科研流程状态、候选仓库、校验摘要、知识入库漏斗、actionItems 和 officialBoundary；非科研团队显示占位，不初始化 workflow。"],
    ["转移记录", "workspace/teams/<teamId>/transfer_records.jsonl", "记录 transfer_request 和 decidedByAgent。"],
    ["本地模型 API", "/api/teams/{teamId}/workflow-orchestration/local-research-model/*", "构建任务包、调用 9B 本地模型、校验并记录 JSON 草稿；不直接写正式知识。"],
    ["paper_note 门禁", "CandidateStore paper_note validation", "paper_note_draft 必须含 keyFindings/methods/limitations/citations，关键发现缺 sourceRef/page/citation 时进入 paper_note_needs_revision。"],
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
    ["验证", "tests/test_data_processing_service.py + tests/test_data_processing_routes.py + tests/test_team_workflow_orchestration_service.py + tests/test_team_workflow_routes.py", "覆盖通用数据处理首切、DataRecord 导入 source_manifest、主路径、非 ownerAgent 不能写最终状态、本地模型任务包、输出校验和知识入库状态总览。"],
  ],
};

const knowledgeNodeRunbook = {
  "01": {
    state: "source_registered",
    agent: "Source Intake Agent",
    agentStatus: "可复用通用 data-processing assignment / source-extraction 后端已接入",
    features: ["DataProcessingRun 建立", "CollectionAssignment 资料搜集任务", "DataRecord 通用记录", "本地资料登记", "source_manifest 写入", "文件路径/页码/来源可信度记录", "本地 PDF sha256/pageAnchors/excerpt 抽取", "可选 research_knowledge_query_tool 查重"],
    tools: ["/api/data-processing/runs", "/api/data-processing/runs/{runId}/collection-assignments", "/api/data-processing/runs/{runId}/collection-assignments/{assignmentId}/outputs", "/api/teams/{teamId}/workflow-orchestration/data-processing/runs/{runId}/records/{recordId}/source-candidate", "research_knowledge_query_tool", "/api/teams/{teamId}/workflow-orchestration/candidates/{candidateId}/source-extraction"],
    localModelUse: "本地 9B 模型适合做标题/摘要/片段初筛，输出 relevanceScore、topicTags、excludeReason，不直接决定正式纳入。",
    humanGate: "确认资料允许分析、来源可信度和是否纳入本轮。",
    gap: "通用资料搜集 assignment/output 已可落库，DataRecord 到 source_manifest 导入桥已接入；长 PDF 自动分批、章节识别和非 PDF 资料解析仍待补。",
    entry: "用户提供 PDF、论文、赛题或补充资料；文件可在挑战杯工作区定位。",
    operation: "先建立通用 DataProcessingRun，由 data_discovery/source_acquisition/content_extraction 等功能 Agent 领取 CollectionAssignment 并提交 CollectionOutput；再通过 Team workflow 导入桥把合格 DataRecord 幂等转成 source_manifest 候选。对本地 PDF 运行 source-extraction，计算 sha256、生成 pageAnchors/excerpt，不改写原文，不自动混入联网资料。",
    exit: "每个资料项先有 DataRecord/sourceRef/rawLocation/title/qualitySignals，再有 source_manifest 的 id、path、type、allowedForAnalysis、sha256、pageScope 和 sourceExtraction.pageAnchors。",
    fallback: "资料不足、路径缺失、来源不明、权限不清、抽取失败或解析器不可用时，assignment 标记 returned/partial，挑战杯候选停在 source_needs_confirmation。",
  },
  "02": {
    state: "paper_note_draft",
    agent: "Paper Note Extraction Agent",
    agentStatus: "自动草稿桥已接入 / 长文 chunk 策略待规划",
    features: ["PDF/资料摘录", "paper_note 候选 JSON 生成", "citation anchors", "uncertainty 字段"],
    tools: ["research_knowledge_query_tool", "sourceExtraction.excerpt", "本地研究模型 task/output API", "/api/teams/{teamId}/workflow-orchestration/candidates/{candidateId}/paper-note-draft"],
    localModelUse: "本地 9B 模型适合按章节或 chunk 生成 paper_note 草稿；32k 内保留 18k-22k 原文证据和输出预留。",
    humanGate: "必要时确认摘要是否保守、是否遗漏关键章节。",
    gap: "paper_note schema 与页码引用校验已接入 CandidateStore；本地 PDF 页码摘录已可由 source-extraction 提供，并已接入自动 paper_note 草稿桥；长文拆分和多草稿合并仍待接。",
    entry: "资料已登记且 allowedForAnalysis=true。",
    operation: "生成 paper_note，抽取 summary、keyFindings、methods、limitations 和 citation anchors。",
    exit: "关键发现能回指 sourceFiles、页码或章节；uncertainty 不为空时显式保留。",
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
.graph-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 10px;
}
.legend-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 9px;
  color: var(--muted);
  background: #fbf7ee;
  border: 1px solid var(--line);
  font: 12px var(--mono);
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

      ${implementationBlueprintHtml()}

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

function flowGraph() {
  return `<div class="flow-board-shell">
  <div class="flow-toolbar" aria-label="画板缩放控制">
    <button type="button" data-zoom-out title="缩小">-</button>
    <button type="button" data-zoom-in title="放大">+</button>
    <button type="button" data-zoom-reset title="重置缩放">100%</button>
    <button type="button" data-zoom-fit title="适配全图">适配全图</button>
    <span class="zoom-readout" data-zoom-readout>100%</span>
  </div>
  <div class="flow-board" data-draggable-board aria-label="可拖动科研流程画板">
    <div class="flow-stage" data-flow-stage>
    <div class="flow-graph" data-flow-graph aria-label="科研流程图结构">
    <svg class="graph-svg" viewBox="0 0 1900 640" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <marker id="arrow-main" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(49, 95, 125, 0.68)"></path>
        </marker>
        <marker id="arrow-draft" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(185, 129, 34, 0.8)"></path>
        </marker>
      </defs>
      <path marker-end="url(#arrow-main)" d="M 265 150 H 430"></path>
      <path marker-end="url(#arrow-main)" d="M 650 150 H 815"></path>
      <path marker-end="url(#arrow-main)" d="M 1035 150 H 1200"></path>
      <path marker-end="url(#arrow-main)" d="M 1420 150 H 1585"></path>
      <path marker-end="url(#arrow-main)" d="M 1700 190 V 290 H 1585"></path>
      <path marker-end="url(#arrow-main)" d="M 1365 320 H 1200"></path>
      <path marker-end="url(#arrow-main)" d="M 980 320 H 815"></path>
      <path marker-end="url(#arrow-main)" d="M 595 320 H 430"></path>
      <path marker-end="url(#arrow-main)" d="M 320 360 V 470 H 430"></path>
      <path marker-end="url(#arrow-main)" d="M 650 500 H 815"></path>
      <path marker-end="url(#arrow-main)" d="M 1035 500 H 1200"></path>
      <path class="dashed" marker-end="url(#arrow-draft)" d="M 1310 540 V 585"></path>
    </svg>
    ${graphNode("01", 160, 150)}
    ${graphNode("02", 540, 150)}
    ${graphNode("03", 925, 150)}
    ${graphNode("04", 1310, 150)}
    ${graphNode("05", 1700, 150)}
    ${graphNode("06", 1475, 320)}
    ${graphNode("07", 1090, 320)}
    ${graphNode("08", 705, 320)}
    ${graphNode("09", 320, 320)}
    ${graphNode("10", 540, 500)}
    ${graphNode("11", 925, 500)}
    ${graphNode("12", 1310, 500)}
    ${graphNode("13", 1310, 610, "maintenance")}
    </div>
    </div>
  </div>
  </div>
  <div class="graph-legend">
    <span class="legend-chip"><span class="legend-line"></span>主流程依赖</span>
    <span class="legend-chip"><span class="legend-line dashed"></span>维护/迭代回写</span>
    <span class="legend-chip">可缩放、可拖动，点击节点进入独立计划页</span>
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
    <title>神经科学启发算法发现科研流程索引</title>
    <link rel="stylesheet" href="research_flow_pages/flow_pages.css" />
  </head>
  <body>
    <main class="shell">
      <section class="top">
        <div class="hero">
          <div>
            <div class="kicker">Challenge Cup Research Flow Index</div>
            <h1>神经科学启发算法发现科研流程索引</h1>
            <p class="subtitle">每个节点都是独立计划页。点击索引卡进入对应页面，查看当前节点的目标、输入、动作、输出、记忆平台边界和图谱同步规则。</p>
          </div>
          <div class="tag-row">
            <span class="tag done">候选知识审核流</span>
            <span class="tag">Knowledge Steward Agent · agent-knowledge-steward</span>
            <span class="tag">Candidate Graph</span>
            <span class="tag">Team Knowledge</span>
          </div>
        </div>
        <aside class="panel">
          <div class="label">流程约束</div>
          <div class="fact-grid">
            <div class="fact"><b>输入</b><span>第一版只处理用户给定资料，不自动联网扩展。</span></div>
            <div class="fact"><b>落库</b><span>科研功能 Agent 只产出候选；知识治理 Agent 负责治理建议。</span></div>
            <div class="fact"><b>图谱</b><span>候选只进候选图谱；ingested 后进入正式图谱。</span></div>
            <div class="fact"><b>实验</b><span>实验验证闭环先占位，未来接训练 runner。</span></div>
          </div>
        </aside>
      </section>

      <section id="flow-board" class="section">
        <div class="section-head">
          <h2>可视化流程图</h2>
          <p class="hint">节点仅显示名称。默认适配全图，可放大查看细节，按住空白区域拖动画板。</p>
        </div>
        ${flowGraph()}
      </section>

      ${knowledgeRunbookHtml()}

      <section class="section">
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
    </main>
    <script>
      (() => {
        const board = document.querySelector("[data-draggable-board]");
        const stage = document.querySelector("[data-flow-stage]");
        const graph = document.querySelector("[data-flow-graph]");
        const readout = document.querySelector("[data-zoom-readout]");
        if (!board || !stage || !graph || !readout) return;
        const naturalWidth = 1900;
        const naturalHeight = 640;
        const minZoom = 0.28;
        const maxZoom = 1.8;
        let zoom = 1;
        const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
        const renderZoom = () => {
          stage.style.width = String(naturalWidth * zoom) + "px";
          stage.style.height = String(naturalHeight * zoom) + "px";
          graph.style.setProperty("--zoom", String(zoom));
          readout.textContent = String(Math.round(zoom * 100)) + "%";
        };
        const setZoom = (nextZoom, anchorX = board.clientWidth / 2, anchorY = board.clientHeight / 2) => {
          const oldZoom = zoom;
          zoom = clamp(nextZoom, minZoom, maxZoom);
          const worldX = (board.scrollLeft + anchorX) / oldZoom;
          const worldY = (board.scrollTop + anchorY) / oldZoom;
          renderZoom();
          board.scrollLeft = worldX * zoom - anchorX;
          board.scrollTop = worldY * zoom - anchorY;
        };
        const fitAll = () => {
          const availableWidth = Math.max(1, board.clientWidth - 28);
          const availableHeight = Math.max(1, board.clientHeight - 28);
          setZoom(Math.min(availableWidth / naturalWidth, availableHeight / naturalHeight));
          board.scrollLeft = 0;
          board.scrollTop = 0;
        };
        document.querySelector("[data-zoom-in]")?.addEventListener("click", () => setZoom(zoom + 0.12));
        document.querySelector("[data-zoom-out]")?.addEventListener("click", () => setZoom(zoom - 0.12));
        document.querySelector("[data-zoom-reset]")?.addEventListener("click", () => {
          setZoom(1);
          board.scrollLeft = 0;
          board.scrollTop = 0;
        });
        document.querySelector("[data-zoom-fit]")?.addEventListener("click", fitAll);
        board.addEventListener("wheel", (event) => {
          if (!event.ctrlKey && !event.metaKey) return;
          event.preventDefault();
          const rect = board.getBoundingClientRect();
          const anchorX = event.clientX - rect.left;
          const anchorY = event.clientY - rect.top;
          setZoom(zoom + (event.deltaY < 0 ? 0.08 : -0.08), anchorX, anchorY);
        }, { passive: false });
        fitAll();
        let dragging = false;
        let startX = 0;
        let startY = 0;
        let startLeft = 0;
        let startTop = 0;
        board.addEventListener("pointerdown", (event) => {
          if (event.target.closest("a")) return;
          dragging = true;
          startX = event.clientX;
          startY = event.clientY;
          startLeft = board.scrollLeft;
          startTop = board.scrollTop;
          board.classList.add("dragging");
          board.setPointerCapture(event.pointerId);
        });
        board.addEventListener("pointermove", (event) => {
          if (!dragging) return;
          board.scrollLeft = startLeft - (event.clientX - startX);
          board.scrollTop = startTop - (event.clientY - startY);
        });
        const stop = (event) => {
          if (!dragging) return;
          dragging = false;
          board.classList.remove("dragging");
          if (board.hasPointerCapture(event.pointerId)) {
            board.releasePointerCapture(event.pointerId);
          }
        };
        board.addEventListener("pointerup", stop);
        board.addEventListener("pointercancel", stop);
      })();
    </script>
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
