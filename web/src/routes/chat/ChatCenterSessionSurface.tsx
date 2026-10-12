/**
 * Chat center surface branch: CLI terminal stack + group surface or session workspace.
 */
import type { ReactNode } from "react";
import { Suspense } from "react";
import styles from "./ChatCenterSessionSurface.styles";

export type ChatCenterSessionSurfaceProps = {
  terminal: ReactNode;
  groupPanelActive: boolean;
  groupSurface: ReactNode;
  sessionWorkspace: ReactNode;
  /** Browsing hides the workspace while preserving its mounted conversation/terminal state. */
  browser?: ReactNode;
};

export function ChatCenterSessionSurface({
  terminal,
  groupPanelActive,
  groupSurface,
  sessionWorkspace,
  browser,
}: ChatCenterSessionSurfaceProps) {
  return (
    <>
      <div className={browser ? styles.hiddenWorkspace : styles.workspace} aria-hidden={browser ? true : undefined}>
        {terminal}
        {groupPanelActive ? (
          <Suspense fallback={null}>{groupSurface}</Suspense>
        ) : (
          sessionWorkspace
        )}
      </div>
      {browser}
    </>
  );
}
