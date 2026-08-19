import { spawn } from "node:child_process";

import { pythonBridgeEnv } from "./pythonBridgeEnv.js";

export const DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES = 64_000;
export const LAUNCHER_API_JSON_BRIDGE_MAX_BYTES = 2_000_000;
export const PYTHON_JSON_BRIDGE_QUERY_TIMEOUT_MS = 5_000;
export const PYTHON_JSON_BRIDGE_COMMAND_TIMEOUT_MS = 20_000;
export const PYTHON_JSON_BRIDGE_ISOLATED_STOP_TIMEOUT_MS = 75_000;
export const PYTHON_JSON_BRIDGE_MAINTENANCE_TIMEOUT_MS = 600_000;
export const PYTHON_JSON_BRIDGE_TERMINATION_GRACE_MS = 2_000;

export type PythonJsonBridgeErrorCode =
  | "timeout"
  | "aborted"
  | "output_limit"
  | "nonzero_exit"
  | "invalid_payload"
  | "uncertain_mutation";

export type PythonJsonBridgeKillPolicy = "child" | "owned-tree" | "none";

export class PythonJsonBridgeError extends Error {
  readonly code: PythonJsonBridgeErrorCode;
  readonly causeCode?: Exclude<PythonJsonBridgeErrorCode, "uncertain_mutation">;

  constructor(
    code: PythonJsonBridgeErrorCode,
    message: string,
    options: { causeCode?: Exclude<PythonJsonBridgeErrorCode, "uncertain_mutation">; cause?: unknown } = {}
  ) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "PythonJsonBridgeError";
    this.code = code;
    this.causeCode = options.causeCode;
  }
}

export type PythonJsonBridgeChild = Pick<
  ReturnType<typeof spawn>,
  "kill" | "once" | "stdout" | "stderr" | "pid"
>;
export type PythonJsonBridgeSpawn = (
  command: string,
  args: string[],
  options: {
    cwd: string;
    windowsHide: boolean;
    stdio: ["ignore", "pipe", "pipe"];
    env: NodeJS.ProcessEnv;
  }
) => PythonJsonBridgeChild;

export type PythonJsonBridgeOwnedTreeTerminator = (child: PythonJsonBridgeChild) => void | Promise<void>;

export function invalidPythonJsonBridgePayload(
  failureLabel: string,
  detail = "returned an invalid JSON payload",
  cause?: unknown
): PythonJsonBridgeError {
  return new PythonJsonBridgeError("invalid_payload", `${failureLabel} ${detail}`, { cause });
}

export function parsePythonJsonBridgePayload<T>(raw: string, failureLabel: string): T {
  try {
    return JSON.parse(raw) as T;
  } catch (error: unknown) {
    throw invalidPythonJsonBridgePayload(failureLabel, "returned malformed JSON", error);
  }
}

function bridgeFailure(
  input: { failureLabel: string; mutation?: boolean },
  code: Exclude<PythonJsonBridgeErrorCode, "invalid_payload" | "uncertain_mutation">,
  message: string
): PythonJsonBridgeError {
  if (input.mutation && code === "timeout") {
    return new PythonJsonBridgeError(
      "uncertain_mutation",
      `${message}; the mutation outcome is uncertain and must be reconciled`,
      { causeCode: "timeout" }
    );
  }
  return new PythonJsonBridgeError(code, message);
}

export async function runPythonJsonBridge(input: {
  pythonPath: string;
  args: string[];
  cwd: string;
  spawnImpl?: PythonJsonBridgeSpawn;
  failureLabel: string;
  maxBytes?: number;
  timeoutMs: number;
  signal?: AbortSignal;
  killPolicy: PythonJsonBridgeKillPolicy;
  mutation?: boolean;
  terminateOwnedTree?: PythonJsonBridgeOwnedTreeTerminator;
  terminationGraceMs?: number;
}): Promise<string> {
  if (!Number.isFinite(input.timeoutMs) || input.timeoutMs <= 0) {
    throw new RangeError("python JSON bridge timeoutMs must be a positive finite number");
  }
  if (input.killPolicy === "owned-tree" && !input.terminateOwnedTree) {
    throw new TypeError("python JSON bridge owned-tree policy requires an explicit owned-tree terminator");
  }
  if (input.signal?.aborted) {
    throw bridgeFailure(input, "aborted", `${input.failureLabel} was aborted before spawn`);
  }

  const spawnImpl = input.spawnImpl ?? spawn;
  const maxBytes = Math.max(1_000, Math.round(input.maxBytes ?? DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES));
  const terminationGraceMs = Math.max(
    1,
    Math.round(input.terminationGraceMs ?? PYTHON_JSON_BRIDGE_TERMINATION_GRACE_MS)
  );
  const child = spawnImpl(input.pythonPath, input.args, {
    cwd: input.cwd,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    env: pythonBridgeEnv()
  });

  return await new Promise((resolveOutput, reject) => {
    const chunks: Buffer[] = [];
    let total = 0;
    let settled = false;
    let terminating = false;
    let pendingFailure: PythonJsonBridgeError | null = null;
    let terminationTimer: ReturnType<typeof setTimeout> | null = null;

    const cleanup = (): void => {
      clearTimeout(timeoutTimer);
      if (terminationTimer !== null) {
        clearTimeout(terminationTimer);
        terminationTimer = null;
      }
      input.signal?.removeEventListener("abort", onAbort);
    };

    const rejectOnce = (error: Error): void => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      reject(error);
    };

    const resolveOnce = (): void => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      resolveOutput(Buffer.concat(chunks).toString("utf8"));
    };

    const finishPendingFailure = (): void => {
      rejectOnce(pendingFailure ?? new PythonJsonBridgeError("aborted", `${input.failureLabel} was aborted`));
    };

    const beginTermination = (failure: PythonJsonBridgeError): void => {
      if (settled || terminating) {
        return;
      }
      terminating = true;
      pendingFailure = failure;
      terminationTimer = setTimeout(finishPendingFailure, terminationGraceMs);
      if (input.killPolicy === "none") {
        return;
      }
      try {
        if (input.killPolicy === "owned-tree") {
          void Promise.resolve(input.terminateOwnedTree?.(child)).catch(() => {
            // The original bounded bridge failure remains authoritative. The
            // grace timer prevents a failed terminator from hanging the caller.
          });
        } else {
          child.kill();
        }
      } catch {
        finishPendingFailure();
      }
    };

    const onAbort = (): void => {
      beginTermination(bridgeFailure(input, "aborted", `${input.failureLabel} was aborted`));
    };

    const timeoutTimer = setTimeout(() => {
      beginTermination(
        bridgeFailure(input, "timeout", `${input.failureLabel} timed out after ${Math.round(input.timeoutMs)}ms`)
      );
    }, Math.round(input.timeoutMs));

    input.signal?.addEventListener("abort", onAbort, { once: true });
    child.stdout?.on("data", (chunk: Buffer) => {
      if (settled || terminating) {
        return;
      }
      total += chunk.length;
      if (total > maxBytes) {
        beginTermination(
          bridgeFailure(input, "output_limit", `${input.failureLabel} output exceeded limit`)
        );
        return;
      }
      chunks.push(chunk);
    });
    child.stderr?.on("data", () => {
      // Drain stderr so stdio pipes cannot deadlock; detailed logs stay in Python log files.
    });
    child.once("error", (error: Error) => {
      if (terminating) {
        finishPendingFailure();
        return;
      }
      rejectOnce(
        new PythonJsonBridgeError(
          "nonzero_exit",
          `${input.failureLabel} failed to start or communicate with the child process`,
          { cause: error }
        )
      );
    });
    child.once("close", (code) => {
      if (settled) {
        return;
      }
      if (terminating) {
        finishPendingFailure();
        return;
      }
      if (code !== 0) {
        rejectOnce(
          bridgeFailure(input, "nonzero_exit", `${input.failureLabel} exited with code ${code ?? "unknown"}`)
        );
        return;
      }
      resolveOnce();
    });
  });
}
