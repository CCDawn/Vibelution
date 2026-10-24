import { randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import { readFileSync, renameSync, unlinkSync } from "node:fs";
import { mkdir, unlink, writeFile } from "node:fs/promises";
import { createServer, type Socket } from "node:net";
import { isAbsolute, join, resolve } from "node:path";
import { TextDecoder } from "node:util";

export type NativeStartResult = {
  schemaVersion?: 1;
  accepted: boolean;
  operation?: string;
  commandId?: string;
  code?: string;
  message?: string;
};

type NativeStartIdentity = { pid: number; createTime: number; executable: string };
type NativeStartOptions = {
  workspaceRoot: string;
  runtimeDir: string;
  identity: NativeStartIdentity;
  onStart: () => Promise<NativeStartResult>;
  /** Unix-socket override for isolated tests; Windows always uses a random named pipe. */
  socketPath?: string;
};

const METADATA_NAME = "native-start-transport.json";
const MAX_REQUEST_BYTES = 2048;
const MAX_RESPONSE_BYTES = 8192;
const MAX_CONNECTIONS = 8;
const FRAME_IDLE_MS = 1000;
const REQUEST_KEYS = new Set([
  "schemaVersion", "protocolVersion", "requestId", "workspaceRoot", "operation", "token",
]);

function sameWorkspace(candidate: unknown, workspaceRoot: string): boolean {
  if (typeof candidate !== "string" || !isAbsolute(candidate)) return false;
  const normalized = resolve(candidate);
  return process.platform === "win32"
    ? normalized.toLowerCase() === workspaceRoot.toLowerCase()
    : normalized === workspaceRoot;
}

function limitedText(value: unknown, limit: number, token: string): string | undefined {
  if (typeof value !== "string") return undefined;
  // Results come from the lifecycle owner, never from exception text or a request echo.
  return [...value.replaceAll(token, "[redacted]")].slice(0, limit).join("");
}

/** Local transport only: onStart remains the sole owner of dispatch and lifecycle policy. */
export async function startNativeLauncherStartTransport(options: NativeStartOptions): Promise<{ close(): Promise<void> }> {
  const { identity, onStart } = options;
  if (!isAbsolute(options.workspaceRoot) || !isAbsolute(options.runtimeDir)
    || !Number.isSafeInteger(identity.pid) || identity.pid <= 0
    || !Number.isFinite(identity.createTime) || identity.createTime <= 0
    || typeof identity.executable !== "string" || !identity.executable.trim()
    || (options.socketPath !== undefined && (process.platform === "win32" || !isAbsolute(options.socketPath)))) {
    throw new Error("Invalid native start transport configuration.");
  }
  const workspaceRoot = resolve(options.workspaceRoot);
  const runtimeDir = resolve(options.runtimeDir);
  const token = randomBytes(32).toString("hex");
  const pipeName = `vibelution-native-start-${identity.pid}-${randomUUID()}`;
  const socketPath = process.platform === "win32"
    ? `\\\\.\\pipe\\${pipeName}`
    : options.socketPath ?? join(runtimeDir, `${pipeName}.sock`);
  const metadataPath = join(runtimeDir, METADATA_NAME);
  const temporaryPath = join(runtimeDir, `.${METADATA_NAME}.${randomUUID()}.tmp`);
  const sockets = new Set<Socket>();
  let closing = false;
  let closePromise: Promise<void> | undefined;

  const response = (socket: Socket, requestId: string, result: NativeStartResult) => {
    if (closing || socket.destroyed || socket.writableEnded) return;
    const payload = {
      schemaVersion: 1,
      protocolVersion: 1,
      requestId,
      workspaceRoot,
      accepted: result.accepted === true,
      ...(typeof result.commandId === "string" && result.commandId
        ? { commandId: limitedText(result.commandId, 512, token) } : {}),
      ...(typeof result.code === "string" ? { code: limitedText(result.code, 128, token) } : {}),
      ...(typeof result.message === "string" ? { message: limitedText(result.message, 1024, token) } : {}),
      ...(result.accepted === false && result.code === "native_requires_legacy_launch" && !result.commandId
        ? { notDispatched: true } : {}),
    };
    let line = `${JSON.stringify(payload)}\n`;
    if (Buffer.byteLength(line) > MAX_RESPONSE_BYTES) {
      // A malformed owner result must not produce an oversized frame or an unsafe retry hint.
      line = `${JSON.stringify({ schemaVersion: 1, protocolVersion: 1, requestId, workspaceRoot,
        accepted: false, code: "native_start_failed", message: "Native start result exceeded the transport limit." })}\n`;
    }
    if (Buffer.byteLength(line) <= MAX_RESPONSE_BYTES) socket.end(line);
    else socket.destroy();
  };

  const server = createServer({ allowHalfOpen: true }, (socket) => {
    socket.on("error", () => { socket.destroy(); });
    if (closing || sockets.size >= MAX_CONNECTIONS) {
      socket.destroy();
      return;
    }
    sockets.add(socket);
    socket.on("close", () => { sockets.delete(socket); });
    let frame = Buffer.alloc(0);
    let handled = false;
    const reject = (requestId = "") => response(socket, requestId, {
      accepted: false, code: "native_invalid_request", message: "Invalid native start request.",
    });
    socket.setTimeout(FRAME_IDLE_MS, () => { socket.destroy(); });
    socket.on("end", () => { if (!handled) socket.destroy(); });
    socket.on("data", (chunk: Buffer) => {
      if (handled || closing) return;
      const newline = chunk.indexOf(10);
      const fragment = newline < 0 ? chunk : chunk.subarray(0, newline);
      if (frame.length + fragment.length > MAX_REQUEST_BYTES) {
        handled = true;
        socket.setTimeout(0);
        reject();
        return;
      }
      frame = Buffer.concat([frame, fragment]);
      if (newline < 0) return;
      handled = true;
      socket.setTimeout(0);
      let request: Record<string, unknown>;
      try {
        const parsed: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(frame));
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
        request = parsed as Record<string, unknown>;
      } catch {
        reject();
        return;
      } finally {
        frame = Buffer.alloc(0);
      }
      const requestId = typeof request.requestId === "string" && /^launch_[a-f0-9]{32}$/.test(request.requestId)
        ? request.requestId : "";
      const suppliedToken = typeof request.token === "string" && /^[a-f0-9]{64}$/.test(request.token)
        ? Buffer.from(request.token, "hex") : null;
      if (Object.keys(request).some((key) => !REQUEST_KEYS.has(key))
        || request.schemaVersion !== 1 || request.protocolVersion !== 1 || !requestId
        || request.operation !== "start" || !sameWorkspace(request.workspaceRoot, workspaceRoot)
        || !suppliedToken || !timingSafeEqual(suppliedToken, Buffer.from(token, "hex"))) {
        reject(requestId);
        return;
      }
      // Invoke synchronously after validation. A subsequent disconnect must neither cancel
      // nor repeat a dispatched operation, and shutdown must not schedule a late invocation.
      try {
        void Promise.resolve(onStart()).then(
          (result) => response(socket, requestId, result && typeof result === "object" ? result : {
            accepted: false, code: "native_start_failed", message: "Native start failed.",
          }),
          () => response(socket, requestId, {
            accepted: false, code: "native_start_failed", message: "Native start failed.",
          }),
        ).catch(() => { socket.destroy(); });
      } catch {
        response(socket, requestId, {
          accepted: false, code: "native_start_failed", message: "Native start failed.",
        });
      }
    });
  });
  // Connection-specific errors are handled above; never log an error containing transport secrets.
  server.on("error", () => {});

  const close = (): Promise<void> => {
    if (closePromise) return closePromise;
    closing = true;
    // A short synchronous ownership check/revoke cannot interleave with a new
    // publication on this event loop. It also completes before app.exit(),
    // which cannot wait for filesystem promises during process shutdown.
    let cleanupFailed = false;
    try {
      const published: unknown = JSON.parse(readFileSync(metadataPath, "utf8"));
      if (published && typeof published === "object" && "pid" in published && "token" in published
        && published.pid === identity.pid && published.token === token) {
        unlinkSync(metadataPath);
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT" && !(error instanceof SyntaxError)) {
        cleanupFailed = true;
      }
    }
    for (const socket of sockets) socket.destroy();
    closePromise = new Promise<void>((done) => { server.close(() => done()); }).then(() => {
      if (cleanupFailed) throw new Error("Could not remove native start transport metadata.");
    });
    return closePromise;
  };

  try {
    await mkdir(runtimeDir, { recursive: true });
    await new Promise<void>((done, failed) => {
      const onError = () => { failed(new Error("Could not listen on native start transport.")); };
      server.once("error", onError);
      server.listen(socketPath, () => { server.off("error", onError); done(); });
    });
    await writeFile(temporaryPath, `${JSON.stringify({
      schemaVersion: 1, protocolVersion: 1, workspaceRoot,
      pid: identity.pid, createTime: identity.createTime, executable: identity.executable, pipeName, token,
    })}\n`, { encoding: "utf8", mode: 0o600, flag: "wx" });
    renameSync(temporaryPath, metadataPath);
  } catch {
    await close().catch(() => {});
    await unlink(temporaryPath).catch(() => {});
    throw new Error("Could not publish native start transport.");
  }
  return { close };
}
