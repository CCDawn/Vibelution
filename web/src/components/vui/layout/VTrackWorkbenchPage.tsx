import { forwardRef, type ComponentPropsWithoutRef, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { VRouteHeader } from "./VRouteHeader";
import { VWorkbenchPage } from "./VWorkbenchPage";
import { VUI_PAGE_BODY_FILL_CLASS } from "./pageRecipeClasses";

export type VTrackWorkbenchHeader = {
  eyebrow?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  /**
   * Hide eyebrow/title column and shrink-wrap around actions
   * (e.g. Evolution supervised focus chrome).
   */
  hideIntro?: boolean;
  className?: string;
  /** Optional landmark on the header element. */
  ariaLabel?: string;
};

export type VTrackWorkbenchPageProps = Omit<ComponentPropsWithoutRef<"section">, "children" | "title"> & {
  ariaLabel?: string;
  /**
   * Route header config. Pass `null` / omit for full-bleed track body
   * (e.g. self-evolution with no route toolbar).
   */
  header?: VTrackWorkbenchHeader | null;
  /**
   * Optional track chrome band between header and body
   * (mode tabs when not placed in header.actions).
   */
  trackChrome?: ReactNode;
  trackChromeClassName?: string;
  /** Full-height domain workspace (multi-rail, panels, …). */
  children: ReactNode;
  bodyClassName?: string;
  /** Domain recipe marker, e.g. evolution-multi-rail. */
  domainRecipe?: string;
  /** Fill viewport height (default true). */
  fill?: boolean;
  className?: string;
};

/**
 * Page recipe: optional route header + optional track chrome + full-height body.
 * Prefer for multi-mode tracks (Evolution supervised/self) where the body owns
 * custom multi-rail layout instead of list-detail or dense-ops tables.
 */
/**
 * forwardRef targets the body host (div) so pane layoutRef typing stays HTMLDivElement.
 * Width reclamp measures the multi-rail body rather than the page section.
 */
export const VTrackWorkbenchPage = forwardRef<HTMLDivElement, VTrackWorkbenchPageProps>(
  function VTrackWorkbenchPage(
    {
      ariaLabel,
      header = null,
      trackChrome,
      trackChromeClassName,
      children,
      bodyClassName,
      domainRecipe,
      fill = true,
      className,
      ...props
    },
    ref,
  ) {
    const hasHeader = header != null;
    const hasTrackChrome = trackChrome != null;
    const hasTopChrome = hasHeader || hasTrackChrome;
    // Keep at most two fill rows (chrome band | body) so grid auto/1fr stays valid.
    const chromeOnlyBody = fill && !hasTopChrome;

    return (
      <VWorkbenchPage
        ariaLabel={ariaLabel}
        fill={fill}
        data-vui-recipe="track-workbench-page"
        data-vui-domain-recipe={domainRecipe}
        className={cn(
          // Single full-height cell when there is no header/chrome band.
          chromeOnlyBody ? "!grid-rows-[minmax(0,1fr)]" : undefined,
          className,
        )}
        {...props}
      >
        {hasTopChrome ? (
          <div data-vui="track-workbench-top" className="grid min-w-0 shrink-0 gap-1.5">
            {hasHeader ? (
              <VRouteHeader
                aria-label={header.ariaLabel}
                className={header.className}
                eyebrow={header.eyebrow}
                title={header.title}
                meta={header.meta}
                actions={header.actions}
                hideIntro={header.hideIntro}
              />
            ) : null}
            {hasTrackChrome ? (
              <div
                data-vui-recipe="track-workbench-chrome"
                className={cn("min-w-0 shrink-0", trackChromeClassName)}
              >
                {trackChrome}
              </div>
            ) : null}
          </div>
        ) : null}
        <div
          ref={ref}
          data-vui="track-workbench-body"
          className={cn(fill ? VUI_PAGE_BODY_FILL_CLASS : "min-h-0 min-w-0", bodyClassName)}
        >
          {children}
        </div>
      </VWorkbenchPage>
    );
  },
);
