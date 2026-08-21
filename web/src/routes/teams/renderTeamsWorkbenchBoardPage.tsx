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
  /** Challenge Cup workflow owns its own process rail and pane geometry. */
  suppressOuterShellChrome?: boolean;
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

type TeamsInspectorOverlayProps = {
  styles: Record<string, string>;
  label: string;
  dismissLabel: string;
  onDismiss?: () => void;
  children: ReactNode;
};

/**
 * Narrow-viewport inspector drawer. The backdrop is a real focusable dismiss
 * control (role=button + Enter/Space) and Escape closes from anywhere inside
 * the drawer via the bubbled keydown at the backdrop layer.
 */
export function TeamsWorkbenchInspectorOverlay({
  styles,
  label,
  dismissLabel,
  onDismiss,
  children,
}: TeamsInspectorOverlayProps) {
  return (
    <div
      className={styles.boardInspectorOverlayBackdrop}
      data-vui-region="teams-inspector-overlay-backdrop"
      role="button"
      tabIndex={0}
      aria-label={dismissLabel}
      onClick={onDismiss}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onDismiss?.();
          return;
        }
        if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onDismiss?.();
        }
      }}
    >
      <div
        className={styles.boardInspectorOverlayPanel}
        role="region"
        aria-label={label}
        data-vui-region="teams-inspector-overlay"
        onClick={(event) => event.stopPropagation()}
      >
        <div className={styles.boardInspectorOverlayHeader}>
          <strong>{label}</strong>
          <VButton
            type="button"
            variant="secondary"
            isIconOnly
            aria-label={dismissLabel}
            title={dismissLabel}
            icon={<X size={15} />}
            onPress={onDismiss}
          />
        </div>
        <div className={styles.boardInspectorOverlayBody}>
          {children}
        </div>
      </div>
    </div>
  );
}

export function renderTeamsWorkbenchBoardPage(props: TeamsWorkbenchBoardPageProps) {
  const p = props;
  const suppressOuterShellChrome = p.suppressOuterShellChrome === true;
  const inspectorVisible = p.showBoardInspectorAside;
  const outerNarrowInspector = !suppressOuterShellChrome && Boolean(p.narrowInspector);
  const overlayActive = Boolean(outerNarrowInspector && p.inspectorOverlayOpen && p.inspectorBody);
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
        layoutId={suppressOuterShellChrome ? undefined : TEAMS_LAYOUT_ID}
        resize={suppressOuterShellChrome ? undefined : {
          ...p.teamsRailResize,
          collapse: {
            sidebar: {
              separatorLabel: p.lang === "zh" ? "调整状态栏宽度" : "Resize status rail",
              collapseLabel: p.lang === "zh" ? "收起状态栏" : "Collapse status rail",
              expandLabel: p.lang === "zh" ? "展开状态栏" : "Expand status rail",
            },
          },
        }}
        railClassName={suppressOuterShellChrome ? "!hidden" : undefined}
        workspaceClassName={suppressOuterShellChrome ? "!grid-cols-[0_minmax(0,1fr)] !gap-0" : undefined}
        shellTestId="team-shell-workspace"
        shellMode="board"
        ariaLabel={p.selectedTeamContextTitle}
        title={p.lang === "zh" ? "团队工作台" : "Team workbench"}
        rail={suppressOuterShellChrome ? null : p.teamShellRail}
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
      {outerNarrowInspector && p.inspectorBody ? (
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
        <TeamsWorkbenchInspectorOverlay
          styles={p.styles}
          label={inspectorOverlayLabel}
          dismissLabel={toggleLabel}
          onDismiss={p.onToggleInspectorOverlay}
        >
          {p.inspectorBody}
        </TeamsWorkbenchInspectorOverlay>
      ) : null}
    </>
  );
}
