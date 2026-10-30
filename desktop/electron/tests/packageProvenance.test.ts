import { describe, expect, it } from "vitest";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createDesktopPackageProvenance } from "../src/packaging/packageProvenance.js";
import { readAssistantPayloadEvidence } from "../src/packaging/assistantPayload.js";
import { parseWritePackageProvenanceArgs } from "../src/scripts/writePackageProvenance.js";

const packageInput = {
  sourceCommit: "a".repeat(40), electronTreeHash: "b".repeat(40), frontendTreeHash: "c".repeat(40),
  frontendContentSha256: "d".repeat(64), frontendBuildKey: "e".repeat(64), frontendSourceCommit: "f".repeat(40),
  mainBundleSha256: "1".repeat(64), preloadBundleSha256: "2".repeat(64), builtAt: "2026-08-11T02:00:00.000Z",
};

const CONTRACTS_BYTES = "API_PROTOCOL_VERSION = '1.0'\nSERVER_VERSION = '0.3.1'\n";
const contractsSha256 = createHash("sha256").update(CONTRACTS_BYTES).digest("hex");

const assistant = {
  manifestSha256: "a".repeat(64), contentSha256: "b".repeat(64), sourceContentSha256: "c".repeat(64),
  runtimeContentSha256: "d".repeat(64), requirementsSha256: "e".repeat(64), contractsSha256,
  pythonVersion: "3.12.10",
};

describe("desktop package provenance", () => {
  it("binds optional assistant evidence while keeping unpackaged inputs compatible", () => {
    expect(createDesktopPackageProvenance({ ...packageInput, assistant }).assistant).toEqual(assistant);
    expect(createDesktopPackageProvenance(packageInput).assistant).toBeUndefined();
  });

  it.each(["manifestSha256", "contentSha256", "sourceContentSha256", "runtimeContentSha256", "requirementsSha256", "contractsSha256", "pythonVersion"])(
    "rejects incomplete assistant evidence in %s", field => {
      expect(() => createDesktopPackageProvenance({ ...packageInput, assistant: { ...assistant, [field]: "invalid" } })).toThrow(/assistant/);
    });

  it("requires assistant inputs at the production provenance entry", () => {
    expect(() => parseWritePackageProvenanceArgs(["--workspace-root", "workspace", "--output", "provenance",
      "--dist-root", "dist", "--frontend-output", "web"])).toThrow(/assistant-payload-root/);
  });

  it("hashes the entire payload including its manifest, and rejects a changed manifest", () => {
    const root = mkdtempSync(join(tmpdir(), "assistant-package-proof-"));
    try {
      mkdirSync(join(root, "source", "core", "external_agent"), { recursive: true });
      writeFileSync(join(root, "source", "core", "external_agent", "contracts.py"), CONTRACTS_BYTES);
      writeFileSync(join(root, "source", "entry.py"), "source");
      writeFileSync(join(root, "manifest.json"), JSON.stringify(assistant));
      const expected = createHash("sha256").update(readFileSync(join(root, "manifest.json"))).digest("hex");
      const first = readAssistantPayloadEvidence(root, expected);
      expect(first.manifestSha256).toBe(expected);
      expect(first.sourceContentSha256).toBe(assistant.sourceContentSha256);
      expect(first.contractsSha256).toBe(contractsSha256);
      writeFileSync(join(root, "source", "entry.py"), "changed");
      const second = readAssistantPayloadEvidence(root, expected);
      expect(second.contentSha256).not.toBe(first.contentSha256);
      expect(second.manifestSha256).toBe(first.manifestSha256);
      writeFileSync(join(root, "manifest.json"), "{}");
      expect(() => readAssistantPayloadEvidence(root, expected)).toThrow(/changed after its owned build/);
    } finally { rmSync(root, { recursive: true, force: true }); }
  });

  it("refuses packaging a payload whose contracts module no longer matches its sealed identity", () => {
    const root = mkdtempSync(join(tmpdir(), "assistant-package-contracts-drift-"));
    try {
      mkdirSync(join(root, "source", "core", "external_agent"), { recursive: true });
      writeFileSync(join(root, "source", "core", "external_agent", "contracts.py"), CONTRACTS_BYTES);
      // Manifest still seals the original tree; the contracts module was edited
      // after the owned build, so packaging must fail instead of sealing drift.
      writeFileSync(join(root, "source", "core", "external_agent", "contracts.py"), "API_PROTOCOL_VERSION = '9.9'\n");
      writeFileSync(join(root, "manifest.json"), JSON.stringify(assistant));
      const expected = createHash("sha256").update(readFileSync(join(root, "manifest.json"))).digest("hex");
      expect(() => readAssistantPayloadEvidence(root, expected)).toThrow(/contracts module does not match/);
      // A snapshot missing the contracts module entirely is refused too.
      rmSync(join(root, "source", "core", "external_agent", "contracts.py"));
      expect(() => readAssistantPayloadEvidence(root, expected)).toThrow(/missing source\/core\/external_agent\/contracts\.py/);
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it("binds a package to immutable source and generated-bundle hashes", () => {
    expect(
      createDesktopPackageProvenance({
        sourceCommit: "a".repeat(40),
        electronTreeHash: "b".repeat(40),
        frontendTreeHash: "c".repeat(40),
        frontendContentSha256: "f".repeat(64),
        frontendBuildKey: "1".repeat(64),
        frontendSourceCommit: "2".repeat(40),
        mainBundleSha256: "d".repeat(64),
        preloadBundleSha256: "e".repeat(64),
        builtAt: "2026-08-11T02:00:00.000Z"
      })
    ).toEqual({
      schemaVersion: 1,
      sourceCommit: "a".repeat(40),
      electronTreeHash: "b".repeat(40),
      frontendTreeHash: "c".repeat(40),
      frontendContentSha256: "f".repeat(64),
      frontendBuildKey: "1".repeat(64),
      frontendSourceCommit: "2".repeat(40),
      mainBundleSha256: "d".repeat(64),
      preloadBundleSha256: "e".repeat(64),
      protocolVersion: 1,
      capabilities: ["desktop_actions.claim", "workbench_close.transaction.v1"],
      builtAt: "2026-08-11T02:00:00.000Z"
    });
  });

  it("rejects incomplete hashes instead of producing unverifiable package evidence", () => {
    expect(() =>
      createDesktopPackageProvenance({
        sourceCommit: "short",
        electronTreeHash: "b".repeat(40),
        frontendTreeHash: "c".repeat(40),
        frontendContentSha256: "f".repeat(64),
        frontendBuildKey: "1".repeat(64),
        frontendSourceCommit: "2".repeat(40),
        mainBundleSha256: "d".repeat(64),
        preloadBundleSha256: "e".repeat(64),
        builtAt: "2026-08-11T02:00:00.000Z"
      })
    ).toThrow("sourceCommit must be a Git object hash");
  });
});
