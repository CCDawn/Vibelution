import { memo, type ReactNode } from "react";

export type VWorkbenchFrameProps = {
  children: ReactNode;
  /** Session recipes already own their pane inset. */
  flush?: boolean;
};

/** Persistent chrome host. Place outside Outlet/Suspense, without a route key. */
export const VWorkbenchFrame = memo(function VWorkbenchFrame({ children, flush = false }: VWorkbenchFrameProps) {
  return <div data-vui="workbench-frame" data-flush={flush ? "true" : undefined}>{children}</div>;
});
