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

const SOURCE_LABELS: Record<string, string> = {
  workflow_default: "团队/工作流默认",
  stage_override: "阶段覆盖",
  node_override: "节点覆盖",
  rebind: "运行内换绑",
  unbound: "未绑定",
};

export function buildResearchAgentCard(input: {
  nodeId: string;
  roleKey: string;
  agentId: string;
  agentName?: string;
  resolvedFrom: string;
  sessionBound: boolean;
  lang?: "zh" | "en";
}): TeamSourceCollectionStageAgentCard {
  const isZh = input.lang !== "en";
  const sourceLabel = SOURCE_LABELS[input.resolvedFrom] ?? input.resolvedFrom;
  const statusLabel = !input.agentId
    ? isZh ? "未绑定" : "Unbound"
    : input.sessionBound
      ? isZh ? `会话已绑定 · ${sourceLabel}` : `Session bound · ${sourceLabel}`
      : isZh ? `已绑定 · ${sourceLabel}` : `Bound · ${sourceLabel}`;

  return {
    id: input.nodeId,
    tone: !input.agentId || input.resolvedFrom === "unbound"
      ? "missing"
      : input.sessionBound ? "ready" : "warning",
    roleLabel: ROLE_LABELS[input.roleKey] ?? input.roleKey,
    agentName: input.agentName || input.agentId || (isZh ? "未绑定" : "Unbound"),
    modelLabel: input.roleKey,
    statusLabel,
    memoryRoute: "",
    configRoute: input.agentId
      ? `/agents?pane=config&agent=${encodeURIComponent(input.agentId)}`
      : "/agents",
    configLabel: isZh ? "Agent 配置" : "Configure",
  };
}
