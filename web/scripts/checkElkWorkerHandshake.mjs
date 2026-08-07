/**
 * T1 test-only Browser handshake check for the production ELK Worker engine.
 *
 * Repo-committable replacement for the throwaway headless runners: it proves
 * against the real production worker asset that
 *   1. the `?worker` build emits exactly one `elk-worker.min-*.js` asset that
 *      fits its dedicated bundle budget (checkBundleBudget, expectElkWorker);
 *   2. a real browser loads the asset, runs a minimal compound layout, gets
 *      node coordinates, edge sections and edge-label coordinates;
 *   3. exactly one Worker is constructed, `terminate()` is invoked, and no
 *      second Worker appears after terminate (no fallback to bundled ELK).
 *
 * The probe page POSTs its machine-readable report back to `/__handshake_result`
 * (real async timing; `--dump-dom` cannot wait for Worker replies).
 *
 * Uses only `node:http` + `vite build --outDir dist-probe` (probe entry is
 * enabled by VIBELUTION_PROBE_BUILD=1). All child processes are spawned with
 * CREATE_NO_WINDOW semantics (windowsHide) so nothing opens a visible
 * console, per AGENTS.md §2.0.
 *
 * Exit code: 0 on success, 1 on any failure (build, budget, browser, report).
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync, readFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { checkBundleBudget } from "./checkBundleBudget.mjs";

const webRoot = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");
const distProbe = join(webRoot, "dist-probe");
const PROBE_PAGE = "/probes/workflow-elk-handshake.html";

const EDGE_CANDIDATES = [
  process.env.VIBELUTION_EDGE_PATH ?? "",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
].filter(Boolean);

function edgeExecutable() {
  return EDGE_CANDIDATES.find((candidate) => existsSync(candidate)) ?? null;
}

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".wasm": "application/wasm",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};

function serve(distDir, onResult) {
  return new Promise((resolveServer, rejectServer) => {
    const server = createServer((req, res) => {
      if (req.method === "POST" && req.url === "/__handshake_result") {
        const chunks = [];
        req.on("data", (chunk) => chunks.push(chunk));
        req.on("end", () => {
          let body = Buffer.concat(chunks).toString("utf-8");
          try {
            body = JSON.parse(body);
          } catch {
            // Keep the raw text; the reporter will fail the gate on shape.
          }
          onResult(body);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end("{}");
        });
        return;
      }
      const pathname = decodeURIComponent((req.url ?? "/").split("?")[0]);
      const filePath = join(distDir, pathname === "/" ? "index.html" : pathname);
      if (!filePath.startsWith(distDir) || !existsSync(filePath)) {
        res.writeHead(404);
        res.end("not found");
        return;
      }
      const type = MIME[extname(filePath).toLowerCase()] ?? "application/octet-stream";
      res.writeHead(200, { "Content-Type": type });
      res.end(readFileSync(filePath));
    });
    server.on("error", rejectServer);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      resolveServer({ server, port: typeof address === "object" && address ? address.port : 0 });
    });
  });
}

function runViteProbeBuild() {
  const viteBin = join(webRoot, "node_modules", "vite", "bin", "vite.js");
  if (!existsSync(viteBin)) {
    throw new Error(`vite bin not found: ${viteBin}`);
  }
  const result = spawnSync(
    process.execPath,
    [viteBin, "build", "--outDir", "dist-probe", "--emptyOutDir"],
    {
      cwd: webRoot,
      env: { ...process.env, VIBELUTION_PROBE_BUILD: "1" },
      windowsHide: true,
      encoding: "utf-8",
      timeout: 180_000,
    },
  );
  if (result.status !== 0) {
    const tail = (result.stdout + result.stderr).trim().split(/\r?\n/).slice(-40).join("\n");
    throw new Error(`vite probe build failed (exit ${result.status ?? "killed"}):\n${tail}`);
  }
  return (result.stdout + result.stderr).trim();
}

function runEdge(executable, url, profileDir) {
  return spawn(
    executable,
    [
      "--headless=new",
      "--disable-gpu",
      "--no-sandbox",
      "--disable-background-timer-throttling",
      `--user-data-dir=${profileDir}`,
      url,
    ],
    { windowsHide: true, stdio: "ignore" },
  );
}

export function validateReport(report) {
  if (!report || typeof report !== "object") {
    return "missing handshake report";
  }
  if (report.ok !== true) {
    return `probe reported ok=false: ${JSON.stringify(report.errors ?? [])}`;
  }
  const required = [
    "workerUrl",
    "worker.constructCount === 1",
    "worker.terminateCount >= 1",
    "!worker.constructedAfterTerminate",
    "worker.urlMatchesWorkerAsset",
    "engine.haveNodeCoordinates",
    "engine.haveEdgeSections",
    "engine.edgeLabelHaveCoordinates",
    "!fallbackBundledDetected",
    "afterTerminateBehavior !== 'still-resolved'",
  ];
  const workerOk =
    typeof report.workerUrl === "string" &&
    report.worker.constructCount === 1 &&
    report.worker.terminateCount >= 1 &&
    report.worker.constructedAfterTerminate !== true &&
    report.worker.urlMatchesWorkerAsset === true;
  const engineOk =
    report.engine.haveNodeCoordinates === true &&
    report.engine.haveEdgeSections === true &&
    report.engine.edgeLabelHaveCoordinates === true;
  const lifecycleOk =
    report.fallbackBundledDetected !== true &&
    report.afterTerminateBehavior !== "still-resolved";
  if (!workerOk || !engineOk || !lifecycleOk) {
    return `report did not satisfy gate (${required.join(", ")}): ${JSON.stringify(report)}`;
  }
  return null;
}

async function main() {
  const edge = edgeExecutable();
  if (!edge) {
    console.error("checkElkWorkerHandshake: Edge not found; set VIBELUTION_EDGE_PATH.");
    return false;
  }

  let serverHandle;
  let edgeChild;
  const profileDir = join(tmpdir(), `vibelution-elk-handshake-${process.pid}`);
  try {
    rmSync(distProbe, { recursive: true, force: true });
    console.log("checkElkWorkerHandshake: building probe dist (dist-probe/) ...");
    const buildLog = runViteProbeBuild();
    const buildTail = buildLog.split(/\r?\n/).filter((line) => line.includes("elk-worker")).join("\n");
    console.log(buildTail ? `  worker asset line:\n${buildTail}` : "  (no explicit worker line in build log)");

    const budget = checkBundleBudget(join(distProbe, "assets"), { expectElkWorker: true });
    if (budget.failures.length > 0) {
      throw new Error(
        `probe bundle budget failed: ${budget.failures
          .map((failure) => `${failure.name}: ${failure.bytes} > ${failure.maxBytes}`)
          .join("; ")}`,
      );
    }
    console.log(`  budget ok, ELK worker asset: ${budget.elkWorker.assets.join(", ")}`);

    let report = null;
    await new Promise((resolveResult, rejectResult) => {
      const timer = setTimeout(
        () => rejectResult(new Error("handshake timed out waiting for POST /__handshake_result")),
        120_000,
      );
      serve(distProbe, (payload) => {
        report = payload;
        clearTimeout(timer);
        resolveResult();
      }).then(({ server, port }) => {
        serverHandle = server;
        const url = `http://127.0.0.1:${port}${PROBE_PAGE}`;
        console.log(`  serving ${url}`);
        edgeChild = runEdge(edge, url, profileDir);
      }, rejectResult);
    });

    const failure = validateReport(report);
    if (failure) {
      console.error(`checkElkWorkerHandshake FAILED: ${failure}`);
      return false;
    }
    console.log(
      `checkElkWorkerHandshake OK: workerUrl=${report.workerUrl} constructCount=${report.worker.constructCount} terminateCount=${report.worker.terminateCount} nodeCount=${report.engine.nodeCount} edgeCount=${report.engine.edgeCount}`,
    );
    return true;
  } catch (error) {
    console.error(`checkElkWorkerHandshake FAILED: ${error.message}`);
    return false;
  } finally {
    if (edgeChild && !edgeChild.killed) {
      edgeChild.kill();
    }
    if (edgeChild && typeof edgeChild.exitCode !== "number") {
      await new Promise((resolveExit) => edgeChild.once("exit", resolveExit));
    }
    if (serverHandle) {
      await new Promise((resolveClose) => serverHandle.close(resolveClose));
    }
    // Headless Edge keeps child processes alive briefly; retry the cleanup.
    const cleanup = (target) => {
      try {
        rmSync(target, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 });
      } catch {
        // Temp/profile leftovers are harmless and do not fail the gate.
      }
    };
    cleanup(profileDir);
    cleanup(distProbe);
  }
}

const isMain =
  process.argv[1] && (import.meta.url === new URL(`file://${process.argv[1].replace(/\\/g, "/")}`).href);

if (isMain) {
  const passed = await main();
  process.exitCode = passed ? 0 : 1;
}

export { main };
