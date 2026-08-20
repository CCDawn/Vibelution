import { knownPidIsAlive, probeTcpConnect } from "../lifecycle/mainLine/observation.js";

export const PORT_RELEASE_WAIT_MS = 8_000;
export const PORT_RELEASE_POLL_MS = 100;
export const PID_TERMINATE_WAIT_MS = 8_000;

const HANDLE_KEYS = [
  "backendPid",
  "backendLaunchPid",
  "browserLaunchPid",
  "browserWindowPid",
  "workbenchBrowserLaunchPid",
  "workbenchBrowserWindowPid",
  "spawnPid"
] as const;

export function collectRegisteredHandles(
  state: Record<string, unknown>,
  extraPids: number[] = []
): number[] {
  const handles = new Set<number>();
  for (const key of HANDLE_KEYS) {
    const pid = Number(state[key] || 0);
    if (Number.isFinite(pid) && pid > 0) {
      handles.add(Math.trunc(pid));
    }
  }
  for (const pid of extraPids) {
    if (Number.isFinite(pid) && pid > 0) {
      handles.add(Math.trunc(pid));
    }
  }
  return [...handles].sort((left, right) => right - left);
}

export function terminatePid(pid: number): void {
  if (!Number.isFinite(pid) || pid <= 0) {
    return;
  }
  try {
    process.kill(Math.trunc(pid));
  } catch {
    // Already gone, or the OS refused the signal. Callers re-check liveness.
  }
}

export async function waitForPortRelease(input: {
  port: number;
  host?: string;
  timeoutMs?: number;
  pollIntervalMs?: number;
  signal?: AbortSignal;
  now?: () => number;
  delay?: (ms: number) => Promise<void>;
  connect?: (port: number, host: string) => Promise<boolean>;
}): Promise<boolean> {
  const port = Math.trunc(input.port);
  if (!Number.isFinite(port) || port <= 0) {
    return true;
  }
  const host = input.host?.trim() || "127.0.0.1";
  const timeoutMs = Math.max(1, input.timeoutMs ?? PORT_RELEASE_WAIT_MS);
  const pollIntervalMs = Math.max(0, input.pollIntervalMs ?? PORT_RELEASE_POLL_MS);
  const now = input.now ?? Date.now;
  const delay = input.delay ?? ((ms) => abortableDelay(ms, input.signal));
  const connect = input.connect ?? ((nextPort, nextHost) => probeTcpConnect(nextPort, nextHost));
  const startedAt = now();
  while (now() - startedAt < timeoutMs) {
    input.signal?.throwIfAborted();
    if (!(await connect(port, host))) {
      return true;
    }
    if (pollIntervalMs > 0) {
      await delay(pollIntervalMs);
    }
  }
  return !(await connect(port, host));
}

export async function retireRegisteredHandles(input: {
  pids: number[];
  port?: number;
  host?: string;
  signal?: AbortSignal;
  now?: () => number;
  delay?: (ms: number) => Promise<void>;
  pidAlive?: (pid: number) => boolean;
  killPid?: (pid: number) => void;
  connect?: (port: number, host: string) => Promise<boolean>;
}): Promise<number[]> {
  const pidAlive = input.pidAlive ?? knownPidIsAlive;
  const killPid = input.killPid ?? terminatePid;
  const unique = [...new Set(input.pids.filter((pid) => Number.isFinite(pid) && pid > 0).map((pid) => Math.trunc(pid)))];
  for (const pid of unique.sort((left, right) => right - left)) {
    input.signal?.throwIfAborted();
    if (pidAlive(pid)) {
      killPid(pid);
    }
  }
  const now = input.now ?? Date.now;
  const delay = input.delay ?? ((ms) => abortableDelay(ms, input.signal));
  const startedAt = now();
  while (now() - startedAt < PID_TERMINATE_WAIT_MS) {
    input.signal?.throwIfAborted();
    if (unique.every((pid) => !pidAlive(pid))) {
      break;
    }
    await delay(PORT_RELEASE_POLL_MS);
  }
  const stillAlive = unique.filter((pid) => pidAlive(pid));
  if (stillAlive.length > 0) {
    throw new Error(`Failed to retire workbench handles still alive: ${stillAlive.join(",")}`);
  }
  const port = Number(input.port);
  if (Number.isFinite(port) && port > 0) {
    await waitForPortRelease({
      port,
      host: input.host,
      signal: input.signal,
      now: input.now,
      delay: input.delay,
      connect: input.connect
    });
  }
  return unique;
}

async function abortableDelay(timeoutMs: number, signal?: AbortSignal): Promise<void> {
  signal?.throwIfAborted();
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, timeoutMs);
    const onAbort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      const reason = signal?.reason;
      reject(reason instanceof Error ? reason : new Error("workbench retire aborted"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
