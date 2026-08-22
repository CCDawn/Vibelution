import { knownPidIsAlive, probeTcpConnect } from "../lifecycle/mainLine/observation.js";
import type { PythonProcessIdentity } from "./pythonJsonBridge.js";

export const PORT_RELEASE_WAIT_MS = 8_000;
export const PORT_RELEASE_POLL_MS = 100;
export const PID_TERMINATE_WAIT_MS = 8_000;
export const GRACEFUL_WORKBENCH_SHUTDOWN_TIMEOUT_MS = 12_000;

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

export type GracefulWorkbenchShutdownResponse = {
  status: number;
};

export type GracefulWorkbenchShutdownResult = {
  requested: boolean;
  completed: boolean;
  status?: number;
  reason: string;
};

/**
 * Ask a verified workbench backend to run its own shutdown cleanup, then wait
 * for both its process and listener to disappear. A 409 is a deliberate
 * active-work refusal and must be left for the caller to handle by its normal
 * force-retire path.
 */
export async function requestGracefulWorkbenchShutdown(input: {
  port: number;
  host?: string;
  backendPid?: number;
  controlToken?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: (
    url: string,
    options: {
      method: "POST";
      signal: AbortSignal;
      headers: Record<string, string>;
    }
  ) => Promise<GracefulWorkbenchShutdownResponse>;
  pidAlive?: (pid: number) => boolean;
  connect?: (port: number, host: string) => Promise<boolean>;
  now?: () => number;
  delay?: (ms: number) => Promise<void>;
}): Promise<GracefulWorkbenchShutdownResult> {
  input.signal?.throwIfAborted();
  const port = Math.trunc(input.port);
  if (!Number.isFinite(port) || port <= 0) {
    return { requested: false, completed: false, reason: "backend port is unavailable" };
  }
  const host = input.host?.trim() || "127.0.0.1";
  const timeoutMs = Math.max(1, Math.round(input.timeoutMs ?? GRACEFUL_WORKBENCH_SHUTDOWN_TIMEOUT_MS));
  const now = input.now ?? Date.now;
  const connect = input.connect ?? ((nextPort, nextHost) => probeTcpConnect(nextPort, nextHost));
  const controlToken = String(input.controlToken ?? process.env.VIBELUTION_WEB_CONTROL_TOKEN ?? "").trim();
  const pidAlive = input.pidAlive ?? knownPidIsAlive;
  const request = input.request ?? (async (url, options) => {
    const response = await fetch(url, options);
    return { status: response.status };
  });
  const controller = new AbortController();
  let timeoutTimer: ReturnType<typeof setTimeout> | null = null;
  const onAbort = (): void => {
    controller.abort(input.signal?.reason);
  };
  input.signal?.addEventListener("abort", onAbort, { once: true });
  try {
    timeoutTimer = setTimeout(() => controller.abort(new Error("graceful shutdown timed out")), timeoutMs);
    const response = await request(`http://${host}:${port}/api/runtime/shutdown`, {
      method: "POST",
      signal: controller.signal,
      headers: {
        "X-Vibelution-Control-Token": controlToken
      }
    });
    if (response.status === 409) {
      return {
        requested: false,
        completed: false,
        status: response.status,
        reason: "backend refused graceful shutdown because active work is running"
      };
    }
    if (response.status !== 202) {
      return {
        requested: false,
        completed: false,
        status: response.status,
        reason: `backend graceful shutdown returned HTTP ${response.status}`
      };
    }

    const deadline = now() + timeoutMs;
    const delay = input.delay ?? ((ms) => abortableDelay(ms, input.signal));
    while (now() < deadline) {
      input.signal?.throwIfAborted();
      const processGone = !input.backendPid || !pidAlive(Math.trunc(input.backendPid));
      const portGone = !(await connect(port, host));
      if (processGone && portGone) {
        return {
          requested: true,
          completed: true,
          status: response.status,
          reason: "backend completed graceful shutdown"
        };
      }
      await delay(Math.min(PORT_RELEASE_POLL_MS, Math.max(1, deadline - now())));
    }
    return {
      requested: true,
      completed: false,
      status: response.status,
      reason: "backend did not complete graceful shutdown before the deadline"
    };
  } catch (error: unknown) {
    if (input.signal?.aborted) {
      throw error;
    }
    return {
      requested: false,
      completed: false,
      reason: error instanceof Error ? error.message : String(error)
    };
  } finally {
    if (timeoutTimer !== null) {
      clearTimeout(timeoutTimer);
    }
    input.signal?.removeEventListener("abort", onAbort);
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
  killPid?: (pid: number) => void | Promise<void>;
  terminateProcessTree?: (pid: number, expectedIdentity?: PythonProcessIdentity) => boolean | Promise<boolean>;
  treePids?: readonly number[];
  expectedIdentities?: Readonly<Record<string, PythonProcessIdentity>>;
  /**
   * PIDs independently proven to be direct children owned by the current
   * Electron lifecycle owner. Registered browser/window handles are not
   * included unless their provider supplied this evidence explicitly.
   */
  ownedDirectPids?: readonly number[];
  /**
   * Report live handles for which this lifecycle owner has no kill authority.
   * Supplying this callback keeps those handles visible while allowing
   * independently verified backend/daemon trees to finish retiring.
   */
  reportUnverified?: (pids: number[]) => void;
  connect?: (port: number, host: string) => Promise<boolean>;
}): Promise<number[]> {
  const pidAlive = input.pidAlive ?? knownPidIsAlive;
  const killPid = input.killPid ?? terminatePid;
  const treePids = new Set((input.treePids ?? [])
    .map((pid) => Math.trunc(Number(pid)))
    .filter((pid) => Number.isFinite(pid) && pid > 0));
  const ownedDirectPids = new Set((input.ownedDirectPids ?? [])
    .map((pid) => Math.trunc(Number(pid)))
    .filter((pid) => Number.isFinite(pid) && pid > 0));
  const unique = [...new Set(input.pids.filter((pid) => Number.isFinite(pid) && pid > 0).map((pid) => Math.trunc(pid)))];
  const live = unique.filter((pid) => pidAlive(pid));
  const unowned = live.filter((pid) => {
    if (ownedDirectPids.has(pid)) {
      return false;
    }
    if (treePids.has(pid)) {
      return !input.terminateProcessTree;
    }
    return true;
  });
  if (unowned.length > 0 && !input.reportUnverified) {
    throw new Error(`Refusing to retire unverified registered process handles: ${unowned.join(",")}`);
  }
  input.reportUnverified?.(unowned);
  const actionable = unique.filter((pid) => !unowned.includes(pid));
  for (const pid of actionable.sort((left, right) => right - left)) {
    input.signal?.throwIfAborted();
    if (input.terminateProcessTree && treePids.has(pid)) {
      // A dead root PID does not establish that its children also exited:
      // Windows can re-parent descendants before the next reconciliation.
      // The verified helper deliberately rejects a missing root, preserving
      // the registered handle instead of washing an unknown tree as closed.
      const expectedIdentity = input.expectedIdentities?.[String(pid)];
      const terminated = expectedIdentity
        ? await input.terminateProcessTree(pid, expectedIdentity)
        : await input.terminateProcessTree(pid);
      if (!terminated) {
        throw new Error(`Failed to verify retirement of owned process tree ${pid}`);
      }
    } else if (pidAlive(pid)) {
      await killPid(pid);
    }
  }
  const now = input.now ?? Date.now;
  const delay = input.delay ?? ((ms) => abortableDelay(ms, input.signal));
  const startedAt = now();
  while (now() - startedAt < PID_TERMINATE_WAIT_MS) {
    input.signal?.throwIfAborted();
    if (actionable.every((pid) => !pidAlive(pid))) {
      break;
    }
    await delay(PORT_RELEASE_POLL_MS);
  }
  const stillAlive = actionable.filter((pid) => pidAlive(pid));
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
