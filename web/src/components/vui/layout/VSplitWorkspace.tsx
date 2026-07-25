import { type ComponentPropsWithoutRef, type ReactNode, useMemo } from "react";

import { PaneResizeHandle } from "../../layout/PaneResizeHandle";
import { usePersistedPaneResize, type UsePersistedPaneResizeResult } from "../../layout/usePersistedPaneResize";
import type { PaneSpec } from "../../layout/paneLayoutPersistence";

const DEFAULT_SIDEBAR: PaneSpec = {
  id: "sidebar",
  defaultWidth: 320,
  minWidth: 220,
  maxWidth: 480,
};

const DEFAULT_ASIDE: PaneSpec = {
  id: "aside",
  defaultWidth: 320,
  minWidth: 240,
  maxWidth: 480,
};

export type VSplitWorkspaceResizeConfig = {
  /** Permanent memory key — required for resize + persistence. */
  layoutId: string;
  sidebar?: Partial<PaneSpec>;
  aside?: Partial<PaneSpec>;
  /** Set false to keep fixed CSS columns (legacy). Default true when layoutId is set. */
  enabled?: boolean;
};

export type VSplitWorkspaceProps = Omit<ComponentPropsWithoutRef<"div">, "children"> & {
  aside?: ReactNode;
  main: ReactNode;
  sidebar?: ReactNode;
  /**
   * Override the default column template.
   * Pass `""` when `className` fully owns the grid columns (route style maps).
   * Ignored when resizable is active (pixel widths + handles take over).
   */
  columnsClassName?: string;
  /**
   * Enable left/right drag with permanent localStorage memory.
   * Prefer `{ layoutId: "skills" }` — all list-detail sidebars should pass a stable id.
   */
  resize?: VSplitWorkspaceResizeConfig | false;
};

function mergePaneSpec(base: PaneSpec, partial?: Partial<PaneSpec>): PaneSpec {
  return {
    id: partial?.id || base.id,
    defaultWidth: partial?.defaultWidth ?? base.defaultWidth,
    minWidth: partial?.minWidth ?? base.minWidth,
    maxWidth: partial?.maxWidth ?? base.maxWidth,
  };
}

/** Drop route-level grid column recipes when flex+resize owns the layout. */
function stripGridLayoutClasses(className?: string): string {
  if (!className) {
    return "";
  }
  return className
    .split(/\s+/)
    .filter((token) => {
      if (!token) {
        return false;
      }
      if (token === "grid") {
        return false;
      }
      if (token.includes("grid-cols") || token.includes("grid-rows")) {
        return false;
      }
      return true;
    })
    .join(" ");
}

function ResizableSplitWorkspace({
  aside,
  className,
  main,
  sidebar,
  resize,
  ...props
}: VSplitWorkspaceProps & { resize: VSplitWorkspaceResizeConfig }) {
  const hasSidebar = Boolean(sidebar);
  const hasAside = Boolean(aside);
  const panes = useMemo(() => {
    const list: PaneSpec[] = [];
    if (hasSidebar) {
      list.push(mergePaneSpec(DEFAULT_SIDEBAR, resize.sidebar));
    }
    if (hasAside) {
      list.push(mergePaneSpec(DEFAULT_ASIDE, resize.aside));
    }
    return list;
  }, [hasAside, hasSidebar, resize.aside, resize.sidebar]);

  const {
    layoutRef,
    widths,
    draggingPaneId,
    startResize,
    onResizeKeyDown,
    getPaneStyle,
  }: UsePersistedPaneResizeResult = usePersistedPaneResize({
    layoutId: resize.layoutId,
    panes,
  });

  const sidebarSpec = panes.find((pane) => pane.id === (resize.sidebar?.id || "sidebar"));
  const asideSpec = panes.find((pane) => pane.id === (resize.aside?.id || "aside"));
  const sidebarWidth = sidebarSpec ? widths[sidebarSpec.id] ?? sidebarSpec.defaultWidth : 0;
  const asideWidth = asideSpec ? widths[asideSpec.id] ?? asideSpec.defaultWidth : 0;

  return (
    <div
      {...props}
      ref={layoutRef}
      data-vui="split-workspace"
      data-vui-resizable="true"
      data-vui-layout-id={resize.layoutId}
      className={["flex min-h-0 min-w-0 gap-0 overflow-hidden", stripGridLayoutClasses(className)].filter(Boolean).join(" ")}
    >
      {sidebar && sidebarSpec ? (
        <>
          <aside
            data-vui="split-sidebar"
            className="min-h-0 min-w-0 shrink-0 overflow-hidden"
            style={{
              width: sidebarWidth,
              flexBasis: sidebarWidth,
              minWidth: sidebarSpec.minWidth,
              maxWidth: sidebarSpec.maxWidth,
            }}
          >
            {sidebar}
          </aside>
          <PaneResizeHandle
            label="调整左侧栏宽度"
            valueNow={sidebarWidth}
            valueMin={sidebarSpec.minWidth}
            valueMax={sidebarSpec.maxWidth}
            active={draggingPaneId === sidebarSpec.id}
            onPointerDown={(event) => startResize(sidebarSpec.id, event, { direction: 1 })}
            onKeyDown={(event) => onResizeKeyDown(sidebarSpec.id, event, { direction: 1 })}
          />
        </>
      ) : null}
      <main data-vui="split-main" className="min-h-0 min-w-0 flex-1 overflow-hidden">
        {main}
      </main>
      {aside && asideSpec ? (
        <>
          <PaneResizeHandle
            label="调整右侧栏宽度"
            valueNow={asideWidth}
            valueMin={asideSpec.minWidth}
            valueMax={asideSpec.maxWidth}
            active={draggingPaneId === asideSpec.id}
            onPointerDown={(event) => startResize(asideSpec.id, event, { direction: -1 })}
            onKeyDown={(event) => onResizeKeyDown(asideSpec.id, event, { direction: -1 })}
          />
          <aside
            data-vui="split-aside"
            className="min-h-0 min-w-0 shrink-0 overflow-hidden"
            style={{
              width: asideWidth,
              flexBasis: asideWidth,
              minWidth: asideSpec.minWidth,
              maxWidth: asideSpec.maxWidth,
            }}
          >
            {aside}
          </aside>
        </>
      ) : null}
    </div>
  );
}

export function VSplitWorkspace({
  aside,
  className,
  columnsClassName,
  main,
  sidebar,
  resize,
  ...props
}: VSplitWorkspaceProps) {
  if (resize && typeof resize === "object" && resize.layoutId && resize.enabled !== false) {
    return (
      <ResizableSplitWorkspace
        {...props}
        aside={aside}
        className={className}
        main={main}
        sidebar={sidebar}
        resize={resize}
      />
    );
  }

  const columns =
    columnsClassName !== undefined
      ? columnsClassName
      : aside
        ? "grid-cols-[minmax(0,var(--vui-workspace-sidebar))_minmax(0,1fr)_minmax(0,var(--vui-workspace-aside))]"
        : sidebar
          ? "grid-cols-[minmax(0,var(--vui-workspace-sidebar))_minmax(0,1fr)]"
          : "grid-cols-[minmax(0,1fr)]";

  return (
    <div
      {...props}
      data-vui="split-workspace"
      className={["grid min-h-0 min-w-0 gap-2", columns, className].filter(Boolean).join(" ")}
    >
      {sidebar ? (
        <aside data-vui="split-sidebar" className="min-h-0 min-w-0">
          {sidebar}
        </aside>
      ) : null}
      <main data-vui="split-main" className="min-h-0 min-w-0">
        {main}
      </main>
      {aside ? (
        <aside data-vui="split-aside" className="min-h-0 min-w-0">
          {aside}
        </aside>
      ) : null}
    </div>
  );
}
