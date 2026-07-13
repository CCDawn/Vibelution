const styles = {
  surface: "grid min-h-[min(520px,calc(100dvh_-_96px))] w-full p-3 sm:p-4",
  surfaceDefault: "place-items-center",
  surfaceStructured: "content-start",
  panel: [
    "w-[min(360px,100%)] rounded-[var(--radius-panel)] border border-vui-border-subtle bg-vui-surface-glass",
    "px-[18px] py-4 text-vui-fg-primary shadow-none backdrop-blur-md",
  ].join(" "),
  structuredPanel: [
    "grid min-h-[min(540px,calc(100dvh_-_120px))] w-full gap-3 overflow-auto rounded-[var(--radius-panel)] md:overflow-hidden",
    "border border-vui-border-subtle bg-vui-surface-panel p-3 text-vui-fg-primary shadow-none",
  ].join(" "),
  loadingHeader: "flex min-w-0 items-center gap-2.5",
  spinnerFrame: [
    "grid size-8 shrink-0 place-items-center rounded-[var(--radius-control)] border",
    "border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-row))] text-[var(--accent-cool)]",
  ].join(" "),
  spinner: "animate-spin motion-reduce:animate-none",
  loadingCopy: "grid min-w-0 gap-0.5",
  title: "block text-[var(--vui-font-chat)] font-bold leading-[1.35]",
  meta: "block text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-tertiary",
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
    "grid content-start gap-2 rounded-[var(--radius-control)] border border-vui-border-subtle",
    "bg-vui-surface-row p-2.5",
  ].join(" "),
  navigationRow: "block h-8 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-panel",
  navigationRowActive: [
    "block h-8 rounded-[var(--radius-control)] border",
    "border-[color-mix(in_srgb,var(--accent-cool)_32%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-row))]",
  ].join(" "),
  contentPanel: "grid min-h-0 content-start gap-3 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row p-3",
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
    "border-vui-border-subtle bg-[color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)] p-4 sm:grid-cols-3",
  ].join(" "),
  canvasNode: "flex min-w-0 items-center gap-2 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-panel p-2.5",
  nodeAvatar: "block size-8 shrink-0 animate-pulse rounded-full bg-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] motion-reduce:animate-none",
  nodeCopy: "grid min-w-0 flex-1 gap-2",
  inspectorPanel: "grid min-h-[240px] content-start gap-3 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row p-3",
  inspectorRow: "grid gap-2 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-panel p-2.5",
} as const;

export default styles;
