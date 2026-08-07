import { forwardRef, type ComponentPropsWithoutRef, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { VUI_PAGE_FILL_CLASS, VUI_PAGE_STACK_FILL_CLASS } from "./pageRecipeClasses";

export type VWorkbenchPageFillLayout = "header-body" | "stack";

export type VWorkbenchPageProps = ComponentPropsWithoutRef<"section"> & {
  ariaLabel?: string;
  children: ReactNode;
  /**
   * When true, page fills the viewport cell.
   * Prefer for workbench recipes so shells stay full-height without per-route CSS.
   */
  fill?: boolean;
  /**
   * `header-body` (default): grid rows auto + 1fr — requires a header row child then body.
   * `stack`: flex column fill — use when hideHeader so the only child is the body
   * (otherwise body sits in the auto track and collapses to content height).
   */
  fillLayout?: VWorkbenchPageFillLayout;
};

export const VWorkbenchPage = forwardRef<HTMLElement, VWorkbenchPageProps>(function VWorkbenchPage(
  {
    ariaLabel,
    children,
    className,
    fill = false,
    fillLayout = "header-body",
    ...props
  },
  ref,
) {
  const fillClass = !fill
    ? "grid content-start gap-2"
    : fillLayout === "stack"
      ? VUI_PAGE_STACK_FILL_CLASS
      : VUI_PAGE_FILL_CLASS;

  return (
    <section
      {...props}
      ref={ref}
      data-vui="workbench-page"
      data-fill={fill ? "true" : "false"}
      data-fill-layout={fill ? fillLayout : undefined}
      aria-label={ariaLabel}
      className={cn(
        "min-h-0 min-w-0 text-vui-fg-primary",
        "bg-transparent [--vui-workspace-sidebar:320px] [--vui-workspace-aside:320px]",
        fillClass,
        className,
      )}
    >
      {children}
    </section>
  );
});
