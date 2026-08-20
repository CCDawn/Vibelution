import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { VRouteHeader } from "./VRouteHeader";
import { VSplitWorkspace, type VSplitWorkspaceResizeConfig } from "./VSplitWorkspace";
import { VWorkbenchPage } from "./VWorkbenchPage";
import {
  VUI_CANVAS_SURFACE_CLASS,
  VUI_PAGE_BODY_FILL_CLASS,
  VUI_PAGE_TOOLBAR_STRIP_CLASS,
  VUI_RAIL_SURFACE_CLASS,
  VUI_WORKBENCH_SURFACE_CLASS,
} from "./pageRecipeClasses";

export type VCanvasWorkbenchPageProps = Omit<ComponentPropsWithoutRef<"section">, "children"> & {
  ariaLabel?: string;
  eyebrow?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  hideHeader?: boolean;
  headerClassName?: string;
  toolbar?: ReactNode;
  toolbarClassName?: string;
  /** Optional left rail (team list, layer list). */
  rail?: ReactNode;
  /** Center canvas / graph host. */
  canvas: ReactNode;
  /** Right inspector / binding panel. */
  inspector?: ReactNode;
  layoutId?: string;
  resize?: Omit<VSplitWorkspaceResizeConfig, "layoutId">;
  domainRecipe?: string;
  shellTestId?: string;
  shellMode?: string;
  railClassName?: string;
  canvasClassName?: string;
  inspectorClassName?: string;
  workspaceClassName?: string;
  className?: string;
};

/**
 * Page recipe: full-height canvas workbench with optional rail + inspector.
 * Prefer for org graphs, flow canvases, and memory graphs.
 */
export function VCanvasWorkbenchPage({
  ariaLabel,
  eyebrow,
  title,
  meta,
  actions,
  hideHeader = false,
  headerClassName,
  toolbar,
  toolbarClassName,
  rail,
  canvas,
  inspector,
  layoutId,
  resize,
  domainRecipe,
  shellTestId,
  shellMode,
  railClassName,
  canvasClassName,
  inspectorClassName,
  workspaceClassName,
  className,
  ...props
}: VCanvasWorkbenchPageProps) {
  const resizeConfig = layoutId
    ? { layoutId, enabled: true as const, ...resize }
    : false;

  return (
    <VWorkbenchPage
      ariaLabel={ariaLabel}
      data-vui-recipe="canvas-workbench-page"
      data-vui-domain-recipe={domainRecipe}
      fill
      // hideHeader → single body child; must use stack or body collapses to content height.
      fillLayout={hideHeader ? "stack" : "header-body"}
      className={className}
      {...props}
    >
      {hideHeader ? null : (
        <VRouteHeader
          className={headerClassName}
          eyebrow={eyebrow}
          title={title}
          meta={meta}
          actions={actions}
        />
      )}
      <div data-vui="canvas-workbench-body" className={cn(VUI_PAGE_BODY_FILL_CLASS, "min-h-0 flex-1")}>
        {toolbar ? (
          <div
            data-vui="canvas-workbench-toolbar"
            className={cn(VUI_PAGE_TOOLBAR_STRIP_CLASS, "relative z-20 shrink-0 overflow-hidden", toolbarClassName)}
          >
            {toolbar}
          </div>
        ) : null}
        {/*
          Do not pair h-full with a toolbar sibling: height 100% of body overflows the
          toolbar strip and clips the canvas. flex-1 min-h-0 fills the remainder.
        */}
        <VSplitWorkspace
          className={cn("min-h-0 min-w-0 flex-1 overflow-hidden !h-auto", workspaceClassName)}
          data-testid={shellTestId}
          data-team-shell-mode={shellMode}
          data-vui-layout-id={layoutId}
          resize={resizeConfig}
          sidebar={
            rail
              ? (
                <div
                  data-vui="canvas-workbench-rail"
                  className={cn(VUI_RAIL_SURFACE_CLASS, "flex h-full min-h-0 flex-col", railClassName)}
                >
                  {rail}
                </div>
              )
              : undefined
          }
          main={(
            <div
              data-vui="canvas-workbench-canvas"
              className={cn(
                VUI_CANVAS_SURFACE_CLASS,
                // Match VBoardWorkbenchPage main: stretch inside split-main.
                "relative flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden",
                canvasClassName,
              )}
            >
              {canvas}
            </div>
          )}
          aside={
            inspector
              ? (
                <div
                  data-vui="canvas-workbench-inspector"
                  className={cn(
                    VUI_WORKBENCH_SURFACE_CLASS,
                    "flex h-full min-h-0 flex-col overflow-hidden",
                    inspectorClassName,
                  )}
                >
                  {inspector}
                </div>
              )
              : undefined
          }
        />
      </div>
    </VWorkbenchPage>
  );
}
