import type { ManagedProcessState } from "./managedProcessTypes.js";

export function markProcessStarting(state: ManagedProcessState, now: string): ManagedProcessState {
  return { ...state, status: "starting", startedAt: now, exitedAt: "", exitCode: null, signal: "", lastError: "" };
}

export function markProcessRunning(state: ManagedProcessState, pid: number): ManagedProcessState {
  return { ...state, status: "running", pid };
}

export function markProcessExited(
  state: ManagedProcessState,
  exitCode: number | null,
  signal: string,
  now: string
): ManagedProcessState {
  return { ...state, status: "exited", pid: 0, exitedAt: now, exitCode, signal };
}

export function markProcessFailed(state: ManagedProcessState, message: string, now: string): ManagedProcessState {
  return { ...state, status: "failed", pid: 0, exitedAt: now, lastError: message };
}
