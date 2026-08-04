import type { ReactNode } from "react";

import { VStateSurface } from "../../components/vui";

export type TeamResearchBoardPrimarySurfaceProps = {
  lang: "zh" | "en";
  /** Board primary region is hidden while the canvas shell is active. */
  researchCanvasVisible: boolean;
  researchWorkflowTeamSelected: boolean;
  showResearchOverview: boolean;
  workflowPending: boolean;
  workflowReady: boolean;
  /** Ready overview (CTA + kanban) when workflow exists. */
  overviewSlot: ReactNode;
  /** Non-overview board view: stage launcher console. */
  launcherSlot: ReactNode;
};

/**
 * Board-mode primary research surface: overview fill loading/empty/ready,
 * or interactive stage launcher when researchView is not overview.
 */
export function TeamResearchBoardPrimarySurface({
  lang,
  researchCanvasVisible,
  researchWorkflowTeamSelected,
  showResearchOverview,
  workflowPending,
  workflowReady,
  overviewSlot,
  launcherSlot,
}: TeamResearchBoardPrimarySurfaceProps) {
  if (researchCanvasVisible || !researchWorkflowTeamSelected) {
    return null;
  }

  if (!showResearchOverview) {
    return <>{launcherSlot}</>;
  }

  if (workflowPending) {
    return (
      <VStateSurface
        fill
        tone="loading"
        title={lang === "zh" ? "正在读取科研总览" : "Loading research overview"}
      >
        {lang === "zh"
          ? "看板、阶段与 CTA 会在工作流返回后原位铺满本区，而不是只显示一行提示。"
          : "Board, stages, and CTA will fill this region once the workflow returns — not a one-line hint."}
      </VStateSurface>
    );
  }

  if (workflowReady) {
    return <>{overviewSlot}</>;
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
