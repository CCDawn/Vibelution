import { createHash, timingSafeEqual, X509Certificate } from "node:crypto";
import { closeSync, fstatSync, lstatSync, openSync, readSync } from "node:fs";
import { createServer, type Server } from "node:https";
import type { IncomingMessage, ServerResponse } from "node:http";
import { join } from "node:path";
import type { AssistantHost, AssistantHostBinding } from "./assistantHost.js";

const ADDRESS = "127.0.0.1";
const TOKEN = /^[a-f0-9]{64}(?![\s\S])/;
const ID = /^[A-Za-z0-9_.:-]{1,160}(?![\s\S])/;
const REQUEST_ID = /^[A-Za-z0-9_.:-]{1,128}(?![\s\S])/;
const MAX_MESSAGE_CHARS = 64_000;
const MAX_BODY_BYTES = MAX_MESSAGE_CHARS * 6 + 1024;
const MAX_AVATAR_BYTES = 5 * 1024 * 1024;
const MAX_HISTORY_PAGE_BYTES = 1024 * 1024;
const AVATAR_TYPES = ["image/png", "image/jpeg", "image/webp", "image/svg+xml"];
const RESPONSE_HEADERS = {
  "Cache-Control": "no-store",
  "Content-Security-Policy": "default-src 'none'; sandbox",
  "X-Content-Type-Options": "nosniff",
  Connection: "close",
};

type RemoteAccessConfig = { port: number; token: string; cert: Buffer; key: Buffer };
type RemoteHost = Pick<AssistantHost, "request">;
type RemoteMessage = { id: string; messageIndex: number; role: "user" | "assistant"; text: string; timestamp: string };

class RemoteError extends Error {
  constructor(readonly status: number, readonly code: string) { super(code); }
}

const invalid = () => new RemoteError(400, "invalid_request");
const invalidNative = () => new RemoteError(503, "assistant_unavailable");

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function id(value: unknown): value is string {
  return typeof value === "string" && ID.test(value);
}

function integer(value: unknown, maximum: number): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0 && value <= maximum;
}

function binding(agentId: unknown, sessionId: unknown): AssistantHostBinding {
  if (!id(agentId) || !id(sessionId)) throw invalid();
  return { agentId, sessionId };
}

function readProvisionedFile(path: string, maxBytes: number, privateFile = true): Buffer {
  const listed = lstatSync(path);
  if (!listed.isFile() || listed.isSymbolicLink()) throw Error("ASSISTANT_REMOTE_CONFIG_INVALID");
  const fd = openSync(path, "r");
  try {
    const stat = fstatSync(fd);
    if (!stat.isFile() || stat.ino !== listed.ino || stat.dev !== listed.dev
      || stat.size < 1 || stat.size > maxBytes
      || (privateFile && process.platform !== "win32" && (stat.mode & 0o077) !== 0)) {
      throw Error("ASSISTANT_REMOTE_CONFIG_INVALID");
    }
    const data = Buffer.alloc(stat.size);
    if (readSync(fd, data, 0, data.length, 0) !== data.length || fstatSync(fd).size !== stat.size) {
      throw Error("ASSISTANT_REMOTE_CONFIG_INVALID");
    }
    return data;
  } finally { closeSync(fd); }
}

function readRemoteAccessConfig(userDataRoot: string): RemoteAccessConfig | null {
  const directory = join(userDataRoot, "assistant");
  const stem = join(directory, "remote-access");
  let provisioned: Buffer;
  try {
    const parent = lstatSync(directory);
    if (!parent.isDirectory() || parent.isSymbolicLink()) throw Error("ASSISTANT_REMOTE_CONFIG_INVALID");
    provisioned = readProvisionedFile(stem + ".json", 1024);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
  const value: unknown = JSON.parse(provisioned.toString("utf8"));
  if (!record(value) || Object.keys(value).length !== 2
    || !integer(value.port, 65535) || value.port < 1024
    || typeof value.token !== "string" || !TOKEN.test(value.token)) throw Error("ASSISTANT_REMOTE_CONFIG_INVALID");
  const cert = readProvisionedFile(stem + ".crt", 32 * 1024, false);
  if (!new X509Certificate(cert).checkIP(ADDRESS)) throw Error("ASSISTANT_REMOTE_CONFIG_INVALID");
  return { port: value.port, token: value.token, cert, key: readProvisionedFile(stem + ".key", 32 * 1024) };
}

function reply(response: ServerResponse, status: number, body: object | Buffer, contentType = "application/json") {
  if (response.destroyed || response.headersSent) return;
  const bytes = Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body));
  response.writeHead(status, { ...RESPONSE_HEADERS, "Content-Type": contentType, "Content-Length": bytes.length });
  response.end(bytes);
}

async function readMessage(request: IncomingMessage): Promise<{
  binding: AssistantHostBinding; message: string; requestId: string;
}> {
  if (request.headers["content-type"]?.split(";", 1)[0].trim().toLowerCase() !== "application/json"
    || request.headers["content-encoding"] !== undefined) throw invalid();
  if (Number(request.headers["content-length"]) > MAX_BODY_BYTES) throw new RemoteError(413, "request_too_large");
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request.iterator({ destroyOnReturn: false })) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) throw new RemoteError(413, "request_too_large");
    chunks.push(chunk);
  }
  let value: unknown;
  try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks, size))); }
  catch { throw invalid(); }
  if (!record(value) || Object.keys(value).length !== 4
    || typeof value.text !== "string" || !value.text.trim() || value.text.length > MAX_MESSAGE_CHARS
    || Buffer.from(value.text).toString("utf8") !== value.text
    || typeof value.requestId !== "string" || !REQUEST_ID.test(value.requestId)) throw invalid();
  return { binding: binding(value.agentId, value.sessionId), message: value.text, requestId: value.requestId };
}

function readQuery(url: URL, history: boolean) {
  const allowed = new Set(history ? ["agentId", "sessionId", "limit", "beforeMessageIndex"] : ["agentId", "sessionId"]);
  for (const key of url.searchParams.keys()) if (!allowed.delete(key)) throw invalid();
  const pagination = (key: string, maximum: number) => {
    const raw = url.searchParams.get(key);
    if (raw === null) return undefined;
    const value = Number(raw);
    if (!integer(value, maximum) || String(value) !== raw) throw invalid();
    return value;
  };
  return {
    binding: binding(url.searchParams.get("agentId"), url.searchParams.get("sessionId")),
    limit: pagination("limit", 50) ?? 50,
    beforeMessageIndex: pagination("beforeMessageIndex", 2_147_483_647),
  };
}

function projectProfile(value: unknown) {
  if (!record(value) || !record(value.assistant)) throw invalidNative();
  const { agentId, directSessionId: sessionId, displayName: name } = value.assistant;
  if (!id(agentId) || !id(sessionId) || typeof name !== "string" || !name.trim() || name.length > 160) throw invalidNative();
  return { agentId, sessionId, name, status: "ready",
    avatarRevision: typeof value.assistantAvatarRevision === "string" && TOKEN.test(value.assistantAvatarRevision)
      ? value.assistantAvatarRevision : null };
}

function projectMessage(value: unknown, sessionId: string): RemoteMessage | null {
  if (!record(value) || typeof value.id !== "string" || !value.id.startsWith(`${sessionId}-message-`)) return null;
  const messageIndex = Number(value.id.slice(sessionId.length + "-message-".length));
  if (!integer(messageIndex, 2_147_483_647) || typeof value.timestamp !== "string" || value.timestamp.length > 64) return null;
  const role = value.role;
  if (role !== "user" && role !== "assistant") return null;
  // Desktop turn items distinguish final replies from reasoning, commentary
  // and tools. Reuse that distinction and omit internal metadata.
  const text = role === "user" ? value.content : Array.isArray(value.turnItems)
    ? value.turnItems.filter(item => record(item) && item.type === "agent_message" && item.phase === "final_answer"
      && item.status === "completed" && typeof item.text === "string").map(item => item.text).join("\n\n")
    : null;
  if (typeof text !== "string" || !text.trim()) return null;
  const clipped = text.length <= MAX_MESSAGE_CHARS ? text
    : text.slice(0, MAX_MESSAGE_CHARS - 1).replace(/[\uD800-\uDBFF]$/, "") + "…";
  return { id: value.id, messageIndex, role, text: clipped, timestamp: value.timestamp };
}

function projectHistory(value: unknown, expected: AssistantHostBinding, limit: number, before?: number) {
  if (!record(value) || value.id !== expected.sessionId || value.agentId !== expected.agentId
    || !record(value.messageWindow) || !Array.isArray(value.messages)) throw invalidNative();
  const { nextBeforeMessageIndex: cursor } = value.messageWindow;
  if (cursor !== null && !integer(cursor, 2_147_483_647)) throw invalidNative();
  const messages: RemoteMessage[] = [];
  let remainingBytes = MAX_HISTORY_PAGE_BYTES - 1024;
  for (let index = value.messages.length - 1; index >= 0; index--) {
    const message = projectMessage(value.messages[index], expected.sessionId);
    if (!message || (before !== undefined && message.messageIndex >= before)) continue;
    remainingBytes -= Buffer.byteLength(JSON.stringify(message)) + 1;
    if (messages.length === limit || remainingBytes < 0) {
      const nextBeforeMessageIndex = messages.at(-1)?.messageIndex;
      if (nextBeforeMessageIndex === undefined) throw invalidNative();
      return { ...expected, messages: messages.reverse(), nextBeforeMessageIndex };
    }
    messages.push(message);
  }
  return { ...expected, messages: messages.reverse(), nextBeforeMessageIndex: cursor };
}

function projectAvatar(value: unknown, expected: AssistantHostBinding) {
  if (!record(value) || value.agentId !== expected.agentId || value.schemaVersion !== 1) throw invalidNative();
  if (value.image === null) throw new RemoteError(404, "assistant_avatar_missing");
  const image = value.image;
  if (!record(image) || typeof image.contentType !== "string" || !AVATAR_TYPES.includes(image.contentType)
    || typeof image.dataBase64 !== "string" || image.dataBase64.length > Math.ceil(MAX_AVATAR_BYTES / 3) * 4) throw invalidNative();
  const bytes = Buffer.from(image.dataBase64, "base64");
  if (!bytes.length || bytes.length > MAX_AVATAR_BYTES || bytes.toString("base64") !== image.dataBase64
    || createHash("sha256").update(bytes).digest("hex") !== image.sha256) throw invalidNative();
  return { bytes, contentType: image.contentType };
}

function projectAcceptance(value: unknown, expected: AssistantHostBinding, requestId: string) {
  const unknown = () => new RemoteError(503, "assistant_submission_unconfirmed");
  if (!record(value) || value.sessionId !== expected.sessionId
    || value.clientSubmissionId !== requestId || value.accepted !== true) throw unknown();
  if (value.status === "queued" && value.turnId === "" && id(value.queuedTurnId)) {
    return { accepted: true, status: "queued", requestId, turnId: "", queuedTurnId: value.queuedTurnId };
  }
  if (value.status !== "queued" && id(value.turnId) && value.queuedTurnId === undefined) {
    return { accepted: true, status: "started", requestId, turnId: value.turnId };
  }
  throw unknown();
}

function nativeError(error: unknown, send: boolean): RemoteError {
  if (error instanceof RemoteError) return error;
  const code = error instanceof Error ? error.message : "";
  if (code === "ASSISTANT_IDENTITY_INVALID") return new RemoteError(409, "assistant_identity_changed");
  if (code === "ASSISTANT_SESSION_CONFLICT") return new RemoteError(409, "assistant_session_conflict");
  if (code === "ASSISTANT_REQUEST_INVALID" || code === "ASSISTANT_SESSION_INVALID") return invalid();
  return send ? new RemoteError(503, "assistant_submission_unconfirmed") : invalidNative();
}

async function invoke(request: IncomingMessage, response: ServerResponse, authority: string,
  bearer: Buffer, host: () => RemoteHost | null, closing: AbortSignal) {
  const authorization = Buffer.from(request.headers.authorization ?? "");
  if (request.socket.remoteAddress !== ADDRESS || request.headers.host !== authority
    || request.headers.origin !== undefined || request.headers["sec-fetch-site"] !== undefined
    || authorization.length !== bearer.length || !timingSafeEqual(authorization, bearer)) {
    reply(response, 403, { error: "forbidden" });
    return;
  }
  let send = false;
  try {
    if (!request.url?.startsWith("/") || request.url.startsWith("//") || request.url.includes("#")) throw invalid();
    const url = new URL(request.url, `https://${authority}`);
    if (url.origin !== `https://${authority}` || request.url.split("?", 1)[0] !== url.pathname) throw invalid();
    const method = request.method;
    send = method === "POST" && url.pathname === "/v1/assistant/messages";
    if (method !== "GET" && !send) throw new RemoteError(404, "not_found");
    if (!send && (request.headers["transfer-encoding"] !== undefined || Number(request.headers["content-length"]) > 0)) throw invalid();
    const aborted = new AbortController();
    const signal = AbortSignal.any([closing, aborted.signal, AbortSignal.timeout(20_000)]);
    const abort = () => aborted.abort();
    response.once("close", abort);
    const invokeHost: RemoteHost["request"] = (input, expected) => {
      const current = host();
      if (!current) throw invalidNative();
      signal.throwIfAborted();
      // The broker deadline does not cancel a native write already dispatched.
      // Clients recover its receipt by retrying the same submission ID.
      return current.request(input, expected, signal);
    };
    try {
      if (send) {
        if (url.search) throw invalid();
        const input = await readMessage(request);
        const result = await invokeHost({ operation: "send", message: input.message, requestId: input.requestId }, input.binding);
        reply(response, 200, projectAcceptance(result, input.binding, input.requestId));
      } else if (url.pathname === "/v1/assistant") {
        if (url.search) throw invalid();
        reply(response, 200, projectProfile(await invokeHost({ operation: "status" })));
      } else if (url.pathname === "/v1/assistant/messages") {
        const input = readQuery(url, true);
        const result = await invokeHost({ operation: "detail", ...(input.beforeMessageIndex === undefined
          ? {} : { beforeMessageIndex: input.beforeMessageIndex }) }, input.binding);
        reply(response, 200, projectHistory(result, input.binding, input.limit, input.beforeMessageIndex));
      } else if (url.pathname === "/v1/assistant/avatar") {
        const expected = readQuery(url, false).binding;
        const image = projectAvatar(await invokeHost({ operation: "assistantAvatar" }, expected), expected);
        reply(response, 200, image.bytes, image.contentType);
      } else throw new RemoteError(404, "not_found");
    } finally { response.off("close", abort); }
  } catch (error) {
    const failure = nativeError(error, send);
    reply(response, failure.status, { error: failure.code });
  }
}

/** Main-process only. Absent provisioning leaves the default desktop surface unchanged. */
export async function openAssistantRemoteAccess(userDataRoot: string, host: () => RemoteHost | null,
  onServerError: () => void): Promise<{ close(): void } | null> {
  const config = readRemoteAccessConfig(userDataRoot);
  if (!config) return null;
  const closing = new AbortController();
  const authority = `${ADDRESS}:${config.port}`;
  const bearer = Buffer.from(`Bearer ${config.token}`, "ascii");
  const server: Server = createServer({
    cert: config.cert, key: config.key, minVersion: "TLSv1.2", requestTimeout: 10_000,
    headersTimeout: 5_000, connectionsCheckingInterval: 1_000,
  }, (request, response) => { void invoke(request, response, authority, bearer, host, closing.signal); });
  server.maxConnections = 12;
  server.setTimeout(25_000, socket => socket.destroy());
  const close = () => {
    if (closing.signal.aborted) return;
    closing.abort();
    server.close();
    server.closeAllConnections();
  };
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(config.port, ADDRESS, () => {
      server.off("error", reject);
      server.on("error", () => { close(); onServerError(); });
      server.unref();
      resolve();
    });
  });
  return { close };
}
