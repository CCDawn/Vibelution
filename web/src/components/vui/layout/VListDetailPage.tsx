import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { VRouteHeader } from "./VRouteHeader";
import { VSplitWorkspace, type VSplitWorkspaceResizeConfig } from "./VSplitWorkspace";
import { VWorkbenchPage } from "./VWorkbenchPage";

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
  className,
  ...props
}: VListDetailPageProps) {
  const resizeConfig = layoutId
    ? { layoutId, enabled: true, ...resize }
    : false;

  return (
    <VWorkbenchPage ariaLabel={ariaLabel} className={className} data-vui-recipe="list-detail-page" {...props}>
      <VRouteHeader
        className={headerClassName}
        eyebrow={eyebrow}
        title={title}
        meta={meta}
        actions={actions}
      />
      {toolbar ? <div data-vui="list-detail-toolbar">{toolbar}</div> : null}
      <VSplitWorkspace
        className={workspaceClassName}
        columnsClassName={columnsClassName}
        sidebar={list}
        main={detail}
        aside={aside}
        resize={resizeConfig}
      />
    </VWorkbenchPage>
  );
}
