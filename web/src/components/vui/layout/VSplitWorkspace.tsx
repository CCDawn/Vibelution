import { type ComponentPropsWithoutRef, type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import { PaneCollapseHandle } from "../../layout/PaneCollapseHandle";
import { PaneResizeHandle } from "../../layout/PaneResizeHandle";
import { paneWidthCssVar } from "../../layout/paneCssVariables";
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

type CollapseControl = {
  separatorLabel: string;
  collapseLabel: string;
  expandLabel: string;
} & (
  | {
      /** Default placement keeps the toggle in the separator rail. */
      placement?: "rail";
      collapsed: boolean;
      onCollapsedChange: (collapsed: boolean) => void;
    }
  | {
      /** Default placement keeps the toggle in the separator rail. */
      placement?: "rail";
      collapsed?: undefined;
      onCollapsedChange?: undefined;
    }
  | {
      /** Header placement leaves the toggle to the owning page, which must control this state. */
      placement: "header";
      collapsed: boolean;
      onCollapsedChange: (collapsed: boolean) => void;
    }
);

export type VSplitWorkspaceResizeConfig = {
  /** Permanent memory key — required for resize + persistence. */
  layoutId: string;
  sidebar?: Partial<PaneSpec>;
  aside?: Partial<PaneSpec>;
  /** Optional collapse controls. Header placement requires owner-controlled state; width memory remains owned by layoutId. */
  collapse?: {
    sidebar?: CollapseControl;
    aside?: CollapseControl;
  };
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
  style,
  ...props
}: VSplitWorkspaceProps & { resize: VSplitWorkspaceResizeConfig }) {
  const hasSidebar = Boolean(sidebar);
  const hasAside = Boolean(aside);
  const [collapsedPaneIds, setCollapsedPaneIds] = useState<Set<string>>(() => new Set());
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
    registerSplitContainer,
    paneVariablesStyle,
    widths,
    draggingPaneId,
    startResize,
    onResizeKeyDown,
  }: UsePersistedPaneResizeResult = usePersistedPaneResize({
    layoutId: resize.layoutId,
    panes,
  });
  // One stable ref callback: the container both drives width reclamp and
  // hosts the --pane-w-* variables panes consume during drags.
  const setSplitContainerRef = useCallback(
    (element: HTMLDivElement | null) => {
      layoutRef.current = element;
      registerSplitContainer(element);
    },
    [layoutRef, registerSplitContainer],
  );

  const sidebarSpec = panes.find((pane) => pane.id === (resize.sidebar?.id || "sidebar"));
  const asideSpec = panes.find((pane) => pane.id === (resize.aside?.id || "aside"));
  const sidebarControlledCollapsed = resize.collapse?.sidebar?.collapsed;
  const asideControlledCollapsed = resize.collapse?.aside?.collapsed;
  // Keep only accepted owner values as the fallback if control is later removed.
  // A controlled click still requests a change without updating visibility.
  useEffect(() => {
    setCollapsedPaneIds((current) => {
      const next = new Set(current);
      for (const [id, collapsed] of [
        [sidebarSpec?.id, sidebarControlledCollapsed],
        [asideSpec?.id, asideControlledCollapsed],
      ] as const) {
        if (!id || collapsed === undefined) continue;
        if (collapsed) next.add(id);
        else next.delete(id);
      }
      return next.size === current.size && [...next].every((id) => current.has(id)) ? current : next;
    });
  }, [asideSpec?.id, asideControlledCollapsed, sidebarSpec?.id, sidebarControlledCollapsed]);
  const sidebarWidth = sidebarSpec ? widths[sidebarSpec.id] ?? sidebarSpec.defaultWidth : 0;
  const asideWidth = asideSpec ? widths[asideSpec.id] ?? asideSpec.defaultWidth : 0;
  const sidebarCollapsed = Boolean(sidebarSpec && (resize.collapse?.sidebar?.collapsed ?? collapsedPaneIds.has(sidebarSpec.id)));
  const asideCollapsed = Boolean(asideSpec && (resize.collapse?.aside?.collapsed ?? collapsedPaneIds.has(asideSpec.id)));
  const togglePane = (paneId: string, control: CollapseControl | undefined, collapsed: boolean) => {
    if (control?.collapsed !== undefined) {
      control.onCollapsedChange(!collapsed);
      return;
    }
    setCollapsedPaneIds((current) => {
      const next = new Set(current);
      if (next.has(paneId)) {
        next.delete(paneId);
      } else {
        next.add(paneId);
      }
      return next;
    });
  };

  return (
    <div
      {...props}
      ref={setSplitContainerRef}
      data-vui="split-workspace"
      data-vui-resizable="true"
      data-vui-collapsible={resize.collapse ? "true" : undefined}
      data-vui-layout-id={resize.layoutId}
      style={style ? { ...paneVariablesStyle, ...style } : paneVariablesStyle}
      className={[
        "flex min-h-0 min-w-0 flex-1 items-stretch gap-0 overflow-hidden",
        stripGridLayoutClasses(className),
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {sidebar && sidebarSpec ? (
        <>
          <aside
            data-vui="split-sidebar"
            data-collapsed={sidebarCollapsed ? "true" : "false"}
            hidden={sidebarCollapsed}
            className="flex h-full min-h-0 min-w-0 shrink-0 flex-col overflow-hidden"
            style={{
              width: `var(${paneWidthCssVar(sidebarSpec.id)})`,
              flexBasis: `var(${paneWidthCssVar(sidebarSpec.id)})`,
              minWidth: sidebarSpec.minWidth,
              maxWidth: sidebarSpec.maxWidth,
            }}
          >
            {sidebar}
          </aside>
          {resize.collapse?.sidebar ? (
            resize.collapse.sidebar.placement === "header" ? (
              sidebarCollapsed ? null : (
                <PaneResizeHandle
                  label={resize.collapse.sidebar.separatorLabel}
                  valueNow={sidebarWidth}
                  valueMin={sidebarSpec.minWidth}
                  valueMax={sidebarSpec.maxWidth}
                  active={draggingPaneId === sidebarSpec.id}
                  onPointerDown={(event) => startResize(sidebarSpec.id, event, { direction: 1 })}
                  onKeyDown={(event) => onResizeKeyDown(sidebarSpec.id, event, { direction: 1 })}
                />
              )
            ) : (
              <PaneCollapseHandle
                side="left"
                collapsed={sidebarCollapsed}
                separatorLabel={resize.collapse.sidebar.separatorLabel}
                collapseLabel={resize.collapse.sidebar.collapseLabel}
                expandLabel={resize.collapse.sidebar.expandLabel}
                valueNow={sidebarWidth}
                valueMin={sidebarSpec.minWidth}
                valueMax={sidebarSpec.maxWidth}
                active={draggingPaneId === sidebarSpec.id}
                onToggle={() => togglePane(sidebarSpec.id, resize.collapse?.sidebar, sidebarCollapsed)}
                onPointerDown={sidebarCollapsed ? undefined : (event) => startResize(sidebarSpec.id, event, { direction: 1 })}
                onKeyDown={sidebarCollapsed ? undefined : (event) => onResizeKeyDown(sidebarSpec.id, event, { direction: 1 })}
              />
            )
          ) : (
            <PaneResizeHandle
              label="调整左侧栏宽度"
              valueNow={sidebarWidth}
              valueMin={sidebarSpec.minWidth}
              valueMax={sidebarSpec.maxWidth}
              active={draggingPaneId === sidebarSpec.id}
              onPointerDown={(event) => startResize(sidebarSpec.id, event, { direction: 1 })}
              onKeyDown={(event) => onResizeKeyDown(sidebarSpec.id, event, { direction: 1 })}
            />
          )}
        </>
      ) : null}
      <main
        data-vui="split-main"
        className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
      >
        {main}
      </main>
      {aside && asideSpec ? (
        <>
          {resize.collapse?.aside ? (
            resize.collapse.aside.placement === "header" ? (
              asideCollapsed ? null : (
                <PaneResizeHandle
                  label={resize.collapse.aside.separatorLabel}
                  valueNow={asideWidth}
                  valueMin={asideSpec.minWidth}
                  valueMax={asideSpec.maxWidth}
                  active={draggingPaneId === asideSpec.id}
                  onPointerDown={(event) => startResize(asideSpec.id, event, { direction: -1 })}
                  onKeyDown={(event) => onResizeKeyDown(asideSpec.id, event, { direction: -1 })}
                />
              )
            ) : (
              <PaneCollapseHandle
                side="right"
                collapsed={asideCollapsed}
                separatorLabel={resize.collapse.aside.separatorLabel}
                collapseLabel={resize.collapse.aside.collapseLabel}
                expandLabel={resize.collapse.aside.expandLabel}
                valueNow={asideWidth}
                valueMin={asideSpec.minWidth}
                valueMax={asideSpec.maxWidth}
                active={draggingPaneId === asideSpec.id}
                onToggle={() => togglePane(asideSpec.id, resize.collapse?.aside, asideCollapsed)}
                onPointerDown={asideCollapsed ? undefined : (event) => startResize(asideSpec.id, event, { direction: -1 })}
                onKeyDown={asideCollapsed ? undefined : (event) => onResizeKeyDown(asideSpec.id, event, { direction: -1 })}
              />
            )
          ) : (
            <PaneResizeHandle
              label="调整右侧栏宽度"
              valueNow={asideWidth}
              valueMin={asideSpec.minWidth}
              valueMax={asideSpec.maxWidth}
              active={draggingPaneId === asideSpec.id}
              onPointerDown={(event) => startResize(asideSpec.id, event, { direction: -1 })}
              onKeyDown={(event) => onResizeKeyDown(asideSpec.id, event, { direction: -1 })}
            />
          )}
          <aside
            data-vui="split-aside"
            data-collapsed={asideCollapsed ? "true" : "false"}
            hidden={asideCollapsed}
            className="flex h-full min-h-0 min-w-0 shrink-0 flex-col overflow-hidden"
            style={{
              width: `var(${paneWidthCssVar(asideSpec.id)})`,
              flexBasis: `var(${paneWidthCssVar(asideSpec.id)})`,
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
        ? "grid-cols-[minmax(0,var(--vui-workspace-sidebar,16rem))_minmax(0,1fr)_minmax(0,var(--vui-workspace-aside,16rem))]"
        : sidebar
          ? "grid-cols-[minmax(0,var(--vui-workspace-sidebar,16rem))_minmax(0,1fr)]"
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
