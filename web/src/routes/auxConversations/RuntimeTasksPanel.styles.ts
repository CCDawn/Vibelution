const root = "grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden !rounded-none !border-0 !p-0 !shadow-none";
const header = "grid min-w-0 gap-2 border-b border-vui-border-subtle px-2 pb-2 pt-2";
const titleRow = "flex min-w-0 items-center justify-between gap-2";
const title = "m-0 min-w-0 truncate text-vui-sm font-semibold text-vui-fg-primary";
const headerActions = "flex shrink-0 items-center gap-1";
const refreshButton = "!h-7 !min-h-7 !w-7 !min-w-7";
const filters = "grid min-w-0 grid-cols-1 gap-1.5";
const filterTabs = "min-w-0 gap-0";
const filterTabList = "flex w-full flex-nowrap";
const filterTabTrigger = "min-w-0 flex-1 px-1.5";
const content = "grid min-h-0 min-w-0 content-start gap-2 overflow-auto overflow-x-hidden p-2";
const section = "grid min-w-0 content-start gap-1.5";
const sectionHeader = "flex min-w-0 items-center justify-between gap-2 px-0.5";
const sectionTitle = "m-0 min-w-0 text-vui-xs font-semibold text-vui-fg-secondary";
const count = "shrink-0 text-vui-xs text-vui-fg-tertiary";
const taskRow = "grid min-h-12 min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2 rounded-[var(--radius-control)] border border-transparent bg-vui-surface-row px-2 py-1.5 text-left text-vui-fg-primary hover:bg-[var(--vui-surface-row-hover)]";
const selectedTaskRow = "!border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] !bg-[var(--vui-surface-row-hover)] shadow-[var(--vui-shadow-inset-accent)]";
const rowIcon = "mt-0.5 shrink-0 text-vui-fg-tertiary";
const rowIconSpin = "animate-spin motion-reduce:animate-none";
const taskMain = "grid min-w-0 content-start gap-0.5";
const taskTop = "flex min-w-0 items-center gap-1.5";
const taskName = "min-w-0 flex-1 truncate text-vui-xs font-medium";
const statusText = "shrink-0 text-vui-xs text-vui-fg-tertiary";
const taskMeta = "flex min-w-0 items-center gap-1.5 text-vui-xs leading-tight text-vui-fg-secondary";
const taskSummary = "min-w-0 truncate";
const timestamp = "shrink-0 pt-0.5 text-right text-vui-xs leading-tight text-vui-fg-tertiary";
const workRow = "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row px-2 py-1.5";
const workCopy = "grid min-w-0 content-start gap-0.5";
const workTitle = "m-0 min-w-0 truncate text-vui-xs font-medium text-vui-fg-primary";
const workSummary = "m-0 min-w-0 break-words text-vui-xs leading-snug text-vui-fg-secondary";
const workActions = "flex shrink-0 items-center gap-1";
const workOpenLink = "!min-h-7 !px-1.5 !text-vui-xs";
const staleRow = "grid min-w-0 gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-warning)_24%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_6%,var(--vui-surface-row))] p-2";
const detail = "grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden";
const detailToolbar = "flex min-w-0 items-center justify-between gap-1 border-b border-vui-border-subtle px-2 py-1.5";
const detailScroll = "grid min-h-0 min-w-0 content-start gap-2 overflow-auto overflow-x-hidden p-2";
const detailHeader = "grid min-w-0 gap-1 rounded-[var(--radius-control)] bg-vui-surface-row p-2";
const detailTitleRow = "flex min-w-0 items-start justify-between gap-2";
const detailTitle = "m-0 min-w-0 break-words [overflow-wrap:anywhere] text-vui-sm font-semibold text-vui-fg-primary";
const detailMeta = "m-0 min-w-0 break-words text-vui-xs leading-snug text-vui-fg-secondary";
const detailActions = "flex min-w-0 flex-wrap items-center gap-1";
const loadMore = "grid min-w-0 justify-items-start gap-1 px-0.5";
const detailSection = "grid min-w-0 gap-1 rounded-[var(--radius-control)] bg-vui-surface-row p-2";
const muted = "m-0 min-w-0 break-words text-vui-xs leading-snug text-vui-fg-secondary";
const transcript = "flex min-h-48 min-w-0 flex-1 flex-col overflow-hidden rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-panel";
const stateSurface = "!min-h-16 !w-full !p-2";
const compactError = "!min-h-0 !p-2";

export const styles = {
  root,
  header,
  titleRow,
  title,
  headerActions,
  refreshButton,
  filters,
  filterTabs,
  filterTabList,
  filterTabTrigger,
  content,
  section,
  sectionHeader,
  sectionTitle,
  count,
  taskRow,
  selectedTaskRow,
  rowIcon,
  rowIconSpin,
  taskMain,
  taskTop,
  taskName,
  statusText,
  taskMeta,
  taskSummary,
  timestamp,
  workRow,
  workCopy,
  workTitle,
  workSummary,
  workActions,
  workOpenLink,
  staleRow,
  detail,
  detailToolbar,
  detailScroll,
  detailHeader,
  detailTitleRow,
  detailTitle,
  detailMeta,
  detailActions,
  loadMore,
  detailSection,
  muted,
  transcript,
  stateSurface,
  compactError,
} as const;
