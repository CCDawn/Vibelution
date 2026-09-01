const route = "h-full min-h-0 min-w-0 overflow-auto bg-[radial-gradient(circle_at_18%_2%,color-mix(in_srgb,var(--accent-cool)_12%,transparent),transparent_30rem),radial-gradient(circle_at_84%_8%,color-mix(in_srgb,var(--state-warning)_8%,transparent),transparent_28rem),var(--vui-surface-workspace)] px-[clamp(28px,5vw,78px)] py-[clamp(26px,4vh,48px)]";
const hero = "mx-auto mb-6 flex max-w-[1220px] min-w-0 items-end justify-between gap-8 max-[900px]:items-start max-[900px]:flex-col";
const heroCopy = "grid min-w-0 gap-2";
const kicker = "m-0 font-mono text-[0.65rem] font-extrabold uppercase tracking-[0.16em] text-[var(--accent-cool)]";
const title = "m-0 text-[clamp(1.65rem,2.4vw,2.25rem)] font-[820] tracking-[-0.04em] text-vui-fg-primary";
const subtitle = "m-0 max-w-[68ch] [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-vui-fg-tertiary";
const count = "grid shrink-0 justify-items-end gap-0.5 [&>strong]:font-mono [&>strong]:text-[2rem] [&>strong]:text-vui-fg-primary [&>span]:[font-size:var(--vui-font-xs)] [&>span]:text-vui-fg-tertiary";
const grid = "mx-auto grid max-w-[1220px] min-w-0 gap-5";
const card = "relative isolate grid min-h-[min(590px,calc(100dvh-250px))] min-w-0 grid-cols-[minmax(0,1.08fr)_minmax(360px,0.92fr)] overflow-hidden rounded-[28px] border border-vui-border-subtle bg-[radial-gradient(circle_at_84%_22%,color-mix(in_srgb,var(--accent-cool)_20%,transparent),transparent_34%),linear-gradient(135deg,var(--vui-surface-panel),color-mix(in_srgb,var(--vui-surface-workspace)_78%,black))] shadow-[var(--vui-elevation-panel)] max-[960px]:grid-cols-1";
const cardGridLines = "pointer-events-none absolute inset-0 -z-[1] opacity-40 [background:linear-gradient(90deg,transparent_49.9%,color-mix(in_srgb,var(--vui-border-subtle)_68%,transparent)_50%,transparent_50.1%),linear-gradient(color-mix(in_srgb,var(--vui-border-subtle)_48%,transparent)_1px,transparent_1px)_0_0/100%_72px]";
const cardCopy = "flex min-w-0 flex-col p-[clamp(30px,4vh,48px)_clamp(26px,3vw,42px)_clamp(28px,4vh,42px)_clamp(34px,4.4vw,64px)] max-[960px]:p-8";
const presenceRow = "flex items-center justify-between gap-4";
const presenceStatus = "flex min-w-0 items-center gap-2";
const unreadBadge = "inline-flex h-6 items-center rounded-full bg-[var(--accent-cool)] px-2.5 [font-size:0.62rem] font-bold text-[var(--bg-primary)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--accent-cool)_12%,transparent)]";
const localTime = "shrink-0 font-mono text-[0.66rem] text-vui-fg-tertiary";
const identityBlock = "mt-auto min-w-0 [&>h2]:m-0 [&>h2]:mt-3 [&>h2]:text-[clamp(3rem,4vw,4.2rem)] [&>h2]:font-[760] [&>h2]:leading-none [&>h2]:tracking-[-0.06em] [&>h2]:text-vui-fg-primary";
const identityCode = "m-0 font-mono text-[0.64rem] font-bold tracking-[0.12em] text-[var(--accent-cool)]";
const identity = "m-0 mt-2 line-clamp-2 [font-size:var(--vui-font-sm)] font-bold leading-[1.5] text-vui-fg-secondary";
const about = "m-0 mt-3 max-w-[58ch] line-clamp-3 [font-size:var(--vui-font-sm)] leading-[1.7] text-vui-fg-tertiary";
const nowCard = "mt-[clamp(20px,3vh,28px)] grid min-w-0 grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3 rounded-[15px] border border-vui-border-subtle bg-[color-mix(in_srgb,var(--vui-surface-row)_78%,var(--vui-surface-panel))] px-4 py-3";
const nowIcon = "grid size-10 place-items-center rounded-xl bg-[color-mix(in_srgb,var(--accent-cool)_14%,transparent)] text-[var(--accent-cool)]";
const nowCopy = "grid min-w-0 gap-0.5 [&>span]:[font-size:0.64rem] [&>span]:text-vui-fg-tertiary [&>strong]:truncate [&>strong]:[font-size:var(--vui-font-sm)] [&>strong]:font-bold [&>strong]:text-vui-fg-primary";
const nowTime = "shrink-0 font-mono text-[0.62rem] text-vui-fg-tertiary max-[560px]:hidden";
const relationshipStrip = "mt-4 grid grid-cols-3 border-y border-vui-border-subtle [&>span]:grid [&>span]:min-w-0 [&>span]:gap-1 [&>span]:px-4 [&>span]:py-3.5 [&>span:first-child]:pl-0 [&>span+span]:border-l [&>span+span]:border-vui-border-subtle [&_small]:[font-size:0.6rem] [&_small]:text-vui-fg-tertiary [&_strong]:line-clamp-2 [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:font-bold [&_strong]:leading-[1.45] [&_strong]:text-vui-fg-secondary max-[560px]:grid-cols-1 max-[560px]:[&>span]:px-0 max-[560px]:[&>span+span]:border-l-0 max-[560px]:[&>span+span]:border-t";
const cardActions = "mt-[clamp(18px,2.8vh,26px)] flex flex-wrap items-center gap-2.5";
const primaryAction = "!h-11 !min-h-11 !px-5";
const secondaryAction = "!h-11 !min-h-11 !px-4";
const cardPortrait = "!min-h-full max-[960px]:!min-h-[420px]";
const portrait = "group relative isolate block min-h-[430px] overflow-hidden bg-[radial-gradient(circle_at_50%_24%,color-mix(in_srgb,var(--accent-cool)_24%,transparent),transparent_43%),var(--vui-surface-rail)] data-[scene-key=campus-day]:bg-[radial-gradient(circle_at_54%_20%,color-mix(in_srgb,var(--accent-cool)_28%,transparent),transparent_40%),linear-gradient(160deg,var(--vui-surface-rail),color-mix(in_srgb,var(--state-success)_10%,var(--vui-surface-rail)))] data-[scene-key=office-day]:bg-[radial-gradient(circle_at_52%_18%,color-mix(in_srgb,var(--state-warning)_18%,transparent),transparent_40%),linear-gradient(160deg,var(--vui-surface-rail),var(--vui-surface-workspace))] data-[scene-key=home-evening]:bg-[radial-gradient(circle_at_50%_20%,color-mix(in_srgb,var(--state-warning)_24%,transparent),transparent_42%),linear-gradient(165deg,var(--vui-surface-rail),color-mix(in_srgb,var(--accent-cool)_8%,black))] data-[scene-key=home-night]:bg-[radial-gradient(circle_at_50%_20%,color-mix(in_srgb,var(--accent-cool)_18%,transparent),transparent_40%),linear-gradient(165deg,var(--vui-surface-rail),color-mix(in_srgb,var(--vui-surface-workspace)_72%,black))] data-[scene-key=outdoors-rain]:bg-[radial-gradient(circle_at_50%_16%,color-mix(in_srgb,var(--accent-cool)_22%,transparent),transparent_38%),linear-gradient(165deg,color-mix(in_srgb,var(--vui-surface-rail)_84%,var(--accent-cool)),var(--vui-surface-workspace))] before:pointer-events-none before:absolute before:inset-[11%_6%_0_5%] before:z-[1] before:rounded-[48%_48%_0_0] before:border before:border-vui-border-subtle before:content-['']";
const avatar = "group relative isolate grid size-11 shrink-0 place-items-center overflow-hidden rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_16%,var(--vui-surface-row))] data-[expression-id=happy]:border-[color-mix(in_srgb,var(--state-success)_55%,var(--vui-border-subtle))] data-[expression-id=low]:saturate-[0.72] data-[expression-id=tired]:brightness-90";
const portraitFigure = "pointer-events-none absolute inset-0 z-[2] origin-bottom";
const portraitSceneImage = "pointer-events-none absolute inset-0 z-0 h-full w-full object-cover opacity-35 saturate-75";
const portraitImage = "absolute bottom-[-2%] left-1/2 h-[98%] w-[110%] max-w-none -translate-x-1/2 object-contain object-bottom drop-shadow-[0_24px_28px_rgba(0,0,0,0.38)] group-data-[expression-id=happy]:saturate-[1.08] group-data-[expression-id=low]:saturate-[0.72] group-data-[expression-id=tired]:brightness-90";
const avatarImage = "absolute inset-0 h-full w-full object-cover object-[50%_24%]";
const portraitInitials = "absolute left-1/2 top-[38%] z-[1] -translate-x-1/2 -translate-y-1/2 font-mono text-[clamp(1rem,2vw,1.55rem)] font-extrabold tracking-[0.08em] text-vui-fg-primary";
const portraitGlow = "pointer-events-none absolute left-1/2 top-[17%] z-[1] size-[min(30vw,390px)] -translate-x-1/2 rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_20%,transparent)] shadow-[0_0_0_50px_color-mix(in_srgb,var(--vui-border-subtle)_14%,transparent),0_0_100px_color-mix(in_srgb,var(--accent-cool)_16%,transparent)]";
const portraitBlink = "pointer-events-none absolute left-1/2 top-[31%] z-[3] flex -translate-x-1/2 gap-[clamp(10px,2.2vw,28px)] opacity-0 [&>i]:block [&>i]:h-[2px] [&>i]:w-[clamp(7px,1.1vw,13px)] [&>i]:rounded-full [&>i]:bg-[color-mix(in_srgb,var(--vui-fg-primary)_62%,transparent)] group-data-[companion-portrait=avatar]:hidden";
const onlineDot = "absolute bottom-3 right-3 z-[3] size-2.5 rounded-full border-2 border-vui-surface-rail bg-[var(--state-success)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--state-success)_12%,transparent)] data-[compact=true]:bottom-0 data-[compact=true]:right-0";
const footer = "mx-auto mt-4 flex max-w-[1220px] items-center justify-between gap-5 [font-size:var(--vui-font-xs)] text-vui-fg-tertiary max-[760px]:flex-col max-[760px]:items-start";
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
  cardGridLines,
  cardCopy,
  presenceRow,
  presenceStatus,
  unreadBadge,
  localTime,
  identityBlock,
  identityCode,
  identity,
  about,
  nowCard,
  nowIcon,
  nowCopy,
  nowTime,
  relationshipStrip,
  cardActions,
  primaryAction,
  secondaryAction,
  cardPortrait,
  portrait,
  avatar,
  portraitFigure,
  portraitSceneImage,
  portraitImage,
  avatarImage,
  portraitInitials,
  portraitGlow,
  portraitBlink,
  onlineDot,
  footer,
  stateHost,
} as const;
