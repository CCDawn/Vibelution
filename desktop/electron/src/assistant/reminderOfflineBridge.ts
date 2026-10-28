import { randomBytes, timingSafeEqual } from "node:crypto";
import { createServer, type Server, type ServerResponse } from "node:http";
import { homedir } from "node:os";
import { isAbsolute, relative } from "node:path";
import type { PreHostSourceLease } from "./projectRegistryConnection.js";

/** Only main constructs this binding after authorization; no renderer paths. */
export type ReminderOfflineBinding = {
  registeredProjectId: string; sourceConfig: string; sourceProjectsHome: string; targetProfile: string; targetConfig: string;
  syncId: string; mode: "start" | "resume"; recoveryId: string | null;
};
const ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/;
const PREP = /^rprep-[a-f0-9]{40}$/;

/** One captured Job; the registry permit remains held until its complete drain. */
export async function openReminderOfflineBridge(lease: PreHostSourceLease, input: ReminderOfflineBinding) {
  if (!input || input.registeredProjectId !== `${lease.registration.baseProjectId}:${lease.registration.registrationUuid}`
      || !ID.test(input.syncId)
      || !["start", "resume"].includes(input.mode) || input.mode === "start" && input.recoveryId !== null
      || input.recoveryId !== null && !PREP.test(input.recoveryId)
      || ![lease.registration.root, input.sourceConfig, input.sourceProjectsHome, input.targetProfile, input.targetConfig]
        .every(path => typeof path === "string" && isAbsolute(path) && !path.includes("\0")))
    throw new Error("REMINDER_WORKER_BINDING_INVALID");
  const targetRelative = relative(input.targetProfile, input.targetConfig);
  if (!targetRelative || targetRelative.startsWith("..") || isAbsolute(targetRelative))
    throw new Error("REMINDER_WORKER_BINDING_INVALID");
  // Derive the operator profile in trusted main, never from renderer input.
  // Python's existing default_data_home uses USERPROFILE on Windows.
  const sourceUserProfile = homedir();
  if (!isAbsolute(sourceUserProfile) || sourceUserProfile.includes("\0")) throw new Error("REMINDER_WORKER_BINDING_INVALID");
  lease.check();
  const token = randomBytes(32).toString("hex");
  let used = false, granted = false, closed = false, release: (() => void) | undefined;
  let commit: Promise<void> | undefined;
  let server!: Server;
  const send = (res: ServerResponse, status: number, body: object) => {
    if (res.headersSent || res.destroyed) return;
    res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", Connection: "close" });
    res.end(JSON.stringify(body));
  };
  server = createServer((request, response) => {
    const actual = Buffer.from(request.headers.authorization ?? "", "utf8");
    const expected = Buffer.from(`Bearer ${token}`, "ascii");
    if (closed || request.socket.remoteAddress !== "127.0.0.1" || actual.length !== expected.length
        || !timingSafeEqual(actual, expected)) { send(response, 403, { code: "unavailable" }); return; }
    if (request.method === "GET" && request.url === "/binding") {
      try {
        lease.check();
        send(response, 200, { schemaVersion: 1, ...input, revision: lease.revision, projectRoot: lease.registration.root, sourceUserProfile });
      } catch { send(response, 409, { code: "unavailable" }); }
      return;
    }
    if (request.method !== "POST" || request.url !== "/permit" || used) {
      send(response, 409, { code: "unavailable" }); return;
    }
    let body = "";
    request.setEncoding("utf8");
    request.on("data", chunk => { body += chunk; if (body.length > 32) request.destroy(); });
    request.on("end", () => {
      if (closed || used || body !== "{}") { send(response, 409, { code: "unavailable" }); return; }
      used = true;
      commit = lease.commit(async () => {
        if (closed) return;
        granted = true;
        send(response, 200, { schemaVersion: 1, granted: true });
        await new Promise<void>(resolve => { release = resolve; });
      });
      void commit.catch(() => send(response, 409, { code: "unavailable" }));
    });
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => { server.off("error", reject); resolve(); });
  });
  const address = server.address();
  if (!address || typeof address === "string") { server.close(); throw new Error("REMINDER_WORKER_BRIDGE_UNAVAILABLE"); }
  return {
    environment: Object.freeze({ VIBELUTION_REMINDER_WORKER_URL: `http://127.0.0.1:${address.port}`,
      VIBELUTION_REMINDER_WORKER_TOKEN: token }),
    wasGranted: () => granted,
    async closeAfterDrain() {
      if (closed) return;
      closed = true; release?.(); server.closeAllConnections();
      await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
      try { await commit; } catch (error) { if (granted) throw error; }
    },
  };
}
