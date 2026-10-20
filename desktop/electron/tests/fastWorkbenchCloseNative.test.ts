import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { createConnection } from "node:net";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { closeOwnedWorkbenchFast } from "../src/process/fastWorkbenchClose.js";
import {
  __setWorkbenchJobNativeForTests,
  hasTrackedWorkbenchJob,
  spawnTrackedWorkbenchProcess,
  terminateTrackedWorkbenchJob
} from "../src/process/workbenchJob.js";

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error: unknown) {
    if ((error as NodeJS.ErrnoException).code === "ESRCH") return false;
    throw error;
  }
}

async function portListening(port: number): Promise<boolean> {
  return await new Promise((resolve) => {
    const socket = createConnection({ host: "127.0.0.1", port });
    const finish = (listening: boolean) => { socket.destroy(); resolve(listening); };
    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
    socket.setTimeout(100, () => finish(false));
  });
}

async function readReady(path: string): Promise<{ pid: number; childPid?: number; port?: number }> {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    if (existsSync(path)) {
      try { return JSON.parse(readFileSync(path, "utf8")); } catch { /* A readiness write may still be completing. */ }
    }
    await sleep(25);
  }
  throw new Error(`Controlled native fixture did not become ready: ${path}`);
}

// Controlled local processes only: no product runtime, model, or external service.
describe.skipIf(process.platform !== "win32")("native fast close with a busy child and wedged HTTP", () => {
  it.each([1, 2, 3])("retires the real captured Windows Job within two seconds, repeat %s", async (repeat) => {
    const temporaryRoot = realpathSync(tmpdir());
    const directory = mkdtempSync(join(temporaryRoot, "vibelution-fast-close-native-"));
    let rootPid: number | undefined;
    try {
      writeFileSync(join(directory, "child.cjs"), `
        require("node:fs").writeFileSync(process.argv[2], JSON.stringify({ pid: process.pid }));
        while (true) { Math.sqrt(Math.random()); }
      `);
      writeFileSync(join(directory, "root.cjs"), `
        const fs = require("node:fs");
        const path = require("node:path");
        const directory = process.argv[2];
        const child = require("node:child_process").spawn(process.execPath, [
          path.join(directory, "child.cjs"), path.join(directory, "child-ready.json")
        ], { windowsHide: true, stdio: "ignore" });
        child.once("error", (error) => { console.error(error); process.exit(1); });
        const server = require("node:http").createServer((request, _response) => {
          fs.appendFileSync(path.join(directory, "http-requests.log"), request.method + " " + request.url + "\\n");
          // Accept requests but never send headers or a body: graceful HTTP is wedged.
        });
        server.listen(0, "127.0.0.1", () => fs.writeFileSync(
          path.join(directory, "root-ready.json"),
          JSON.stringify({ pid: process.pid, childPid: child.pid, port: server.address().port })
        ));
      `);
      rootPid = spawnTrackedWorkbenchProcess(directory, {
        executable: process.execPath,
        arguments: [join(directory, "root.cjs"), directory],
        cwd: directory,
        env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" },
        stdoutPath: join(directory, "stdout.log"),
        stderrPath: join(directory, "stderr.log")
      }).pid;
      const root = await readReady(join(directory, "root-ready.json"));
      const child = await readReady(join(directory, "child-ready.json"));
      expect(root.pid).toBe(rootPid);
      expect(root.childPid).toBe(child.pid);
      expect(child.pid).toBeGreaterThan(0);
      expect(child.pid).not.toBe(rootPid);
      const port = root.port!;
      expect(Number.isInteger(port) && port > 0).toBe(true);
      expect(pidAlive(rootPid)).toBe(true);
      expect(pidAlive(child.pid)).toBe(true);
      expect(await portListening(port)).toBe(true);
      expect(hasTrackedWorkbenchJob(directory)).toBe(true);

      const requestedAt = Date.now();
      const started = performance.now();
      const closed = await closeOwnedWorkbenchFast({
        workspaceRoot: directory, spawnPid: rootPid, port,
        deadlineAt: requestedAt + 1800, forceAt: requestedAt + 1200
      });
      const rootStillAlive = pidAlive(rootPid);
      const childStillAlive = pidAlive(child.pid);
      const portStillListening = await portListening(port);
      const elapsedMs = performance.now() - started;
      console.info(`native fast close repeat ${repeat}: ${elapsedMs.toFixed(1)}ms; rootAlive=${rootStillAlive}; childAlive=${childStillAlive}; portListening=${portStillListening}`);
      expect(closed).toBe(true);
      expect(rootStillAlive).toBe(false);
      expect(childStillAlive).toBe(false);
      expect(portStillListening).toBe(false);
      expect(hasTrackedWorkbenchJob(directory)).toBe(false);
      expect(readFileSync(join(directory, "http-requests.log"), "utf8")).toContain("GET /api/health");
      expect(elapsedMs).toBeGreaterThanOrEqual(1150);
      expect(elapsedMs).toBeLessThan(2000);
    } finally {
      try {
        if (rootPid !== undefined) await terminateTrackedWorkbenchJob(directory, rootPid);
      } finally {
        __setWorkbenchJobNativeForTests(undefined);
        // Verify the resolved deletion target remains inside the OS temporary directory.
        const resolvedDirectory = realpathSync(directory);
        const withinTemporaryRoot = relative(temporaryRoot, resolvedDirectory);
        if (!withinTemporaryRoot || withinTemporaryRoot.startsWith("..") || isAbsolute(withinTemporaryRoot)) {
          throw new Error("Refusing native fixture cleanup outside its temporary directory");
        }
        rmSync(resolvedDirectory, { recursive: true, force: true });
      }
    }
  }, 20_000);
});
