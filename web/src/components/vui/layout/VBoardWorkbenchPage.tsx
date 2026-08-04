import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { VRouteHeader } from "./VRouteHeader";
import { VSplitWorkspace, type VSplitWorkspaceResizeConfig } from "./VSplitWorkspace";
import { VWorkbenchPage } from "./VWorkbenchPage";
import {
  VUI_BOARD_CONTENT_PAD_CLASS,
  VUI_PAGE_BODY_FILL_CLASS,
  VUI_PAGE_TOOLBAR_STRIP_CLASS,
  VUI_RAIL_SURFACE_CLASS,
} from "./pageRecipeClasses";

export type VBoardWorkbenchPageProps = Omit<ComponentPropsWithoutRef<"section">, "children"> & {
  ariaLabel?: string;
  eyebrow?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  /** Hide route header chrome (shell-owned title already in app topbar). */
  hideHeader?: boolean;
  headerClassName?: string;
  /** Strip under header: mode switch, refresh, filters. */
  toolbar?: ReactNode;
  toolbarClassName?: string;
  /** Left team/list rail. */
  rail: ReactNode;
  /** Main board content (CTA, kanban, tables…). */
  board: ReactNode;
  /** Stable layoutId for rail resize persistence. */
  layoutId?: string;
  resize?: Omit<VSplitWorkspaceResizeConfig, "layoutId">;
  /** Domain recipe marker, e.g. teams-organization-workbench. */
  domainRecipe?: string;
  /** Stable test id on the split workspace root (e.g. team-shell-workspace). */
  shellTestId?: string;
  /** Optional mode attribute for board/canvas shells. */
  shellMode?: string;
  railClassName?: string;
  boardClassName?: string;
  workspaceClassName?: string;
  className?: string;
};

/**
 * Page recipe: full-height left rail + board main (Teams-style workbench).
 * Prefer over hand-rolled flex shells for list → board surfaces.
 */
export function VBoardWorkbenchPage({
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
  board,
  layoutId,
  resize,
  domainRecipe,
  shellTestId,
  shellMode,
  railClassName,
  boardClassName,
  workspaceClassName,
  className,
  ...props
}: VBoardWorkbenchPageProps) {
  const resizeConfig = layoutId
    ? { layoutId, enabled: true as const, ...resize }
    : false;

  return (
    <VWorkbenchPage
      ariaLabel={ariaLabel}
      data-vui-recipe="board-workbench-page"
      data-vui-domain-recipe={domainRecipe}
      fill
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
      <div data-vui="board-workbench-body" className={VUI_PAGE_BODY_FILL_CLASS}>
        <VSplitWorkspace
          className={cn("h-full min-h-0", workspaceClassName)}
          data-testid={shellTestId}
          data-team-shell-mode={shellMode}
          data-vui-layout-id={layoutId}
          resize={resizeConfig}
          sidebar={(
            <div
              data-vui="board-workbench-rail"
              className={cn(VUI_RAIL_SURFACE_CLASS, "flex flex-col", railClassName)}
            >
              {rail}
            </div>
          )}
          main={(
            <div
              data-vui="board-workbench-main"
              className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-[var(--vui-surface-panel)]"
            >
              {toolbar ? (
                <div
                  data-vui="board-workbench-toolbar"
                  className={cn(VUI_PAGE_TOOLBAR_STRIP_CLASS, toolbarClassName)}
                >
                  {toolbar}
                </div>
              ) : null}
              <div
                data-vui="board-workbench-board"
                className={cn(VUI_BOARD_CONTENT_PAD_CLASS, boardClassName)}
              >
                {board}
              </div>
            </div>
          )}
        />
      </div>
    </VWorkbenchPage>
  );
}
