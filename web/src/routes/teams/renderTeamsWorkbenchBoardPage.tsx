/**
 * Board-mode shell return for Teams workbench (R2-q extract).
 */
import type { ReactNode } from "react";
import { VBoardWorkbenchPage } from "../../components/vui";
import { TeamsOverviewComposer } from "./TeamsOverviewComposer";
import { TEAMS_LAYOUT_ID } from "./teamsWorkbenchChrome";
import type { PaneSpec } from "../../components/layout/paneLayoutPersistence";

export type TeamsWorkbenchBoardPageProps = {
  lang: "zh" | "en";
  styles: Record<string, string>;
  teamsRailResize: { sidebar: PaneSpec; aside: PaneSpec };
  selectedTeamContextTitle: string;
  teamShellRail: ReactNode;
  teamShellToolbar: ReactNode;
  boardPrimaryMode: string;
  workflowPending: boolean;
  workflowReady: boolean;
  challengeCupResearchTeamSelected: boolean;
  overviewSlot: ReactNode;
  stageSlot: ReactNode;
  launcherSlot: ReactNode;
  showBoardInspectorAside: boolean;
  inspectorBody: ReactNode;
};

export function renderTeamsWorkbenchBoardPage(props: TeamsWorkbenchBoardPageProps) {
  const p = props;
  return (
    <VBoardWorkbenchPage
      className={p.styles.route}
      hideHeader
      domainRecipe="teams-organization-workbench"
      layoutId={TEAMS_LAYOUT_ID}
      resize={p.teamsRailResize}
      shellTestId="team-shell-workspace"
      shellMode="board"
      ariaLabel={p.selectedTeamContextTitle}
      title={p.lang === "zh" ? "团队工作台" : "Team workbench"}
      rail={p.teamShellRail}
      toolbar={p.teamShellToolbar}
      // Process / challenge board: pure fill host (no pad/scroll/content-start floor).
      // Absolute children (ResearchProcessWorkspace) pin to this cell.
      boardClassName={
        p.challengeCupResearchTeamSelected || p.boardPrimaryMode === "overview"
          ? "!relative !gap-0 !overflow-hidden !p-0 !h-full min-h-0 flex-1"
          : "!gap-0 !overflow-hidden !p-0"
      }
      board={(
        <TeamsOverviewComposer
          lang={p.lang}
          boardPrimaryMode={p.boardPrimaryMode as any}
          workflowPending={p.workflowPending}
          workflowReady={p.workflowReady}
          className={
            p.challengeCupResearchTeamSelected || p.boardPrimaryMode === "overview"
              ? "absolute inset-0 flex min-h-0 w-full min-w-0 flex-col overflow-hidden p-0"
              : p.styles.teamShellBoardBody
          }
          challengeWorkspaceClassName={p.styles.challengeWorkspaceBody}
          challengeCupResearchTeamSelected={p.challengeCupResearchTeamSelected}
          overviewSlot={p.overviewSlot}
          stageSlot={p.stageSlot}
          launcherSlot={p.launcherSlot}
        />
      )}
      aside={
        p.showBoardInspectorAside ? (
          <div
            className={[
              "flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-auto p-2 [scrollbar-gutter:stable]",
              p.styles.inspectorBody,
            ].filter(Boolean).join(" ")}
            data-vui-region="teams-inspector"
          >
            {p.inspectorBody}
          </div>
        ) : undefined
      }
    />
  );
}
