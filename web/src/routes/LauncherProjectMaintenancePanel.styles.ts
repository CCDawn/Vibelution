import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const panelSurface = `${vuiFlatPanelClass}`;
const rowSurface = `${vuiOpaqueRowClass}`;
const mutedControl =
  "inline-flex min-h-7 w-fit max-w-full flex-none items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-vui-border-soft bg-vui-control-muted px-2 [font-size:var(--vui-font-xs)] leading-none text-vui-fg-secondary no-underline hover:border-vui-border-soft hover:bg-vui-control-muted-hover hover:text-vui-fg-primary disabled:cursor-default disabled:opacity-55 [&[data-vui]]:min-w-0";
const primaryControl =
  "min-h-7 w-fit max-w-full flex-none gap-1.5 px-2 [font-size:var(--vui-font-xs)] leading-none [&[data-vui]]:min-w-0";

const styles = {
  // Wave 6F: height from PersistedHeightListShell, not fixed max-h.
  cleanupConsole: `col-span-full grid min-h-0 min-w-0 gap-1.5 overflow-auto ${rowSurface} p-2 [scrollbar-gutter:stable]`,
  cleanupConsoleResizeHandle:
    "cleanupConsoleResizeHandle",
  cleanupMetrics: "flex min-w-0 flex-wrap items-center gap-1.5 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-[var(--fg-tertiary)] [&_strong]:text-[var(--fg-primary)] max-[620px]:grid max-[620px]:grid-cols-[minmax(0,1fr)]",
  cleanupPlan: "grid min-w-0 gap-1 rounded-md border border-[color-mix(in_srgb,var(--state-warning)_34%,var(--border-soft))] bg-[color-mix(in_srgb,var(--state-warning)_6%,var(--vui-surface-row))] p-1.5 [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-[var(--fg-secondary)] [&_li]:min-w-0 [&_li]:truncate [&_li]:[font-size:var(--vui-font-xs)] [&_li]:text-[var(--fg-secondary)] [&_ul]:m-0 [&_ul]:grid [&_ul]:min-w-0 [&_ul]:gap-0.5 [&_ul]:pl-4",
  developerGrid: "grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] gap-1.5",
  developerNoise: `grid min-h-0 min-w-0 gap-1.5 overflow-hidden ${rowSurface} p-2`,
  developerNoiseHeader: "flex min-w-0 items-start justify-between gap-2 [&_small]:min-w-0 [&_small]:text-vui-fg-secondary",
  developerPanel: `mx-2 mt-1.5 grid min-h-0 min-w-0 max-w-full gap-1.5 overflow-hidden ${panelSurface} px-2 py-1.5 data-[enabled=true]:border-[color-mix(in_srgb,var(--state-warning)_42%,transparent)]`,
  developerPanelHeader: "flex min-w-0 items-center justify-between gap-2 max-[860px]:flex-col max-[860px]:items-start [&>div]:grid [&>div]:min-w-0 [&>div]:gap-0.5 [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)]",
  developerStatus: `grid min-w-0 content-start gap-1 ${rowSurface} p-2 data-[tone=warning]:border-[color-mix(in_srgb,var(--state-warning)_42%,transparent)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-vui-fg-tertiary [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-vui-fg-primary [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-vui-fg-secondary`,
  emptyList: "min-w-0 [font-size:var(--vui-font-xs)] text-vui-fg-tertiary",
  iconButton: mutedControl,
  noiseItem: "grid min-w-0 gap-0.5 rounded-md border border-[color-mix(in_srgb,var(--border-soft)_72%,transparent)] px-1.5 py-1 data-[protected=true]:opacity-80 [&_span]:min-w-0 [&_span]:truncate [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-[var(--fg-secondary)] [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)] [&_small]:min-w-0 [&_small]:truncate [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-[var(--fg-secondary)]",
  // Wave 6G: height from PersistedHeightListShell, not fixed max-h.
  noiseItemGrid: "grid min-h-0 min-w-0 grid-cols-4 gap-1 overflow-auto pr-0.5 [scrollbar-gutter:stable] max-[860px]:grid-cols-[minmax(0,1fr)]",
  noiseItemGridResizeHandle:
    "noiseItemGridResizeHandle",
  maintenanceActions: "flex min-w-0 justify-end gap-1.5 max-[620px]:flex-wrap",
  profileHeading: "grid min-w-0 gap-0.5 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:font-medium [&_span]:text-vui-fg-primary [&_small]:[font-size:var(--vui-font-xs)] [&_small]:text-vui-fg-secondary",
  primaryButton: primaryControl,
  segmentedControl: `!grid w-full min-w-0 max-w-full !grid-cols-2 gap-0.5 ${vuiOpaqueRowClass} p-0.5`,
  segmentedTrigger: [
    "min-h-9 !w-full min-w-0 !rounded-[calc(var(--radius-control)-2px)] !border-0 !bg-transparent !px-2 !py-1",
    "[font-size:var(--vui-font-xs)] leading-none text-[var(--fg-secondary)]",
    "data-[state=active]:!bg-[color-mix(in_srgb,var(--accent-primary)_11%,var(--vui-surface-panel))]",
    "data-[state=active]:!text-[var(--fg-primary)] data-[state=active]:shadow-none",
    "disabled:cursor-default disabled:opacity-60",
  ].join(" "),
  spin: "animate-spin",
} as const;

export default styles;
