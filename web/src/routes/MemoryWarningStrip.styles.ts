import { vuiStateWarningSoftClass } from "../design/vuiSurfaceRecipes";

const styles = {
  warningBody: "warningBody min-w-0 flex-1 [font-size:var(--vui-font-sm)] leading-snug text-[var(--fg-secondary)]",
  warningChip: "warningChip inline-flex items-center gap-1 shrink-0",
  warningStrip: `warningStrip min-w-0 flex flex-wrap items-center gap-2 ${vuiStateWarningSoftClass} !border-[color-mix(in_srgb,var(--state-warning)_28%,transparent)]`,
} as const;

export default styles;
