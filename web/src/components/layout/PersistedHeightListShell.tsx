import type { ComponentPropsWithoutRef, CSSProperties, ReactNode } from "react";
import { useMemo } from "react";

import { PaneHeightResizeHandle } from "./PaneHeightResizeHandle";
import type { PaneHeightSpec } from "./paneHeightPersistence";
import { usePersistedPaneHeight } from "./usePersistedPaneHeight";

export type PersistedHeightListShellProps = Omit<
  ComponentPropsWithoutRef<"div">,
  "children" | "className" | "style"
> & {
  /** WORKBENCH_LAYOUT_IDS.* value — shares vibelution.pane-heights.v1 namespace. */
  layoutId: string;
  /** Single-pane height contract for this list shell. Prefer a module-level constant. */
  pane: PaneHeightSpec;
  /** Accessible label for the height separator. */
  label: string;
  className?: string;
  /** Placement-only class for PaneHeightResizeHandle. */
  resizeHandleClassName?: string;
  /** Expand the current page into its owning scroll workspace instead of nesting another fixed-height scroller. */
  expandToContent?: boolean;
  children: ReactNode;
};

/**
 * Scrollable list shell with permanent height memory + shared row-resize handle.
 * Use for fixed max-h candidate/list strips (Teams source-collection, etc.).
 */
export function PersistedHeightListShell({
  layoutId,
  pane,
  label,
  className = "",
  resizeHandleClassName = "",
  expandToContent = false,
  children,
  ...props
}: PersistedHeightListShellProps) {
  // Stable panes identity for the height hook (avoid reset on every render).
  const panes = useMemo(() => [pane] as const, [pane]);
  const {
    heights,
    draggingPaneId,
    startResize,
    onResizeKeyDown,
  } = usePersistedPaneHeight({
    layoutId,
    panes,
  });
  const height = heights[pane.id] ?? pane.defaultHeight;
  const style = expandToContent
    ? {
        height: "auto",
      }
    : {
        height: `${height}px`,
      } as CSSProperties;

  return (
    <>
      <div
        className={className}
        style={style}
        data-vui-height-pane={pane.id}
        data-vui-layout-id={layoutId}
        data-vui-expand-to-content={expandToContent ? "true" : undefined}
        {...props}
      >
        {children}
      </div>
      {expandToContent ? null : (
        <PaneHeightResizeHandle
          label={label}
          valueNow={height}
          valueMin={pane.minHeight}
          valueMax={pane.maxHeight}
          active={draggingPaneId === pane.id}
          className={resizeHandleClassName}
          onPointerDown={(event) => startResize(pane.id, event, { direction: 1 })}
          onKeyDown={(event) => onResizeKeyDown(pane.id, event, { direction: 1 })}
        />
      )}
    </>
  );
}
