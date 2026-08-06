/**
 * Chat session workbench geometry host.
 *
 * Owns recipe markers + the three-pane grid host element used by
 * `useChatWorkbenchLayout` (layoutRef / dual-write widths / responsive attrs).
 * Domain dual-pane math stays in the layout hook; this shell only hosts the
 * workbench root so a future session page recipe can wrap the same contract.
 *
 * Prefer explicit slots (`statusRail` / `center` / `conversationIndex`) when
 * composing; `children` is for host-level dialogs and transitional full-body
 * content during migration.
 */
import type { CSSProperties, ReactNode, RefObject } from "react";

import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";

export type ChatSessionWorkbenchShellProps = {
  layoutRef: RefObject<HTMLDivElement | null>;
  className: string;
  style?: CSSProperties;
  responsiveMode: string;
  statusRailCollapsed: boolean;
  /** Full-screen backdrop when a responsive overlay pane is open. */
  overlay?: ReactNode;
  /** Right status rail (or overlay). */
  statusRail?: ReactNode;
  leftResizeHandle?: ReactNode;
  /** Center conversation / workspace column. */
  center?: ReactNode;
  rightResizeHandle?: ReactNode;
  /** Left conversation index / directory rail. */
  conversationIndex?: ReactNode;
  /** Dialogs and transitional full-body content under the layout root. */
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
    <div
      ref={layoutRef}
      className={className}
      style={style}
      data-vui="chat-session-workbench-shell"
      data-vui-recipe="chat-session-workbench"
      data-vui-domain-recipe="chat-dual-pane"
      data-vui-layout-id={WORKBENCH_LAYOUT_IDS.chat}
      data-chat-responsive-mode={responsiveMode}
      data-chat-status-rail={statusRailCollapsed ? "collapsed" : "visible"}
    >
      {overlay}
      {statusRail}
      {leftResizeHandle}
      {center}
      {rightResizeHandle}
      {conversationIndex}
      {children}
    </div>
  );
}
