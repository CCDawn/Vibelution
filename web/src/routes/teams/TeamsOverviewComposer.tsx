/**
 * Overview board primary surface composer — keeps TeamsRoute board body thin.
 */
import type { ReactNode } from "react";

import { TeamResearchBoardPrimarySurface } from "./TeamResearchBoardPrimarySurface";

export type TeamsOverviewComposerProps = {
  lang: "zh" | "en";
  boardPrimaryMode: "overview" | "stage" | "launcher" | "hidden";
  workflowPending: boolean;
  workflowReady: boolean;
  overviewSlot: ReactNode;
  stageSlot: ReactNode;
  launcherSlot: ReactNode;
  className?: string;
  challengeWorkspaceClassName?: string;
  challengeCupResearchTeamSelected?: boolean;
};

export function TeamsOverviewComposer({
  lang,
  boardPrimaryMode,
  workflowPending,
  workflowReady,
  overviewSlot,
  stageSlot,
  launcherSlot,
  className = "",
  challengeWorkspaceClassName = "",
  challengeCupResearchTeamSelected = false,
}: TeamsOverviewComposerProps) {
  const fillHost =
    challengeCupResearchTeamSelected
    || boardPrimaryMode === "overview"
    || boardPrimaryMode === "stage";

  return (
    <div
      className={[
        "flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden",
        className,
        challengeCupResearchTeamSelected ? challengeWorkspaceClassName : "",
      ].filter(Boolean).join(" ")}
      data-vui-region="teams-board-main"
      data-composer="teams-overview"
      data-fill-host={fillHost ? "true" : "false"}
    >
      <TeamResearchBoardPrimarySurface
        lang={lang}
        boardPrimaryMode={boardPrimaryMode}
        workflowPending={workflowPending}
        workflowReady={workflowReady}
        overviewSlot={overviewSlot}
        stageSlot={stageSlot}
        launcherSlot={launcherSlot}
      />
    </div>
  );
}
