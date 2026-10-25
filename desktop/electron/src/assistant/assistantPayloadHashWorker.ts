import { isAbsolute } from "node:path";
import { parentPort, workerData } from "node:worker_threads";
import { sha256DirectoryTree } from "../packaging/frontendBundle.js";

if (!parentPort) throw new Error("ASSISTANT_PAYLOAD_HASH_FAILED");
try {
  if (typeof workerData !== "string" || !isAbsolute(workerData)) throw new Error("invalid root");
  parentPort.postMessage({ ok: true, sha256: sha256DirectoryTree(workerData) });
} catch {
  // Never serialize native filesystem errors, package paths, or environment values.
  parentPort.postMessage({ ok: false });
}
