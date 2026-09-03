const styles: Record<string, string> = {
  // The panel lives inside the 300–520px inspector pane, so all multi-column
  // grids below respond to the container (@container), never the viewport.
  workspace: "@container grid gap-4 text-[var(--fg-primary)]",
  archiveWorkspace: "h-full min-h-0 overflow-auto bg-[var(--surface-canvas)] p-4 sm:p-6",
  archiveMetrics: "w-full [&>div]:min-w-[140px] [&>div]:flex-1",
  archiveGrid: "grid items-start gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(300px,0.65fr)]",
  archiveError: "grid min-h-60 content-center justify-items-start gap-4 bg-[var(--surface-canvas)] p-5 sm:p-8",
  archiveTimeline: "m-0 grid list-none gap-2 p-0",
  archiveTimelineItem: "grid grid-cols-[10px_minmax(0,1fr)] items-start gap-3 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3",
  archiveTimelineMarker: "mt-1.5 size-2 rounded-full bg-[var(--accent-cool)]",
  archiveTimelineTopline: "flex flex-wrap items-center justify-between gap-2",
  archiveTimelineDetail: "mt-1 [font-size:var(--vui-font-xs)] leading-5 text-[var(--fg-secondary)]",
  runSwitcher:
    "flex items-center gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_select]:max-w-44",
  header:
    "flex flex-wrap items-start justify-between gap-3 [&_h2]:m-0 [&_h2]:mt-1 [&_h2]:[font-size:var(--vui-font-xl)] [&_h2]:leading-[1.3]",
  questionZh: "m-0 text-[var(--fg-secondary)]",
  headerActions: "flex shrink-0 items-center gap-2",
  eyebrow: "[font-size:var(--vui-font-2xs)] font-[650] tracking-[0.02em] text-[var(--fg-secondary)]",
  anchorNav:
    "grid gap-3 [&_a]:flex [&_a]:min-w-0 [&_a]:items-center [&_a]:gap-[7px] [&_a]:rounded-[var(--vui-radius-control)] [&_a]:border [&_a]:border-[var(--vui-border-subtle)] [&_a]:bg-[var(--vui-surface-panel)] [&_a]:px-2.5 [&_a]:py-[9px] [&_a]:[font-size:var(--vui-font-2xs)] [&_a]:text-inherit [&_a]:no-underline",
  // Two-stage anchor directory: zone title row + its anchor links. The archive
  // mode still renders bare links, so link styles stay on the anchorNav
  // descendant selector and cover both layouts.
  anchorGroup: "grid gap-1.5",
  anchorGroupTitle:
    "flex items-center gap-1.5 [font-size:var(--vui-font-2xs)] font-[650] tracking-[0.02em] text-[var(--fg-secondary)]",
  anchorGroupLinks: "grid grid-cols-2 gap-1.5 @min-[430px]:grid-cols-4",
  stageZone:
    "grid scroll-mt-5 gap-1.5 border-b border-[var(--vui-border-subtle)] pb-2",
  stageZoneTopline: "flex flex-wrap items-center justify-between gap-2",
  stageZoneTitle: "m-0 [font-size:var(--vui-font-md)] leading-[1.35]",
  stageZoneHint: "m-0 [font-size:var(--vui-font-2xs)] leading-5 text-[var(--fg-secondary)]",
  archiveHint: "m-0 [font-size:var(--vui-font-xs)] leading-5 text-[var(--fg-secondary)]",
  section:
    "grid scroll-mt-5 gap-3 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-4 [&_h3]:m-0 [&_h4]:m-0 [&_p]:m-0",
  sectionHeading:
    "flex items-start gap-2.5 [&>span]:pt-[3px] [&>span]:[font-size:var(--vui-font-2xs)] [&>span]:font-[650] [&>span]:tracking-[0.02em] [&>span]:text-[var(--fg-secondary)] [&_h3]:[font-size:var(--vui-font-md)] [&_p]:mt-0.5 [&_p]:[font-size:var(--vui-font-2xs)] [&_p]:text-[var(--fg-secondary)]",
  factGrid:
    "grid grid-cols-2 gap-2 [&_section]:grid [&_section]:gap-1 [&_span]:[font-size:var(--vui-font-2xs)] [&_span]:font-[650] [&_span]:tracking-[0.02em] [&_span]:text-[var(--fg-secondary)]",
  warning:
    "flex items-start gap-[9px] rounded-[var(--vui-radius-panel-soft)] border border-[color-mix(in_srgb,var(--state-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_8%,transparent)] px-3 py-2.5 [&_svg]:shrink-0 [&_svg]:text-[var(--state-warning)] [&_p]:mt-0.5 [&_p]:[font-size:var(--vui-font-2xs)] [&_p]:text-[var(--fg-secondary)]",
  explanation:
    "grid gap-2.5 [&_dl]:m-0 [&_dl]:grid [&_dl]:grid-cols-1 [&_dl]:gap-2 [&_dl>div]:grid [&_dl>div]:gap-[3px] [&_dt]:[font-size:var(--vui-font-2xs)] [&_dt]:text-[var(--fg-secondary)] [&_dd]:m-0",
  cardList: "grid gap-[9px]",
  evidenceCard:
    "rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3",
  cardTopline: "flex items-center justify-between gap-3",
  metadata:
    "mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)] [&_a]:inline-flex [&_a]:items-center [&_a]:gap-[3px] [&_a]:text-[var(--accent-cool)]",
  fact:
    "mt-2.5 border-l-[3px] border-[var(--accent-cool)] bg-[var(--vui-surface-inset)] px-2.5 py-[9px] [&>span]:[font-size:var(--vui-font-2xs)] [&>span]:font-[650] [&>span]:tracking-[0.02em] [&>span]:text-[var(--fg-secondary)] [&_p]:mt-[3px]",
  missing: "[font-size:var(--vui-font-2xs)] text-[var(--state-warning)]",
  missingLine: "mt-1.5 [font-size:var(--vui-font-2xs)] text-[var(--state-warning)]",
  compactList: "mt-[3px] mb-0 grid gap-[3px] pl-[18px]",
  twoColumn: "grid grid-cols-1 gap-2.5",
  hypothesisCard:
    "grid gap-2.5 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3 [&_h4]:[font-size:var(--vui-font-sm)] [&_h4]:leading-[1.45] [&_dl]:m-0 [&_dl]:grid [&_dl]:gap-2 [&_dl>div]:grid [&_dl>div]:gap-[3px] [&_dt]:[font-size:var(--vui-font-2xs)] [&_dt]:text-[var(--fg-secondary)] [&_dd]:m-0",
  hypothesisSummaryList: "grid gap-2",
  hypothesisSummaryCard: "overflow-hidden rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)]",
  hypothesisToggle: "flex w-full items-start justify-between gap-3 px-3 py-3 text-left whitespace-normal hover:bg-[var(--vui-surface-inset)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--focus-ring)]",
  hypothesisToggleCopy: "flex min-w-0 flex-1 flex-wrap items-start gap-2 [font-size:var(--vui-font-sm)] leading-5",
  hypothesisIndex: "inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-[var(--vui-surface-inset)] [font-size:var(--vui-font-2xs)] font-semibold text-[var(--fg-tertiary)]",
  hypothesisSummaryDetail: "border-t border-[var(--vui-border-subtle)] bg-[var(--vui-surface-inset)] px-4 py-3 [&_dl]:m-0 [&_dl]:grid [&_dl]:gap-2 [&_dl>div]:grid [&_dl>div]:gap-1 [&_dt]:[font-size:var(--vui-font-2xs)] [&_dt]:font-semibold [&_dt]:text-[var(--fg-tertiary)] [&_dd]:m-0 [&_dd]:[font-size:var(--vui-font-sm)] [&_dd]:leading-6 [&_dd]:text-[var(--fg-secondary)]",
  reviewGroups:
    "grid gap-[9px] [&>article]:grid [&>article]:gap-2 [&>article]:rounded-[var(--vui-radius-panel-soft)] [&>article]:border [&>article]:border-[var(--vui-border-subtle)] [&>article]:bg-[var(--vui-surface-card)] [&>article]:p-3",
  reviewGrid:
    "grid grid-cols-2 gap-1.5 @min-[400px]:grid-cols-3 [&>div]:grid [&>div]:min-w-0 [&>div]:content-start [&>div]:gap-1 [&>div]:rounded-[var(--vui-radius-control)] [&>div]:bg-[var(--vui-surface-inset)] [&>div]:p-2 [&_span]:[font-size:var(--vui-font-2xs)] [&_span]:text-[var(--fg-secondary)] [&_small]:[font-size:var(--vui-font-2xs)] [&_small]:text-[var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-2xs)] [&_p]:leading-[1.45]",
  selection:
    "grid grid-cols-1 gap-2.5 [&>div]:grid [&>div]:content-start [&>div]:gap-1.25 [&>div]:rounded-[var(--vui-radius-control)] [&>div]:bg-[var(--vui-surface-inset)] [&>div]:p-2.5 [&>div>span]:[font-size:var(--vui-font-2xs)] [&>div>span]:font-[650] [&>div>span]:tracking-[0.02em] [&>div>span]:text-[var(--fg-secondary)]",
  plan: "grid gap-2.5",
  sectionHeadingRow: "flex flex-wrap items-center justify-between gap-2",
  planProposalTag:
    "grid gap-1 rounded-[var(--vui-radius-control)] bg-[var(--vui-surface-inset)] p-2.5 [&>span]:[font-size:var(--vui-font-2xs)] [&>span]:leading-5 [&>span]:text-[var(--fg-secondary)]",
  planGrid:
    "grid grid-cols-1 gap-2 @min-[430px]:grid-cols-2 [&>div]:grid [&>div]:content-start [&>div]:gap-1.25 [&>div]:rounded-[var(--vui-radius-control)] [&>div]:bg-[var(--vui-surface-inset)] [&>div]:p-2.5",
  workPackage:
    "grid gap-1.25 rounded-[var(--vui-radius-control)] border border-[var(--vui-border-subtle)] p-2.5 [&_small]:text-[var(--fg-secondary)]",
  timeline:
    "grid gap-[9px] [&_article]:grid [&_article]:grid-cols-[76px_1fr] [&_article]:gap-3 [&_article]:rounded-[var(--vui-radius-panel-soft)] [&_article]:border [&_article]:border-[var(--vui-border-subtle)] [&_article]:bg-[var(--vui-surface-card)] [&_article]:p-3 [&_article>span]:font-bold [&_article>span]:text-[var(--accent-cool)] [&_small]:text-[var(--state-warning)]",
  reviewForm:
    "grid gap-3 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3",
  reviewSuccess:
    "rounded-[var(--vui-radius-panel-soft)] border border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] px-3 py-2 [font-size:var(--vui-font-2xs)] text-[var(--state-success)]",
  reviewSummary:
    "grid gap-2 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-card)] p-3 [&_p]:[font-size:var(--vui-font-2xs)]",
  gateList: "grid gap-1.5",
  gateRow:
    "grid grid-cols-[1fr_auto] items-center gap-2 [&>span]:[font-size:var(--vui-font-2xs)] [&>span]:font-[650] [&>span]:text-[var(--fg-secondary)] [&>button]:col-span-2",
  field: "grid gap-1 [&>span]:[font-size:var(--vui-font-2xs)] [&>span]:font-[650] [&>span]:text-[var(--fg-secondary)]",
  registerDialog: "grid gap-3 text-[var(--fg-primary)]",
  registerFields: "grid grid-cols-1 gap-2 sm:grid-cols-2",
  registerPreview:
    "break-all rounded bg-[var(--vui-surface-inset)] px-2 py-1.5 font-mono text-[10px] text-[var(--fg-secondary)]",
  registerHint: "m-0 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  registerResult:
    "grid gap-2 rounded-[var(--vui-radius-panel-soft)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-inset)] p-3",
  registerResultGrid: "flex flex-wrap items-center gap-1.5",
  registerActions: "flex flex-wrap items-center gap-2",
  resetDialog: "grid gap-3 text-[var(--fg-primary)] [&_p]:m-0",
  resetImpactList: "m-0 grid list-none gap-1.5 p-0 [&_li]:grid [&_li]:grid-cols-[1fr_auto] [&_li]:items-center [&_li]:gap-3 [&_li]:rounded-[var(--vui-radius-control)] [&_li]:bg-[var(--vui-surface-inset)] [&_li]:px-2.5 [&_li]:py-2 [&_span]:[font-size:var(--vui-font-2xs)] [&_span]:text-[var(--fg-secondary)]",
  resetWarning: "rounded-[var(--vui-radius-panel-soft)] border border-[color-mix(in_srgb,var(--state-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_8%,transparent)] px-3 py-2 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  artifact:
    "flex items-start gap-2.5 [&>div]:grid [&>div]:min-w-0 [&>div]:gap-1.25 [&_code]:wrap-anywhere [&_code]:[font-size:var(--vui-font-2xs)] [&_code]:text-[var(--fg-secondary)]",
  state:
    "grid min-h-60 content-center justify-items-start gap-2.5 [&_span]:text-[var(--fg-secondary)] [&_code]:wrap-anywhere [&_code]:[font-size:var(--vui-font-2xs)] [&_code]:text-[var(--fg-secondary)]",
  techDetails:
    "grid max-w-full gap-1 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)] [&>summary]:w-fit [&>summary]:cursor-pointer [&_code]:wrap-anywhere [&_code]:text-[10px] [&_code]:text-[var(--fg-secondary)]",
};

export default styles;
