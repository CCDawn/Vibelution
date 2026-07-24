import {
  vuiInsetFillClass,
  vuiToolbarFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  rail:
    "grid h-full min-h-0 min-w-0 [grid-template-rows:auto_minmax(0,_1fr)] gap-0 overflow-hidden",
  railHeader: `grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 border-b border-[color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] ${vuiToolbarFillClass} px-2.5 py-2 [&_div]:grid [&_div]:min-w-0 [&_div]:gap-0.5 [&_p]:m-0 [&_p]:[font-size:var(--vui-font-xs)] [&_p]:uppercase [&_p]:tracking-[0.06em] [&_p]:text-[var(--fg-tertiary)] [&_strong]:truncate [&_strong]:text-[0.9rem] [&_strong]:text-[var(--fg-primary)]`,
  closeButton: "self-start",
  railBody:
    "grid min-h-0 min-w-0 content-start gap-0 overflow-auto overscroll-contain [&_>_*]:rounded-none [&_>_*]:border-x-0 [&_>_*+[data-vui-product],_&>_*+section]:border-t [&_>_*+[data-vui-product],_&>_*+section]:border-[color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)]",
  emptyRail: `grid h-full min-h-0 place-content-center place-items-center gap-2 border border-dashed border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] ${vuiInsetFillClass} p-4 text-center text-[var(--fg-tertiary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:leading-[1.4]`,
} as const;

export default styles;
