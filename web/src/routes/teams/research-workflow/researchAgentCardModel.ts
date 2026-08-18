import type { TeamSourceCollectionStageAgentCard } from "../source-collection/ui/TeamSourceCollectionStageAgentsPanel";

const ROLE_LABELS: Record<string, string> = {
  source_finder: "资料寻找",
  source_extractor: "资料提炼",
  source_relation_mapper: "证据关系",
  source_ingestor: "知识入库",
  experiment_planner: "实验规划",
  experiment_ledger: "实验证据",
  iteration_planner: "迭代决策",
  iteration_versioning: "版本治理",
};

export function buildResearchAgentCard(input: {
  nodeId: string;
  roleKey: string;
  roleLabel?: string;
  agentId: string;
  agentName?: string;
  modelLabel?: string;
  resolvedFrom: string;
  sessionBound: boolean;
  lang?: "zh" | "en";
}): TeamSourceCollectionStageAgentCard {
  const isZh = input.lang !== "en";
  const statusLabel = !input.agentId
    ? isZh ? "未配置" : "Not configured"
    : isZh ? "可运行" : "Ready";

  return {
    id: input.nodeId,
    tone: !input.agentId || input.resolvedFrom === "unbound" ? "missing" : "ready",
    roleLabel: input.roleLabel || ROLE_LABELS[input.roleKey] || (isZh ? "科研执行" : "Research execution"),
    agentName: input.agentName || input.agentId || (isZh ? "未绑定" : "Unbound"),
    modelLabel: input.modelLabel || "",
    statusLabel,
    memoryRoute: "",
    configRoute: input.agentId
      ? `/agents?pane=config&agent=${encodeURIComponent(input.agentId)}`
      : "/agents",
    configLabel: input.agentId
      ? (isZh ? "配置" : "Configure")
      : (isZh ? "绑定" : "Bind"),
  };
}
