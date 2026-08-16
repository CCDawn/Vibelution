import { useRef } from "react";

import { ChatSessionWorkbenchShell } from "../routes/chat/ChatSessionWorkbenchShell";
import chatStyles from "../routes/ChatCodingRoute.styles";
import { ProgressiveRegionSkeleton } from "../routes/shared/ProgressiveRegionSkeleton";

import { type RouteErrorSurface } from "./RouteErrorBoundary";

export type ChatRouteLoadingShellProps = {
  label?: string;
  surface?: RouteErrorSurface;
};

/**
 * Chat route Suspense fallback — reuses the real three-pane workbench geometry
 * and fills data slots with ProgressiveRegionSkeleton instead of a fake two-pane shell.
 */
export function ChatRouteLoadingShell({
  label = "正在加载对话",
  surface = "workbench",
}: ChatRouteLoadingShellProps) {
  const layoutRef = useRef<HTMLDivElement>(null);
  const conversationIndexPaneClassName = `${chatStyles.rightPane} ${chatStyles.rightPaneWithoutTabs}`;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label={label}
      data-vui-app={surface}
      data-route-loading="chat"
      className="min-w-0 w-full"
    >
      <span className="sr-only">{label}</span>
      <ChatSessionWorkbenchShell
        layoutRef={layoutRef}
        className={chatStyles.layout}
        responsiveMode="wide"
        statusRailCollapsed={false}
        conversationIndex={(
          <div
            data-loading-region="chat-index"
            className={`${conversationIndexPaneClassName} min-h-0`}
          >
            <ProgressiveRegionSkeleton
              className="min-h-0 flex-1 overflow-hidden p-1"
              label={label}
              variant="list"
            />
          </div>
        )}
        center={(
          <div
            data-loading-region="chat-workspace"
            className={`${chatStyles.centerPane} min-h-0`}
          >
            <ProgressiveRegionSkeleton
              className="min-h-0 h-full"
              label={label}
              variant="conversation"
            />
          </div>
        )}
        statusRail={(
          <div
            data-loading-region="chat-status-rail"
            className={`${chatStyles.leftRail} min-h-0`}
          >
            <ProgressiveRegionSkeleton className="p-1" label={label} variant="panel" />
          </div>
        )}
      />
    </div>
  );
}
