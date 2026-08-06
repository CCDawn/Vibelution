/**
 * Chat center surface branch: CLI terminal stack + group surface or session workspace.
 */
import type { ReactNode } from "react";
import { Suspense } from "react";

export type ChatCenterSessionSurfaceProps = {
  terminal: ReactNode;
  groupPanelActive: boolean;
  groupSurface: ReactNode;
  sessionWorkspace: ReactNode;
};

export function ChatCenterSessionSurface({
  terminal,
  groupPanelActive,
  groupSurface,
  sessionWorkspace,
}: ChatCenterSessionSurfaceProps) {
  return (
    <>
      {terminal}
      {groupPanelActive ? (
        <Suspense fallback={null}>{groupSurface}</Suspense>
      ) : (
        sessionWorkspace
      )}
    </>
  );
}
