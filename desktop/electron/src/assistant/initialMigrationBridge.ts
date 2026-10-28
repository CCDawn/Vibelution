import { randomBytes, timingSafeEqual } from "node:crypto";
import { createServer, type Server, type ServerResponse } from "node:http";
import { isAbsolute, relative } from "node:path";
import type { PreHostSourceLease } from "./projectRegistryConnection.js";

/** Main-only launch data. No renderer or model supplies these paths. */
export type InitialMigrationLaunchBinding = {
  registeredProjectId: string;
  sourceConfig: string;
  targetProfile: string;
  targetConfig: string;
  operationId: string;
};

const ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/;
const OPERATION = /^initial-[a-f0-9]{40}$/;
const bad = () => { throw new Error("INITIAL_MIGRATION_BRIDGE_INVALID"); };

/**
 * A private, one-use loopback channel for one owned offline migration Job.
 * Main must call closeAfterDrain only after the captured Job and output drains
 * have exited. A granted permit stays held until that point, so later stop or
 * registry changes wait for the admitted writer instead of racing its commit.
 */
export async function openInitialMigrationBridge(lease: PreHostSourceLease, input: InitialMigrationLaunchBinding): Promise<{
  environment: Readonly<{ VIBELUTION_INITIAL_MIGRATION_URL: string; VIBELUTION_INITIAL_MIGRATION_TOKEN: string }>;
  wasGranted(): boolean;
  closeAfterDrain(): Promise<void>;
}> {
  if (!input || !ID.test(input.registeredProjectId) || !OPERATION.test(input.operationId)
    || input.registeredProjectId !== `${lease.registration.baseProjectId}:${lease.registration.registrationUuid}`
    || ![input.sourceConfig, input.targetProfile, input.targetConfig, lease.registration.root].every(path => typeof path === "string" && isAbsolute(path) && !path.includes("\0"))) bad();
  const targetRelative = relative(input.targetProfile, input.targetConfig);
  if (!targetRelative || targetRelative.startsWith("..") || isAbsolute(targetRelative)) bad();
  lease.check();
  const token = randomBytes(32).toString("hex");
  let permitUsed = false, granted = false, closed = false, release: (() => void) | undefined;
  let commit: Promise<void> | undefined;
  let server!: Server;
  const send = (res: ServerResponse, status: number, value: object) => {
    if (res.headersSent || res.destroyed) return;
    res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", Connection: "close" });
    res.end(JSON.stringify(value));
  };
  server = createServer((request, response) => {
    const auth = request.headers.authorization ?? "";
    const expected = `Bearer ${token}`;
    const actualBytes = Buffer.from(auth, "utf8"), expectedBytes = Buffer.from(expected, "ascii");
    if (closed || request.socket.remoteAddress !== "127.0.0.1" || actualBytes.length !== expectedBytes.length
      || !timingSafeEqual(actualBytes, expectedBytes)) {
      send(response, 403, { schemaVersion: 1, code: "unavailable" }); return;
    }
    if (request.method === "GET" && request.url === "/binding") {
      try {
        lease.check();
        send(response, 200, { schemaVersion: 1, registeredProjectId: input.registeredProjectId,
          revision: lease.revision, projectRoot: lease.registration.root, sourceConfig: input.sourceConfig,
          targetProfile: input.targetProfile, targetConfig: input.targetConfig, operationId: input.operationId });
      } catch { send(response, 409, { schemaVersion: 1, code: "unavailable" }); }
      return;
    }
    if (request.method !== "POST" || request.url !== "/permit" || permitUsed) {
      send(response, 409, { schemaVersion: 1, code: "unavailable" }); return;
    }
    let body = "";
    request.setEncoding("utf8");
    request.on("data", chunk => { body += chunk; if (body.length > 32) request.destroy(); });
    request.on("end", () => {
      if (body !== "{}" || permitUsed || closed) { send(response, 409, { schemaVersion: 1, code: "unavailable" }); return; }
      permitUsed = true;
      commit = lease.commit(async () => {
        granted = true;
        send(response, 200, { schemaVersion: 1, granted: true });
        await new Promise<void>(resolve => { release = resolve; });
      });
      void commit.catch(() => send(response, 409, { schemaVersion: 1, code: "unavailable" }));
    });
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => { server.off("error", reject); resolve(); });
  });
  const address = server.address();
  if (!address || typeof address === "string") { server.close(); return bad(); }
  return {
    environment: Object.freeze({ VIBELUTION_INITIAL_MIGRATION_URL: `http://127.0.0.1:${address.port}`,
      VIBELUTION_INITIAL_MIGRATION_TOKEN: token }),
    wasGranted: () => granted,
    async closeAfterDrain() {
      if (closed) return;
      closed = true;
      release?.();
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
      await commit;
    },
  };
}
