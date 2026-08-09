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
} from "../source-collection/ui/TeamSourceCollectionStageAgentsPanel";
import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import { buildResearchAgentCard } from "./researchAgentCardModel";
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
      return buildResearchAgentCard({
        nodeId: binding.nodeId,
        roleKey: String(snap?.roleKey || binding.roleKey || ""),
        agentId,
        agentName: String(snap?.displayName || agentId),
        resolvedFrom: source,
        sessionBound: hasSession,
        lang,
      });
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
