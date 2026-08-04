import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { VRouteHeader } from "./VRouteHeader";
import { VSplitWorkspace, type VSplitWorkspaceResizeConfig } from "./VSplitWorkspace";
import { VWorkbenchPage } from "./VWorkbenchPage";
import { VUI_PAGE_BODY_FILL_CLASS } from "./pageRecipeClasses";

export type VListDetailPageProps = Omit<ComponentPropsWithoutRef<"section">, "children"> & {
  /** Page landmark label. */
  ariaLabel?: string;
  /** Optional eyebrow above the title. */
  eyebrow?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  /** Header actions (refresh, create, …). */
  actions?: ReactNode;
  headerClassName?: string;
  /** Optional strip between header and workspace (metrics, filters). */
  toolbar?: ReactNode;
  /** Left list / filter column. */
  list: ReactNode;
  /** Main detail / empty selection column. */
  detail: ReactNode;
  /** Optional third column. */
  aside?: ReactNode;
  /** Applied to the split workspace grid (route style maps). */
  workspaceClassName?: string;
  /**
   * Override default split columns. Pass `""` when workspaceClassName owns columns.
   * Ignored when `layoutId` enables resizable panes.
   */
  columnsClassName?: string;
  /**
   * Stable id for permanent sidebar width memory (localStorage).
   * When set, left/right rails are draggable and widths persist across reloads.
   */
  layoutId?: string;
  /** Optional min/max/default overrides for resizable panes. */
  resize?: Omit<VSplitWorkspaceResizeConfig, "layoutId">;
  /** Fill viewport height (default true). */
  fill?: boolean;
  className?: string;
};

/**
 * Page recipe: route header + optional toolbar + list/detail split.
 * Prefer this over hand-assembling VWorkbenchPage + VSplitWorkspace for new list-detail surfaces.
 */
export function VListDetailPage({
  ariaLabel,
  eyebrow,
  title,
  meta,
  actions,
  headerClassName,
  toolbar,
  list,
  detail,
  aside,
  workspaceClassName,
  columnsClassName,
  layoutId,
  resize,
  fill = true,
  className,
  ...props
}: VListDetailPageProps) {
  const resizeConfig = layoutId
    ? { layoutId, enabled: true, ...resize }
    : false;

  return (
    <VWorkbenchPage
      ariaLabel={ariaLabel}
      className={className}
      data-vui-recipe="list-detail-page"
      fill={fill}
      {...props}
    >
      <VRouteHeader
        className={headerClassName}
        eyebrow={eyebrow}
        title={title}
        meta={meta}
        actions={actions}
      />
      {toolbar ? (
        <div data-vui="list-detail-toolbar" className="min-w-0 shrink-0">
          {toolbar}
        </div>
      ) : null}
      <div className={fill ? VUI_PAGE_BODY_FILL_CLASS : "min-h-0 min-w-0"}>
        <VSplitWorkspace
          className={cn(fill ? "h-full min-h-0" : undefined, workspaceClassName)}
          columnsClassName={columnsClassName}
          sidebar={list}
          main={detail}
          aside={aside}
          resize={resizeConfig}
        />
      </div>
    </VWorkbenchPage>
  );
}
