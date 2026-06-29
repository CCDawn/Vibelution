import { type ComponentPropsWithoutRef } from "react";

export type VToolbarProps = ComponentPropsWithoutRef<"div"> & {
  ariaLabel: string;
};

export function VToolbar({ ariaLabel, className, ...props }: VToolbarProps) {
  return (
    <div
      {...props}
      data-vui="toolbar"
      role="toolbar"
      aria-label={ariaLabel}
      className={["flex min-w-0 flex-wrap items-center gap-1.5", className]
        .filter(Boolean)
        .join(" ")}
    />
  );
}
