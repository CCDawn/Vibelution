/**
 * Board-mode shell return for Teams workbench (R2-q extract).
 */
import type { ReactNode } from "react";
import { X } from "lucide-react";
import { VBoardWorkbenchPage, VButton } from "../../components/vui";
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
  /** Narrow window (<=900px): inspector renders as an overlay drawer instead of a side column. */
  narrowInspector?: boolean;
  inspectorOverlayOpen?: boolean;
  onToggleInspectorOverlay?: () => void;
};

export function renderTeamsWorkbenchBoardPage(props: TeamsWorkbenchBoardPageProps) {
  const p = props;
  const inspectorVisible = p.showBoardInspectorAside;
  const overlayActive = Boolean(p.narrowInspector && p.inspectorOverlayOpen && p.inspectorBody);
  const inspectorOverlayLabel = p.lang === "zh" ? "详情面板" : "Detail panel";
  const toggleLabel = overlayActive
    ? (p.lang === "zh" ? "关闭详情面板" : "Close detail panel")
    : (p.lang === "zh" ? "打开详情面板" : "Open detail panel");

  return (
    <>
      <VBoardWorkbenchPage
        className={p.styles.route}
        hideHeader
        domainRecipe="teams-organization-workbench"
        layoutId={TEAMS_LAYOUT_ID}
        resize={{
          ...p.teamsRailResize,
          collapse: {
            sidebar: {
              separatorLabel: p.lang === "zh" ? "调整团队栏宽度" : "Resize team rail",
              collapseLabel: p.lang === "zh" ? "收起团队栏" : "Collapse team rail",
              expandLabel: p.lang === "zh" ? "展开团队栏" : "Expand team rail",
            },
          },
        }}
        shellTestId="team-shell-workspace"
        shellMode="board"
        ariaLabel={p.selectedTeamContextTitle}
        title={p.lang === "zh" ? "团队工作台" : "Team workbench"}
        rail={p.teamShellRail}
        toolbar={p.challengeCupResearchTeamSelected ? undefined : p.teamShellToolbar}
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
          inspectorVisible && !p.narrowInspector ? (
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
      {p.narrowInspector && p.inspectorBody ? (
        <div className={p.styles.boardInspectorFloatingToggle}>
          <VButton
            type="button"
            variant="secondary"
            aria-label={toggleLabel}
            title={toggleLabel}
            onPress={p.onToggleInspectorOverlay}
          >
            {overlayActive ? null : (p.lang === "zh" ? "详情面板" : "Details")}
          </VButton>
        </div>
      ) : null}
      {overlayActive ? (
        <div
          className={p.styles.boardInspectorOverlayBackdrop}
          data-vui-region="teams-inspector-overlay-backdrop"
          onClick={p.onToggleInspectorOverlay}
        >
          <div
            className={p.styles.boardInspectorOverlayPanel}
            role="region"
            aria-label={inspectorOverlayLabel}
            data-vui-region="teams-inspector-overlay"
            onClick={(event) => event.stopPropagation()}
          >
            <div className={p.styles.boardInspectorOverlayHeader}>
              <strong>{inspectorOverlayLabel}</strong>
              <VButton
                type="button"
                variant="secondary"
                isIconOnly
                aria-label={toggleLabel}
                title={toggleLabel}
                icon={<X size={15} />}
                onPress={p.onToggleInspectorOverlay}
              />
            </div>
            <div className={p.styles.boardInspectorOverlayBody}>
              {p.inspectorBody}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
