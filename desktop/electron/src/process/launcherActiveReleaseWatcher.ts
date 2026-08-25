import { watch, type FSWatcher } from "node:fs";

export type LauncherActiveReleaseWatcherHandle = {
  stop(): void;
};

export const LAUNCHER_ACTIVE_RELEASE_DEBOUNCE_MS = 250;

/**
 * Match events that may touch the atomic active-release pointer the Python
 * builder publishes.  A null filename is a directory-level notification, so it
 * is treated as relevant; the debounced callback re-resolves the pointer
 * itself and no-ops when the release did not actually change.
 */
export function isActiveReleasePointerEvent(filename: string | null): boolean {
  return filename === null || filename.replace(/\\/g, "/").endsWith("active.json");
}

/**
 * Watch the builds directory for active.json switches while the desktop shell
 * stays resident, so an already-open launcher window can be reloaded onto the
 * fresh release.  Returns null when the builds root is not watchable yet
 * (first run before any build exists).
 */
export function startLauncherActiveReleaseWatcher(input: {
  buildsRoot: string;
  onChange: () => void;
  debounceMs?: number;
  watchFn?: (
    root: string,
    listener: (event: string, filename: string | null) => void
  ) => FSWatcher;
}): LauncherActiveReleaseWatcherHandle | null {
  const debounceMs = Math.max(0, input.debounceMs ?? LAUNCHER_ACTIVE_RELEASE_DEBOUNCE_MS);
  const startWatch =
    input.watchFn ??
    ((root: string, listener: (event: string, filename: string | null) => void) =>
      watch(
        root,
        { persistent: false },
        (event: string, filename: string | Buffer | null) =>
          listener(event, filename === null ? null : filename.toString())
      ));
  let watcher: FSWatcher;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;
  try {
    watcher = startWatch(input.buildsRoot, (_event, filename) => {
      if (stopped || !isActiveReleasePointerEvent(filename)) {
        return;
      }
      if (timer !== null) {
        clearTimeout(timer);
      }
      timer = setTimeout(() => {
        timer = null;
        if (stopped) {
          return;
        }
        try {
          input.onChange();
        } catch {
          // Best-effort refresh; the next open re-checks the content version.
        }
      }, debounceMs);
    });
  } catch {
    return null;
  }
  watcher.on("error", () => {
    // The watcher is best-effort; a lost watch recovers on the next open.
  });
  return {
    stop(): void {
      stopped = true;
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      try {
        watcher.close();
      } catch {
        // Already closed.
      }
    }
  };
}
