import { type ComponentPropsWithoutRef, type ReactNode } from "react";

type VSurfaceElement = "article" | "aside" | "div" | "header" | "main" | "section";
export type VSurfaceTone =
  | "workspace"
  | "region"
  | "card"
  | "inset"
  | "control"
  | "popover"
  | "panel"
  | "rail"
  | "glass"
  | "toolbar"
  | "row";
export type VSurfaceElevation = "flat" | "panel" | "overlay";
type VSurfacePadding = "none" | "compact" | "normal";

export type VSurfaceProps = ComponentPropsWithoutRef<"section"> & {
  as?: VSurfaceElement;
  ariaLabel?: string;
  children: ReactNode;
  "data-vui"?: string;
  elevation?: VSurfaceElevation;
  padding?: VSurfacePadding;
  tone?: VSurfaceTone;
};

const toneClass: Record<VSurfaceTone, string> = {
  card: "bg-vui-surface-card",
  control: "bg-vui-surface-control",
  glass: "bg-vui-surface-glass backdrop-blur-[1px]",
  inset: "bg-vui-surface-inset",
  panel: "bg-vui-surface-panel",
  popover: "bg-vui-surface-popover backdrop-blur-[1px]",
  rail: "bg-vui-surface-rail",
  region: "bg-vui-surface-region",
  row: "bg-vui-surface-row",
  toolbar: "bg-vui-surface-toolbar",
  workspace: "bg-vui-surface-workspace",
};

const elevationClass: Record<VSurfaceElevation, string> = {
  flat: "shadow-none",
  panel: "shadow-[var(--vui-elevation-panel)]",
  overlay: "shadow-[var(--vui-elevation-overlay)]",
};

const paddingClass: Record<VSurfacePadding, string> = {
  compact: "p-2",
  none: "",
  normal: "p-3",
};

export function VSurface({
  as: Element = "section",
  ariaLabel,
  "aria-label": nativeAriaLabel,
  className,
  children,
  "data-vui": dataVui = "surface",
  elevation = "flat",
  padding = "compact",
  tone = "panel",
  ...props
}: VSurfaceProps) {
  return (
    <Element
      {...props}
      data-vui={dataVui}
      data-tone={tone}
      data-elevation={elevation}
      aria-label={ariaLabel ?? nativeAriaLabel}
      className={[
        "min-w-0 rounded-[var(--vui-radius-panel-soft)] border border-vui-border-subtle",
        toneClass[tone],
        elevationClass[elevation],
        paddingClass[padding],
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </Element>
  );
}
