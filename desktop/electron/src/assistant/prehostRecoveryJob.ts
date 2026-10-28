import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { mkdirSync, mkdtempSync, realpathSync, statSync } from "node:fs";
import { createServer, type ServerResponse } from "node:http";
import { homedir } from "node:os";
import { isAbsolute, join } from "node:path";
import { loadWorkbenchJobNative, type WorkbenchJobHandle, type WorkbenchJobNative } from "../process/workbenchJob.js";
import { resolveNoConsolePython } from "../process/workbenchBackend.js";
import type { ProjectAdmissionSeal } from "../lifecycle/projectAdmission.js";
import type { AssistantProjectRegistryConnection, PreHostRecoverySourceLease } from "./projectRegistryConnection.js";

type Marker = Parameters<Parameters<AssistantProjectRegistryConnection["recoverPreHostSource"]>[1]>[0];
type Commit = { markerPath: string; markerSha256: string; markerIdentity: { device: string; inode: string; birthtimeNs: string };
  commitKey: string; checkAuthority(): void };
export type PrehostRecoveryJobLease = PreHostRecoverySourceLease & { commitMarker(input: Commit): Promise<boolean> };
/** The captured Job and both streams have ended, but their result is unusable. */
export class PrehostRecoveryDrainedUnknown extends Error {
  constructor() { super("PREHOST_RECOVERY_DRAIN_UNKNOWN"); this.name = "PrehostRecoveryDrainedUnknown"; }
}

/** Main-only original marker binding; no ordinary dispatch is opened. */
export async function startPrehostRecoveryJob(input: { marker: Marker; sourceRoot: string; pythonPath: string;
  pythonArguments: string[]; runtimeRoot: string; sourceConfig: string; sourceProjectsHome: string;
  targetProfile: string; env: NodeJS.ProcessEnv; projectSeal: ProjectAdmissionSeal;
  native?: WorkbenchJobNative }): Promise<PrehostRecoveryJobLease | null> {
  const { marker, projectSeal } = input;
  if (!marker || !/^(?:initial|ksync|krec|affairs)-[a-f0-9]{40}$/.test(marker.operationId)
      || ![input.sourceRoot, input.pythonPath, input.runtimeRoot, input.sourceConfig, input.sourceProjectsHome,
           input.targetProfile, marker.registration.root, homedir()].every(path => isAbsolute(path) && !path.includes("\0")))
    throw new Error("PREHOST_RECOVERY_INVALID");
  const checkBinding = () => {
    projectSeal.check();
    const canonical = (path: string) => {
      const value = realpathSync.native(path);
      return process.platform === "win32" ? value.toLowerCase() : value;
    };
    const info = statSync(marker.registration.root, { bigint: true });
    if (canonical(projectSeal.root) !== canonical(marker.registration.root) || !info.isDirectory()
        || info.dev.toString() !== marker.identity.dev || info.ino.toString() !== marker.identity.ino
        || info.birthtimeNs.toString() !== marker.identity.birthtimeNs) throw new Error("PREHOST_RECOVERY_INVALID");
  };
  checkBinding();
  await projectSeal.drain();
  const native = input.native ?? loadWorkbenchJobNative();
  if (typeof native.exitCode !== "function" || typeof native.drainStatus !== "function") throw new Error("PREHOST_RECOVERY_UNAVAILABLE");
  const exitCode = native.exitCode.bind(native), drainStatus = native.drainStatus.bind(native);
  const secret = randomBytes(32).toString("hex");
  let ready = false, closing = false, drained = false, closed = false, drainHealthy = false;
  let resolveReady!: (value: boolean) => void;
  const readyPromise = new Promise<boolean>(resolve => { resolveReady = resolve; });
  let pending: { id: string; kind: "check" | "commit"; dispatched: boolean; commit?: Commit; resolve(value: boolean): void } | undefined;
  const respond = (response: ServerResponse, value: object, status = 200) => {
    if (response.headersSent || response.destroyed) return;
    response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", Connection: "close" });
    response.end(JSON.stringify(value));
  };
  const server = createServer((request, response) => {
    const actual = Buffer.from(request.headers.authorization ?? "", "utf8"), expected = Buffer.from(`Bearer ${secret}`, "ascii");
    if (closed || request.socket.remoteAddress !== "127.0.0.1" || actual.length !== expected.length
        || !timingSafeEqual(actual, expected) || request.method !== "GET") { respond(response, {}, 403); return; }
    if (request.url === "/binding") {
      try {
        checkBinding();
        respond(response, { schemaVersion: 1, projectId: marker.projectId, operationId: marker.operationId,
          revision: marker.revision, projectRoot: marker.registration.root, sourceConfig: input.sourceConfig,
          sourceProjectsHome: input.sourceProjectsHome, sourceUserProfile: homedir(), targetProfile: input.targetProfile });
      } catch { respond(response, {}, 409); }
      return;
    }
    if (request.url === "/ready" && !ready && !closing) {
      try { checkBinding(); ready = true; resolveReady(true); respond(response, { schemaVersion: 1, accepted: true }); }
      catch { respond(response, {}, 409); }
      return;
    }
    if (request.url === "/poll") {
      if (closing) { respond(response, { schemaVersion: 1, action: "release" }); return; }
      if (!pending || pending.dispatched) { respond(response, { schemaVersion: 1, action: "wait" }); return; }
      pending.dispatched = true;
      if (pending.kind === "commit") {
        const c = pending.commit!;
        respond(response, { schemaVersion: 1, action: "commit", requestId: pending.id, markerPath: c.markerPath,
          markerSha256: c.markerSha256, markerIdentity: c.markerIdentity, commitKey: c.commitKey });
      } else respond(response, { schemaVersion: 1, action: "check", requestId: pending.id });
      return;
    }
    if (pending && request.url === `/commit-check/${pending.id}` && pending.kind === "commit") {
      try { checkBinding(); if ((pending.commit!.checkAuthority as () => unknown)() !== undefined) throw new Error();
        respond(response, { schemaVersion: 1, accepted: true }); }
      catch { respond(response, {}, 409); }
      return;
    }
    if (pending && (request.url === `/ok/${pending.id}` || request.url === `/failed/${pending.id}`)) {
      const item = pending; pending = undefined; item.resolve(request.url === `/ok/${item.id}`);
      respond(response, { schemaVersion: 1, accepted: true }); return;
    }
    respond(response, {}, 409);
  });
  await new Promise<void>((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", () => { server.off("error", reject); resolve(); }); });
  const address = server.address();
  if (!address || typeof address === "string") { server.close(); throw new Error("PREHOST_RECOVERY_UNAVAILABLE"); }
  mkdirSync(input.runtimeRoot, { recursive: true });
  const directory = mkdtempSync(join(input.runtimeRoot, "recovery-"));
  const allowed = new Set(["SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "SYSTEMDRIVE", "TEMP", "TMP"]);
  const env = Object.fromEntries(Object.entries(input.env).filter(([key]) => allowed.has(key.toUpperCase())));
  Object.assign(env, { VIBELUTION_PREHOST_RECOVERY_URL: `http://127.0.0.1:${address.port}`,
    VIBELUTION_PREHOST_RECOVERY_TOKEN: secret, PYTHONDONTWRITEBYTECODE: "1", PYTHONIOENCODING: "utf-8" });
  let job: WorkbenchJobHandle, validPid = false;
  try {
    checkBinding();
    const spawned = native.spawn({ executable: resolveNoConsolePython(input.pythonPath),
      arguments: [...input.pythonArguments, join(input.sourceRoot, "scripts", "assistant_prehost_recovery_verifier.py")],
      cwd: input.sourceRoot, env, stdoutPath: join(directory, "stdout.log"), stderrPath: join(directory, "stderr.log"),
      containDescendants: true, maxLogBytes: 65536 });
    job = spawned.job;
    validPid = Number.isSafeInteger(spawned.pid) && spawned.pid > 0;
  } catch (error) { closed = true; server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); throw error; }
  const revoke = () => { closing = true; pending?.resolve(false); pending = undefined; };
  projectSeal.signal.addEventListener("abort", revoke, { once: true });
  if (projectSeal.signal.aborted || !validPid) revoke();
  const done = (async () => {
    while (!drained) {
      try { const status = drainStatus(job); const exit = exitCode(job);
        drained = native.activeCount(job) === 0 && exit !== null && status.complete;
        if (drained) drainHealthy = exit === 0 && status.channels.length === 2
          && new Set(status.channels.map(channel => channel.stream)).size === 2
          && status.channels.every(channel => channel.complete && channel.errorCode === 0
            && channel.droppedBytes === 0 && channel.rotations === 0); }
      catch { /* Preserve the original Job until inspection succeeds. */ }
      if (!drained) await new Promise<void>(resolve => setTimeout(resolve, 100));
    }
    resolveReady(false); pending?.resolve(false); pending = undefined;
  })();
  const release = async () => {
    closing = true; pending?.resolve(false); pending = undefined;
    await done;
    if (closed) { if (!drainHealthy) throw new PrehostRecoveryDrainedUnknown(); return; }
    closed = true; projectSeal.signal.removeEventListener("abort", revoke);
    native.close(job); server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    if (!drainHealthy) throw new PrehostRecoveryDrainedUnknown();
  };
  if (!await readyPromise) { await release(); return null; }
  const request = async (kind: "check" | "commit", commit?: Commit): Promise<boolean> => {
    try {
      checkBinding();
      if (!ready || closing || drained || pending || exitCode(job) !== null || native.activeCount(job) < 1) return false;
      if (kind === "commit" && (!commit || !isAbsolute(commit.markerPath)
          || !/^[a-f0-9]{64}$/.test(commit.markerSha256)
          || commit.commitKey !== createHash("sha256").update(`Vibelution.PrehostCommit.v1\0${commit.markerSha256}`, "ascii").digest("hex")
          || typeof commit.checkAuthority !== "function")) return false;
      const id = randomBytes(16).toString("hex");
      const result = await new Promise<boolean>(resolve => { pending = { id, kind, dispatched: false, commit, resolve }; });
      checkBinding();
      return result && !closing && !drained && exitCode(job) === null && native.activeCount(job) > 0;
    } catch { return false; }
  };
  return Object.freeze({ check: () => request("check"), verifyReceipt: () => request("check"),
    commitMarker: (commit: Commit) => request("commit", commit), release });
}
