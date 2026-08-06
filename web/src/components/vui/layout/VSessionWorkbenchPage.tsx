import { forwardRef, type ComponentPropsWithoutRef, type CSSProperties, type ReactNode, type RefObject } from "react";

import { cn } from "../lib/cn";
import { VRouteHeader } from "./VRouteHeader";
import { VWorkbenchPage } from "./VWorkbenchPage";
import { VUI_PAGE_BODY_FILL_CLASS } from "./pageRecipeClasses";

export type VSessionWorkbenchHeader = {
  eyebrow?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  hideIntro?: boolean;
  className?: string;
  ariaLabel?: string;
};

export type VSessionWorkbenchPageProps = Omit<ComponentPropsWithoutRef<"div">, "children" | "title"> & {
  ariaLabel?: string;
  /**
   * Optional route header. Pass `null` / omit when the app chrome already owns the title
   * (Chat coding workbench).
   */
  header?: VSessionWorkbenchHeader | null;
  /** Domain marker, e.g. chat-session-workbench. */
  domainRecipe?: string;
  /** Permanent pane layout id (e.g. WORKBENCH_LAYOUT_IDS.chat). */
  layoutId?: string;
  /**
   * Geometry host ref for dual-pane resize/reclamp.
   * Prefer this over outer ref when the host is an inner filled body.
   */
  layoutRef?: RefObject<HTMLDivElement | null>;
  /** Full-viewport page fill (default true). */
  fill?: boolean;
  /**
   * When true (default), the dual-pane host is the page root (Chat-style).
   * When false, page is VWorkbenchPage + filled body host (header-friendly).
   */
  hostAsRoot?: boolean;
  /** Classes for the dual-pane geometry host (grid template, height). */
  hostClassName?: string;
  hostStyle?: CSSProperties;
  /** Responsive overlay backdrop. */
  overlay?: ReactNode;
  /** Right / status rail. */
  statusRail?: ReactNode;
  leftResizeHandle?: ReactNode;
  /** Main session / conversation column. */
  session?: ReactNode;
  rightResizeHandle?: ReactNode;
  /** Left conversation index / directory rail. */
  indexRail?: ReactNode;
  /** Host-level dialogs and portals. */
  children?: ReactNode;
  className?: string;
};

/**
 * Page recipe: session workbench with index + session + status rails.
 * Prefer for Chat dual-pane (domain geometry stays in route layout hooks).
 */
export const VSessionWorkbenchPage = forwardRef<HTMLDivElement, VSessionWorkbenchPageProps>(
  function VSessionWorkbenchPage(
    {
      ariaLabel,
      header = null,
      domainRecipe,
      layoutId,
      layoutRef,
      fill = true,
      hostAsRoot = true,
      hostClassName,
      hostStyle,
      overlay = null,
      statusRail = null,
      leftResizeHandle = null,
      session = null,
      rightResizeHandle = null,
      indexRail = null,
      children = null,
      className,
      ...props
    },
    ref,
  ) {
    const hasHeader = header != null;
    const host = (
      <div
        ref={hostAsRoot ? (layoutRef ?? ref) : layoutRef}
        {...(hostAsRoot ? props : {})}
        data-vui={hostAsRoot ? (props as { "data-vui"?: string })["data-vui"] ?? "session-workbench-host" : "session-workbench-host"}
        data-vui-recipe={hostAsRoot ? "session-workbench-page" : undefined}
        data-vui-domain-recipe={hostAsRoot ? domainRecipe : undefined}
        data-vui-layout-id={layoutId}
        aria-label={hostAsRoot ? ariaLabel : undefined}
        className={cn(hostAsRoot ? className : undefined, !hostAsRoot && fill ? "h-full min-h-0" : undefined, hostClassName)}
        style={hostStyle}
      >
        {overlay}
        {statusRail}
        {leftResizeHandle}
        {session}
        {rightResizeHandle}
        {indexRail}
        {children}
      </div>
    );

    if (hostAsRoot) {
      return host;
    }

    return (
      <VWorkbenchPage
        ref={ref as never}
        ariaLabel={ariaLabel}
        fill={fill}
        data-vui-recipe="session-workbench-page"
        data-vui-domain-recipe={domainRecipe}
        className={cn(hasHeader ? undefined : fill ? "!grid-rows-[minmax(0,1fr)]" : undefined, className)}
        {...props}
      >
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
        <div data-vui="session-workbench-body" className={fill ? VUI_PAGE_BODY_FILL_CLASS : "min-h-0 min-w-0"}>
          {host}
        </div>
      </VWorkbenchPage>
    );
  },
);
