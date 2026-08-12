export type DesktopCloseReason =
  | "workbench_window_close"
  | "desktop_shell_quit"
  | "desktop_shell_restart"
  | "update_install"
  | "os_session_end"
  | "crash_recovery";

export type DesktopSessionMutationKind = "register" | "heartbeat" | "window" | "close";

const SHELL_EXIT_REASONS: ReadonlySet<DesktopCloseReason> = new Set([
  "desktop_shell_quit",
  "desktop_shell_restart",
  "update_install",
  "os_session_end"
]);

/** Shell-level exits must not wait forever on an in-flight workbench close transaction. */
export function desktopCloseReasonSupersedes(
  pendingReason: DesktopCloseReason,
  nextReason: DesktopCloseReason
): boolean {
  return pendingReason === "workbench_window_close" && SHELL_EXIT_REASONS.has(nextReason);
}

export class DesktopLifecycleCoordinator {
  private pending: Promise<unknown> | null = null;
  private reason: DesktopCloseReason | null = null;

  request<T>(reason: DesktopCloseReason, operation: (reason: DesktopCloseReason) => Promise<T>): Promise<T> {
    if (this.pending !== null) {
      if (this.reason === null || !desktopCloseReasonSupersedes(this.reason, reason)) {
        return this.pending as Promise<T>;
      }
      // Fall through and replace the pending workbench-close promise with a shell exit.
    }
    this.reason = reason;
    const pending = operation(reason);
    this.pending = pending;
    void pending.finally(() => {
      if (this.pending === pending) {
        this.pending = null;
        this.reason = null;
      }
    });
    return pending;
  }

  pendingReason(): DesktopCloseReason | null {
    return this.reason;
  }

  recordSessionEnd(): { closeReason: "os_session_end"; recoveryReason: "crash_recovery" } {
    return { closeReason: "os_session_end", recoveryReason: "crash_recovery" };
  }
}

export class DesktopSessionMutationQueue {
  private tail: Promise<void> = Promise.resolve();
  private phase: "active" | "closing" | "closed" = "active";
  private pendingClose: Promise<unknown> | null = null;

  accepts(kind: Exclude<DesktopSessionMutationKind, "register">): boolean {
    return this.phase === "active" || (kind === "close" && this.phase === "closing");
  }

  enqueue<T>(kind: DesktopSessionMutationKind, operation: () => Promise<T>): Promise<T> {
    if (kind === "close" && this.pendingClose !== null) {
      return this.pendingClose as Promise<T>;
    }
    if (this.phase === "closed" || (this.phase === "closing" && kind !== "close")) {
      return Promise.reject(new Error(`desktop session mutation dropped: ${kind}`));
    }
    if (kind === "close") {
      this.phase = "closing";
    }
    const result = this.tail.then(operation);
    this.tail = result.then(
      () => undefined,
      () => undefined
    );
    if (kind === "close") {
      this.pendingClose = result;
      void result.then(
        () => {
          this.phase = "closed";
        },
        () => {
          this.phase = "active";
        }
      ).finally(() => {
        this.pendingClose = null;
      });
    }
    return result;
  }
}
