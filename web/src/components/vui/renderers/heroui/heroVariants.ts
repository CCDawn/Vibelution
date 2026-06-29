export type VuiTone = "neutral" | "accent" | "info" | "success" | "warning" | "danger";
export type VuiDensity = "compact" | "normal";
export type VuiButtonVariant = "primary" | "secondary" | "ghost" | "danger";

export function vuiControlHeight(density: VuiDensity | undefined): "sm" | "md" {
  return density === "normal" ? "md" : "sm";
}

export function vuiToneClass(tone: VuiTone | undefined): string {
  return `vui-tone-${tone ?? "neutral"}`;
}
