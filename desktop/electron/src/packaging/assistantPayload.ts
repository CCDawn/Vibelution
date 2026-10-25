import { createHash } from "node:crypto";
import { lstatSync, readFileSync } from "node:fs";
import { join, resolve, toNamespacedPath } from "node:path";
import type { AssistantPayloadEvidence } from "../assistant/assistantResources.js";
import { sha256DirectoryTree } from "./frontendBundle.js";
import { assertAssistantPayloadEvidence } from "./packageProvenance.js";

/** Python owns dependency/RECORD validation; Node binds the exact copied tree. */
export function readAssistantPayloadEvidence(payloadRoot: string, expectedManifestSha256: string): AssistantPayloadEvidence {
  const root = toNamespacedPath(resolve(payloadRoot));
  const info = lstatSync(root);
  if (info.isSymbolicLink() || !info.isDirectory()) throw new Error("Assistant payload directory is invalid.");
  const manifestPath = join(root, "manifest.json");
  const manifestInfo = lstatSync(manifestPath);
  if (!manifestInfo.isFile() || manifestInfo.isSymbolicLink() || manifestInfo.size > 32 * 1024 * 1024) {
    throw new Error("Assistant payload manifest is invalid.");
  }
  const bytes = readFileSync(manifestPath);
  const manifestSha256 = createHash("sha256").update(bytes).digest("hex");
  if (!/^[0-9a-f]{64}$/.test(expectedManifestSha256) || manifestSha256 !== expectedManifestSha256) {
    throw new Error("Assistant payload manifest changed after its owned build.");
  }
  const manifest: unknown = JSON.parse(bytes.toString("utf8"));
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) throw new Error("Assistant manifest must be an object.");
  const data = manifest as Record<string, unknown>;
  const evidence = {
    manifestSha256, contentSha256: sha256DirectoryTree(root), sourceContentSha256: data.sourceContentSha256,
    runtimeContentSha256: data.runtimeContentSha256, requirementsSha256: data.requirementsSha256, pythonVersion: data.pythonVersion,
  };
  assertAssistantPayloadEvidence(evidence);
  return evidence;
}
