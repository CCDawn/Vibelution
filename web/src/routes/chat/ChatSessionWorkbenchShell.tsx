/**
 * Chat dual-pane geometry host — thin adapter over VSessionWorkbenchPage.
 * Keeps Chat-specific data attributes and slot names used by the workbench.
 */
import type { CSSProperties, ReactNode, RefObject } from "react";

import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import { VSessionWorkbenchPage } from "../../components/vui";

export type ChatSessionWorkbenchShellProps = {
  layoutRef: RefObject<HTMLDivElement | null>;
  className: string;
  style?: CSSProperties;
  responsiveMode: string;
  statusRailCollapsed: boolean;
  overlay?: ReactNode;
  statusRail?: ReactNode;
  leftResizeHandle?: ReactNode;
  center?: ReactNode;
  rightResizeHandle?: ReactNode;
  conversationIndex?: ReactNode;
  children?: ReactNode;
};

export function ChatSessionWorkbenchShell({
  layoutRef,
  className,
  style,
  responsiveMode,
  statusRailCollapsed,
  overlay = null,
  statusRail = null,
  leftResizeHandle = null,
  center = null,
  rightResizeHandle = null,
  conversationIndex = null,
  children = null,
}: ChatSessionWorkbenchShellProps) {
  return (
    <VSessionWorkbenchPage
      layoutRef={layoutRef}
      hostAsRoot
      fill
      className={className}
      hostStyle={style}
      domainRecipe="chat-session-workbench"
      layoutId={WORKBENCH_LAYOUT_IDS.chat}
      data-vui="chat-session-workbench-shell"
      data-chat-responsive-mode={responsiveMode}
      data-chat-status-rail={statusRailCollapsed ? "collapsed" : "visible"}
      data-chat-geometry="dual-pane"
      overlay={overlay}
      statusRail={statusRail}
      leftResizeHandle={leftResizeHandle}
      session={center}
      rightResizeHandle={rightResizeHandle}
      indexRail={conversationIndex}
    >
      {children}
    </VSessionWorkbenchPage>
  );
}
