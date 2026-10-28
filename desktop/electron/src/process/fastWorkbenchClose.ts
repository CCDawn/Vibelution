import { probeTcpConnect } from "../lifecycle/mainLine/observation.js";
import { sameProjectRoot } from "./workbenchBackend.js";
import type { GracefulWorkbenchShutdownResponse } from "./workbenchBackendRetire.js";
import { captureTrackedWorkbenchJobRetirement } from "./workbenchJob.js";

/** Trusted main-only close context; never decoded from renderer JSON. */
export type WorkbenchCloseTiming = {
  deadlineAt: number;
  forceAt: number;
  background?: { retireFrontendBuilds: () => Promise<boolean> };
};

export type FastWorkbenchCloseInput = {
  workspaceRoot: string;
  port: number;
  spawnPid: number;
  /** Absolute times measured from the original window-close request. */
  deadlineAt: number;
  forceAt: number;
  signal?: AbortSignal;
  controlToken?: string;
  captureRetirement?: typeof captureTrackedWorkbenchJobRetirement;
  /** Main-line queue hook for operations that can outlive the deadline. */
  trackBackground?: (work: Promise<unknown>) => void;
  connect?: (port: number, host: string) => Promise<boolean>;
  request?: (url: string, options: {
    method: "GET" | "POST";
    signal: AbortSignal;
    headers?: Record<string, string>;
    body?: string;
    redirect: "manual";
  }) => Promise<GracefulWorkbenchShutdownResponse>;
};

/** Close only the Job captured at entry, with no PID/tree discovery fallback. */
export async function closeOwnedWorkbenchFast(input: FastWorkbenchCloseInput): Promise<boolean> {
  if (input.signal?.aborted || !Number.isFinite(input.deadlineAt)
    || !Number.isFinite(input.forceAt) || Date.now() >= input.deadlineAt
    || !Number.isInteger(input.port) || input.port <= 0 || input.port > 65535
    || !Number.isInteger(input.spawnPid) || input.spawnPid <= 0) return false;

  // Capture the exact object before health, token, or any other await.
  let retire: ReturnType<typeof captureTrackedWorkbenchJobRetirement>;
  try {
    retire = (input.captureRetirement ?? captureTrackedWorkbenchJobRetirement)(input.workspaceRoot, input.spawnPid);
  } catch {
    return false;
  }
  if (!retire) return false;
  const owned = retire;
  const host = "127.0.0.1";
  const baseUrl = `http://${host}:${input.port}`;
  const http = new AbortController();
  const request = input.request ?? ((url, options) => fetch(url, options));
  const connect = input.connect ?? ((port, nextHost) => probeTcpConnect(
    port, nextHost, Math.max(1, Math.min(100, input.deadlineAt - Date.now()))
  ));

  return await new Promise<boolean>((resolve) => {
    let settled = false;
    let retiring = false;
    let forceTimer: ReturnType<typeof setTimeout> | undefined;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let deadlineTimer: ReturnType<typeof setTimeout> | undefined;
    const live = (): boolean => !settled && !input.signal?.aborted && Date.now() < input.deadlineAt;
    const finish = (success: boolean): void => {
      if (settled) return;
      const confirmed = success && live();
      settled = true;
      clearTimeout(forceTimer);
      clearTimeout(pollTimer);
      clearTimeout(deadlineTimer);
      input.signal?.removeEventListener("abort", onAbort);
      http.abort();
      resolve(confirmed);
    };
    const onAbort = (): void => finish(false);
    const httpAllowed = (): boolean => live() && Date.now() < input.forceAt
      && !http.signal.aborted && owned.isCurrent();
    const pollPort = async (onClosed: () => void, afterRetirement = retiring): Promise<void> => {
      const canPoll = (): boolean => live() && retiring === afterRetirement;
      if (!canPoll()) return;
      try {
        const listening = await connect(input.port, host);
        if (!canPoll()) return;
        if (!listening) {
          onClosed();
          return;
        }
      } catch {
        // A failed probe is not evidence that the listener has closed.
      }
      if (canPoll()) pollTimer = setTimeout(() => { void pollPort(onClosed, afterRetirement); }, 25);
    };
    const forceRetirement = (): void => {
      if (!live() || retiring) return;
      retiring = true;
      http.abort();
      clearTimeout(pollTimer);
      // The native helper may take 8s; the independent deadline still settles
      // this call, and late completion cannot touch a replacement registration.
      const forceWork = (async () => {
        try {
          if (!(await owned())) {
            finish(false);
            return;
          }
          if (live()) await pollPort(() => finish(true));
        } catch {
          finish(false);
        }
      })();
      input.trackBackground?.(forceWork);
    };
    const graceful = async (): Promise<void> => {
      try {
        if (!httpAllowed()) return;
        const health = await request(`${baseUrl}/api/health`, {
          method: "GET", signal: http.signal, redirect: "manual"
        });
        if (!httpAllowed() || health.status !== 200 || !health.json) return;
        const payload = await health.json();
        if (!httpAllowed() || !isRecord(payload) || payload.status !== "ok"
          || typeof payload.workspaceRoot !== "string"
          || !sameProjectRoot(payload.workspaceRoot, input.workspaceRoot)) return;
        let token = input.controlToken?.trim() || "";
        if (!token) {
          const response = await request(`${baseUrl}/api/control-token`, {
            method: "GET", signal: http.signal, redirect: "manual"
          });
          if (!httpAllowed() || response.status !== 200 || !response.json) return;
          const body = await response.json();
          if (!httpAllowed() || !isRecord(body) || typeof body.controlToken !== "string") return;
          token = body.controlToken.trim();
        }
        if (!token || !httpAllowed()) return;
        const response = await request(`${baseUrl}/api/runtime/shutdown`, {
          method: "POST", signal: http.signal, redirect: "manual",
          headers: { "X-Vibelution-Control-Token": token, "Content-Type": "application/json" },
          body: JSON.stringify({ source: "electron_user_close", reason: "user_close", interruptActiveWork: true })
        });
        if (!live() || http.signal.aborted || response.status !== 202) return;
        await pollPort(forceRetirement);
      } catch {
        // The force timer is independent of every network and JSON await.
      }
    };

    input.signal?.addEventListener("abort", onAbort, { once: true });
    if (!live()) {
      finish(false);
      return;
    }
    deadlineTimer = setTimeout(() => finish(false), Math.max(0, input.deadlineAt - Date.now()));
    if (Date.now() >= input.forceAt) forceRetirement();
    else {
      forceTimer = setTimeout(forceRetirement, Math.max(0, input.forceAt - Date.now()));
      const gracefulWork = graceful();
      input.trackBackground?.(gracefulWork);
    }
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
