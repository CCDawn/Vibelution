interface ExitWindow {
  isDestroyed(): boolean;
  isVisible(): boolean;
  isMinimized(): boolean;
  hide(): void;
  showInactive(): void;
  minimize(): void;
}

export function hideDesktopShellWindowsForExit(windows: readonly ExitWindow[]): { restore(): void } {
  const snapshots: { window: ExitWindow; minimized: boolean }[] = [];
  // Capture original presentation before hide events can affect other windows.
  for (const window of windows) {
    try {
      if (window.isDestroyed()) continue;
      const minimized = window.isMinimized();
      const visible = window.isVisible();
      if (visible || minimized) snapshots.push({ window, minimized });
    } catch {
      // A stale window handle must not interrupt the remaining exit work.
    }
  }

  const hiddenWindows: typeof snapshots = [];
  for (const snapshot of snapshots) {
    try {
      if (snapshot.window.isDestroyed()) continue;
      // hide may take effect before throwing, so keep its restoration record.
      hiddenWindows.push(snapshot);
      snapshot.window.hide();
    } catch {
      // Continue hiding the other windows even if this handle fails.
    }
  }

  let restored = false;
  return {
    restore() {
      if (restored) return;
      restored = true;
      for (const { window, minimized } of hiddenWindows) {
        try {
          if (window.isDestroyed()) continue;
          window.showInactive();
          if (minimized && !window.isDestroyed()) window.minimize();
        } catch {
          // One failed restoration must not leave the other windows hidden.
        }
      }
    },
  };
}
