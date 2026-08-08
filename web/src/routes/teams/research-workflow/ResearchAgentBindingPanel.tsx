/**
 * Agent binding panel for the research workflow single-canvas workspace.
 *
 * Reuses the existing team Agent-card visual (TeamSourceCollectionStageAgentsPanel)
 * — no second card system. Cards show: role, bound Agent (name/id), binding
 * source (team default / workflow / stage / node / run snapshot / rebind),
 * current session state, the exact-session entry and the config entry
 * /agents?pane=config&agent={agentId}.
 */
import { useMemo } from "react";

import type { EffectiveAgentBinding } from "../../../api/types/researchWorkflow";
import {
  TeamSourceCollectionStageAgentsPanel,
  type TeamSourceCollectionStageAgentCard,
  type TeamSourceCollectionStageAgentTone,
} from "../source-collection/ui/TeamSourceCollectionStageAgentsPanel";
import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import styles from "./ResearchAgentBindingPanel.styles";

type ResearchAgentBindingPanelProps = {
  teamId: string;
  run: WorkflowRunRecord | null;
  effectiveBindings: EffectiveAgentBinding[] | null;
  lang?: "zh" | "en";
};

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

function sourceLabel(source: string): string {
  const labels: Record<string, string> = {
    workflow_default: "团队/工作流默认",
    stage_override: "阶段覆盖",
    node_override: "节点覆盖",
    rebind: "运行内换绑",
    unbound: "未绑定",
  };
  return labels[source] ?? source;
}

function toneFor(source: string, hasSession: boolean): TeamSourceCollectionStageAgentTone {
  if (source === "unbound" || !source) return "missing";
  if (!hasSession) return "warning";
  return "ready";
}

export function ResearchAgentBindingPanel({
  teamId,
  run,
  effectiveBindings,
  lang = "zh",
}: ResearchAgentBindingPanelProps) {
  const isZh = lang === "zh";

  const cards = useMemo<TeamSourceCollectionStageAgentCard[]>(() => {
    const snapshots = run?.bindingSnapshots ?? [];
    const snapByNode = new Map(
      snapshots.map((snap) => [String(snap.nodeId || ""), snap as Record<string, unknown>]),
    );
    const sessionByNode = new Map(
      Object.entries(((run as { sessionBindings?: Record<string, unknown> } | null)?.sessionBindings) ?? {}),
    );

    return (effectiveBindings ?? []).map((binding) => {
      const snap = snapByNode.get(binding.nodeId);
      // Run snapshot (immutable) is the per-run authority; effective config
      // only informs the source label when no snapshot exists.
      const agentId = String(snap?.agentId || binding.agentId || "");
      const source = String(snap?.resolvedFrom || binding.resolvedFrom || "unbound");
      const session = sessionByNode.get(binding.nodeId) as
        | { sessionId?: string; status?: string }
        | undefined;
      const hasSession = Boolean(session?.sessionId && session.status === "bound");
      const statusLabel = !agentId
        ? isZh ? "未绑定" : "Unbound"
        : hasSession
          ? isZh ? `会话已绑定${sourceLabel(source)}` : `Session bound · ${sourceLabel(source)}`
          : isZh ? `已绑定 · ${sourceLabel(source)}` : `Bound · ${sourceLabel(source)}`;
      return {
        id: binding.nodeId,
        tone: toneFor(source, hasSession),
        roleLabel: ROLE_LABELS[binding.roleKey] ?? binding.roleKey,
        agentName: agentId || (isZh ? "未绑定" : "Unbound"),
        modelLabel: String(snap?.roleKey || binding.roleKey || ""),
        statusLabel,
        memoryRoute: "",
        configRoute: agentId ? `/agents?pane=config&agent=${encodeURIComponent(agentId)}` : "/agents",
        configLabel: isZh ? "Agent 配置" : "Configure",
      };
    });
  }, [effectiveBindings, run, isZh]);

  if (!teamId) {
    return null;
  }

  if (!effectiveBindings) {
    return (
      <div className={styles.emptyState}>
        <p className={styles.emptyStateText}>
          {isZh ? "当前团队尚无有效绑定数据" : "No effective bindings for this team"}
        </p>
      </div>
    );
  }

  return (
    <TeamSourceCollectionStageAgentsPanel
      lang={isZh ? "zh" : "en"}
      agents={cards}
    />
  );
}
