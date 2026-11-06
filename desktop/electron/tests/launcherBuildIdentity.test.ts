import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { captureRunningLauncherBuild, parseLauncherBuild } from "../src/process/launcherBuildIdentity.js";
import { projectLauncherUpdateFreshness } from "../src/process/launcherUpdate.js";

const roots: string[] = [];
function fixture() {
  const root = mkdtempSync(resolve(tmpdir(), "launcher-build-identity-"));
  roots.push(root);
  const dist = resolve(root, "dist");
  mkdirSync(dist);
  writeFileSync(resolve(dist, "main.js"), "actual main");
  writeFileSync(resolve(dist, "preload.cjs"), "actual preload");
  writeFileSync(resolve(dist, "unpackaged-provenance.json"), JSON.stringify({ schemaVersion: 1, electronTreeHash: "a".repeat(40) }));
  return { root, dist, input: { packaged: false, desktopBundleRoot: dist, resourcesRoot: root } };
}
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

describe("Launcher build artifact identities", () => {
  it("freezes a real running build across a later disk promotion", () => {
    const { input, dist } = fixture();
    const running = captureRunningLauncherBuild(input)!;
    writeFileSync(resolve(dist, "main.js"), "replacement main");
    const replacement = captureRunningLauncherBuild(input)!;
    expect(running.id).not.toBe(replacement.id);
    expect(running.electronTree).toBe(replacement.electronTree);
    expect(Object.isFrozen(running)).toBe(true);
    expect(running.sourceCommit).toBeUndefined();
    const projected = projectLauncherUpdateFreshness({ raw: { current: true,
      runningCommit: "fake-head", runningShort: "fake-head", headShort: "fake-head",
      availableBuild: replacement, availableBuildState: "ready" }, packaged: false,
      runningBuild: running, activeWork: { state: "idle", message: "" }, updating: false });
    expect(projected).toMatchObject({ current: false, updateAvailable: true,
      runningBuild: running, availableBuild: replacement, runningCommit: "", runningShort: "", headShort: "" });
  });
  it("includes imported modules in the output digest, even when HEAD is unchanged", () => {
    const { input, dist } = fixture();
    writeFileSync(resolve(dist, "imported.js"), "old implementation");
    const before = captureRunningLauncherBuild(input)!;
    writeFileSync(resolve(dist, "imported.js"), "new implementation");
    expect(captureRunningLauncherBuild(input)?.id).not.toBe(before.id);
  });
  it("never substitutes checkout HEAD for a missing or invalid build", () => {
    const { input, dist } = fixture();
    writeFileSync(resolve(dist, "unpackaged-provenance.json"), "{}");
    expect(captureRunningLauncherBuild(input)).toBeNull();
    expect(parseLauncherBuild({ kind: "unpackaged", id: "HEAD", electronTree: "a".repeat(40) }, "unpackaged")).toBeNull();
  });
  it("uses packaged build evidence rather than current source commit", () => {
    const { root, dist } = fixture();
    mkdirSync(resolve(root, "app.asar.unpacked"));
    writeFileSync(resolve(root, "app.asar"), "real archive");
    const parts = ["a".repeat(40), "b".repeat(64), "c".repeat(64), "d".repeat(64), "e".repeat(64)];
    writeFileSync(resolve(root, "app.asar.unpacked/package-provenance.json"), JSON.stringify({
      electronTreeHash: parts[0], mainBundleSha256: parts[1], preloadBundleSha256: parts[2],
      frontendContentSha256: parts[3], assistant: { contentSha256: parts[4] }, sourceCommit: "f".repeat(40),
    }));
    const input = { packaged: true, desktopBundleRoot: dist, resourcesRoot: root };
    const running = captureRunningLauncherBuild(input)!;
    const archiveHash = createHash("sha256").update("real archive").digest("hex");
    expect(running).toMatchObject({ id: createHash("sha256").update(JSON.stringify(["packaged", ...parts, archiveHash])).digest("hex"), sourceCommit: "f".repeat(40) });
    writeFileSync(resolve(root, "app.asar"), "same metadata, different imported module");
    expect(captureRunningLauncherBuild(input)?.id).not.toBe(running.id);
  });
  it("reports no ready version until a complete candidate exists", () => {
    const { input } = fixture();
    const running = captureRunningLauncherBuild(input)!;
    const projected = projectLauncherUpdateFreshness({ raw: { current: true, shellStale: true,
      availableBuildState: "not_built", headShort: "fake-head" }, packaged: false, runningBuild: running,
      activeWork: { state: "active", message: "" }, updating: false });
    expect(projected).toMatchObject({ current: null, availableBuild: null, availableBuildState: "not_built", updateAvailable: true, headShort: "" });
  });
  it("rejects cross-kind and malformed ready candidates", () => {
    const { input } = fixture();
    const running = captureRunningLauncherBuild(input)!;
    const projected = projectLauncherUpdateFreshness({ raw: { current: true, availableBuildState: "ready",
      availableBuild: { ...running, kind: "packaged" } }, packaged: false, runningBuild: running,
      activeWork: { state: "idle", message: "" }, updating: false });
    expect(projected).toMatchObject({ current: null, availableBuild: null, availableBuildState: "unknown" });
  });
});
