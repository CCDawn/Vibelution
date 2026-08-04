import type { ReactNode } from "react";

import { VStateSurface } from "../../components/vui";
import shellStyles from "../TeamsRoute.styles";
import workflowRouteStyles from "../TeamsRoute.workflow.styles";

const styles = {
  ...shellStyles,
  ...workflowRouteStyles,
} as Record<string, string>;

export type TeamResearchWorkflowPanelHostProps = {
  lang: "zh" | "en";
  /** True when the selected team is a Challenge Cup / research workflow team. */
  researchWorkflowTeamSelected: boolean;
  /** Status chip next to the section title. */
  statusText: string;
  workflowPending: boolean;
  workflowReady: boolean;
  workflowErrorMessage?: string | null;
  candidatesErrorMessage?: string | null;
  /** Stage-specific modules (source collection, coordination, graph, candidates, …). */
  children?: ReactNode;
};

/**
 * Shared host for research workflow stage modules on board + canvas shells.
 * Overview CTA/kanban stay outside (ResearchOverviewSurface); this only wraps
 * non-overview stage panels that still live under `showWorkflowPanel`.
 */
export function TeamResearchWorkflowPanelHost({
  lang,
  researchWorkflowTeamSelected,
  statusText,
  workflowPending,
  workflowReady,
  workflowErrorMessage,
  candidatesErrorMessage,
  children,
}: TeamResearchWorkflowPanelHostProps) {
  return (
    <section className={styles.workflowPanel} id="research-workflow-overview">
      <div className={styles.sectionTitle}>
        <strong>{lang === "zh" ? "科研流程" : "Research workflow"}</strong>
        <span>{statusText}</span>
      </div>
      {researchWorkflowTeamSelected ? (
        workflowPending ? (
          <VStateSurface
            tone="loading"
            title={lang === "zh" ? "正在读取科研工作流" : "Loading research workflow"}
            skeletonLines={3}
          >
            {lang === "zh"
              ? "TeamWorkflowOrchestration 返回后会显示流程模块。"
              : "Workflow modules appear after TeamWorkflowOrchestration returns."}
          </VStateSurface>
        ) : workflowReady ? (
          <>
            {/* Overview hero/stages/secondary render via ResearchOverviewSurface above this host. */}
            {children}
          </>
        ) : (
          <div className={styles.empty}>
            {lang === "zh" ? "科研流程尚未初始化。" : "Research workflow is not initialized yet."}
          </div>
        )
      ) : (
        <div className={styles.empty}>
          {lang === "zh"
            ? "选择 research-team / 挑战杯ai科研团队 后显示挑战杯科研流程。"
            : "Select research-team to view the Challenge Cup workflow."}
        </div>
      )}
      {workflowErrorMessage ? (
        <div className={styles.messageError}>{workflowErrorMessage}</div>
      ) : null}
      {candidatesErrorMessage ? (
        <div className={styles.messageError}>{candidatesErrorMessage}</div>
      ) : null}
    </section>
  );
}
