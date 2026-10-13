const bone =
  "block animate-pulse rounded-full bg-[color-mix(in_srgb,var(--vui-border-subtle)_70%,transparent)] motion-reduce:animate-none";

const styles = {
  bone,
  boneLine: `${bone} h-2.5 w-full`,
  boneShort: `${bone} h-2.5 w-[64%]`,
  boneTitle: `${bone} h-3 w-24`,
  boneMeta: `${bone} h-2.5 w-14`,
  boneEyebrow: `${bone} h-2.5 w-16`,
  check:
    "block size-4 animate-pulse rounded-[4px] bg-[color-mix(in_srgb,var(--vui-border-subtle)_70%,transparent)] motion-reduce:animate-none",
  header:
    "grid min-w-0 shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-[var(--radius-panel)] border border-vui-border-subtle bg-vui-surface-glass px-3 py-2",
  headerCopy: "grid min-w-0 gap-1.5",
  headerAction: `${bone} h-8 w-16 rounded-[var(--radius-control)]`,
  page: "grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-2 overflow-hidden p-2",
  pageStack: "grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-2 overflow-hidden",
  body: "grid min-h-0 min-w-0",
  pane: "grid min-h-0 min-w-0 content-start gap-1.5 overflow-hidden p-1.5",
  rowStack: "grid min-w-0 content-start gap-1",
  lineStack: "grid min-w-0 content-start gap-2.5 p-3",
  tabStrip: "flex h-8 min-w-0 items-center gap-1.5 px-2",
  tab: `${bone} h-7 w-14 rounded-[var(--radius-control)]`,
  row52:
    "grid min-h-[52px] grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-[var(--radius-control)] border border-vui-border-subtle px-2.5 py-2",
  row56: "grid min-h-14 content-center gap-1.5 px-2 py-2",
  row72: "grid min-h-[72px] content-center gap-1.5 px-2 py-1.5",
  row44: "grid min-h-11 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-2",
  checkRow:
    "grid min-h-11 grid-cols-[28px_minmax(0,1fr)] items-center gap-1 px-1",
  agentsSplit:
    "grid h-full min-h-0 grid-cols-[340px_minmax(0,1fr)_360px] max-[1100px]:grid-cols-[340px_minmax(0,1fr)] max-[760px]:grid-cols-1",
  skillsSplit:
    "grid h-full min-h-0 grid-cols-[clamp(280px,26vw,420px)_minmax(0,1fr)] gap-4 px-4 pb-4 pt-3 max-[920px]:grid-cols-1",
  promptsSplit:
    "grid h-full min-h-0 grid-cols-[clamp(280px,26vw,440px)_minmax(0,1fr)] gap-4 px-4 pb-4 pt-3 max-[980px]:grid-cols-1",
  kernelSplit:
    "grid h-full min-h-0 grid-cols-[clamp(280px,28vw,400px)_minmax(0,1fr)] gap-2 px-2 pb-2 pt-1.5 max-[1120px]:grid-cols-1",
  kernelDetail:
    "grid h-full min-h-0 grid-cols-[minmax(0,1fr)_clamp(280px,26vw,380px)] gap-2 max-[1280px]:grid-cols-1",
  auxSplit:
    "grid h-full min-h-0 grid-cols-[clamp(300px,28vw,420px)_minmax(0,1fr)] gap-2 px-2 pb-2 pt-1.5 max-[1120px]:grid-cols-1",
  toolsSplit:
    "grid h-full min-h-0 grid-cols-[350px_10px_minmax(0,1fr)] max-[760px]:grid-cols-1",
  reviewSplit:
    "grid h-full min-h-0 grid-cols-[380px_minmax(0,1fr)] max-[980px]:grid-cols-1",
  evolutionLive:
    "grid h-full min-h-0 grid-cols-[440px_12px_minmax(360px,1fr)_12px_380px] max-[1200px]:grid-cols-[minmax(0,1fr)_minmax(292px,0.82fr)] max-[1200px]:grid-rows-[minmax(180px,0.58fr)_minmax(300px,1fr)] max-[900px]:grid-cols-1 max-[900px]:grid-rows-none",
  evolutionQueue: "grid h-full min-h-0 grid-cols-[380px_minmax(0,1fr)] max-[900px]:grid-cols-1",
  evolutionLibrary: "grid h-full min-h-0 grid-cols-[360px_minmax(0,1fr)] max-[900px]:grid-cols-1",
  gitBody: "grid min-h-0 grid-rows-[auto_minmax(0,1fr)]",
  gitWorkspace:
    "grid h-full min-h-0 grid-cols-[340px_10px_minmax(0,1fr)_clamp(250px,22vw,360px)] p-1.5 max-[1200px]:grid-cols-[minmax(240px,340px)_8px_minmax(0,1fr)] max-[1200px]:grid-rows-[minmax(0,1fr)_minmax(200px,34vh)] max-[1200px]:[&>*:nth-child(4)]:col-span-full max-[860px]:grid-cols-1 max-[860px]:grid-rows-none",
  gitSummary: "mx-2 min-h-[48px]",
  logsWorkspace:
    "grid h-full min-h-0 grid-cols-[320px_10px_minmax(0,1fr)_10px_280px] p-1.5 max-[760px]:grid-cols-1",
  memoryPersonal:
    "grid h-full min-h-0 grid-cols-[220px_300px_minmax(0,1fr)] max-[900px]:grid-cols-1",
  memoryKnowledge:
    "grid h-full min-h-0 grid-cols-[230px_minmax(0,1fr)_320px] max-[900px]:grid-cols-1",
  memoryCards: "grid min-h-0 content-start grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3 p-2",
  memoryCard: "grid min-h-[4.5rem] content-start gap-2 rounded-[var(--radius-panel)] border border-vui-border-subtle p-3",
  canvas: "grid h-full min-h-[390px] content-start gap-3 p-3",
  usagePage: "h-full min-h-0 min-w-0 overflow-auto px-4 py-5 max-[700px]:px-2 max-[700px]:py-2",
  usageSheet: "mx-auto grid w-full max-w-[1120px] min-w-0 content-start",
  usageBreadcrumb: "mb-6 flex min-w-0 items-center",
  usageRange: "mt-7 flex min-w-0 items-center justify-between gap-3",
  usageMetrics: "my-7 grid min-w-0 grid-cols-[1.25fr_1fr_1fr] gap-6 max-[700px]:grid-cols-1",
  usageMetric: "flex min-h-[96px] min-w-0 flex-col justify-center gap-2 border-l border-vui-border-subtle pl-6",
  usageValue: `${bone} h-8 w-24`,
  petMetrics: "grid min-w-0 grid-cols-4 gap-1.5 max-[860px]:grid-cols-2 max-[640px]:grid-cols-1",
  petCard: "grid min-h-12 grid-cols-[auto_minmax(0,1fr)] items-baseline gap-2 rounded-[var(--radius-panel)] border border-vui-border-subtle p-2",
  petStatus: "grid min-w-0 grid-cols-3 items-start gap-1.5 max-[860px]:grid-cols-2 max-[640px]:grid-cols-1",
  petStatusCard: "grid min-h-28 content-start gap-2 rounded-[var(--radius-panel)] border border-vui-border-subtle p-2",
  resetStatus: "grid min-h-12 grid-cols-[auto_minmax(0,1fr)] items-center gap-2 rounded-[var(--radius-panel)] border border-vui-border-subtle px-3",
  resetCard: "grid min-h-28 content-start gap-2 rounded-[var(--radius-panel)] border border-vui-border-subtle p-3",
  launcherRows: "grid min-h-0 content-start",
  companionRoute: "h-full min-h-0 min-w-0 overflow-auto px-[clamp(28px,5vw,78px)] py-[clamp(26px,4vh,48px)]",
  companionHero: "mx-auto mb-6 flex max-w-[1220px] min-w-0 items-end justify-between gap-8",
  companionHeroCopy: "grid min-w-0 gap-2",
  companionGrid: "mx-auto grid max-w-[1220px] min-w-0 gap-5",
  companionCard:
    "grid min-h-[min(590px,calc(100dvh-250px))] min-w-0 grid-cols-[minmax(0,1.08fr)_minmax(360px,0.92fr)] overflow-hidden rounded-[28px] border border-vui-border-subtle max-[960px]:grid-cols-1",
  companionCopy: "grid min-w-0 content-start gap-3 p-[clamp(30px,4vh,48px)]",
  companionPortrait: "min-h-[430px] max-[960px]:min-h-[420px]",
  companionTitle: `${bone} h-9 w-40`,
  companionSubtitle: `${bone} h-4 w-[min(100%,28rem)]`,
  companionNow: "mt-[clamp(20px,3vh,28px)] h-16 rounded-[15px] border border-vui-border-subtle",
  companionStrip: "mt-4 grid grid-cols-3 gap-3 border-y border-vui-border-subtle py-3.5 max-[560px]:grid-cols-1",
} as const;

export default styles;
