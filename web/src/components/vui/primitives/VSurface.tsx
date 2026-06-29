import { type ComponentPropsWithoutRef, type ReactNode } from "react";

type VSurfaceElement = "article" | "aside" | "div" | "header" | "main" | "section";
type VSurfaceTone = "panel" | "glass" | "toolbar" | "row";
type VSurfacePadding = "none" | "compact" | "normal";

export type VSurfaceProps = ComponentPropsWithoutRef<"section"> & {
  as?: VSurfaceElement;
  ariaLabel?: string;
  children: ReactNode;
  "data-vui"?: string;
  padding?: VSurfacePadding;
  tone?: VSurfaceTone;
};

const toneClass: Record<VSurfaceTone, string> = {
  glass: "bg-vui-surface-glass backdrop-blur-[1px]",
  panel: "bg-vui-surface-panel/82",
  row: "bg-vui-surface-row",
  toolbar: "bg-vui-surface-toolbar",
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
  padding = "compact",
  tone = "panel",
  ...props
}: VSurfaceProps) {
  return (
    <Element
      {...props}
      data-vui={dataVui}
      aria-label={ariaLabel ?? nativeAriaLabel}
      className={[
        "min-w-0 rounded-[var(--radius-panel)] border border-vui-border-subtle shadow-none",
        toneClass[tone],
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
