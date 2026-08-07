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

/**
 * Route shells often pass `styles.route` which still carries legacy
 * `grid grid-rows-[auto_minmax(0,1fr)]`. `cn` does not de-dupe Tailwind, so those
 * utilities fight recipe fill and collapse the body to content height (huge empty floor).
 * Strip display / track geometry so fillLayout always owns the page box.
 */
function stripConflictingFillGeometry(className: string | undefined): string {
  if (!className) {
    return "";
  }
  return className
    .split(/\s+/)
    .filter((token) => {
      if (!token) {
        return false;
      }
      if (
        token === "grid"
        || token === "flex"
        || token === "inline-grid"
        || token === "inline-flex"
        || token === "block"
        || token === "contents"
      ) {
        return false;
      }
      if (
        token.startsWith("grid-rows-")
        || token.startsWith("grid-cols-")
        || token.startsWith("auto-rows-")
        || token.startsWith("auto-cols-")
      ) {
        return false;
      }
      if (
        token === "content-start"
        || token === "content-end"
        || token === "content-center"
        || token === "content-between"
        || token === "content-around"
        || token === "content-evenly"
        || token === "content-stretch"
        || token === "content-baseline"
      ) {
        return false;
      }
      return true;
    })
    .join(" ");
}

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

  const safeClassName = fill ? stripConflictingFillGeometry(className) : className;

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
        // Safe extras first; recipe fill geometry always last so it owns display/rows.
        safeClassName,
        fillClass,
      )}
    >
      {children}
    </section>
  );
});
