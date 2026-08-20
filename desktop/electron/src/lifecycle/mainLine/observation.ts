import { createConnection } from "node:net";

import {
  projectInstanceLifecycle,
  type InstanceLifecycleProjection,
} from "../instanceLifecycleProjection.js";

export const MAIN_LINE_CONNECT_TIMEOUT_MS = 250;

export type MainLineObserveInput = {
  port?: number;
  host?: string;
  knownPids?: number[];
  windowOpen?: boolean;
  desiredState?: "open" | "closed" | string;
  phase?: string;
  registryStatus?: string;
  frontendReady?: boolean;
  failureMessage?: string;
  connect?: (port: number, host: string) => Promise<boolean>;
  pidAlive?: (pid: number) => boolean;
};

export type MainLineObservation = InstanceLifecycleProjection & {
  backendAlive: boolean;
  backendListening: boolean;
  backendHealthy: boolean;
  livePids: number[];
};

export function knownPidIsAlive(pid: number): boolean {
  if (!Number.isFinite(pid) || pid <= 0) {
    return false;
  }
  try {
    process.kill(Math.trunc(pid), 0);
    return true;
  } catch {
    return false;
  }
}

export function probeTcpConnect(
  port: number,
  host = "127.0.0.1",
  timeoutMs = MAIN_LINE_CONNECT_TIMEOUT_MS,
): Promise<boolean> {
  if (!Number.isFinite(port) || port <= 0) {
    return Promise.resolve(false);
  }
  return new Promise((resolve) => {
    const socket = createConnection({ port: Math.trunc(port), host });
    let settled = false;
    const finish = (ok: boolean) => {
      if (settled) {
        return;
      }
      settled = true;
      socket.removeAllListeners();
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(Math.max(1, timeoutMs));
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
  });
}

/**
 * Main-line observation for I4b: TCP connect health gate plus known-pid
 * liveness. Port-owner tables stay in the Python multi-process domain.
 * Projection is the I1 authority.
 */
export async function observeMainLineWorkbench(input: MainLineObserveInput): Promise<MainLineObservation> {
  const pidAlive = input.pidAlive ?? knownPidIsAlive;
  const connect = input.connect ?? ((port, host) => probeTcpConnect(port, host));
  const livePids = (input.knownPids ?? []).filter((pid) => (
    Number.isFinite(pid) && pid > 0 && pidAlive(pid)
  ));
  const backendAlive = livePids.length > 0;
  const port = Number(input.port);
  const backendListening = Number.isFinite(port) && port > 0
    ? await connect(port, input.host ?? "127.0.0.1")
    : false;
  const backendHealthy = backendListening;
  const projection = projectInstanceLifecycle({
    desiredState: input.desiredState,
    phase: input.phase,
    registryStatus: input.registryStatus,
    backendAlive,
    backendHealthy,
    backendListening,
    windowOpen: input.windowOpen,
    frontendReady: input.frontendReady,
    failureMessage: input.failureMessage,
  });
  return {
    ...projection,
    backendAlive,
    backendListening,
    backendHealthy,
    livePids,
  };
}

export function mainLineHasLiveSignal(observation: Pick<
  MainLineObservation,
  "backendAlive" | "backendListening" | "lifecycleState"
> & { windowOpen?: boolean }): boolean {
  return Boolean(observation.backendAlive || observation.backendListening || observation.windowOpen);
}
