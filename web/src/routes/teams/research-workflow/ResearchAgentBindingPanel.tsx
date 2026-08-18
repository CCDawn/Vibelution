/**
 * Agent binding panel for the research workflow single-canvas workspace.
 *
 * Reuses the existing dense Agent summary (TeamSourceCollectionStageAgentsPanel)
 * — no second presentation system. Each row exposes only the responsibility,
 * configured model and actionable status, while the row opens the exact Agent
 * configuration entry /agents?pane=config&agent={agentId}.
 */
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { listAgentSummaries } from "../../../api/agents";
import { queryKeys } from "../../../api/queryKeys";
import type { AgentConfigWorkspaceAgent } from "../../../api/types";
import type { EffectiveAgentBinding } from "../../../api/types/researchWorkflow";
import {
  TeamSourceCollectionStageAgentsPanel,
  type TeamSourceCollectionStageAgentCard,
} from "../source-collection/ui/TeamSourceCollectionStageAgentsPanel";
import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import { buildResearchAgentCard } from "./researchAgentCardModel";
import {
  researchStageAgentConfigStatusLabel,
  researchStageAgentConfigTone,
  researchStageAgentModelLabel,
} from "../researchStageAgentPresentation";
import styles from "./ResearchAgentBindingPanel.styles";

type ResearchAgentBindingPanelProps = {
  teamId: string;
  run: WorkflowRunRecord | null;
  effectiveBindings: EffectiveAgentBinding[] | null;
  lang?: "zh" | "en";
};

export function ResearchAgentBindingPanel({
  teamId,
  run,
  effectiveBindings,
  lang = "zh",
}: ResearchAgentBindingPanelProps) {
  const isZh = lang === "zh";
  const agentSummaryQuery = useQuery({
    queryKey: queryKeys.agentSummary(false),
    queryFn: ({ signal }) => listAgentSummaries<AgentConfigWorkspaceAgent>({ signal }),
    enabled: Boolean(teamId),
    staleTime: 10_000,
  });
  const agentById = useMemo(
    () => new Map((agentSummaryQuery.data ?? []).map((agent) => [agent.agentId, agent])),
    [agentSummaryQuery.data],
  );

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
      const agent = agentById.get(agentId);
      const modelLabel = !agentId
        ? "—"
        : agent
          ? researchStageAgentModelLabel(agent, lang)
          : agentSummaryQuery.isPending
            ? (isZh ? "加载中" : "Loading")
            : agentSummaryQuery.isError
              ? (isZh ? "读取失败" : "Unavailable")
              : (isZh ? "未配置模型" : "Model missing");
      const card = buildResearchAgentCard({
        nodeId: binding.nodeId,
        roleKey: String(snap?.roleKey || binding.roleKey || ""),
        agentId,
        agentName: String(snap?.displayName || binding.displayName || agentId),
        resolvedFrom: source,
        sessionBound: hasSession,
        modelLabel,
        lang,
      });
      if (!agentId) return card;
      if (agent) {
        return {
          ...card,
          tone: researchStageAgentConfigTone(agent),
          statusLabel: researchStageAgentConfigStatusLabel(agent, lang),
        };
      }
      return {
        ...card,
        tone: agentSummaryQuery.isPending ? "warning" : "blocked",
        statusLabel: agentSummaryQuery.isPending
          ? (isZh ? "加载中" : "Loading")
          : (isZh ? "需修复" : "Needs repair"),
      };
    });
  }, [agentById, agentSummaryQuery.isError, agentSummaryQuery.isPending, effectiveBindings, isZh, lang, run]);

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
