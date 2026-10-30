import { createHash } from "node:crypto";
import { open, stat } from "node:fs/promises";
import { isAbsolute, join, toNamespacedPath } from "node:path";
import { Worker } from "node:worker_threads";

const SHA256 = /^[0-9a-f]{64}$/;
const PYTHON_VERSION = /^3\.\d+\.\d+$/;
const HASH_TIMEOUT_MS = 120_000;
const EVIDENCE_HASHES = ["manifestSha256", "contentSha256", "sourceContentSha256", "runtimeContentSha256", "requirementsSha256", "contractsSha256"] as const;

export type AssistantPayloadEvidence = {
  manifestSha256: string;
  contentSha256: string;
  sourceContentSha256: string;
  runtimeContentSha256: string;
  requirementsSha256: string;
  /** Sealed hash of source/core/external_agent/contracts.py: the packaged wire-contract identity. */
  contractsSha256: string;
  pythonVersion: string;
};

export type AssistantResources = {
  sourceRoot: string;
  pythonPath: string;
  env: NodeJS.ProcessEnv;
  pythonArguments: string[];
  payloadRoot: string | null;
  payloadEvidence: AssistantPayloadEvidence | null;
};

export type AssistantResourcesInput = {
  packaged: boolean;
  resourcesRoot: string;
  developmentSourceRoot: string;
  developmentPythonPath: string;
  env: NodeJS.ProcessEnv;
  /** Tests may hash small fixture trees inline; production always uses a Worker. */
  hashTree?: (root: string) => Promise<string>;
};

export class AssistantResourceError extends Error {
  constructor(readonly boundedCode: string) {
    super(boundedCode);
    this.name = "AssistantResourceError";
  }
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function cleanEnvironment(env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  return Object.fromEntries(Object.entries(env).filter(([key]) => !/^PYTHON(?:PATH|HOME)$/i.test(key)));
}

async function readBoundedBytes(path: string, maximum: number, boundedCode: string): Promise<Buffer> {
  const file = await open(path, "r");
  try {
    const info = await file.stat();
    if (!info.isFile() || !Number.isSafeInteger(info.size) || info.size < 1 || info.size > maximum) {
      throw new AssistantResourceError(boundedCode);
    }
    // One extra byte detects a growing input without an unbounded readFile().
    const bytes = Buffer.alloc(info.size + 1);
    let offset = 0;
    while (offset < bytes.byteLength) {
      const part = await file.read(bytes, offset, bytes.byteLength - offset, offset);
      if (!part.bytesRead) break;
      offset += part.bytesRead;
    }
    if (offset !== info.size) throw new AssistantResourceError(boundedCode);
    return bytes.subarray(0, offset);
  } finally {
    await file.close();
  }
}

function parseObject(bytes: Buffer, boundedCode: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(bytes.toString("utf8"));
    if (object(value)) return value;
  } catch { /* Only the fixed error code may cross the resource boundary. */ }
  throw new AssistantResourceError(boundedCode);
}

function payloadEvidence(value: unknown): AssistantPayloadEvidence {
  if (!object(value) || EVIDENCE_HASHES.some(field => typeof value[field] !== "string" || !SHA256.test(value[field] as string))
    || typeof value.pythonVersion !== "string" || value.pythonVersion.length > 32 || !PYTHON_VERSION.test(value.pythonVersion)) {
    throw new AssistantResourceError("ASSISTANT_PROVENANCE_INVALID");
  }
  return {
    manifestSha256: value.manifestSha256 as string, contentSha256: value.contentSha256 as string,
    sourceContentSha256: value.sourceContentSha256 as string, runtimeContentSha256: value.runtimeContentSha256 as string,
    requirementsSha256: value.requirementsSha256 as string, contractsSha256: value.contractsSha256 as string,
    pythonVersion: value.pythonVersion,
  };
}

function validateManifest(manifest: Record<string, unknown>, evidence: AssistantPayloadEvidence): void {
  const machines: Record<string, string[]> = { x64: ["amd64", "x86_64", "x64"], arm64: ["arm64", "aarch64"], ia32: ["x86", "i386", "i686"] };
  const [major, minor] = evidence.pythonVersion.split(".");
  if (manifest.schemaVersion !== 1 || manifest.protocolVersion !== 1
    || process.platform !== "win32" || manifest.platform !== "win32"
    || typeof manifest.machine !== "string" || !machines[process.arch]?.includes(manifest.machine.toLowerCase())
    || manifest.pythonVersion !== evidence.pythonVersion || manifest.pythonAbi !== `cp${major}${minor}`
    || manifest.entrypoint !== "source/scripts/assistant_host.py" || manifest.pythonEntrypoint !== "python/pythonw.exe"
    || manifest.sourceContentSha256 !== evidence.sourceContentSha256 || manifest.runtimeContentSha256 !== evidence.runtimeContentSha256
    || manifest.requirementsSha256 !== evidence.requirementsSha256 || manifest.contractsSha256 !== evidence.contractsSha256) {
    throw new AssistantResourceError("ASSISTANT_MANIFEST_INVALID");
  }
}

function hashTreeInWorker(root: string): Promise<string> {
  return new Promise((resolveHash, rejectHash) => {
    const worker = new Worker(new URL("./assistantPayloadHashWorker.js", import.meta.url), { workerData: root });
    let settled = false;
    const finish = (digest?: string): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      void worker.terminate().catch(() => undefined);
      if (digest && SHA256.test(digest)) resolveHash(digest);
      else rejectHash(new AssistantResourceError("ASSISTANT_PAYLOAD_HASH_FAILED"));
    };
    const timer = setTimeout(() => finish(), HASH_TIMEOUT_MS);
    worker.once("message", (message: unknown) => {
      finish(object(message) && message.ok === true && typeof message.sha256 === "string" ? message.sha256 : undefined);
    });
    worker.once("error", () => finish());
    worker.once("exit", () => finish());
  });
}

/** Resolve verified package bytes; a failed packaged lookup never uses checkout resources. */
export async function resolveAssistantResources(input: AssistantResourcesInput): Promise<AssistantResources> {
  try {
    const env = cleanEnvironment(input.env);
    if (!input.packaged) {
      if (!isAbsolute(input.developmentSourceRoot) || !isAbsolute(input.developmentPythonPath)) {
        throw new AssistantResourceError("ASSISTANT_RESOURCE_UNAVAILABLE");
      }
      return { sourceRoot: input.developmentSourceRoot, pythonPath: input.developmentPythonPath, env,
        pythonArguments: [], payloadRoot: null, payloadEvidence: null };
    }
    if (!isAbsolute(input.resourcesRoot)) throw new AssistantResourceError("ASSISTANT_RESOURCE_UNAVAILABLE");
    const payloadRoot = toNamespacedPath(join(input.resourcesRoot, "launcher-assistant"));
    const provenancePath = toNamespacedPath(join(input.resourcesRoot, "app.asar.unpacked", "package-provenance.json"));
    const provenance = parseObject(await readBoundedBytes(provenancePath, 256 * 1024, "ASSISTANT_PROVENANCE_INVALID"), "ASSISTANT_PROVENANCE_INVALID");
    const evidence = payloadEvidence(provenance.assistant);
    const manifestBytes = await readBoundedBytes(join(payloadRoot, "manifest.json"), 32 * 1024 * 1024, "ASSISTANT_MANIFEST_INVALID");
    if (createHash("sha256").update(manifestBytes).digest("hex") !== evidence.manifestSha256) {
      throw new AssistantResourceError("ASSISTANT_MANIFEST_INVALID");
    }
    validateManifest(parseObject(manifestBytes, "ASSISTANT_MANIFEST_INVALID"), evidence);
    const sourceRoot = join(payloadRoot, "source");
    const pythonPath = join(payloadRoot, "python", "pythonw.exe");
    if (!(await stat(sourceRoot)).isDirectory() || !(await stat(join(sourceRoot, "scripts", "assistant_host.py"))).isFile()
      || !(await stat(pythonPath)).isFile()) throw new AssistantResourceError("ASSISTANT_RESOURCE_UNAVAILABLE");
    let contentSha256: string;
    try {
      contentSha256 = await (input.hashTree ?? hashTreeInWorker)(payloadRoot);
      if (!SHA256.test(contentSha256)) throw new Error("invalid digest");
    } catch { throw new AssistantResourceError("ASSISTANT_PAYLOAD_HASH_FAILED"); }
    if (contentSha256 !== evidence.contentSha256) throw new AssistantResourceError("ASSISTANT_PAYLOAD_INTEGRITY_FAILED");
    return { sourceRoot, pythonPath, env, pythonArguments: ["-I", "-B", "-X", "utf8"], payloadRoot, payloadEvidence: evidence };
  } catch (error) {
    if (error instanceof AssistantResourceError) throw error;
    throw new AssistantResourceError("ASSISTANT_RESOURCE_UNAVAILABLE");
  }
}
