const railBase = "!rounded-none !border-0 !shadow-none min-h-0 min-w-0 overflow-hidden bg-vui-surface-rail";
const personRail = `${railBase} relative isolate !flex flex-col border-r border-r-vui-border-subtle`;
const lifeRail = `${railBase} !flex flex-col border-l border-l-vui-border-subtle`;
const railActions = "pointer-events-none absolute inset-x-0 top-0 z-20 flex items-center justify-between gap-2 p-3 [&>*]:pointer-events-auto";
const railIconButton = "!size-8 !min-h-8 !rounded-full !border !border-vui-border-subtle !bg-vui-surface-panel !p-0 text-vui-fg-secondary shadow-sm hover:!bg-vui-surface-row-hover hover:text-vui-fg-primary";
const profile = "relative flex min-h-0 flex-1 flex-col overflow-hidden";
const railPortrait = "!min-h-0 flex-1 !rounded-none !border-0 before:!inset-[10%_4%_0]";
const personSummary = "relative z-10 grid gap-3 border-t border-vui-border-subtle bg-[linear-gradient(180deg,var(--vui-surface-row),var(--vui-surface-panel))] p-4 shadow-[0_-18px_42px_rgba(0,0,0,0.16)] max-[1100px]:gap-2.5 max-[1100px]:p-3";
const personPresence = "flex min-w-0 items-center justify-between gap-2 [&>time]:font-mono [&>time]:text-[0.62rem] [&>time]:text-vui-fg-tertiary";
const personNameCopy = "flex min-w-0 items-center justify-between gap-2 [&>h1]:m-0 [&>h1]:truncate [&>h1]:text-[clamp(1.65rem,2.2vw,2.15rem)] [&>h1]:font-[820] [&>h1]:tracking-[-0.05em] [&>span]:grid [&>span]:size-8 [&>span]:shrink-0 [&>span]:place-items-center [&>span]:rounded-full [&>span]:bg-[color-mix(in_srgb,var(--state-success)_12%,var(--vui-surface-row))] [&>span]:text-lg [&>span]:text-[var(--state-success)]";
const personStatus = "m-0 line-clamp-2 min-h-[2.5em] text-[0.8rem] font-semibold leading-[1.4] text-vui-fg-secondary";
const personFacts = "grid grid-cols-3 gap-1.5 [&>span]:grid [&>span]:min-w-0 [&>span]:justify-items-center [&>span]:gap-1 [&>span]:rounded-xl [&>span]:bg-vui-surface-row [&>span]:px-1.5 [&>span]:py-2 [&>span]:text-[var(--accent-cool)] [&_strong]:w-full [&_strong]:truncate [&_strong]:text-center [&_strong]:text-[0.62rem] [&_strong]:font-bold [&_strong]:text-vui-fg-secondary";
const about = "m-0 [font-size:var(--vui-font-xs)] leading-[1.62] text-vui-fg-tertiary";
const lifeCard = "grid gap-1.5 !rounded-[var(--radius-control)] !border-0 !bg-vui-surface-row p-2.5 !shadow-none max-[1100px]:gap-1 max-[1100px]:p-2";
const lifeCardAccent = `${lifeCard} shadow-[inset_2px_0_0_var(--accent-cool)]`;
const cardLabel = "m-0 [font-size:0.62rem] font-extrabold uppercase tracking-[0.08em] text-vui-fg-tertiary";
const cardTitle = "m-0 text-[0.86rem] font-[780] leading-[1.35] text-vui-fg-primary";
const cardCopy = "m-0 [font-size:var(--vui-font-xs)] leading-[1.55] text-vui-fg-tertiary";
const cardMeta = "font-mono text-[0.62rem] text-[var(--accent-cool)]";
const lifeHeader = "grid gap-2 border-b border-vui-border-subtle px-3 pb-2 pt-3 max-[1100px]:px-2.5";
const lifeTitleRow = "flex min-w-0 items-start justify-between gap-2";
const lifeTitleCopy = "min-w-0 [&>p]:m-0 [&>p]:text-[0.6rem] [&>p]:font-bold [&>p]:uppercase [&>p]:tracking-[0.1em] [&>p]:text-[var(--accent-cool)] [&>h2]:m-0 [&>h2]:mt-0.5 [&>h2]:truncate [&>h2]:text-sm [&>h2]:font-[820]";
const tabs = "gap-0";
const tabList = "w-full !grid grid-cols-3";
const tabTrigger = "w-full";
const lifeContent = "grid min-h-0 content-start gap-2.5 overflow-y-auto overscroll-contain [scrollbar-gutter:stable] p-3 max-[1100px]:gap-2 max-[1100px]:p-2.5";
const sceneCard = "relative isolate grid min-h-28 overflow-hidden rounded-[18px] border border-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] bg-[radial-gradient(circle_at_84%_18%,color-mix(in_srgb,var(--accent-cool)_25%,transparent),transparent_44%),linear-gradient(135deg,var(--vui-surface-panel),var(--vui-surface-row))] p-4 shadow-[var(--vui-elevation-card)]";
const sceneIcon = "absolute -bottom-3 -right-2 grid size-24 place-items-center rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_18%,transparent)] text-[var(--accent-cool)] opacity-50";
const sceneCopy = "relative z-10 grid max-w-[78%] content-end gap-1 [&>span]:text-[0.6rem] [&>span]:font-bold [&>span]:uppercase [&>span]:tracking-[0.1em] [&>span]:text-[var(--accent-cool)] [&>strong]:line-clamp-2 [&>strong]:text-[1rem] [&>strong]:font-[820] [&>strong]:leading-[1.3] [&>small]:flex [&>small]:items-center [&>small]:gap-1 [&>small]:text-[0.62rem] [&>small]:text-vui-fg-tertiary";
const vitalGrid = "grid grid-cols-[0.78fr_1.22fr] gap-2";
const moodVisual = "flex min-w-0 items-center gap-2 rounded-[16px] bg-vui-surface-row p-3 [&>span]:grid [&>span]:size-10 [&>span]:shrink-0 [&>span]:place-items-center [&>span]:rounded-full [&>span]:bg-[color-mix(in_srgb,var(--state-success)_12%,transparent)] [&>span]:text-xl [&>span]:text-[var(--state-success)] [&>div]:grid [&>div]:min-w-0 [&>div]:gap-0.5 [&_small]:text-[0.58rem] [&_small]:text-vui-fg-tertiary [&_strong]:truncate [&_strong]:text-[0.76rem]";
const meterPanel = "grid gap-1.5 rounded-[16px] bg-vui-surface-row p-3";
const meterLine = "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1 [&>small]:text-[0.58rem] [&>small]:text-vui-fg-tertiary [&>strong]:font-mono [&>strong]:text-[0.64rem]";
const meterTrack = "col-span-2 h-1.5 overflow-hidden rounded-full bg-vui-surface-overlay";
const meterFillEnergy = "block h-full rounded-full bg-[var(--accent-cool)] transition-[width] duration-300";
const meterFillSocial = "block h-full rounded-full bg-[var(--state-success)] transition-[width] duration-300";
const nextCard = "grid min-w-0 grid-cols-[44px_minmax(0,1fr)_auto] items-center gap-2.5 rounded-[16px] border border-vui-border-subtle bg-vui-surface-row px-3 py-2.5 [&>time]:font-mono [&>time]:text-[0.65rem] [&>time]:font-bold [&>time]:text-[var(--accent-cool)] [&>div]:grid [&>div]:min-w-0 [&>div]:gap-0.5 [&_small]:text-[0.58rem] [&_small]:text-vui-fg-tertiary [&_strong]:truncate [&_strong]:text-[0.72rem] [&>svg]:text-vui-fg-tertiary";
const detailDisclosure = "group rounded-[16px] border border-vui-border-subtle bg-vui-surface-row";
const detailSummary = "cursor-pointer list-none px-3 py-2.5 text-[0.66rem] font-bold text-vui-fg-secondary marker:hidden after:float-right after:text-vui-fg-tertiary after:content-['＋'] group-open:after:content-['−']";
const detailContent = "grid gap-2 border-t border-vui-border-subtle p-2";
const scheduleList = "grid gap-0.5";
const scheduleItem = "relative grid min-w-0 grid-cols-[44px_10px_minmax(0,1fr)] gap-2 px-1 py-2 before:absolute before:bottom-[-4px] before:left-[52px] before:top-[24px] before:w-px before:bg-vui-border-subtle before:content-[''] last:before:hidden [&>time]:font-mono [&>time]:text-[0.6rem] [&>time]:text-vui-fg-tertiary [&>i]:mt-1.5 [&>i]:size-2 [&>i]:rounded-full [&>i]:bg-[var(--accent-cool)] [&>div]:min-w-0 [&>div]:grid [&>div]:gap-0.5 [&>div>strong]:truncate [&>div>strong]:[font-size:var(--vui-font-xs)] [&>div>span]:[font-size:0.6rem] [&>div>span]:leading-[1.4] [&>div>span]:text-vui-fg-tertiary";
const eventList = "grid gap-1.5";
const eventItem = "grid min-w-0 grid-cols-[44px_minmax(0,1fr)] gap-2 rounded-[var(--radius-control)] bg-vui-surface-row px-2 py-1.5";
const eventTime = "font-mono text-[0.62rem] text-vui-fg-tertiary";
const eventCopy = "grid min-w-0 gap-0.5 [&>strong]:truncate [&>strong]:[font-size:var(--vui-font-xs)] [&>span]:line-clamp-2 [&>span]:text-[0.62rem] [&>span]:leading-[1.45] [&>span]:text-vui-fg-tertiary";
const memoryList = "grid gap-1.5";
const memoryItem = "grid gap-2 rounded-[16px] border border-vui-border-subtle bg-[linear-gradient(135deg,color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-row)),var(--vui-surface-row))] p-2.5";
const memoryVisualRow = "grid min-w-0 grid-cols-[38px_minmax(0,1fr)] items-start gap-2";
const memoryVisual = "grid size-[38px] place-items-center rounded-xl bg-[color-mix(in_srgb,var(--accent-cool)_14%,transparent)] text-[var(--accent-cool)]";
const memoryBody = "grid min-w-0 gap-1.5";
const memoryItemHeader = "flex min-w-0 items-baseline justify-between gap-2 [&>strong]:truncate [&>strong]:[font-size:var(--vui-font-xs)] [&>time]:shrink-0 [&>time]:font-mono [&>time]:text-[0.6rem] [&>time]:text-vui-fg-tertiary";
const memoryMeta = "font-mono text-[0.6rem] text-[var(--accent-cool)]";
const memoryText = "m-0 line-clamp-3 [font-size:var(--vui-font-xs)] leading-[1.55] text-vui-fg-secondary";
const memoryMetaRow = "flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 [font-size:0.6rem] leading-[1.4] text-vui-fg-tertiary [&>span]:truncate";
const memoryOverview = "flex min-w-0 items-center justify-between gap-2 [&>strong]:font-mono [&>strong]:text-[0.72rem] [&>strong]:text-vui-fg-primary";
const relationshipGrid = "grid gap-1.5";
const relationshipItem = "grid min-w-0 gap-0.5 rounded-[var(--radius-control)] bg-vui-surface-row px-2 py-1.5 [&>span]:text-[0.6rem] [&>span]:text-vui-fg-tertiary [&>strong]:[font-size:var(--vui-font-xs)] [&>strong]:leading-[1.45] [&>strong]:text-vui-fg-secondary [&>small]:line-clamp-2 [&>small]:text-[0.6rem] [&>small]:leading-[1.4] [&>small]:text-vui-fg-tertiary";
const moodRow = "flex items-center justify-between gap-2 [&>strong]:text-[0.82rem] [&>span]:font-mono [&>span]:text-[0.62rem] [&>span]:text-vui-fg-tertiary";
const facts = "grid grid-cols-2 gap-1.5";
const fact = "grid gap-0.5 rounded-[var(--radius-control)] bg-vui-surface-row px-2 py-1.5 [&>span]:text-[0.6rem] [&>span]:text-vui-fg-tertiary [&>strong]:font-mono [&>strong]:text-[0.72rem] [&>strong]:text-vui-fg-primary";
const locationRow = "flex min-w-0 items-center justify-between gap-2 border-t border-vui-border-subtle pt-1.5 [&>span]:text-[0.6rem] [&>span]:text-vui-fg-tertiary [&>strong]:truncate [&>strong]:text-[0.68rem] [&>strong]:text-vui-fg-secondary";
const sourceCopy = "line-clamp-2 text-[0.6rem] leading-[1.4] text-vui-fg-tertiary";
const compactList = "grid gap-1.5";
const compactItem = "grid min-w-0 gap-0.5 rounded-[var(--radius-control)] bg-vui-surface-row px-2 py-1.5 [&>strong]:line-clamp-2 [&>strong]:[font-size:var(--vui-font-xs)] [&>strong]:leading-[1.45] [&>small]:line-clamp-2 [&>small]:text-[0.6rem] [&>small]:leading-[1.4] [&>small]:text-vui-fg-tertiary";
const compactItemHeader = "flex min-w-0 items-baseline justify-between gap-2 [&>strong]:truncate [&>strong]:[font-size:var(--vui-font-xs)] [&>span]:shrink-0 [&>span]:font-mono [&>span]:text-[0.62rem] [&>span]:text-vui-fg-secondary";
const compactActions = "mt-1 flex flex-wrap items-center gap-1.5";
const reviewNotice = "m-0 [font-size:0.62rem] leading-[1.45] text-vui-fg-secondary";
const progressItem = "grid gap-1 rounded-[var(--radius-control)] bg-vui-surface-row px-2 py-1.5";
const progressHeader = "flex min-w-0 items-baseline justify-between gap-2 [&>strong]:truncate [&>strong]:[font-size:var(--vui-font-xs)] [&>span]:[font-size:0.6rem] [&>span]:text-vui-fg-tertiary [&>strong:last-child]:font-mono [&>strong:last-child]:text-[0.62rem] [&>strong:last-child]:text-vui-fg-secondary";
const progressTrack = "h-1 overflow-hidden rounded-full bg-vui-surface-overlay";
const progressFill = "block h-full rounded-full bg-[var(--accent-cool)] transition-[width] duration-300";
const timelineList = "grid gap-0.5";
const timelineItem = "grid min-w-0 grid-cols-[8px_minmax(0,1fr)] gap-2 [&>span]:mt-1.5 [&>span]:size-1.5 [&>span]:rounded-full [&>span]:bg-[var(--accent-cool)] [&>div]:grid [&>div]:gap-0.5 [&>div]:border-l [&>div]:border-vui-border-subtle [&>div]:pb-2 [&>div]:pl-2 [&>div>time]:font-mono [&>div>time]:text-[0.6rem] [&>div>time]:text-vui-fg-tertiary [&>div>p]:m-0 [&>div>p]:line-clamp-3 [&>div>p]:[font-size:var(--vui-font-xs)] [&>div>p]:leading-[1.5] [&>div>p]:text-vui-fg-secondary [&>div>small]:text-[0.6rem] [&>div>small]:text-vui-fg-tertiary";
const state = "m-3";

export default {
  personRail,
  lifeRail,
  railActions,
  railIconButton,
  profile,
  railPortrait,
  personSummary,
  personPresence,
  personNameCopy,
  personStatus,
  personFacts,
  about,
  lifeCard,
  lifeCardAccent,
  cardLabel,
  cardTitle,
  cardCopy,
  cardMeta,
  lifeHeader,
  lifeTitleRow,
  lifeTitleCopy,
  tabs,
  tabList,
  tabTrigger,
  lifeContent,
  sceneCard,
  sceneIcon,
  sceneCopy,
  vitalGrid,
  moodVisual,
  meterPanel,
  meterLine,
  meterTrack,
  meterFillEnergy,
  meterFillSocial,
  nextCard,
  detailDisclosure,
  detailSummary,
  detailContent,
  scheduleList,
  scheduleItem,
  eventList,
  eventItem,
  eventTime,
  eventCopy,
  memoryList,
  memoryItem,
  memoryVisualRow,
  memoryVisual,
  memoryBody,
  memoryItemHeader,
  memoryMeta,
  memoryText,
  memoryMetaRow,
  memoryOverview,
  relationshipGrid,
  relationshipItem,
  moodRow,
  facts,
  fact,
  locationRow,
  sourceCopy,
  compactList,
  compactItem,
  compactItemHeader,
  compactActions,
  reviewNotice,
  progressItem,
  progressHeader,
  progressTrack,
  progressFill,
  timelineList,
  timelineItem,
  state,
} as const;
