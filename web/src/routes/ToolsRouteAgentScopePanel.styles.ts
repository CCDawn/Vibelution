import { vuiOpaqueRowClass } from "../design/vuiSurfaceRecipes";

const coolSurface =
  "rounded-[var(--radius-panel)] border border-[color:color-mix(in_srgb,var(--accent-cool)_20%,transparent)] bg-[color:color-mix(in_srgb,var(--accent-cool)_5%,transparent)] p-[7px]";
const rowDescendant = vuiOpaqueRowClass
  .split(/\s+/)
  .filter(Boolean)
  .map((token) => `[&>span]:${token}`)
  .join(" ");

const styles = {
  agentScopeBar:
    `grid min-w-0 grid-cols-[minmax(0,1fr)_clamp(160px,16vw,220px)_clamp(130px,14vw,180px)_fit-content(18rem)] items-center gap-[7px] ${coolSurface} max-[1180px]:grid-cols-[minmax(0,1fr)_clamp(160px,18vw,220px)_clamp(130px,14vw,180px)] max-[880px]:grid-cols-[minmax(0,1fr)_clamp(160px,22vw,220px)] max-[640px]:grid-cols-[1fr]`,
  scopeCopy:
    "grid min-w-0 gap-[2px] [&>strong]:truncate [&>strong]:[font-size:var(--vui-font-sm)] [&>strong]:font-extrabold [&>strong]:text-vui-fg-primary [&>span]:truncate [&>span]:[font-size:var(--vui-font-xs)] [&>span]:font-semibold [&>span]:text-vui-fg-tertiary",
  panelEyebrow:
    "m-0 truncate [font-size:var(--vui-font-xs)] font-bold uppercase tracking-[0.06em] text-vui-fg-tertiary",
  scopeSelect:
    "grid min-w-0 gap-[3px] [font-size:var(--vui-font-xs)] font-semibold text-vui-fg-tertiary [&_[data-vui=native-select]]:w-full",
  scopeStats:
    `flex min-w-0 flex-wrap items-center justify-end gap-1 [font-size:var(--vui-font-xs)] font-semibold text-vui-fg-tertiary max-[1180px]:col-span-full max-[1180px]:justify-start max-[640px]:col-span-auto [&>span]:inline-grid [&>span]:min-h-6 [&>span]:grid-cols-[auto_auto] [&>span]:items-center [&>span]:gap-1 ${rowDescendant} [&>span]:px-2 [&_strong]:text-vui-fg-primary`,
  deepLinkNotice:
    "col-span-full m-0 min-w-0 rounded-[var(--radius-control)] border border-[color:color-mix(in_srgb,var(--accent-cool)_32%,transparent)] bg-[color:color-mix(in_srgb,var(--accent-cool)_9%,transparent)] px-2 py-1.5 [font-size:var(--vui-font-xs)] font-semibold leading-[var(--vui-line-readable)] text-vui-accent-cool",
} as const;

export default styles;
