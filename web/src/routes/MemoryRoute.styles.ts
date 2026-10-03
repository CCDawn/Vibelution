// Memory route shell styles (Wave 8A prune).
// Panel-owned classes live under *Panel.styles.ts after domain componentization.
// Keep only keys referenced by MemoryRoute.tsx.

import {
  vuiControlPillClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
  vuiStateDangerSoftClass,
  vuiStateSelectedRowClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  browseViewStack:
    "browseViewStack min-w-0 h-full min-h-0 flex flex-col overflow-hidden",
  libraryBrowseFill:
    "libraryBrowseFill min-h-0 min-w-0 flex-1 overflow-hidden",
  controlStrip:
    "controlStrip min-w-0 flex items-center gap-1.5 overflow-x-auto overflow-y-hidden px-2 pb-1",
  graphViewStack:
    "graphViewStack min-w-0 !flex h-full min-h-0 flex-col overflow-hidden [&>section]:flex-1",
  knowledgeGovernanceDeck:
    "knowledgeGovernanceDeck min-w-0 grid hidden max-[900px]:grid-cols-[minmax(0,1fr)]",
  knowledgeMain:
    "knowledgeMain min-w-0 grid h-full min-h-0 content-start gap-1.5 overflow-auto p-0.5 [&_.managementPanel]:content-start",
  knowledgeWorkbenchPage:
    "min-w-0 h-full min-h-0 flex-1 overflow-hidden",
  knowledgeViewStack:
    "knowledgeViewStack min-w-0 grid !flex h-full flex-col min-h-0 overflow-hidden [&>.summaryGrid]:[grid-template-columns:repeat(4,minmax(0,1fr))] max-[720px]:[&>.summaryGrid]:[grid-template-columns:repeat(2,minmax(0,1fr))] max-[460px]:[&>.summaryGrid]:[grid-template-columns:minmax(0,1fr)] [&>.knowledgeWorkspace]:flex-1 [&>.knowledgeGovernanceDeck]:hidden",
  // Width ownership: VSplitWorkspace + WORKBENCH_LAYOUT_IDS.memory (left/right pane ids).
  knowledgeWorkspace:
    `knowledgeWorkspace min-w-0 h-full min-h-0 flex-1 overflow-hidden p-2 ${vuiWorkspaceFillClass}`,
  panelError: `panelError min-w-0 ${vuiFlatPanelClass} p-2 ${vuiStateDangerSoftClass}`,
  panelNotice: `panelNotice min-w-0 ${vuiFlatPanelClass} p-2`,
  route:
    `route min-w-0 grid h-full min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden text-[var(--fg-primary)] ${vuiWorkspaceFillClass}`,
  statusPill:
    `statusPill min-w-0 ${vuiControlPillClass}`,
  statusPillMuted:
    "statusPillMuted min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  statusPillPrompt:
    "statusPillPrompt min-w-0",
  statusPillVisible:
    "statusPillVisible min-w-0",
  subnav:
    "subnav min-w-0 inline-flex w-fit max-w-full items-center justify-self-start gap-1 overflow-x-auto overflow-y-hidden p-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)]",
  subnavLink:
    "subnavLink min-w-0 inline-flex shrink-0 items-center justify-center min-h-[24px] w-fit min-w-[74px] max-w-[9.5rem] px-2 rounded-[var(--radius-control)] [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] font-[700] no-underline whitespace-nowrap hover:text-[var(--fg-primary)] hover:bg-[var(--vui-control-muted-hover)]",
  subnavLinkActive:
    `subnavLinkActive min-w-0 ${vuiStateSelectedRowClass}`,
  viewStack:
    "viewStack min-w-0 flex h-full min-h-0 flex-col overflow-hidden [&>.workspace]:flex-1 [&>.workspace]:min-h-0 [&>.cleanupWorkspace]:flex-1 [&>.cleanupWorkspace]:min-h-0 [&>.overviewStack]:flex-1 [&>.overviewStack]:min-h-0 [&>.overviewGrid]:flex-1 [&>.overviewGrid]:min-h-0 [&>.effectiveGrid]:flex-1 [&>.effectiveGrid]:min-h-0 [&>.summaryGrid]:shrink-0 [&>.githubProjectsPanel]:shrink-0 [&>.libraryBrowseFill]:flex-1 [&>.libraryBrowseFill]:min-h-0",
  // Width ownership: VSplitWorkspace + WORKBENCH_LAYOUT_IDS.memory (left/right pane ids).
  workspace:
    `workspace min-w-0 h-full min-h-0 flex-1 overflow-hidden p-2 ${vuiWorkspaceFillClass}`,
} as const;

export default styles;
