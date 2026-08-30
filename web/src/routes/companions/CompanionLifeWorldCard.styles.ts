const card = "grid min-w-0 gap-2.5 overflow-hidden rounded-[16px] border border-[color-mix(in_srgb,var(--accent-warm)_24%,var(--vui-border-subtle))] bg-[linear-gradient(145deg,color-mix(in_srgb,var(--accent-warm)_9%,var(--vui-surface-row)),var(--vui-surface-row))] p-3 max-[1100px]:p-2.5";
const header = "flex min-w-0 items-start justify-between gap-2";
const title = "flex min-w-0 items-start gap-2 [&>span]:grid [&>span]:size-8 [&>span]:shrink-0 [&>span]:place-items-center [&>span]:rounded-xl [&>span]:bg-[color-mix(in_srgb,var(--accent-warm)_15%,transparent)] [&>span]:text-[var(--accent-warm)] [&>div]:min-w-0 [&>div]:grid [&>div]:gap-0.5 [&_p]:m-0 [&_p]:[font-size:0.6rem] [&_p]:font-extrabold [&_p]:uppercase [&_p]:tracking-[0.08em] [&_p]:text-vui-fg-tertiary [&_h3]:m-0 [&_h3]:truncate [&_h3]:text-sm [&_h3]:font-extrabold";
const lead = "m-0 [font-size:0.68rem] leading-[1.5] text-vui-fg-secondary";
const identityGrid = "grid min-w-0 grid-cols-2 gap-1.5";
const identityFact = "grid min-w-0 gap-0.5 rounded-[var(--radius-control)] bg-vui-surface-row px-2 py-1.5 [&>span]:text-[0.58rem] [&>span]:text-vui-fg-tertiary [&>strong]:truncate [&>strong]:text-[0.68rem] [&>strong]:text-vui-fg-primary";
const assetList = "flex min-w-0 flex-wrap gap-1.5";
const asset = "inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-vui-border-subtle bg-vui-surface-panel px-2 py-1 [font-size:0.6rem] text-vui-fg-secondary [&>svg]:shrink-0 [&>span]:truncate";
const moneyList = "grid min-w-0 gap-1.5";
const moneyRow = "flex min-w-0 items-baseline justify-between gap-2 rounded-[var(--radius-control)] bg-vui-surface-panel px-2 py-1.5 [&>span]:truncate [&>span]:[font-size:0.6rem] [&>span]:text-vui-fg-tertiary [&>strong]:shrink-0 [&>strong]:font-mono [&>strong]:text-[0.66rem]";
const disclosure = "group rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-panel";
const summary = "cursor-pointer list-none px-2 py-1.5 [font-size:0.64rem] font-bold text-vui-fg-secondary marker:hidden group-open:border-b group-open:border-vui-border-subtle after:float-right after:content-['＋'] group-open:after:content-['－']";
const form = "grid min-w-0 grid-cols-2 gap-2 p-2 max-[1180px]:grid-cols-1";
const field = "grid min-w-0 gap-1 [&>span]:[font-size:0.6rem] [&>span]:font-bold [&>span]:text-vui-fg-tertiary";
const actions = "col-span-2 flex min-w-0 flex-wrap justify-end gap-1.5 border-t border-vui-border-subtle pt-2 max-[1180px]:col-span-1";
const draftActions = "flex min-w-0 justify-end";
const notice = "m-0 rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] px-2 py-1.5 [font-size:0.62rem] leading-[1.45] text-vui-fg-secondary";
const disclaimer = "m-0 text-[0.58rem] leading-[1.4] text-vui-fg-tertiary";

export default {
  card,
  header,
  title,
  lead,
  identityGrid,
  identityFact,
  assetList,
  asset,
  moneyList,
  moneyRow,
  disclosure,
  summary,
  form,
  field,
  actions,
  draftActions,
  notice,
  disclaimer,
} as const;
