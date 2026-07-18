export type VuiTone = "neutral" | "accent" | "info" | "success" | "warning" | "danger";
export type VuiDensity = "compact" | "normal";
export type VuiButtonVariant = "primary" | "secondary" | "ghost" | "danger";

/** Height token class for density. */
export function vuiButtonDensityClass(density: VuiDensity | undefined): string {
  if (density === "normal") {
    return "min-h-[var(--vui-control-height-md)] h-[var(--vui-control-height-md)]";
  }
  return "min-h-[var(--vui-control-height-sm)] h-[var(--vui-control-height-sm)]";
}

/** @deprecated Prefer vuiButtonDensityClass; kept for HeroUI size mapping if needed. */
export function vuiControlHeight(density: VuiDensity | undefined): "sm" | "md" {
  return density === "normal" ? "md" : "sm";
}

export function vuiToneClass(tone: VuiTone | undefined): string {
  return `vui-tone-${tone ?? "neutral"}`;
}
