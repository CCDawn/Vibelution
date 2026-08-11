export const DESKTOP_PACKAGE_PROVENANCE_FILE = "package-provenance.json";

const REQUIRED_LAUNCHER_CAPABILITIES = ["desktop_actions.claim", "workbench_close.transaction.v1"] as const;
const GIT_OBJECT_HASH = /^[0-9a-f]{40,64}$/i;
const SHA256_HASH = /^[0-9a-f]{64}$/i;

export type DesktopPackageProvenanceInput = {
  sourceCommit: string;
  electronTreeHash: string;
  frontendTreeHash: string;
  mainBundleSha256: string;
  preloadBundleSha256: string;
  builtAt: string;
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
  assertSha256("mainBundleSha256", input.mainBundleSha256);
  assertSha256("preloadBundleSha256", input.preloadBundleSha256);
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
