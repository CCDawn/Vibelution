import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { VRouteHeader } from "./VRouteHeader";
import { VSplitWorkspace } from "./VSplitWorkspace";
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
   */
  columnsClassName?: string;
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
  className,
  ...props
}: VListDetailPageProps) {
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
      />
    </VWorkbenchPage>
  );
}
