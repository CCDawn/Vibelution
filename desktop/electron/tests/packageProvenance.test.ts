import { describe, expect, it } from "vitest";
import { createDesktopPackageProvenance } from "../src/packaging/packageProvenance.js";

describe("desktop package provenance", () => {
  it("binds a package to immutable source and generated-bundle hashes", () => {
    expect(
      createDesktopPackageProvenance({
        sourceCommit: "a".repeat(40),
        electronTreeHash: "b".repeat(40),
        frontendTreeHash: "c".repeat(40),
        mainBundleSha256: "d".repeat(64),
        preloadBundleSha256: "e".repeat(64),
        builtAt: "2026-08-11T02:00:00.000Z"
      })
    ).toEqual({
      schemaVersion: 1,
      sourceCommit: "a".repeat(40),
      electronTreeHash: "b".repeat(40),
      frontendTreeHash: "c".repeat(40),
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
        mainBundleSha256: "d".repeat(64),
        preloadBundleSha256: "e".repeat(64),
        builtAt: "2026-08-11T02:00:00.000Z"
      })
    ).toThrow("sourceCommit must be a Git object hash");
  });
});
