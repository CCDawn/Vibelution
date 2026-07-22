import type { ResearchStageType } from "./source-collection/stageProjection";

export type ResearchStageAgentRoleDefinition = {
  key: string;
  roleKeys: string[];
  zh: string;
  en: string;
  zhFocus: string;
  enFocus: string;
  fallbackAgentId?: string;
};

export const RESEARCH_STAGE_AGENT_ROLES: Record<ResearchStageType, ResearchStageAgentRoleDefinition[]> = {
  knowledge_collection: [
    {
      key: "research_coordination",
      roleKeys: ["research_coordination", "data_intake_coordinator", "ceo", "organization_coordinator"],
      zh: "科研协调",
      en: "Research coordination",
      zhFocus: "阶段调度与分工",
      enFocus: "Stage coordination",
    },
    {
      key: "source_finder",
      roleKeys: ["source_finder"],
      zh: "资料寻找",
      en: "Source finder",
      zhFocus: "搜索、获取和本地登记",
      enFocus: "Search, fetch, and register",
    },
    {
      key: "source_extractor",
      roleKeys: ["source_extractor"],
      zh: "资料提炼",
      en: "Source extractor",
      zhFocus: "资料提炼、价值判断和保留说明",
      enFocus: "Extraction and review",
    },
    {
      key: "source_relation_mapper",
      roleKeys: ["source_relation_mapper"],
      zh: "资料关系整理",
      en: "Source relation mapping",
      zhFocus: "主题、来源和证据关系",
      enFocus: "Topic, source, and evidence links",
    },
    {
      key: "source_ingestor",
      roleKeys: ["source_ingestor"],
      zh: "资料入库",
      en: "Source ingestion",
      zhFocus: "最终审核与正式入库",
      enFocus: "Final review and formal ingestion",
    },
  ],
  experiment: [
    {
      key: "experiment_planner",
      roleKeys: ["experiment_planner", "challenge_cup_experiment_planner"],
      zh: "实验规划",
      en: "Experiment planner",
      zhFocus: "计划、baseline 与 smoke gate",
      enFocus: "Plan, baseline, smoke gate",
    },
    {
      key: "experiment_ledger",
      roleKeys: ["experiment_ledger", "challenge_cup_experiment_ledger"],
      zh: "实验证据",
      en: "Experiment ledger",
      zhFocus: "artifact、metric 与结果登记",
      enFocus: "Artifacts, metrics, results",
    },
  ],
  iteration: [
    {
      key: "research_coordination",
      roleKeys: ["research_coordination", "ceo", "organization_coordinator"],
      zh: "科研协调",
      en: "Research coordination",
      zhFocus: "复盘调度与下一轮任务",
      enFocus: "Review coordination",
    },
    {
      key: "iteration_planner",
      roleKeys: ["iteration_planner", "challenge_cup_iteration_planner"],
      zh: "迭代决策",
      en: "Iteration planner",
      zhFocus: "Research Loop 与下一轮决策",
      enFocus: "Research Loop and next step",
    },
    {
      key: "iteration_versioning",
      roleKeys: ["iteration_versioning", "challenge_cup_versioning", "versioning"],
      zh: "版本治理",
      en: "Versioning",
      zhFocus: "versionHistory 与拒绝归档",
      enFocus: "Version history and archive",
    },
    {
      key: "knowledge_steward",
      roleKeys: ["knowledge_steward", "steward", "ingestion_approval"],
      zh: "知识治理",
      en: "Knowledge steward",
      zhFocus: "正式入库建议与审核边界",
      enFocus: "Knowledge governance",
      fallbackAgentId: "agent-knowledge-steward",
    },
  ],
};

export const KNOWLEDGE_EXPANSION_STAGE_AGENT_ROLES: Record<ResearchStageType, ResearchStageAgentRoleDefinition[]> = {
  knowledge_collection: [
    {
      key: "source_finder",
      roleKeys: ["source_finder"],
      zh: "资料寻找",
      en: "Source finder",
      zhFocus: "网络搜集、本地下载与来源登记",
      enFocus: "Web search, local download, and provenance",
    },
    {
      key: "source_extractor",
      roleKeys: ["source_extractor"],
      zh: "资料提炼",
      en: "Source extractor",
      zhFocus: "提炼、宽松保留和无效来源移出",
      enFocus: "Extraction, review, and exclusion",
    },
    {
      key: "source_relation_mapper",
      roleKeys: ["source_relation_mapper"],
      zh: "资料关系整理",
      en: "Source relation mapping",
      zhFocus: "候选知识关系与断链预览",
      enFocus: "Candidate links and gaps",
    },
    {
      key: "source_ingestor",
      roleKeys: ["source_ingestor"],
      zh: "资料入库",
      en: "Source ingestion",
      zhFocus: "正式入库审核与治理门禁",
      enFocus: "Formal ingestion review and governance gate",
    },
  ],
  experiment: [],
  iteration: [],
};
