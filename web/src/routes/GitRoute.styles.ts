import {
  vuiOpaqueRowClass,
  vuiStateSelectedRowFillClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const panelSurface =
  "rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] !bg-[var(--vui-surface-panel)]";
const rowSurface =
  "rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-subtle)_70%,transparent)] !bg-[var(--vui-surface-row)]";
const rowSurfaceHover =
  "hover:border-[color-mix(in_srgb,var(--vui-border-soft)_88%,transparent)] hover:!bg-[var(--vui-surface-row-hover)]";
const mutedControl =
  "inline-flex h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-soft)_76%,transparent)] bg-[color-mix(in_srgb,var(--vui-control-muted)_72%,transparent)] px-[9px] py-1.5 [font-size:var(--vui-font-xs)] text-vui-fg-secondary hover:border-[color-mix(in_srgb,var(--border-strong)_78%,transparent)] hover:bg-[color-mix(in_srgb,var(--vui-control-muted-hover)_82%,transparent)] hover:text-vui-fg-primary disabled:cursor-default disabled:opacity-55";
const activeControl =
  "h-[var(--vui-control-height-sm)] border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_14%,var(--vui-control-muted))] text-[var(--accent-warm-2)]";

export const gitRouteStyles = {
  route:
    `grid h-full min-h-0 min-w-0 max-w-full grid-rows-[auto_auto_auto_minmax(0,1fr)] overflow-hidden overflow-x-hidden text-vui-fg-primary max-[860px]:overflow-auto ${vuiWorkspaceFillClass}`,
  header:
    "mx-2 mt-1.5 min-w-0 border-[var(--vui-border-subtle)] !bg-transparent !shadow-none !backdrop-blur-none",
  panelEyebrow: "m-0 mb-0.5 [font-size:var(--vui-font-xs)] uppercase tracking-[0.08em] text-[var(--fg-tertiary)]",
  refreshButton:
    "h-[var(--vui-control-height-sm)] min-h-8 w-[var(--vui-control-height-sm)] flex-none p-0",
  summaryGrid:
    "mx-2 mt-1 min-h-[48px] min-w-0 max-w-full overflow-x-auto",
  notice:
    "mx-2 mt-1.5 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--state-error)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_12%,transparent)] px-2.5 py-2 [font-size:var(--vui-font-xs)] text-[var(--state-error)]",
  workspace:
    `grid min-h-0 min-w-0 grid-cols-[var(--git-change-panel-width,320px)_10px_minmax(0,1fr)_clamp(250px,22vw,360px)] p-1.5 max-[1200px]:grid-cols-[minmax(240px,var(--git-change-panel-width,300px))_8px_minmax(0,1fr)] max-[1200px]:grid-rows-[minmax(0,1fr)_minmax(200px,34vh)] max-[1200px]:gap-y-1.5 max-[860px]:grid-cols-[minmax(0,1fr)] max-[860px]:grid-rows-none max-[860px]:content-start max-[860px]:gap-1.5 ${vuiWorkspaceFillClass}`,
  // Clean overview must fully override the dirty-mode 4-column change-list template
  // (workspace + workspaceOverview are combined). Without !grid-cols, left rail stays
  // ~320px and nested 本地提交|WORKTREE cards crush/overlap text.
  workspaceOverview:
    "!grid-cols-[minmax(360px,1fr)_minmax(0,1.2fr)_minmax(300px,0.85fr)] !gap-2 max-[1400px]:!grid-cols-[minmax(0,1fr)_minmax(300px,0.9fr)] max-[1400px]:!grid-rows-[minmax(240px,0.95fr)_minmax(220px,0.85fr)] max-[1400px]:!gap-y-2 max-[860px]:!grid-cols-[minmax(0,1fr)] max-[860px]:!grid-rows-none max-[860px]:!content-start max-[860px]:!gap-1.5",
  resizeHandle: `relative min-w-2.5 cursor-col-resize touch-none border-0 bg-transparent p-0 outline-none before:absolute before:inset-y-0 before:left-1/2 before:w-[3px] before:-translate-x-1/2 before:rounded-full before:${vuiOpaqueRowClass} before:transition before:content-[''] hover:before:bg-[color-mix(in_srgb,var(--accent-warm)_52%,transparent)] hover:before:shadow-none focus-visible:before:bg-[color-mix(in_srgb,var(--accent-warm)_52%,transparent)] focus-visible:before:shadow-none max-[860px]:hidden`,
  changePanel:
    `grid min-h-0 grid-rows-[auto_auto_auto_minmax(0,1fr)] gap-1.5 ${panelSurface} p-2`,
  commitPanel:
    `grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-1.5 ${panelSurface} p-2 max-[1200px]:col-span-full max-[1200px]:row-start-2 max-[1200px]:grid-cols-[minmax(280px,0.9fr)_minmax(0,1.1fr)] max-[1200px]:grid-rows-[auto_minmax(0,1fr)] max-[1200px]:items-start max-[860px]:col-auto max-[860px]:row-auto max-[860px]:grid-cols-[minmax(0,1fr)] max-[860px]:grid-rows-[auto_auto_minmax(180px,1fr)]`,
  gitOverviewPanel:
    "grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-2 max-[1200px]:[.workspaceOverview_&]:col-start-1 max-[1200px]:[.workspaceOverview_&]:row-start-1 max-[860px]:[.workspaceOverview_&]:col-auto max-[860px]:[.workspaceOverview_&]:row-auto",
  cleanStateStrip:
    `grid w-full min-w-0 cursor-pointer grid-cols-[minmax(140px,auto)_minmax(0,1fr)] items-center gap-3 ${panelSurface} px-3 py-2.5 text-left text-inherit hover:border-[color-mix(in_srgb,var(--accent-cool)_30%,transparent)] hover:bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-panel))] max-[860px]:grid-cols-[minmax(0,1fr)] [&_h2]:m-0 [&_h2]:text-[0.98rem] [&_h2]:text-vui-fg-primary [&>span]:min-w-0 [&>span]:[overflow-wrap:anywhere] [&>span]:[white-space:normal] [&>span]:[font-size:var(--vui-font-xs)] [&>span]:leading-tight [&>span]:text-vui-fg-secondary`,
  gitSituationGrid:
    "grid min-h-0 min-w-0 grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)] gap-2 max-[1200px]:grid-cols-1",
  gitSituationCard:
    `grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-2 ${panelSurface} p-2.5 [&_h2]:m-0 [&_h2]:min-w-0 [&_h2]:text-[0.98rem] [&_h2]:text-vui-fg-primary`,
  situationList: "grid min-h-0 content-start gap-2.5 overflow-auto pr-1",
  worktreeList: "grid min-h-0 content-start gap-2.5 overflow-auto pr-1",
  worktreeItem:
    `grid w-full min-w-0 cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-start gap-2 ${rowSurface} px-[9px] py-2 text-left text-inherit ${rowSurfaceHover} max-[520px]:grid-cols-[minmax(0,1fr)] [&_div]:grid [&_div]:min-w-0 [&_div]:gap-0.5 [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-vui-fg-primary [&_span]:min-w-0 [&_span]:overflow-hidden [&_span]:text-ellipsis [&_span]:whitespace-nowrap [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary [&_code]:shrink-0 [&_code]:whitespace-nowrap [&_code]:font-mono [&_code]:[font-size:var(--vui-font-xs)] [&_code]:text-[var(--accent-warm-2)]`,
  historyPanel:
    "grid-rows-[auto_minmax(0,1fr)] max-[1200px]:[.workspaceOverview_&]:col-start-2 max-[1200px]:[.workspaceOverview_&]:row-[1/span_2] max-[1200px]:[.workspaceOverview_&]:grid-cols-1 max-[1200px]:[.workspaceOverview_&]:grid-rows-[auto_minmax(0,1fr)] max-[860px]:[.workspaceOverview_&]:col-auto max-[860px]:[.workspaceOverview_&]:row-auto",
  paneCollapsed: "overflow-hidden p-0 invisible",
  panelHeader: "flex items-center justify-between gap-2 [&_h2]:m-0 [&_h2]:text-[0.94rem]",
  countPill:
    "inline-flex min-h-6 items-center justify-center gap-1.5 whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_22%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] px-2 [font-size:var(--vui-font-xs)] text-[var(--accent-cool)]",
  inlineMeta:
    "inline-flex min-h-6 items-center justify-center gap-1.5 whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_22%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] px-2 [font-size:var(--vui-font-xs)] text-[var(--accent-cool)]",
  filterRow: "flex flex-wrap gap-1.5",
  selectionRow: "flex gap-1.5",
  filterButton:
    mutedControl,
  filterButtonActive: activeControl,
  selectionButton:
    mutedControl,
  fileList: "grid min-h-0 content-start gap-1.5 overflow-auto pr-1",
  commitList: "grid min-h-0 content-start gap-2.5 overflow-auto pr-1",
  fileButton:
    `grid w-full grid-cols-[22px_34px_minmax(0,1fr)] items-start gap-1.5 ${rowSurface} p-[6px] text-left text-vui-fg-primary ${rowSurfaceHover}`,
  fileButtonActive:
    "grid w-full grid-cols-[22px_34px_minmax(0,1fr)] items-start gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_10%,var(--vui-surface-row))] p-[6px] text-left text-vui-fg-primary shadow-[var(--vui-shadow-inset-accent)]",
  fileButtonSelected:
    "border-[color-mix(in_srgb,var(--state-success)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_8%,var(--vui-surface-row))]",
  fileStatus: "font-mono [font-size:var(--vui-font-xs)] text-[var(--accent-warm-2)]",
  fileCheckButton:
    "inline-grid h-5 min-h-5 w-5 min-w-5 place-items-center border-0 bg-transparent p-0 text-left text-[var(--accent-warm-2)]",
  fileCopyButton:
    "grid min-w-0 gap-1 border-0 bg-transparent p-0 text-left text-inherit [&_strong]:block [&_strong]:min-w-0 [&_strong]:max-w-full [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap",
  filePathText: "m-0 overflow-hidden text-ellipsis whitespace-nowrap [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  fileBadgeRow: "flex min-h-5 flex-wrap gap-[5px]",
  fileBadgeActive:
    "inline-flex min-h-[19px] items-center rounded-full border border-[color-mix(in_srgb,var(--accent-warm)_28%,transparent)] px-1.5 [font-size:var(--vui-font-xs)] leading-none text-[var(--accent-warm-2)]",
  fileBadgeSelected:
    "inline-flex min-h-[19px] items-center rounded-full border border-[color-mix(in_srgb,var(--state-success)_28%,transparent)] px-1.5 [font-size:var(--vui-font-xs)] leading-none text-[var(--state-success)]",
  diffPanel: "min-h-0 min-w-0",
  objectDetailPanel:
    "min-h-0 min-w-0 max-[1200px]:[.workspaceOverview_&]:col-start-1 max-[1200px]:[.workspaceOverview_&]:row-start-2 max-[860px]:[.workspaceOverview_&]:col-auto max-[860px]:[.workspaceOverview_&]:row-auto",
  emptyPreview:
    `grid h-full content-start justify-items-start gap-[7px] ${panelSurface} p-3.5 text-vui-fg-secondary [&_p]:m-0 [&_p]:[font-size:var(--vui-font-xs)] [&_p]:leading-tight [&_p]:text-vui-fg-secondary [&_strong]:text-[0.98rem] [&_strong]:text-vui-fg-primary [&_svg]:h-[18px] [&_svg]:w-[18px] [&_svg]:text-[var(--accent-cool)]`,
  emptyState: "m-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  // Single-column card with readable vertical rhythm: roomy padding, clear
  // inter-card gap (commitList), and distinct header / title / author rows.
  commitItem:
    `!grid h-auto min-h-[4.5rem] w-full min-w-0 grid-cols-1 auto-rows-auto content-start items-stretch justify-items-stretch gap-1.5 whitespace-normal ${rowSurface} px-2.5 py-2.5 text-left [color:var(--fg-primary)] ${rowSurfaceHover}`,
  commitSubject:
    "block m-0 min-h-[1.35em] min-w-0 max-w-full overflow-hidden text-ellipsis whitespace-nowrap font-semibold leading-snug [font-size:var(--vui-font-sm)] [color:var(--fg-primary)]",
  commitAuthor:
    "block m-0 mt-0.5 min-h-[1.2em] min-w-0 max-w-full overflow-hidden text-ellipsis whitespace-nowrap font-normal leading-tight [font-size:var(--vui-font-xs)] [color:var(--fg-secondary)]",
  objectItemActive:
    `border-[color-mix(in_srgb,var(--accent-cool)_40%,transparent)] ${vuiStateSelectedRowFillClass} shadow-[var(--vui-shadow-inset-accent)]`,
  manualCommitPanel:
    "grid min-h-0 max-h-[min(100%,calc(100dvh-178px))] content-start gap-2 overflow-auto border-b border-[var(--border-soft)] pb-2 max-[1200px]:row-span-2 max-[1200px]:border-b-0 max-[1200px]:border-r max-[1200px]:pb-0 max-[1200px]:pr-3 max-[860px]:row-auto max-[860px]:max-h-none max-[860px]:overflow-visible max-[860px]:border-b max-[860px]:border-r-0 max-[860px]:pb-3 max-[860px]:pr-0",
  commitScopeBox: `grid gap-2 ${rowSurface} p-[9px]`,
  scopeHeader:
    "flex items-start justify-between gap-2.5 [&_div]:grid [&_div]:min-w-0 [&_div]:gap-1 [&_div>span]:m-0 [&_div>span]:[font-size:var(--vui-font-xs)] [&_div>span]:leading-snug [&_div>span]:text-[var(--fg-tertiary)] [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[0.9rem] [&_strong]:text-[var(--fg-primary)]",
  scopeReady:
    "inline-flex min-h-[23px] items-center whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--state-success)_26%,transparent)] px-2 text-[var(--state-success)]",
  scopeList: "grid gap-1.5",
  scopeItem:
    "grid min-w-0 grid-cols-[42px_minmax(0,1fr)] items-center gap-2 [&_span]:font-mono [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-[var(--accent-warm-2)] [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:font-medium [&_strong]:text-[var(--fg-secondary)]",
  scopeEmpty: "m-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-tertiary)]",
  scopeMore: "m-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-tertiary)]",
  scopeWarning:
    "grid gap-1 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--state-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] p-[9px] [&_p]:m-0 [&_p]:[font-size:var(--vui-font-xs)] [&_p]:leading-snug [&_p]:text-[var(--fg-tertiary)] [&_span]:m-0 [&_span]:overflow-hidden [&_span]:text-ellipsis [&_span]:whitespace-nowrap [&_span]:[font-size:var(--vui-font-xs)] [&_span]:leading-snug [&_span]:text-[var(--fg-tertiary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--state-warning)]",
  messageField:
    "grid gap-[7px] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary [&_select]:min-h-[34px] [&_select]:w-full [&_select]:rounded-[var(--radius-control)] [&_select]:border [&_select]:border-[color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] [&_select]:bg-[color-mix(in_srgb,var(--vui-control-muted)_78%,transparent)] [&_select]:px-[9px] [&_select]:py-2 [&_select]:leading-snug [&_select]:text-vui-fg-primary [&_select:focus]:border-[color-mix(in_srgb,var(--accent-warm)_42%,transparent)] [&_select:focus]:outline-none [&_textarea]:min-h-24 [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-[var(--radius-control)] [&_textarea]:border [&_textarea]:border-[color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] [&_textarea]:bg-[color-mix(in_srgb,var(--vui-control-muted)_78%,transparent)] [&_textarea]:px-[9px] [&_textarea]:py-2 [&_textarea]:leading-snug [&_textarea]:text-vui-fg-primary [&_textarea:focus]:border-[color-mix(in_srgb,var(--accent-warm)_42%,transparent)] [&_textarea:focus]:outline-none",
  promptTemplateField: "[&_textarea]:min-h-[86px] [&_textarea]:font-mono [&_textarea]:[font-size:var(--vui-font-xs)]",
  modelDefaultRow:
    "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 [&_span]:min-w-0 [&_span]:overflow-hidden [&_span]:text-ellipsis [&_span]:whitespace-nowrap [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-[var(--fg-tertiary)]",
  modelActionRow: "grid-cols-[auto] justify-end",
  commitActions:
    "flex min-w-0 flex-wrap justify-end gap-1.5 max-[520px]:justify-start",
  secondaryButton:
    mutedControl,
  primaryButton:
    "h-[var(--vui-control-height-sm)] border-[color-mix(in_srgb,var(--accent-warm)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_16%,var(--vui-control-muted))] px-[9px] py-1.5 [font-size:var(--vui-font-xs)] text-[var(--accent-warm-2)] hover:border-[color-mix(in_srgb,var(--accent-warm)_52%,transparent)] hover:bg-[color-mix(in_srgb,var(--accent-warm)_22%,var(--vui-control-muted))] disabled:cursor-default disabled:opacity-55",
  commitNotice: "m-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--state-success)]",
  commitNoticeError: "m-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--state-error)]",
  commitBlockReason: "m-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--accent-warm-2)]",
  commitReady: "m-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--state-success)]",
  commitHeader:
    "mb-0.5 flex w-full min-w-0 items-center justify-between gap-2 leading-tight [&_code]:shrink-0 [&_code]:font-mono [&_code]:[font-size:var(--vui-font-xs)] [&_code]:[color:var(--accent-warm-2)] [&_span]:inline-flex [&_span]:min-w-0 [&_span]:shrink-0 [&_span]:items-center [&_span]:gap-[5px] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:leading-tight [&_span]:[color:var(--fg-tertiary)]",
} as const;
