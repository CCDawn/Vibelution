import type { LauncherBranchInstance } from "../api/launcher";
import type { LauncherProcessRow } from "./LauncherProcessMonitorPanel";
import { instanceRuntimeState, instanceRuntimeStateLabel } from "./LauncherBranchInstancesPanel.model";

export function listMonitoredInstances(items: readonly LauncherBranchInstance[]): LauncherBranchInstance[] {
  return items.filter((item) => item.kind === "main" || (item.kind === "worktree" && item.checkedOut));
}

export function buildAllInstanceMonitorRows(
  items: readonly LauncherBranchInstance[],
  options: { isZh: boolean; queryFailed?: boolean },
): LauncherProcessRow[] {
  return listMonitoredInstances(items).map((item) => {
    const state = instanceRuntimeState(item);
    const backend = item.runtime.backend;
    const window = item.runtime.window;
    const backendPid = Number(backend.pid || item.pids?.backend || 0);
    const windowPid = Number(window.pid || item.pids?.window || 0);
    const port = Number(backend.port || item.port || 0);
    const backendState = backend.alive || backend.listening
      ? (options.isZh ? "后台运行中" : "Backend running")
      : (options.isZh ? "后台未运行" : "Backend stopped");
    const windowState = window.open
      ? (options.isZh ? "窗口已打开" : "Window open")
      : (options.isZh ? "窗口未打开" : "Window closed");
    const observation = `${backendState} · ${windowState}`;
    return {
      id: item.id,
      label: item.shortName || item.branch || item.id,
      status: options.queryFailed
        ? (options.isZh ? "状态未知" : "Status unknown")
        : instanceRuntimeStateLabel(state, options.isZh),
      pid: backendPid > 0 ? String(backendPid) : "-",
      port: port > 0 ? String(port) : "-",
      ownership: options.isZh ? "托管" : "Owned",
      detail: options.queryFailed
        ? `${options.isZh ? "上次记录" : "Last observation"}: ${observation}`
        : observation,
      technical: `${item.id} · ${item.path || item.displayPath || "-"} · ${observation} · backend ${backendPid || "-"} · window ${windowPid || "-"} · port ${port || "-"}`,
      ok: !options.queryFailed && state === "running",
      tone: options.queryFailed ? "warning" : state === "running" ? "success" : "neutral",
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
