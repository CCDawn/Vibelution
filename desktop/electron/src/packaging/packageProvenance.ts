import type { AssistantPayloadEvidence } from "../assistant/assistantResources.js";

export const DESKTOP_PACKAGE_PROVENANCE_FILE = "package-provenance.json";

const REQUIRED_LAUNCHER_CAPABILITIES = ["desktop_actions.claim", "workbench_close.transaction.v1"] as const;
const GIT_OBJECT_HASH = /^[0-9a-f]{40,64}$/i;
const SHA256_HASH = /^[0-9a-f]{64}$/i;

export type DesktopPackageProvenanceInput = {
  sourceCommit: string;
  electronTreeHash: string;
  frontendTreeHash: string;
  frontendContentSha256: string;
  frontendBuildKey: string;
  frontendSourceCommit: string;
  mainBundleSha256: string;
  preloadBundleSha256: string;
  builtAt: string;
  /** Development/unpackaged evidence may omit the resident runtime. */
  assistant?: AssistantPayloadEvidence;
};

export type DesktopPackageProvenance = DesktopPackageProvenanceInput & {
  schemaVersion: 1;
  protocolVersion: 1;
  capabilities: readonly string[];
};

export function createDesktopPackageProvenance(input: DesktopPackageProvenanceInput): DesktopPackageProvenance {
  assertGitObjectHash("sourceCommit", input.sourceCommit);
  assertGitObjectHash("electronTreeHash", input.electronTreeHash);
  assertGitObjectHash("frontendTreeHash", input.frontendTreeHash);
  assertGitObjectHash("frontendSourceCommit", input.frontendSourceCommit);
  assertSha256("frontendContentSha256", input.frontendContentSha256);
  if (!/^[0-9a-f]{64}$/i.test(input.frontendBuildKey)) {
    throw new Error("frontendBuildKey must be a SHA-256 build key");
  }
  assertSha256("mainBundleSha256", input.mainBundleSha256);
  assertSha256("preloadBundleSha256", input.preloadBundleSha256);
  if (input.assistant !== undefined) assertAssistantPayloadEvidence(input.assistant);
  if (Number.isNaN(Date.parse(input.builtAt))) {
    throw new Error("builtAt must be an ISO timestamp");
  }
  return {
    schemaVersion: 1,
    ...input,
    protocolVersion: 1,
    capabilities: REQUIRED_LAUNCHER_CAPABILITIES
  };
}

export function assertAssistantPayloadEvidence(value: unknown): asserts value is AssistantPayloadEvidence {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("assistant evidence must be an object");
  const evidence = value as Record<string, unknown>;
  for (const field of ["manifestSha256", "contentSha256", "sourceContentSha256", "runtimeContentSha256", "requirementsSha256"]) {
    if (typeof evidence[field] !== "string" || !/^[0-9a-f]{64}$/.test(evidence[field] as string)) {
      throw new Error(`assistant.${field} must be a SHA-256 hash`);
    }
  }
  if (typeof evidence.pythonVersion !== "string" || !/^3\.[0-9]+\.[0-9]+$/.test(evidence.pythonVersion)) {
    throw new Error("assistant.pythonVersion must be a complete CPython version");
  }
}

function assertGitObjectHash(field: string, value: string): void {
  if (!GIT_OBJECT_HASH.test(value)) {
    throw new Error(`${field} must be a Git object hash`);
  }
}

function assertSha256(field: string, value: string): void {
  if (!SHA256_HASH.test(value)) {
    throw new Error(`${field} must be a SHA-256 hash`);
  }
}
