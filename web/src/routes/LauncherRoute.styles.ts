import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
  vuiToolbarFillClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const panelSurface = `${vuiFlatPanelClass}`;
const rowSurface = `${vuiOpaqueRowClass}`;
const rowSurfaceMuted = "rounded-md border border-vui-border-subtle bg-vui-surface-row";
const rowSurfaceHover = "hover:border-vui-border-soft hover:!bg-[var(--vui-surface-row-hover)]";
const mutedControl =
  "inline-flex min-h-7 w-fit max-w-full flex-none items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-vui-border-soft bg-vui-control-muted px-2 [font-size:var(--vui-font-xs)] leading-none text-vui-fg-secondary no-underline hover:border-vui-border-soft hover:bg-vui-control-muted-hover hover:text-vui-fg-primary disabled:cursor-default disabled:opacity-55 [&[data-vui]]:min-w-0";
const primaryControl =
  "inline-flex min-h-7 w-fit max-w-full flex-none items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-primary)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-primary)_12%,var(--vui-control-muted))] px-2 [font-size:var(--vui-font-xs)] leading-none text-vui-fg-primary no-underline hover:border-[color-mix(in_srgb,var(--accent-primary)_44%,transparent)] hover:bg-[color-mix(in_srgb,var(--accent-primary)_18%,var(--vui-control-muted))] disabled:cursor-default disabled:opacity-55 [&[data-vui]]:min-w-0";
const dangerControl =
  "border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[color-mix(in_srgb,var(--danger)_9%,var(--vui-control-muted))] text-[color-mix(in_srgb,var(--danger)_74%,var(--vui-fg-primary))] hover:border-[color-mix(in_srgb,var(--danger)_52%,transparent)] hover:bg-[color-mix(in_srgb,var(--danger)_14%,var(--vui-control-muted))] hover:text-vui-fg-primary";
const panelHeaderText =
  "[&_span]:[font-size:var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-vui-fg-primary";

export const launcherRouteStyles = {
  route:
    `grid h-full min-h-full max-w-full content-start overflow-y-auto overflow-x-hidden overscroll-contain pb-[max(12px,env(safe-area-inset-bottom))] text-vui-fg-primary [scrollbar-gutter:stable] [--accent-primary:var(--accent-warm)] [--danger:var(--state-error)] [&_[data-vui=button]]:w-fit [&_[data-vui=button]]:[max-width:100%] [&_[data-vui=button]]:[white-space:nowrap] ${vuiWorkspaceFillClass}`,
  header:
    "mx-2 mt-2 min-w-0 border-[var(--vui-border-subtle)] !bg-transparent !shadow-none !backdrop-blur-none",
  panelEyebrow: "m-0 [font-size:var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary",
  statusBar:
    "grid w-full max-w-none min-w-0 grid-cols-[minmax(0,1fr)_max-content] items-center gap-2 max-[1200px]:grid-cols-[minmax(0,1fr)] max-[1200px]:justify-items-stretch",
  statusBarReason:
    `grid min-h-7 min-w-0 grid-cols-[minmax(76px,max-content)_minmax(94px,max-content)_minmax(0,1fr)] items-center gap-1.5 ${rowSurface} px-2 data-[tone=success]:border-[color-mix(in_srgb,var(--state-success)_34%,transparent)] data-[tone=warning]:border-[color-mix(in_srgb,var(--state-warning)_38%,transparent)] data-[tone=error]:border-[color-mix(in_srgb,var(--state-error)_38%,transparent)] max-[860px]:grid-cols-[minmax(0,1fr)] ${panelHeaderText} [&_span]:whitespace-nowrap [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-vui-fg-secondary max-[860px]:[&_span]:whitespace-normal max-[860px]:[&_span]:overflow-visible max-[860px]:[&_span]:overflow-wrap-anywhere max-[860px]:[&_strong]:whitespace-normal max-[860px]:[&_strong]:overflow-visible max-[860px]:[&_strong]:overflow-wrap-anywhere max-[860px]:[&_small]:whitespace-normal max-[860px]:[&_small]:overflow-visible max-[860px]:[&_small]:overflow-wrap-anywhere`,
  statusBarActions:
    "flex min-w-0 flex-wrap items-center justify-end gap-1.5 max-[1200px]:justify-start",
  primaryButton: primaryControl,
  iconButton: mutedControl,
  statusBarButton: mutedControl,
  dangerButton: dangerControl,
  summaryStrip: "grid grid-cols-4 gap-1.5 px-2 pt-2 max-[1200px]:grid-cols-2 max-[620px]:grid-cols-1",
  userGuide:
    `mx-2 mt-1.5 grid min-w-0 grid-cols-[max-content_minmax(132px,max-content)_max-content] items-center gap-2 ${panelSurface} px-2 py-1.5 data-[tone=success]:border-[color-mix(in_srgb,var(--state-success)_38%,transparent)] data-[tone=warning]:border-[color-mix(in_srgb,var(--state-warning)_42%,transparent)] data-[tone=error]:border-[color-mix(in_srgb,var(--state-error)_42%,transparent)] max-[1200px]:grid-cols-[max-content_minmax(132px,max-content)_minmax(0,1fr)] max-[860px]:grid-cols-[minmax(0,1fr)] ${panelHeaderText} [&_em]:min-w-0 [&_em]:truncate [&_em]:[font-size:var(--vui-font-xs)] [&_em]:not-italic [&_em]:text-vui-fg-secondary max-[1200px]:[&_em]:col-[2/-1] max-[860px]:[&_em]:col-auto max-[860px]:[&_em]:whitespace-normal max-[860px]:[&_em]:overflow-visible max-[860px]:[&_em]:overflow-wrap-anywhere`,
  dangerZone:
    `mx-2 mt-1.5 grid min-w-0 grid-cols-[max-content_minmax(0,1fr)_max-content] items-center gap-2 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--danger)_30%,transparent)] bg-[color-mix(in_srgb,var(--danger)_5%,var(--vui-surface-panel))] px-2 py-1.5 max-[860px]:grid-cols-[minmax(0,1fr)] [&_span]:whitespace-nowrap [&_span]:[font-size:var(--vui-font-xs)] [&_span]:font-bold [&_span]:text-[color-mix(in_srgb,var(--danger)_72%,var(--vui-fg-primary))] [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-vui-fg-secondary max-[860px]:[&_small]:whitespace-normal max-[860px]:[&_small]:overflow-visible max-[860px]:[&_small]:overflow-wrap-anywhere`,
  dangerActions: "flex min-w-0 justify-end max-[860px]:justify-start",
  settingsStrip:
    `mx-2 mt-1.5 grid min-h-0 min-w-0 max-w-full grid-cols-[minmax(104px,0.76fr)_minmax(92px,0.6fr)_repeat(3,minmax(74px,0.5fr))_max-content_minmax(96px,0.62fr)_minmax(100px,0.64fr)_max-content_max-content_max-content] items-end gap-1 self-start overflow-hidden ${panelSurface} px-2 py-1.5 max-[1320px]:grid-cols-[minmax(112px,max-content)_minmax(118px,max-content)_repeat(2,minmax(92px,1fr))_max-content] max-[1040px]:grid-cols-[repeat(2,minmax(0,1fr))] max-[620px]:grid-cols-[minmax(0,1fr)] [&>small]:col-span-full`,
  settingsHeader:
    "grid self-center gap-0.5 [&>span]:[font-size:var(--vui-font-xs)] [&>span]:uppercase [&>span]:tracking-[0.06em] [&>span]:text-[var(--fg-tertiary)] [&>strong]:min-w-0 [&>strong]:truncate [&>strong]:[font-size:var(--vui-font-xs)] [&>strong]:text-[var(--fg-primary)] [&>small]:min-w-0 [&>small]:truncate [&>small]:[font-size:var(--vui-font-xs)] [&>small]:text-[var(--fg-secondary)]",
  settingField:
    "grid min-w-0 gap-[3px] [&>span]:[font-size:var(--vui-font-xs)] [&>span]:uppercase [&>span]:tracking-[0.06em] [&>span]:text-[var(--fg-tertiary)] [&>small]:min-w-0 [&>small]:truncate [&>small]:[font-size:var(--vui-font-xs)] [&>small]:text-[var(--fg-secondary)] [&_input]:min-h-7 [&_input]:w-full [&_input]:min-w-0 [&_input]:rounded-[var(--radius-control)] [&_input]:border [&_input]:border-[var(--border-soft)] [&_input]:bg-[var(--vui-surface-row)] [&_input]:px-[7px] [&_input]:py-[3px] [&_input]:[font-size:var(--vui-font-xs)] [&_input]:text-[var(--fg-primary)] [&_select]:min-h-7 [&_select]:w-full [&_select]:min-w-0 [&_select]:rounded-[var(--radius-control)] [&_select]:border [&_select]:border-[var(--border-soft)] [&_select]:bg-[var(--vui-surface-row)] [&_select]:px-[7px] [&_select]:py-[3px] [&_select]:[font-size:var(--vui-font-xs)] [&_select]:text-[var(--fg-primary)]",
  settingToggle:
    "inline-flex min-h-7 min-w-0 items-center gap-1.5 whitespace-nowrap pb-px [&>span]:[font-size:var(--vui-font-xs)] [&>span]:uppercase [&>span]:tracking-[0.06em] [&>span]:text-[var(--fg-tertiary)] [&_input]:m-0 [&_input]:h-3.5 [&_input]:w-3.5",
  settingsSaveButton:
    `${primaryControl} justify-self-start py-[3px]`,
  settingError: "col-span-full [font-size:var(--vui-font-xs)] text-[var(--state-error)]",
  segmentedControl: `inline-flex min-w-0 max-w-full flex-wrap items-center gap-0.5 rounded-[var(--radius-control)] border border-vui-border-subtle ${vuiToolbarFillClass} p-0.5 max-[860px]:justify-self-start [&_button]:min-h-[25px] [&_button]:rounded-[calc(var(--radius-control)-2px)] [&_button]:border-0 [&_button]:bg-transparent [&_button]:px-[7px] [&_button]:py-[3px] [&_button]:[font-size:var(--vui-font-xs)] [&_button]:leading-none [&_button]:text-vui-fg-secondary [&_button[data-active=true]]:bg-[color-mix(in_srgb,var(--accent-primary)_12%,var(--vui-control-muted))] [&_button[data-active=true]]:text-vui-fg-primary [&_button:disabled]:cursor-default [&_button:disabled]:opacity-60 [&_button[data-vui]]:min-w-0 [&_button[data-vui]_[data-slot=vui-button-content]]:inline-flex [&_button[data-vui]_[data-slot=vui-button-content]]:items-center [&_button[data-vui]_[data-slot=vui-button-content]]:gap-[5px] [&_button[data-vui]_[data-slot=vui-button-label]]:inline-flex [&_button[data-vui]_[data-slot=vui-button-label]]:items-center [&_button[data-vui]_[data-slot=vui-button-label]]:gap-[5px]`,
  developerPanel:
    `mx-2 mt-1.5 grid min-h-0 min-w-0 max-w-full gap-1.5 overflow-hidden ${panelSurface} px-2 py-1.5 data-[enabled=true]:border-[color-mix(in_srgb,var(--state-warning)_42%,transparent)]`,
  developerPanelHeader:
    "flex min-w-0 items-center justify-between gap-2 max-[860px]:flex-col max-[860px]:items-start [&>div]:grid [&>div]:min-w-0 [&>div]:gap-0.5 [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)]",
  developerGrid: "grid min-h-0 min-w-0 grid-cols-[clamp(120px,14vw,160px)_minmax(0,1fr)_clamp(240px,22vw,360px)] gap-1.5 max-[1200px]:grid-cols-[minmax(0,1fr)]",
  developerStatus:
    `grid min-w-0 content-start gap-1 ${rowSurface} p-[7px] data-[tone=warning]:border-[color-mix(in_srgb,var(--state-warning)_42%,transparent)] ${panelHeaderText} [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-vui-fg-secondary`,
  developerNoise: `grid min-h-0 min-w-0 gap-1.5 overflow-hidden ${rowSurface} p-[7px]`,
  developerNoiseHeader: "flex min-w-0 items-center justify-between gap-2 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-[var(--fg-tertiary)]",
  compactButton:
    "inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-[5px] rounded-[var(--radius-control)] border border-vui-border-soft bg-vui-control-muted px-1.5 py-[3px] [font-size:var(--vui-font-xs)] text-vui-fg-secondary hover:bg-vui-control-muted-hover disabled:cursor-default disabled:opacity-60 [&[data-vui]]:min-w-0",
  // Legacy style map key; live panels use PersistedHeightListShell.
  noiseItemGrid: "grid min-h-0 min-w-0 grid-cols-4 gap-[5px] overflow-auto pr-0.5 [scrollbar-gutter:stable] max-[860px]:grid-cols-[minmax(0,1fr)]",
  noiseItem:
    "grid min-w-0 gap-0.5 rounded-md border border-[color-mix(in_srgb,var(--border-soft)_72%,transparent)] px-1.5 py-[5px] data-[protected=true]:opacity-80 [&_span]:min-w-0 [&_span]:truncate [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-[var(--fg-secondary)] [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-[var(--fg-secondary)]",
  // Legacy key; live cleanup consoles use PersistedHeightListShell on panel styles.
  cleanupConsole: `grid min-h-0 min-w-0 gap-1.5 overflow-auto ${rowSurface} p-[7px] [scrollbar-gutter:stable]`,
  cleanupMetrics:
    "flex min-w-0 flex-wrap items-center gap-1.5 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-[var(--fg-tertiary)] [&_strong]:text-[var(--fg-primary)] max-[620px]:grid max-[620px]:grid-cols-[minmax(0,1fr)]",
  cleanupActions: "flex min-w-0 flex-wrap items-center justify-start gap-1.5",
  cleanupPlan:
    "grid min-w-0 gap-[3px] rounded-md border border-[color-mix(in_srgb,var(--state-warning)_34%,var(--border-soft))] bg-[color-mix(in_srgb,var(--state-warning)_6%,var(--vui-surface-row))] p-1.5 [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-[var(--fg-secondary)] [&_li]:min-w-0 [&_li]:truncate [&_li]:[font-size:var(--vui-font-xs)] [&_li]:text-[var(--fg-secondary)] [&_ul]:m-0 [&_ul]:grid [&_ul]:min-w-0 [&_ul]:gap-0.5 [&_ul]:pl-4",
  metric: `grid min-w-0 grid-cols-[minmax(72px,max-content)_minmax(0,1fr)] items-baseline gap-x-[7px] gap-y-0.5 rounded-[7px] border border-[color-mix(in_srgb,var(--border-soft)_90%,var(--vui-surface-base))] ${vuiFlatPanelClass} px-[9px] py-[7px] data-[tone=success]:border-[color-mix(in_srgb,var(--state-success)_38%,var(--border-soft))] data-[tone=warning]:border-[color-mix(in_srgb,var(--state-warning)_42%,var(--border-soft))] data-[tone=error]:border-[color-mix(in_srgb,var(--state-error)_42%,var(--border-soft))] max-[620px]:grid-cols-[82px_minmax(0,1fr)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-[var(--fg-tertiary)] [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:text-[var(--fg-primary)] [&_small]:col-span-full [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:leading-tight [&_small]:text-[var(--fg-secondary)]`,
  notice:
    `mx-2 mt-1.5 grid gap-0.5 ${panelSurface} px-2 py-1.5 [font-size:var(--vui-font-xs)] text-vui-fg-secondary data-[tone=success]:border-[color-mix(in_srgb,var(--state-success)_34%,transparent)] data-[tone=success]:text-[var(--state-success)] data-[tone=warning]:border-[color-mix(in_srgb,var(--state-warning)_34%,transparent)] data-[tone=warning]:text-[var(--state-warning)] data-[tone=error]:border-[color-mix(in_srgb,var(--state-error)_34%,transparent)] data-[tone=error]:text-[var(--state-error)] [&_span]:min-w-0 [&_span]:truncate [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary`,
  workspace:
    `grid min-h-0 grid-cols-[minmax(0,1fr)_auto_var(--launcher-rail-width,clamp(300px,26vw,420px))] auto-rows-min gap-1.5 overflow-visible px-2 pb-[max(14px,env(safe-area-inset-bottom))] pt-1.5 max-[1200px]:grid-cols-[minmax(0,1fr)] ${vuiWorkspaceFillClass}`,
  // Wave 4B: shared PaneResizeHandle visual.
  railResizeHandle:
    "max-[1200px]:hidden",
  panel: `block min-h-0 min-w-0 overflow-hidden ${panelSurface} px-2 py-[7px]`,
  matrixPanel: "col-auto min-h-0",
  panelHeader:
    "flex min-h-0 min-w-0 items-baseline justify-between gap-2.5 border-b border-[var(--border-soft)] pb-1.5 [&>*]:min-w-0 [&_strong]:flex-auto [&_strong]:truncate [&_strong]:text-right [&_strong]:text-[var(--fg-primary)]",
  guardStrip: `my-1.5 grid min-w-0 grid-cols-[minmax(82px,max-content)_minmax(128px,max-content)_minmax(0,1fr)] items-center gap-[7px] rounded-[7px] border border-[var(--border-soft)] ${vuiOpaqueRowClass} px-2 py-1.5 data-[tone=success]:border-[color-mix(in_srgb,var(--state-success)_34%,var(--border-soft))] data-[tone=warning]:border-[color-mix(in_srgb,var(--state-warning)_40%,var(--border-soft))] max-[620px]:grid-cols-[minmax(0,1fr)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-[var(--fg-tertiary)] [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-[var(--fg-secondary)]`,
  specGrid:
    "mt-2 grid min-w-0 grid-cols-[minmax(72px,max-content)_minmax(0,1fr)] gap-x-2.5 gap-y-1.5 [&_dt]:m-0 [&_dt]:min-w-0 [&_dt]:[font-size:var(--vui-font-xs)] [&_dt]:uppercase [&_dt]:tracking-[0.06em] [&_dt]:text-[var(--fg-tertiary)] [&_dd]:m-0 [&_dd]:min-w-0 [&_dd]:truncate [&_dd]:[font-size:var(--vui-font-xs)] [&_dd]:leading-tight [&_dd]:text-[var(--fg-primary)]",
  diagnosticsGrid:
    "grid min-w-0 grid-cols-[minmax(72px,max-content)_minmax(0,1fr)] gap-x-2.5 gap-y-1.5 px-2.5 pb-2.5 [&_dt]:m-0 [&_dt]:min-w-0 [&_dt]:[font-size:var(--vui-font-xs)] [&_dt]:uppercase [&_dt]:tracking-[0.06em] [&_dt]:text-[var(--fg-tertiary)] [&_dd]:m-0 [&_dd]:min-w-0 [&_dd]:truncate [&_dd]:[font-size:var(--vui-font-xs)] [&_dd]:leading-tight [&_dd]:text-[var(--fg-primary)]",
  statusTable: `mt-1.5 grid min-w-0 overflow-hidden ${rowSurfaceMuted}`,
  guardianTable: `mt-1.5 grid min-w-0 overflow-hidden ${rowSurfaceMuted}`,
  statusHead: `grid min-w-0 grid-cols-[minmax(140px,0.9fr)_minmax(92px,0.62fr)_minmax(160px,0.95fr)_minmax(0,1.7fr)] items-center gap-[7px] border-b border-[var(--border-soft)] ${vuiOpaqueRowClass} px-2 py-1.5 [font-size:var(--vui-font-xs)] uppercase tracking-[0.06em] text-[var(--fg-tertiary)] max-[860px]:grid-cols-[minmax(118px,0.9fr)_minmax(82px,0.7fr)_minmax(0,1.4fr)] max-[860px]:[&>span:nth-child(3)]:hidden max-[620px]:grid-cols-[minmax(0,1fr)] max-[620px]:[&>span:nth-child(n+3)]:hidden`,
  statusRow:
    "grid min-w-0 grid-cols-[minmax(140px,0.9fr)_minmax(92px,0.62fr)_minmax(160px,0.95fr)_minmax(0,1.7fr)] items-center gap-[7px] border-t border-[color-mix(in_srgb,var(--border-soft)_72%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-base)_74%,var(--vui-surface-row))] px-2 py-1.5 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] first:border-t-0 data-[tone=success]:border-l-2 data-[tone=success]:border-l-[var(--state-success)] data-[tone=warning]:border-l-2 data-[tone=warning]:border-l-[var(--state-warning)] data-[tone=error]:border-l-2 data-[tone=error]:border-l-[var(--state-error)] max-[860px]:grid-cols-[minmax(118px,0.9fr)_minmax(82px,0.7fr)_minmax(0,1.4fr)] max-[860px]:[&>span:nth-child(3)]:hidden max-[620px]:grid-cols-[minmax(0,1fr)] max-[620px]:[&>span:nth-child(n+3)]:hidden [&_span]:min-w-0 [&_span]:truncate [&_strong]:text-[var(--fg-primary)]",
  guardianHead: `grid min-w-0 grid-cols-[minmax(178px,1fr)_minmax(120px,0.7fr)_minmax(84px,0.52fr)_minmax(0,1.7fr)] items-center gap-[7px] border-b border-[var(--border-soft)] ${vuiOpaqueRowClass} px-2 py-1.5 [font-size:var(--vui-font-xs)] uppercase tracking-[0.06em] text-[var(--fg-tertiary)] max-[860px]:grid-cols-[minmax(140px,1fr)_minmax(96px,0.65fr)_minmax(82px,0.5fr)_minmax(0,1.4fr)] max-[620px]:grid-cols-[minmax(0,1fr)] max-[620px]:[&>span:nth-child(n+3)]:hidden`,
  guardianRow:
    "grid min-w-0 grid-cols-[minmax(178px,1fr)_minmax(120px,0.7fr)_minmax(84px,0.52fr)_minmax(0,1.7fr)] items-center gap-[7px] border-t border-[color-mix(in_srgb,var(--border-soft)_72%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-base)_74%,var(--vui-surface-row))] px-2 py-1.5 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] first:border-t-0 data-[tone=success]:border-l-2 data-[tone=success]:border-l-[var(--state-success)] data-[tone=warning]:border-l-2 data-[tone=warning]:border-l-[var(--state-warning)] data-[tone=error]:border-l-2 data-[tone=error]:border-l-[var(--state-error)] max-[860px]:grid-cols-[minmax(140px,1fr)_minmax(96px,0.65fr)_minmax(82px,0.5fr)_minmax(0,1.4fr)] max-[620px]:grid-cols-[minmax(0,1fr)] max-[620px]:[&>span:nth-child(n+3)]:hidden [&_span]:min-w-0 [&_span]:truncate [&_strong]:text-[var(--fg-primary)]",
  commandLine:
    `mt-2 grid min-w-0 grid-cols-[88px_minmax(0,1fr)] gap-x-2 gap-y-[5px] ${rowSurface} px-[9px] py-[7px] max-[620px]:grid-cols-[minmax(0,1fr)] ${panelHeaderText} [&_small]:col-start-2 [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-vui-fg-secondary max-[620px]:[&_small]:col-start-1`,
  recoveryLine:
    `mt-2 grid min-w-0 grid-cols-[88px_minmax(0,1fr)] gap-x-2 gap-y-[5px] ${rowSurface} px-[9px] py-[7px] data-[tone=success]:border-[color-mix(in_srgb,var(--state-success)_36%,transparent)] data-[tone=warning]:border-[color-mix(in_srgb,var(--state-warning)_42%,transparent)] max-[620px]:grid-cols-[minmax(0,1fr)] ${panelHeaderText} [&_small]:col-start-2 [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-vui-fg-secondary max-[620px]:[&_small]:col-start-1`,
  compactList: "mt-2 grid min-w-0 gap-[5px] [&>small]:text-[var(--fg-secondary)]",
  compactItem:
    "grid min-w-0 grid-cols-[minmax(150px,0.74fr)_minmax(0,1fr)] gap-2 border-b border-[color-mix(in_srgb,var(--border-soft)_68%,transparent)] py-[5px] data-[tone=success]:[&_strong]:text-[var(--state-success)] data-[tone=error]:[&_strong]:text-[var(--state-error)] max-[620px]:grid-cols-[minmax(0,1fr)] [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-[var(--fg-secondary)]",
  guardianSummary:
    "mt-2 grid min-w-0 grid-cols-[minmax(0,1fr)_repeat(3,max-content)_auto] items-center gap-2 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] max-[860px]:grid-cols-2 max-[860px]:[&_span]:col-span-full max-[620px]:grid-cols-[minmax(0,1fr)] [&_span]:min-w-0 [&_span]:truncate [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:font-semibold [&_strong]:text-[var(--fg-primary)]",
  diagnosticsPanel:
    "col-auto block min-h-0 p-0 [&_summary]:flex [&_summary]:min-w-0 [&_summary]:cursor-pointer [&_summary]:items-baseline [&_summary]:justify-between [&_summary]:gap-2.5 [&_summary]:px-2.5 [&_summary]:py-2 [&_summary]:text-[var(--fg-secondary)] [&_summary_span]:[font-size:var(--vui-font-xs)] [&_summary_span]:uppercase [&_summary_span]:tracking-[0.08em] [&_summary_span]:text-[var(--fg-tertiary)] [&_summary_strong]:text-[var(--fg-primary)]",
  diagnosticsBody: "grid min-w-0 grid-cols-2 gap-2 px-2.5 pb-2.5 max-[620px]:grid-cols-[minmax(0,1fr)]",
  diagnosticSection:
    `min-w-0 ${rowSurface} ${rowSurfaceHover} p-2`,
  spin: "animate-spin",
} as const;
