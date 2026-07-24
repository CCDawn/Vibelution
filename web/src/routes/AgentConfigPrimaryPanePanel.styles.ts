import {
  vuiStateDangerPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  opsZone:
    `grid min-w-0 content-start gap-2 ${vuiStateDangerPanelClass} p-2.5`,
  opsHeader: "grid min-w-0 gap-0.5 px-0.5",
  opsTitle:
    "m-0 [font-size:var(--vui-font-xs)] font-bold uppercase tracking-[0.08em] text-[var(--state-error)]",
  opsHint:
    "m-0 [font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
} as const;

export default styles;
