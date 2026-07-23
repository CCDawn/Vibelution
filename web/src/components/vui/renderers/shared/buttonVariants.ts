export type VuiTone = "neutral" | "accent" | "info" | "success" | "warning" | "danger";
export type VuiDensity = "compact" | "normal";
export type VuiButtonVariant = "primary" | "secondary" | "ghost" | "danger";

/** Minimum control height for wrapping labels and grouped controls. */
export function vuiControlMinHeightClass(density: VuiDensity | undefined): string {
  if (density === "normal") {
    return "min-h-[var(--vui-control-height-md)]";
  }
  return "min-h-[var(--vui-control-height-sm)]";
}

/** Shared control geometry for the two supported operating densities. */
export function vuiControlDensityClass(density: VuiDensity | undefined): string {
  if (density === "normal") {
    return `${vuiControlMinHeightClass(density)} h-[var(--vui-control-height-md)]`;
  }
  return `${vuiControlMinHeightClass(density)} h-[var(--vui-control-height-sm)]`;
}

/** Height token class for button consumers. */
export function vuiButtonDensityClass(density: VuiDensity | undefined): string {
  return vuiControlDensityClass(density);
}

/** @deprecated Prefer vuiButtonDensityClass; kept for HeroUI size mapping if needed. */
export function vuiControlHeight(density: VuiDensity | undefined): "sm" | "md" {
  return density === "normal" ? "md" : "sm";
}

export function vuiToneClass(tone: VuiTone | undefined): string {
  return `vui-tone-${tone ?? "neutral"}`;
}
