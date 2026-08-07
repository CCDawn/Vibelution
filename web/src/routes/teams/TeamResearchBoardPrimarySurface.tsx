import type { ReactNode } from "react";

import { VStateSurface } from "../../components/vui";

export type TeamResearchBoardPrimaryMode = "overview" | "stage" | "launcher" | "hidden";

export type TeamResearchBoardPrimarySurfaceProps = {
  lang: "zh" | "en";
  /**
   * Which primary body to mount inside the board shell:
   * - overview: CTA + three-column kanban summary
   * - stage: experiment / iteration standalone workspace (full main column)
   * - launcher: three-stage control console (hub / knowledge path)
   * - hidden: canvas shell or non-research team
   */
  boardPrimaryMode: TeamResearchBoardPrimaryMode;
  /** True while the workflow query is still in flight (overview progressive shell). */
  workflowPending: boolean;
  workflowReady: boolean;
  /**
   * Overview composition (stable IA + progressive skeleton/data).
   * Mounted while boardPrimaryMode is overview and (pending or ready).
   */
  overviewSlot: ReactNode;
  /** Experiment / iteration dedicated workspace (fills board main). */
  stageSlot: ReactNode;
  /** Interactive three-stage launcher console (not a stage destination). */
  launcherSlot: ReactNode;
};

/**
 * Board-mode primary research surface.
 *
 * Product contract:
 * - overview → overview IA
 * - experiment / iteration → stage standalone workspace (not the three-card hub)
 * - other non-overview → launcher hub only when no dedicated stage page
 * - Loading: progressive overview shell; never swap mid-load to fill "正在读取"
 */
export function TeamResearchBoardPrimarySurface({
  lang,
  boardPrimaryMode,
  workflowPending,
  workflowReady,
  overviewSlot,
  stageSlot,
  launcherSlot,
}: TeamResearchBoardPrimarySurfaceProps) {
  if (boardPrimaryMode === "hidden") {
    return null;
  }

  if (boardPrimaryMode === "stage") {
    return <>{stageSlot}</>;
  }

  if (boardPrimaryMode === "launcher") {
    return <>{launcherSlot}</>;
  }

  // overview / process workflow: keep a full-height host so fill children can stretch
  // (bare fragment cannot establish flex height for nested canvas recipes).
  if (workflowPending || workflowReady) {
    return (
      <div
        data-fill="true"
        data-vui-region="teams-board-primary-fill"
        className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden"
      >
        {overviewSlot}
      </div>
    );
  }

  return (
    <VStateSurface
      fill
      tone="empty"
      title={lang === "zh" ? "科研工作流尚未初始化" : "Research workflow is not initialized"}
    >
      {lang === "zh"
        ? "初始化后总览会占满此主区。"
        : "After initialization, the overview will occupy this main region."}
    </VStateSurface>
  );
}
