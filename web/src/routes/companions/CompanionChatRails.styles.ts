const railBase = "!rounded-none !border-0 !shadow-none min-h-0 min-w-0 overflow-hidden bg-vui-surface-rail";
const personRail = `${railBase} !flex flex-col overflow-x-hidden overflow-y-auto overscroll-contain border-r border-r-vui-border-subtle p-3 max-[1100px]:p-2.5`;
const lifeRail = `${railBase} !flex flex-col border-l border-l-vui-border-subtle`;
const railActions = "flex items-center justify-between gap-2";
const quietLink = "!h-7 !min-h-7 !rounded-[var(--radius-control)] !border-0 !bg-transparent !px-1.5 [font-size:var(--vui-font-xs)] text-vui-fg-tertiary hover:!bg-vui-surface-row-hover hover:text-vui-fg-primary";
const profile = "grid gap-3 pt-2";
const railPortrait = "!min-h-[min(35vh,260px)] rounded-[18px] border border-vui-border-subtle";
const personPresence = "flex min-w-0 items-center justify-between gap-2 [&>span:first-child]:font-mono [&>span:first-child]:text-[0.62rem] [&>span:first-child]:font-bold [&>span:first-child]:tracking-[0.12em] [&>span:first-child]:text-[var(--accent-cool)]";
const personNameCopy = "min-w-0 [&>h1]:m-0 [&>h1]:truncate [&>h1]:text-[1.6rem] [&>h1]:font-[820] [&>h1]:tracking-[-0.04em] [&>p]:m-0 [&>p]:mt-1 [&>p]:line-clamp-2 [&>p]:[font-size:var(--vui-font-xs)] [&>p]:leading-[1.45] [&>p]:text-vui-fg-secondary";
const personQuote = "m-0 border-y border-vui-border-subtle py-3 [font-size:var(--vui-font-xs)] leading-[1.65] text-vui-fg-tertiary";
const personFacts = "grid [&>span]:grid [&>span]:min-w-0 [&>span]:grid-cols-[54px_minmax(0,1fr)] [&>span]:gap-2 [&>span]:border-b [&>span]:border-vui-border-subtle [&>span]:py-2.5 [&_small]:[font-size:0.6rem] [&_small]:text-vui-fg-tertiary [&_strong]:line-clamp-2 [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:font-bold [&_strong]:leading-[1.45] [&_strong]:text-vui-fg-secondary";
const profileLink = "!w-full !justify-center";
const about = "m-0 [font-size:var(--vui-font-xs)] leading-[1.62] text-vui-fg-tertiary";
const lifeCard = "grid gap-1.5 !rounded-[var(--radius-control)] !border-0 !bg-vui-surface-row p-2.5 !shadow-none max-[1100px]:gap-1 max-[1100px]:p-2";
const lifeCardAccent = `${lifeCard} shadow-[inset_2px_0_0_var(--accent-cool)]`;
const cardLabel = "m-0 [font-size:0.62rem] font-extrabold uppercase tracking-[0.08em] text-vui-fg-tertiary";
const cardTitle = "m-0 text-[0.86rem] font-[780] leading-[1.35] text-vui-fg-primary";
const cardCopy = "m-0 [font-size:var(--vui-font-xs)] leading-[1.55] text-vui-fg-tertiary";
const cardMeta = "font-mono text-[0.62rem] text-[var(--accent-cool)]";
const personFooter = "mt-auto grid gap-1 border-t border-vui-border-subtle pt-3 [font-size:var(--vui-font-xs)] leading-[1.45] text-vui-fg-tertiary [&>strong]:text-vui-fg-secondary";
const lifeHeader = "grid gap-2.5 border-b border-vui-border-subtle p-3 max-[1100px]:gap-2 max-[1100px]:p-2.5";
const lifeTitleRow = "flex min-w-0 items-start justify-between gap-2";
const lifeTitleCopy = "min-w-0 [&>p]:m-0 [&>p]:font-mono [&>p]:text-[0.62rem] [&>p]:font-extrabold [&>p]:uppercase [&>p]:tracking-[0.1em] [&>p]:text-[var(--accent-cool)] [&>h2]:m-0 [&>h2]:mt-0.5 [&>h2]:truncate [&>h2]:text-sm [&>h2]:font-[820]";
const tabs = "gap-0";
const tabList = "w-full !grid grid-cols-3";
const tabTrigger = "w-full";
const lifeContent = "grid min-h-0 content-start gap-2 overflow-y-auto overscroll-contain [scrollbar-gutter:stable] p-3 max-[1100px]:gap-1.5 max-[1100px]:p-2.5";
const scheduleList = "grid gap-1.5";
const scheduleItem = "grid min-w-0 grid-cols-[44px_minmax(0,1fr)] gap-2 rounded-[var(--radius-control)] bg-vui-surface-row px-2 py-1.5 [&>time]:font-mono [&>time]:text-[0.62rem] [&>time]:text-vui-fg-tertiary [&>div]:min-w-0 [&>div]:grid [&>div]:gap-0.5 [&>div>strong]:truncate [&>div>strong]:[font-size:var(--vui-font-xs)] [&>div>span]:[font-size:0.62rem] [&>div>span]:leading-[1.45] [&>div>span]:text-vui-fg-tertiary";
const eventList = "grid gap-1.5";
const eventItem = "grid min-w-0 grid-cols-[44px_minmax(0,1fr)] gap-2 rounded-[var(--radius-control)] bg-vui-surface-row px-2 py-1.5";
const eventTime = "font-mono text-[0.62rem] text-vui-fg-tertiary";
const eventCopy = "grid min-w-0 gap-0.5 [&>strong]:truncate [&>strong]:[font-size:var(--vui-font-xs)] [&>span]:line-clamp-2 [&>span]:text-[0.62rem] [&>span]:leading-[1.45] [&>span]:text-vui-fg-tertiary";
const memoryList = "grid gap-1.5";
const memoryItem = "grid gap-1.5 rounded-[var(--radius-control)] bg-vui-surface-row px-2 py-2";
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
  quietLink,
  profile,
  railPortrait,
  personPresence,
  personNameCopy,
  personQuote,
  personFacts,
  profileLink,
  about,
  lifeCard,
  lifeCardAccent,
  cardLabel,
  cardTitle,
  cardCopy,
  cardMeta,
  personFooter,
  lifeHeader,
  lifeTitleRow,
  lifeTitleCopy,
  tabs,
  tabList,
  tabTrigger,
  lifeContent,
  scheduleList,
  scheduleItem,
  eventList,
  eventItem,
  eventTime,
  eventCopy,
  memoryList,
  memoryItem,
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
  progressItem,
  progressHeader,
  progressTrack,
  progressFill,
  timelineList,
  timelineItem,
  state,
} as const;
