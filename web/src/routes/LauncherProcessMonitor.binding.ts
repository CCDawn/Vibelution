import type { LauncherBranchInstance } from "../api/launcher";
import type { LauncherProcessRow } from "./LauncherProcessMonitorPanel";

export function listMonitoredInstances(items: readonly LauncherBranchInstance[]): LauncherBranchInstance[] {
  return items.filter((item) => item.kind === "main" || (item.kind === "worktree" && item.checkedOut));
}

export function buildAllInstanceMonitorRows(
  items: readonly LauncherBranchInstance[],
  live: {
    currentId: string;
    backendPid?: number;
    windowPid?: number;
    port?: number;
    alive?: boolean;
  },
  labels: {
    running: string;
    stopped: string;
    owned: string;
    windowRunning: string;
    windowStopped: string;
  },
): LauncherProcessRow[] {
  return listMonitoredInstances(items).map((item) => {
    const isCurrent = Boolean(item.current || item.id === live.currentId);
    const backendPid = isCurrent && (live.backendPid || 0) > 0 ? Number(live.backendPid) : Number(item.pids?.backend || 0);
    const windowPid = isCurrent && (live.windowPid || 0) > 0 ? Number(live.windowPid) : Number(item.pids?.window || 0);
    const port = isCurrent && (live.port || 0) > 0 ? Number(live.port) : Number(item.port || 0);
    const alive = isCurrent && live.alive !== undefined ? Boolean(live.alive) : Boolean(item.alive);
    const name = item.shortName || item.branch || item.id;
    return {
      id: item.id,
      label: name,
      status: alive ? labels.running : labels.stopped,
      pid: backendPid > 0 ? String(backendPid) : "-",
      port: port > 0 ? String(port) : "-",
      ownership: labels.owned,
      detail: `${windowPid > 0 ? labels.windowRunning : labels.windowStopped} · ${item.displayPath || item.path || item.id}`,
      technical: `${item.id} · ${item.path || item.displayPath || "-"} · backend ${backendPid || "-"} · window ${windowPid || "-"} · port ${port || "-"}`,
      ok: alive,
      tone: alive ? "success" : "neutral",
    };
  });
}

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
