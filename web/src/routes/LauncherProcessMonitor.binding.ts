import type { LauncherBranchInstance } from "../api/launcher";

export function resolveLiveInstance(
  items: readonly LauncherBranchInstance[],
  currentId: string,
  lastStartedId = "",
): LauncherBranchInstance | undefined {
  const lastStarted = lastStartedId ? items.find((item) => item.id === lastStartedId) : undefined;
  if (lastStarted?.alive) {
    return lastStarted;
  }
  const current = items.find((item) => item.current || item.id === currentId);
  if (current?.alive) {
    return current;
  }
  return items.find((item) => item.alive);
}

export function resolveProcessMonitorTarget(
  items: readonly LauncherBranchInstance[],
  {
    selectedId,
    currentId,
    lastStartedId = "",
    explicitSelect = false,
  }: {
    selectedId: string;
    currentId: string;
    lastStartedId?: string;
    explicitSelect?: boolean;
  },
): LauncherBranchInstance | undefined {
  const selected = items.find((item) => item.id === selectedId);
  const live = resolveLiveInstance(items, currentId, lastStartedId);
  if (explicitSelect && selected?.checkedOut && selected.id !== live?.id) {
    return selected;
  }
  return live || selected || items.find((item) => item.current || item.id === currentId);
}
