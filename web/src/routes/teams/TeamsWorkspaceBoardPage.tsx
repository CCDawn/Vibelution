import { TeamWorkspaceFrame } from "./TeamWorkspaceFrame";
import { TeamsOverviewComposer } from "./TeamsOverviewComposer";
import { TeamsWorkbenchInspectorOverlay, type TeamsWorkbenchBoardPageProps } from "./renderTeamsWorkbenchBoardPage";
import type { ReactNode } from "react";
import { VButton } from "../../components/vui";
import { TEAMS_LAYOUT_ID } from "./teamsWorkbenchChrome";

export function renderTeamsWorkspaceBoardPage(p: TeamsWorkbenchBoardPageProps & { teamSwitcher?: ReactNode }) {
  const label = p.lang === "zh" ? "详情面板" : "Detail panel";
  const dismissLabel = p.lang === "zh" ? "关闭详情面板" : "Close detail panel";
  return <>
    <TeamWorkspaceFrame ariaLabel={p.selectedTeamContextTitle} title={p.lang === "zh" ? "团队工作台" : "Team workbench"}
      domainRecipe="teams-organization-workbench" layoutId={TEAMS_LAYOUT_ID} resize={p.teamsRailResize}
      shellTestId="team-shell-workspace" shellMode="board" railTitle={p.teamSwitcher}
      rail={p.teamShellRail} toolbar={p.teamShellToolbar} inspectorTitle={label}
      inspector={p.showBoardInspectorAside && !p.narrowInspector ? p.inspectorBody : undefined}
      canvas={<TeamsOverviewComposer lang={p.lang} boardPrimaryMode={p.boardPrimaryMode as any}
        workflowPending={p.workflowPending} workflowReady={p.workflowReady}
        className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-auto"
        challengeWorkspaceClassName={p.styles.challengeWorkspaceBody}
        challengeCupResearchTeamSelected={p.challengeCupResearchTeamSelected}
        overviewSlot={p.overviewSlot} stageSlot={p.stageSlot} launcherSlot={p.launcherSlot} />}
    />
    {p.narrowInspector && p.inspectorBody ? <div className={p.styles.boardInspectorFloatingToggle}>
      <VButton variant="secondary" onClick={p.onToggleInspectorOverlay}>{p.inspectorOverlayOpen ? dismissLabel : label}</VButton>
    </div> : null}
    {p.narrowInspector && p.inspectorOverlayOpen && p.inspectorBody ? <TeamsWorkbenchInspectorOverlay
      styles={p.styles} label={label} dismissLabel={dismissLabel} onDismiss={p.onToggleInspectorOverlay}>{p.inspectorBody}</TeamsWorkbenchInspectorOverlay> : null}
  </>;
}
