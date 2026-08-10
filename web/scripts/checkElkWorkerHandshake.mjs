/**
 * Builds a test-only entry and verifies the emitted ELK Worker in headless
 * Edge. The only child process is Edge and it is always hidden on Windows.
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { checkBundleBudget } from "./checkBundleBudget.mjs";

const webRoot = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");
const probeDist = join(webRoot, "dist-probe");
const probePath = "/probes/workflow-elk-handshake.html";
const buildOnly = process.argv.includes("--build-only");
const edgeCandidates = [
  process.env.VIBELUTION_EDGE_PATH ?? "",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
].filter(Boolean);
const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};

function findEdge() {
  return edgeCandidates.find((candidate) => existsSync(candidate)) ?? null;
}

function buildProbe() {
  const vite = join(webRoot, "node_modules", "vite", "bin", "vite.js");
  if (!existsSync(vite)) {
    throw new Error("vite executable is missing: " + vite);
  }
  rmSync(probeDist, { recursive: true, force: true });
  const result = spawnSync(
    process.execPath,
    [vite, "build", "--config", "vite.config.ts", "--outDir", "dist-probe", "--emptyOutDir"],
    {
      cwd: webRoot,
      env: { ...process.env, VIBELUTION_PROBE_BUILD: "1" },
      encoding: "utf8",
      timeout: 180000,
      windowsHide: true,
    },
  );
  if (result.status !== 0) {
    const output = String(result.stdout ?? "") + String(result.stderr ?? "");
    throw new Error("Vite probe build failed:\n" + output.split(/\r?\n/).slice(-40).join("\n"));
  }
  const budget = checkBundleBudget(join(probeDist, "assets"), { expectElkWorker: true });
  if (budget.failures.length > 0) {
    throw new Error(
      "Probe bundle budget failed: " + budget.failures.map((failure) => failure.name).join(", "),
    );
  }
  return budget.elkWorker.assets;
}

function startServer(onReport) {
  return new Promise((resolveServer, rejectServer) => {
    const server = createServer((request, response) => {
      if (request.method === "POST" && request.url === "/__handshake_result") {
        const chunks = [];
        request.on("data", (chunk) => chunks.push(chunk));
        request.on("end", () => {
          try {
            onReport(JSON.parse(Buffer.concat(chunks).toString("utf8")));
          } catch {
            onReport(null);
          }
          response.writeHead(204);
          response.end();
        });
        return;
      }
      const requestPath = decodeURIComponent((request.url ?? "/").split("?")[0]);
      const filePath = resolve(probeDist, "." + (requestPath === "/" ? "/index.html" : requestPath));
      if (!filePath.startsWith(probeDist + sep) || !existsSync(filePath)) {
        response.writeHead(404);
        response.end("not found");
        return;
      }
      response.writeHead(200, {
        "Content-Type": mimeTypes[extname(filePath).toLowerCase()] ?? "application/octet-stream",
      });
      response.end(readFileSync(filePath));
    });
    server.once("error", rejectServer);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      resolveServer({ server, port: typeof address === "object" && address ? address.port : 0 });
    });
  });
}

function validate(report) {
  if (!report || report.ok !== true) return "probe did not report success";
  const worker = report.worker ?? {};
  const engine = report.engine ?? {};
  if (
    typeof report.workerUrl !== "string" ||
    worker.constructCount !== 1 ||
    worker.terminateCount < 1 ||
    worker.constructedAfterTerminate === true ||
    worker.urlMatchesWorkerAsset !== true ||
    engine.haveNodeCoordinates !== true ||
    engine.haveEdgeSections !== true ||
    engine.edgeLabelHaveCoordinates !== true ||
    report.fallbackBundledDetected === true ||
    report.afterTerminateBehavior === "still-resolved"
  ) {
    return "probe contract failed: " + JSON.stringify(report);
  }
  return null;
}

async function main() {
  let server;
  let profile;
  let edgeChild;
  try {
    const workerAssets = buildProbe();
    if (buildOnly) {
      console.log("ELK Worker probe build passed: " + workerAssets.join(", "));
      return true;
    }
    const edge = findEdge();
    if (!edge) throw new Error("Microsoft Edge was not found; set VIBELUTION_EDGE_PATH.");
    profile = join(tmpdir(), "vibelution-elk-handshake-" + process.pid);
    const report = await new Promise((resolveReport, rejectReport) => {
      const timer = setTimeout(
        () => rejectReport(new Error("timed out waiting for ELK Worker handshake")),
        45000,
      );
      startServer((payload) => {
        clearTimeout(timer);
        resolveReport(payload);
      }).then(
        (handle) => {
          server = handle.server;
          const url = "http://127.0.0.1:" + handle.port + probePath;
          edgeChild = spawn(
            edge,
            [
              "--headless=new",
              "--disable-gpu",
              "--no-sandbox",
              "--disable-background-timer-throttling",
              "--user-data-dir=" + profile,
              url,
            ],
            { windowsHide: true, stdio: "ignore" },
          );
          edgeChild.once("error", rejectReport);
        },
        rejectReport,
      );
    });
    const failure = validate(report);
    if (failure) throw new Error(failure);
    console.log("ELK Worker browser handshake passed.");
    return true;
  } catch (error) {
    console.error(
      "ELK Worker browser handshake failed: " + String(error instanceof Error ? error.message : error),
    );
    return false;
  } finally {
    if (edgeChild && edgeChild.exitCode === null && !edgeChild.killed) {
      edgeChild.kill();
      await Promise.race([
        new Promise((resolveExit) => edgeChild.once("exit", resolveExit)),
        new Promise((resolveTimeout) => setTimeout(resolveTimeout, 3000)),
      ]);
    }
    if (server) await new Promise((resolveClose) => server.close(resolveClose));
    if (profile) rmSync(profile, { recursive: true, force: true, maxRetries: 8, retryDelay: 250 });
    if (!buildOnly) rmSync(probeDist, { recursive: true, force: true });
  }
}

const passed = await main();
process.exitCode = passed ? 0 : 1;
