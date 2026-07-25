// Memory route shell styles (Wave 8A prune).
// Panel-owned classes live under *Panel.styles.ts after domain componentization.
// Keep only keys referenced by MemoryRoute.tsx.

import {
  vuiControlPillClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
  vuiStateCoolInfoClass,
  vuiStateDangerSoftClass,
  vuiStateSelectedRowClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  agentMemoryViewStack:
    `agentMemoryViewStack min-w-0 !grid h-full min-h-0 !grid-rows-[auto_minmax(0,1fr)] overflow-hidden ${vuiStateCoolInfoClass}`,
  controlStrip:
    "controlStrip min-w-0 flex items-center gap-1.5 overflow-x-auto overflow-y-hidden px-2 pb-1",
  graphViewStack:
    "graphViewStack min-w-0 !grid h-full min-h-0 !grid-rows-[auto_minmax(0,1fr)] overflow-hidden",
  header:
    "header min-w-0 flex flex-wrap items-center gap-1.5",
  headerActions:
    "headerActions min-w-0 flex flex-wrap items-center gap-1.5 justify-end [&>a]:shrink-0 [&>button]:shrink-0 [&_[data-vui=\"button\"]]:w-fit [&_[data-vui=\"button\"]]:max-w-full",
  knowledgeGovernanceDeck:
    "knowledgeGovernanceDeck min-w-0 grid hidden max-[900px]:grid-cols-[minmax(0,1fr)]",
  knowledgeMain:
    "knowledgeMain min-w-0 grid min-h-0 content-start gap-1.5 overflow-hidden [&_.managementPanel]:content-start",
  knowledgeViewStack:
    "knowledgeViewStack min-w-0 grid !flex h-full flex-col min-h-0 overflow-hidden [&>.summaryGrid]:[grid-template-columns:repeat(4,minmax(0,1fr))] max-[720px]:[&>.summaryGrid]:[grid-template-columns:repeat(2,minmax(0,1fr))] max-[460px]:[&>.summaryGrid]:[grid-template-columns:minmax(0,1fr)] [&>.knowledgeWorkspace]:flex-1 [&>.knowledgeGovernanceDeck]:hidden",
  knowledgeWorkspace:
    "knowledgeWorkspace relative min-w-0 grid h-full min-h-0 gap-2 p-2 grid-cols-[var(--memory-left-width,minmax(170px,205px))_minmax(0,1.24fr)_var(--memory-right-width,minmax(260px,0.62fr))] overflow-hidden max-[1180px]:grid-cols-[var(--memory-left-width,minmax(180px,220px))_minmax(0,1fr)] max-[1180px]:[&_.detailPanel]:col-span-2 max-[820px]:grid-cols-1 max-[820px]:overflow-auto max-[820px]:[&_.detailPanel]:col-span-1",
  // Wave 4B: PaneResizeHandle placement only (visual rule is shared).
  paneResizeHandleLeft:
    "memoryPaneResizeHandleLeft !absolute top-2 bottom-2 left-[var(--memory-left-width,230px)] z-30 w-1.5 -translate-x-1/2 max-[780px]:hidden",
  paneResizeHandleRight:
    "memoryPaneResizeHandleRight !absolute top-2 bottom-2 right-[var(--memory-right-width,320px)] z-30 w-1.5 translate-x-1/2 max-[780px]:hidden max-[1120px]:hidden",
  panelError: `panelError min-w-0 ${vuiFlatPanelClass} p-2 ${vuiStateDangerSoftClass}`,
  panelNotice: `panelNotice min-w-0 ${vuiFlatPanelClass} p-2`,
  refreshButton:
    "refreshButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full shrink-0 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  returnButton:
    "returnButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full shrink-0 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
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
    "subnav min-w-0 inline-flex w-fit max-w-full items-center justify-self-start gap-[3px] overflow-x-auto overflow-y-hidden p-[3px] rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)]",
  subnavLink:
    "subnavLink min-w-0 inline-flex shrink-0 items-center justify-center min-h-[24px] w-fit min-w-[74px] max-w-[9.5rem] px-[9px] rounded-[var(--radius-control)] [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] font-[700] no-underline whitespace-nowrap hover:text-[var(--fg-primary)] hover:bg-[var(--vui-control-muted-hover)]",
  subnavLinkActive:
    `subnavLinkActive min-w-0 ${vuiStateSelectedRowClass}`,
  viewStack:
    "viewStack min-w-0 flex h-full min-h-0 flex-col overflow-hidden [&>.workspace]:flex-1 [&>.workspace]:min-h-0 [&>.cleanupWorkspace]:flex-1 [&>.cleanupWorkspace]:min-h-0 [&>.overviewStack]:flex-1 [&>.overviewStack]:min-h-0 [&>.overviewGrid]:flex-1 [&>.overviewGrid]:min-h-0 [&>.effectiveGrid]:flex-1 [&>.effectiveGrid]:min-h-0 [&>.summaryGrid]:shrink-0",
  workspace:
    `workspace relative min-w-0 grid h-full min-h-0 flex-1 gap-2 p-2 grid-cols-[var(--memory-left-width,clamp(200px,18vw,260px))_minmax(0,1fr)_var(--memory-right-width,clamp(280px,24vw,380px))] grid-rows-[minmax(0,1fr)] overflow-hidden max-[1120px]:grid-cols-[var(--memory-left-width,clamp(190px,18vw,240px))_minmax(0,1fr)] max-[1120px]:[&_.detailPanel]:col-span-2 max-[780px]:grid-cols-1 max-[780px]:overflow-auto max-[780px]:[&_.detailPanel]:col-span-1 ${vuiWorkspaceFillClass}`,
} as const;

export default styles;
