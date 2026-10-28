import { mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";
import { expect, it } from "vitest";
import { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";

const addon = process.env.VIBELUTION_MUTEX_TEST_ADDON, python = process.env.VIBELUTION_TEST_PYTHONW;
it.skipIf(process.platform !== "win32" || !addon || !python).each(["inventory", "admission"])("orders real cross-process %s revocation after the captured Job drains", async reason => {
  const root = realpathSync.native(mkdtempSync(join(tmpdir(), "assistant-recovery-gate-")));
  const project = join(root, "project"), integration = join(root, "integration"), registry = join(root, "registry", "projects.json");
  for (const path of [project, integration]) { mkdirSync(join(path, ".vibelution"), { recursive: true });
    writeFileSync(join(path, ".vibelution", "project.json"), JSON.stringify({ projectId: "project" })); }
  const payload = { schemaVersion: 1, integrationRoot: integration, items: [{ id: "source", path: project, checkedOut: true }] };
  const original = new AssistantProjectRegistryConnection(registry);
  const native = createRequire(import.meta.url)(addon!);
  let job: object | undefined, ready = false, drained = false;
  const resume = join(root, "resume"), started = join(root, "started");
  const deadline = async (predicate: () => boolean) => {
    const until = Date.now() + 12000;
    while (!predicate()) { if (Date.now() > until) throw new Error("fixture timed out"); await new Promise(resolveDelay => setTimeout(resolveDelay, 20)); }
  };
  try {
    await original.reconcile(payload);
    const id = Object.keys(original.snapshot().projects)[0], operationId = "initial-" + "d".repeat(40);
    await original.withPreHostSource(id, lease => lease.commit(async () => "unknown"), { operationId, receiptConfirmed: () => false });
    // Read the newly published marker in a fresh registry connection.
    const owner = new AssistantProjectRegistryConnection(registry, { acquireRecoveryCommitGate: key => {
      const acquired = native.tryAcquireReminderMutex(key); if (!acquired) return null;
      let held = true;
      return { abandoned: acquired.abandoned, check: () => { if (!held) throw new Error("released"); },
        release: () => { native.releaseReminderMutex(acquired.handle); held = false; } };
    } });
    await owner.reconcile(payload);
    const source = async () => ({ check: async () => true, verifyReceipt: async () => true,
      commitMarker: async ({ commitKey }: { commitKey: string }) => {
        const code = `import pathlib,sys,time\nsys.path.insert(0,sys.argv[1])\nfrom core.infrastructure.reminder_source_mutex import _try_digest\nlease=_try_digest(sys.argv[2])\nassert lease is not None\npathlib.Path(sys.argv[3]).write_text('ready')\nuntil=time.monotonic()+10\nwhile not pathlib.Path(sys.argv[4]).exists() and time.monotonic()<until: time.sleep(.02)\nlease.release()\n`;
        const child = native.spawn({ executable: python!, arguments: ["-B", "-c", code, resolve("../.."), commitKey, started, resume],
          cwd: resolve("../.."), env: Object.fromEntries(Object.entries(process.env)
            .filter(([key]) => ["SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "SYSTEMDRIVE", "TEMP", "TMP"].includes(key.toUpperCase()))), stdoutPath: join(root, "stdout.log"), stderrPath: join(root, "stderr.log"),
          containDescendants: true, maxLogBytes: 65536 });
        job = child.job; await deadline(() => existsSync(started)); ready = true;
        await deadline(() => native.exitCode(job) !== null && native.activeCount(job) === 0 && native.drainStatus(job).complete);
        expect(native.exitCode(job)).toBe(0);
        const output = native.drainStatus(job);
        expect(output.channels).toHaveLength(2);
        expect(output.channels.every((channel: { complete: boolean; errorCode: number; droppedBytes: number }) =>
          channel.complete && channel.errorCode === 0 && channel.droppedBytes === 0)).toBe(true);
        drained = true; return false;
      }, release: async () => { if (job) { await deadline(() => drained); native.close(job); job = undefined; } } });
    const work = owner.recoverPreHostSource(operationId, source);
    await deadline(() => ready);
    let reconciled = false;
    if (reason === "admission") owner.revokePreHostRecovery();
    const observation = owner.reconcile(payload).then(() => { reconciled = true; });
    await new Promise(resolveDelay => setTimeout(resolveDelay, 100));
    expect(reconciled).toBe(false);
    expect(drained).toBe(false);
    expect(existsSync(registry + ".prehost-recovery.json.revoked")).toBe(false);
    writeFileSync(resume, "go");
    expect(await work).toBe(false); await observation;
    expect(drained).toBe(true);
    expect(JSON.parse(readFileSync(registry + ".prehost-recovery.json.revoked", "utf8")).reason).toBe("revoked");
    const restarted = new AssistantProjectRegistryConnection(registry);
    await restarted.start((_snapshot, suspended) => { expect(suspended).toBe(true);
      return { start: async () => {}, stop: async () => {}, updateProjects: async () => {} }; });
    await restarted.stop(); await owner.stop(); await original.stop();
  } finally {
    if (!existsSync(resume)) writeFileSync(resume, "cleanup");
    if (job) { await deadline(() => native.exitCode(job) !== null && native.activeCount(job) === 0 && native.drainStatus(job).complete); native.close(job); }
    rmSync(root, { recursive: true, force: true });
  }
}, 30000);
