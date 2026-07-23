import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { VEmptyState } from "./VEmptyState";
import { VRouteHeader } from "./VRouteHeader";
import { VToolbar } from "./VToolbar";
import { VWorkbenchPage } from "./VWorkbenchPage";

export type VDenseOpsPageProps = Omit<ComponentPropsWithoutRef<"section">, "children"> & {
  ariaLabel?: string;
  eyebrow?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  headerClassName?: string;
  /**
   * Dense ops toolbar (filters, bulk actions) wrapped in VToolbar.
   * Prefer `toolbarSlot` when the slot is already a strip (e.g. VMetricStrip).
   */
  toolbar?: ReactNode;
  toolbarAriaLabel?: string;
  /** Raw toolbar region without VToolbar chrome (metrics, status bands). */
  toolbarSlot?: ReactNode;
  /** Primary dense table / list content. */
  children?: ReactNode;
  bodyClassName?: string;
  /** Shown when the table has no rows (optional). */
  empty?: {
    title: ReactNode;
    description?: string;
    actions?: ReactNode;
  };
  /** When true and empty is set, render empty state instead of children. */
  isEmpty?: boolean;
  className?: string;
};

/**
 * Page recipe: header + dense toolbar + table/body (or empty state).
 * Prefer for ops tables, queues, and bulk-maintenance surfaces.
 */
export function VDenseOpsPage({
  ariaLabel,
  eyebrow,
  title,
  meta,
  actions,
  headerClassName,
  toolbar,
  toolbarAriaLabel = "Operations",
  toolbarSlot,
  children,
  bodyClassName,
  empty,
  isEmpty = false,
  className,
  ...props
}: VDenseOpsPageProps) {
  return (
    <VWorkbenchPage ariaLabel={ariaLabel} className={className} data-vui-recipe="dense-ops-page" {...props}>
      <VRouteHeader
        className={headerClassName}
        eyebrow={eyebrow}
        title={title}
        meta={meta}
        actions={actions}
      />
      {toolbarSlot ? <div data-vui-recipe="dense-ops-toolbar">{toolbarSlot}</div> : null}
      {toolbar ? (
        <VToolbar ariaLabel={toolbarAriaLabel} data-vui-recipe="dense-ops-toolbar">
          {toolbar}
        </VToolbar>
      ) : null}
      <div data-vui="dense-ops-body" className={["min-h-0 min-w-0", bodyClassName].filter(Boolean).join(" ")}>
        {isEmpty && empty ? (
          empty.description ? (
            <VEmptyState title={empty.title} actions={empty.actions}>
              {empty.description}
            </VEmptyState>
          ) : (
            <VEmptyState title={empty.title} actions={empty.actions} />
          )
        ) : (
          children
        )}
      </div>
    </VWorkbenchPage>
  );
}
