import { type ComponentPropsWithoutRef } from "react";

export type VToolbarProps = ComponentPropsWithoutRef<"div"> & {
  ariaLabel: string;
  /** Default wraps. Dense single-row chrome (team + experiment + actions) should pass false. */
  wrap?: boolean;
};

export function VToolbar({ ariaLabel, className, wrap = true, ...props }: VToolbarProps) {
  return (
    <div
      {...props}
      data-vui="toolbar"
      role="toolbar"
      aria-label={ariaLabel}
      className={[
        wrap
          ? "flex min-w-0 flex-wrap items-center gap-1.5"
          : "flex min-w-0 flex-nowrap items-center gap-1.5 overflow-hidden",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    />
  );
}
