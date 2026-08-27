const route = "h-full min-h-0 min-w-0 overflow-auto bg-[radial-gradient(circle_at_20%_0%,color-mix(in_srgb,var(--accent-cool)_10%,transparent),transparent_28rem),radial-gradient(circle_at_82%_2%,color-mix(in_srgb,var(--state-warning)_7%,transparent),transparent_26rem),var(--vui-surface-workspace)] px-[clamp(28px,5vw,76px)] py-9";
const hero = "mx-auto mb-6 flex max-w-[1180px] min-w-0 items-end justify-between gap-8 max-[880px]:items-start max-[880px]:flex-col";
const heroCopy = "grid min-w-0 gap-2";
const kicker = "m-0 font-mono text-[0.65rem] font-extrabold uppercase tracking-[0.14em] text-[var(--accent-cool)]";
const title = "m-0 text-[clamp(1.55rem,2.2vw,2rem)] font-[820] tracking-[-0.035em] text-vui-fg-primary";
const subtitle = "m-0 max-w-[68ch] [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-vui-fg-tertiary";
const count = "grid shrink-0 justify-items-end gap-0.5 [&>strong]:font-mono [&>strong]:text-[1.9rem] [&>strong]:text-vui-fg-primary [&>span]:[font-size:var(--vui-font-xs)] [&>span]:text-vui-fg-tertiary";
const grid = "mx-auto grid max-w-[1180px] min-w-0 grid-cols-2 gap-4 max-[1060px]:grid-cols-1";
const card = "!grid !h-auto min-h-[244px] w-full min-w-0 !max-w-none !grid-cols-[minmax(190px,42%)_minmax(0,1fr)] overflow-hidden !rounded-[var(--vui-radius-panel-soft)] !border !border-vui-border-subtle !bg-vui-surface-panel !p-0 text-left !text-vui-fg-primary !shadow-[var(--vui-elevation-panel)] transition-[transform,border-color,background-color] duration-150 hover:-translate-y-0.5 hover:!border-[color-mix(in_srgb,var(--accent-cool)_36%,var(--vui-border-subtle))] hover:!bg-vui-surface-region max-[680px]:!grid-cols-1 [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents [&_[data-slot=vui-button-label]]:overflow-visible [&_[data-slot=vui-button-label]]:whitespace-normal";
const cardCopy = "flex min-w-0 flex-col p-5";
const cardNameLine = "flex min-w-0 items-baseline justify-between gap-3 [&>strong]:min-w-0 [&>strong]:truncate [&>strong]:text-[1.05rem] [&>strong]:font-[820] [&>span]:shrink-0 [&>span]:font-mono [&>span]:text-[0.62rem] [&>span]:text-vui-fg-tertiary";
const identity = "mt-1 line-clamp-2 [font-size:var(--vui-font-xs)] font-bold leading-[1.45] text-[var(--accent-cool)]";
const presence = "mt-5 line-clamp-2 [font-size:var(--vui-font-sm)] leading-[1.5] text-vui-fg-secondary";
const about = "mt-2 line-clamp-3 [font-size:var(--vui-font-xs)] leading-[1.6] text-vui-fg-tertiary";
const enter = "mt-auto flex items-center justify-between gap-3 pt-5 [font-size:var(--vui-font-xs)] font-bold text-vui-fg-secondary [&>svg]:text-[var(--accent-cool)]";
const portrait = "relative isolate block min-h-[244px] overflow-hidden border-r border-vui-border-subtle bg-[radial-gradient(circle_at_68%_22%,color-mix(in_srgb,var(--accent-cool)_38%,transparent),transparent_27%),linear-gradient(155deg,color-mix(in_srgb,var(--accent-cool)_20%,var(--vui-surface-panel))_0%,var(--vui-surface-rail)_62%,var(--vui-surface-workspace)_100%)] max-[680px]:min-h-[190px] max-[680px]:border-r-0 max-[680px]:border-b";
const avatar = "relative isolate grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_16%,var(--vui-surface-row))]";
const portraitImage = "absolute inset-0 z-[2] h-full w-full object-cover";
const portraitInitials = "absolute left-1/2 top-[38%] z-[1] -translate-x-1/2 -translate-y-1/2 font-mono text-[clamp(1rem,2vw,1.55rem)] font-extrabold tracking-[0.08em] text-vui-fg-primary";
const portraitGlow = "absolute inset-[28%_8%_-28%_22%] -z-[1] rounded-[50%_50%_18%_18%] bg-[color-mix(in_srgb,var(--accent-cool)_22%,transparent)]";
const onlineDot = "absolute bottom-3 right-3 z-[3] h-2.5 w-2.5 rounded-full border-2 border-vui-surface-rail bg-[var(--state-success)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--state-success)_12%,transparent)] data-[compact=true]:bottom-0 data-[compact=true]:right-0";
const footer = "mx-auto mt-4 flex max-w-[1180px] items-center justify-between gap-5 [font-size:var(--vui-font-xs)] text-vui-fg-tertiary max-[760px]:flex-col max-[760px]:items-start";
const stateHost = "mx-auto max-w-[860px] py-12";

export default {
  route,
  hero,
  heroCopy,
  kicker,
  title,
  subtitle,
  count,
  grid,
  card,
  cardCopy,
  cardNameLine,
  identity,
  presence,
  about,
  enter,
  portrait,
  avatar,
  portraitImage,
  portraitInitials,
  portraitGlow,
  onlineDot,
  footer,
  stateHost,
} as const;
