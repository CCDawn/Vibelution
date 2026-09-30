const styles = {
  root:
    "flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-[var(--bg-canvas)] text-[var(--fg-primary)]",
  header:
    "relative z-20 grid h-12 min-h-12 shrink-0 grid-cols-[minmax(120px,1fr)_minmax(340px,430px)_auto] grid-rows-[48px] items-center gap-4 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-3 max-[879px]:!grid-cols-[minmax(0,1fr)_auto] max-[879px]:!gap-x-2 max-[879px]:!gap-y-0 max-[879px]:!px-2.5",
  headerWithNavigation: "!grid max-[879px]:!h-[88px] max-[879px]:!min-h-[88px] max-[879px]:!grid-rows-[44px_44px]",
  narrowHeader: "!grid !grid-cols-[minmax(0,1fr)_auto] !gap-x-2 !gap-y-0 !px-2.5 [&_[data-vui=button]]:!min-h-11",
  narrowHeaderWithNavigation: "!grid !h-[88px] !min-h-[88px] !grid-rows-[44px_44px]",
  narrowPhaseNavigation: "!col-span-2 !col-start-1 !row-start-2 !justify-start",
  narrowToolbar: "!col-start-2",
  headerWithoutNavigation:
    "!grid !grid-cols-[minmax(0,1fr)_auto] max-[879px]:!h-11 max-[879px]:!min-h-11 max-[879px]:!grid-rows-[44px]",
  runIdentity:
    "col-start-1 row-start-1 flex min-h-0 min-w-0 items-center gap-3 [&_[data-vui=button]]:!min-h-8 [&_[data-vui=button]]:!w-fit [&_[data-vui=button]]:!max-w-full [&_[data-vui=button]]:!gap-1.5 [&_[data-vui=button]]:!px-2 [&_[data-vui=button]]:!text-[length:var(--vui-font-xs)] max-[879px]:[&_[data-vui=button]]:!min-h-11 max-[879px]:[&_[data-vui=button]]:!px-1.5 [&_[data-vui=button]>span]:min-w-0 [&_[data-vui=button]>span]:truncate",
  title:
    "m-0 min-w-0 flex-1 truncate text-vui-micro-13 font-semibold leading-tight tracking-[-0.01em] text-[var(--fg-primary)]",
  titleWithSource: "max-[879px]:hidden",
  sourceButton:
    "!inline-flex !min-h-8 !w-fit min-w-0 max-w-[min(280px,45vw)] shrink items-center justify-start gap-1.5 whitespace-nowrap !px-2 text-[length:var(--vui-font-xs)] font-medium !text-[var(--fg-secondary)] hover:!bg-[var(--vui-surface-row)] max-[879px]:!min-h-11 max-[879px]:!px-1.5",
  sourceValue:
    "min-w-0 truncate text-[var(--fg-tertiary)] max-[600px]:hidden",
  phaseNavigation:
    "col-start-2 row-start-1 flex min-w-0 items-center justify-center gap-2 max-[879px]:col-span-2 max-[879px]:col-start-1 max-[879px]:row-start-2 max-[879px]:justify-start",
  trackTabs: "!flex !min-w-0 !shrink-0 !gap-0",
  trackTabList: "!flex-nowrap !gap-0.5 !p-0.5",
  trackTabTrigger:
    "!min-h-7 !px-2 !text-[length:var(--vui-font-xs)] max-[879px]:!min-h-10 max-[879px]:!px-2.5",
  phaseSelect:
    "!w-full !min-w-0 !flex-1 [&_button]:!h-8 [&_button]:!min-h-8 [&_button]:!rounded-[var(--radius-control)] [&_button]:!border-[var(--vui-border-subtle)] [&_button]:!bg-[var(--vui-surface-panel)] [&_button]:!px-2.5 [&_button]:!text-[length:var(--vui-font-xs)] max-[879px]:[&_button]:!h-11 max-[879px]:[&_button]:!min-h-11",
  toolbar:
    "col-start-3 row-start-1 flex min-w-0 shrink-0 items-center justify-end gap-1 max-[879px]:col-start-2",
  toolbarWithoutNavigation: "!col-start-2",
  toolbarButton:
    "!inline-flex !min-h-8 !w-fit min-w-0 max-w-full items-center justify-center gap-1.5 whitespace-nowrap !px-2 text-[length:var(--vui-font-xs)] font-medium !text-[var(--fg-secondary)] hover:!bg-[var(--vui-surface-row)] max-[879px]:!min-h-11 max-[879px]:!px-2 [&_svg]:shrink-0",
  moreLabel: "max-[879px]:hidden",
  splitWorkspace:
    "!flex !min-h-0 !min-w-0 !flex-1 !items-stretch !gap-0 !overflow-hidden",
  workspaceBody: "flex min-h-0 min-w-0 flex-1 overflow-hidden",
  contextPanel:
    "flex h-full min-h-0 w-[248px] shrink-0 flex-col overflow-y-auto !rounded-none !border-0 border-r border-[var(--vui-border-subtle)] bg-[var(--vui-surface-rail)] !p-3 max-[879px]:!w-full",
  sourceSection: "shrink-0 border-b border-[var(--vui-border-subtle)] pb-4",
  contextHeading: "m-0 mb-2 text-[length:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]",
  contextRunGroups: "flex shrink-0 flex-col gap-3 border-b border-[var(--vui-border-subtle)] pb-3",
  runGroup: "min-w-0",
  runGroupHeading:
    "m-0 mb-1.5 flex items-center justify-between gap-2 text-[length:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]",
  runGroupCount:
    "flex size-5 shrink-0 items-center justify-center rounded-full bg-[var(--vui-control-muted)] text-vui-micro-10 font-medium text-[var(--fg-tertiary)]",
  runGroupItems: "flex min-w-0 flex-col gap-0.5",
  runHistory: "mt-1 border-t border-[var(--vui-border-subtle)] pt-1",
  runHistoryToggle:
    "!flex !h-auto !min-h-9 !w-full !justify-between !px-2 !text-[length:var(--vui-font-xs)] !text-[var(--fg-secondary)]",
  runHistoryLabel: "flex min-w-0 items-center gap-1.5",
  runHistoryAll:
    "!flex !h-auto !min-h-9 !w-full !justify-start !px-2 !text-left !text-[length:var(--vui-font-xs)] !text-[var(--fg-secondary)]",
  runItem:
    "!flex !h-auto !min-h-10 !w-full !min-w-0 !justify-start !px-2 !py-1.5 text-left aria-pressed:!bg-[var(--vui-surface-panel)] max-[879px]:!min-h-11",
  runItemText: "flex min-w-0 flex-1 flex-col items-start gap-0.5 text-left",
  runItemTitle: "w-full truncate text-left text-[length:var(--vui-font-xs)] text-[var(--fg-primary)]",
  runItemStatus: "w-full truncate text-left text-vui-micro-10 font-normal text-[var(--fg-tertiary)]",
  runGroupEmpty: "m-0 px-2 py-1 text-[length:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  trackContext: "shrink-0 border-b border-[var(--vui-border-subtle)] py-3 text-[length:var(--vui-font-xs)]",
  contextSourceButton: "!flex !h-auto !min-h-10 !w-full !justify-start !gap-2 !px-1 !py-2 !text-[length:var(--vui-font-xs)] !whitespace-normal",
  contextSourceName: "min-w-0 flex-1 break-words text-left [overflow-wrap:anywhere]",
  sourceSummary: "mt-1 text-[length:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  contextPhases: "shrink-0 py-4",
  contextPhase:
    "!flex !h-auto !min-h-10 !w-full !justify-start !gap-2 !px-1.5 !py-2 !text-[length:var(--vui-font-xs)] aria-pressed:!bg-[var(--vui-surface-panel)] max-[879px]:!min-h-11",
  phaseNumber: "flex size-5 shrink-0 items-center justify-center rounded-full border border-[var(--vui-border-subtle)] text-vui-micro-10",
  contextPhaseName: "min-w-0 flex-1 whitespace-normal text-left",
  contextPhaseStatus: "shrink-0 text-vui-micro-10 text-[var(--fg-tertiary)]",
  contextLinks: "flex shrink-0 flex-col gap-1 border-t border-[var(--vui-border-subtle)] pt-2",
  contextLink: "!flex !min-h-10 !w-full !justify-start !gap-2 !px-2 !text-[length:var(--vui-font-xs)] max-[879px]:!min-h-11",
  mobileNavigationDialog:
    "!fixed !left-0 !right-auto !top-0 !bottom-0 !h-[100dvh] !max-h-[100dvh] !w-[min(88vw,300px)] !max-w-[calc(100vw-18px)] !translate-none !transform-none !animate-none !rounded-none shadow-[var(--vui-elevation-panel)]",
  mainPane:
    "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-[var(--vui-surface-panel)]",
  followLiveNotice:
    "flex min-h-9 shrink-0 items-center justify-between gap-2 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-rail)] px-3 py-1 text-[length:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  followLiveButton:
    "!inline-flex !min-h-7 !w-fit items-center gap-1.5 px-2 text-[length:var(--vui-font-xs)] font-medium text-[var(--fg-primary)]",
  conversationFrame: "relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden [&_.timeline]:!px-6 [&_.assistantTurn]:!max-w-[1120px] [&_.assistantTurn]:!justify-self-start [&_.userTurn]:!max-w-[1120px] [&_.userTurn]:!justify-self-start [&_.timelineAssistantTextCell]:!w-full [&_.timelineAssistantTextCell]:!max-w-[1120px] [&_.timelineAssistantTextCell]:!mx-0 max-[879px]:[&_.timeline]:!px-3",
  footer:
    "z-10 shrink-0 border-t border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)]",
  setupFrame: "flex min-h-0 min-w-0 flex-1 overflow-auto",
  evidencePanel:
    "flex h-full min-h-0 min-w-0 shrink-0 flex-col overflow-hidden border-l border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)]",
  evidenceHeading:
    "flex min-h-11 shrink-0 items-center justify-between gap-3 border-b border-[var(--vui-border-subtle)] px-3",
  evidenceHeadingTitle:
    "truncate text-[length:var(--vui-font-sm)] font-semibold text-[var(--fg-primary)]",
  evidenceClose:
    "max-[879px]:!h-10 max-[879px]:!w-10 max-[879px]:!min-w-10",
  evidenceTabs: "!flex !min-h-0 !min-w-0 !flex-1 !flex-col !gap-0 overflow-hidden",
  evidenceTabList:
    "!flex !min-h-10 !shrink-0 !flex-nowrap !items-center !gap-1 !rounded-none !border-0 !border-b !border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-rail)] !px-2 !py-1",
  evidenceTabTrigger:
    "!min-h-8 !min-w-0 !px-2 !text-[length:var(--vui-font-xs)] data-[state=active]:!bg-[var(--vui-surface-panel)] max-[879px]:!min-h-10",
  evidenceTabBody:
    "min-h-0 min-w-0 overflow-auto p-3 text-[length:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  mobileEvidenceDialog:
    "!fixed !left-auto !right-0 !top-0 !bottom-0 !h-[100dvh] !max-h-[100dvh] !w-[min(88vw,420px)] !max-w-[calc(100vw-18px)] !translate-none !transform-none !animate-none !rounded-none !border-y-0 !border-r-0 shadow-[var(--vui-elevation-panel)]",
  mobileEvidenceBody: "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden",
} as const;

export default styles;
