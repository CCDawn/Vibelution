const styles = {
  workspaceFill: "flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden",
  surface: "grid min-h-[min(520px,calc(100dvh_-_96px))] w-full p-3 sm:p-4",
  surfaceQuiet: "min-h-[min(520px,calc(100dvh_-_96px))] w-full",
  surfaceStructured: "content-start",
  srOnly: "sr-only",
  structuredPanel: [
    "grid h-full min-h-0 w-full gap-0 overflow-auto md:overflow-hidden",
    "bg-transparent p-0 text-vui-fg-primary shadow-none",
  ].join(" "),
  skeletonLine: [
    "block h-2.5 w-full max-w-[340px] animate-pulse rounded-full",
    "bg-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] motion-reduce:animate-none",
  ].join(" "),
  skeletonLineCompact: [
    "block h-2.5 w-[58%] max-w-[210px] animate-pulse rounded-full",
    "bg-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] motion-reduce:animate-none",
  ].join(" "),
  configGrid: "grid min-h-0 grid-cols-1 gap-3 md:grid-cols-[minmax(168px,0.24fr)_minmax(0,1fr)]",
  navigationPanel: [
    "vui-workbench-rail grid content-start gap-2 p-2.5",
  ].join(" "),
  navigationRow: "block h-8 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-panel",
  navigationRowActive: [
    "block h-8 rounded-[var(--radius-control)] border",
    "border-[color-mix(in_srgb,var(--accent-cool)_32%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-row))]",
  ].join(" "),
  contentPanel: "vui-workbench-pane grid min-h-0 content-start gap-3 p-3",
  sectionHeading: "flex min-w-0 items-start justify-between gap-3 border-b border-vui-border-subtle pb-3",
  headingCopy: "grid min-w-0 flex-1 gap-2",
  headingAction: "block h-8 w-20 shrink-0 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-panel",
  configCards: "grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2",
  configCard: "grid min-h-28 content-start gap-3 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-panel p-3",
  teamsStack: "grid min-h-0 gap-3",
  statusStrip: "grid grid-cols-2 gap-2 sm:grid-cols-4",
  statusItem: "grid h-10 content-center rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row px-2.5",
  teamsGrid: "grid min-h-0 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(250px,0.32fr)]",
  canvasPanel: "grid min-h-[390px] content-start gap-3 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row p-3",
  canvasBoard: [
    "grid min-h-[300px] grid-cols-2 content-center items-center gap-3 rounded-[var(--radius-control)] border border-dashed",
    "border-vui-border-subtle !bg-[var(--vui-surface-panel)] p-4 sm:grid-cols-3",
  ].join(" "),
  canvasNode: "flex min-w-0 items-center gap-2 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-panel p-2.5",
  nodeAvatar: "block size-8 shrink-0 animate-pulse rounded-full bg-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] motion-reduce:animate-none",
  nodeCopy: "grid min-w-0 flex-1 gap-2",
  inspectorPanel: "grid min-h-[240px] content-start gap-3 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row p-3",
  inspectorRow: "grid gap-2 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-panel p-2.5",
} as const;

export default styles;
