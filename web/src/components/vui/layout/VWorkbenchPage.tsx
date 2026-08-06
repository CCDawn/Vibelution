import { forwardRef, type ComponentPropsWithoutRef, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { VUI_PAGE_FILL_CLASS } from "./pageRecipeClasses";

export type VWorkbenchPageProps = ComponentPropsWithoutRef<"section"> & {
  ariaLabel?: string;
  children: ReactNode;
  /**
   * When true, page fills the viewport cell (header auto + body 1fr).
   * Prefer for workbench recipes so shells stay full-height without per-route CSS.
   */
  fill?: boolean;
};

export const VWorkbenchPage = forwardRef<HTMLElement, VWorkbenchPageProps>(function VWorkbenchPage(
  {
    ariaLabel,
    children,
    className,
    fill = false,
    ...props
  },
  ref,
) {
  return (
    <section
      {...props}
      ref={ref}
      data-vui="workbench-page"
      data-fill={fill ? "true" : "false"}
      aria-label={ariaLabel}
      className={cn(
        "min-h-0 min-w-0 text-vui-fg-primary",
        "bg-transparent [--vui-workspace-sidebar:320px] [--vui-workspace-aside:320px]",
        fill
          ? VUI_PAGE_FILL_CLASS
          : "grid content-start gap-2",
        className,
      )}
    >
      {children}
    </section>
  );
});
