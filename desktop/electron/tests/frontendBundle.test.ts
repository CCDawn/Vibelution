import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { preparePackagedFrontend, sha256DirectoryTree } from "../src/packaging/frontendBundle.js";

const temporaryRoots: string[] = [];

function createFixture() {
  const root = mkdtempSync(join(tmpdir(), "vibelution-frontend-package-"));
  temporaryRoots.push(root);
  const workspaceRoot = resolve(root, "workspace");
  const electronRoot = resolve(workspaceRoot, "desktop/electron");
  const release = resolve(workspaceRoot, "web/.vibelution-builds/release-abcdef0123456789");
  const buildKey = "a".repeat(64);
  mkdirSync(release, { recursive: true });
  mkdirSync(join(release, "assets"), { recursive: true });
  writeFileSync(join(release, "index.html"), "<main>launcher</main>\n", "utf8");
  writeFileSync(join(release, "assets", "launcher.js"), "export const launcher = true;\n", "utf8");
  writeFileSync(
    join(release, ".vibelution-build.json"),
    JSON.stringify({
      schemaVersion: 2,
      buildKey,
      frontendTree: "b".repeat(40),
      sourceCommit: "c".repeat(40)
    }),
    "utf8"
  );
  writeFileSync(
    join(workspaceRoot, "web/.vibelution-builds/active.json"),
    JSON.stringify({ release: "release-abcdef0123456789", buildKey }),
    "utf8"
  );
  return {
    workspaceRoot,
    electronRoot,
    release,
    buildKey,
    packageInputRoot: resolve(root, "build/session-1/package-web-dist")
  };
}

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("packaged frontend input", () => {
  it("uses the shared path-and-byte SHA-256 format", () => {
    const root = mkdtempSync(join(tmpdir(), "vibelution-frontend-digest-"));
    temporaryRoots.push(root);
    mkdirSync(join(root, "assets"), { recursive: true });
    writeFileSync(join(root, "assets", "app.js"), "export{};\n", "utf8");
    writeFileSync(join(root, "index.html"), "<main>v</main>\n", "utf8");

    expect(sha256DirectoryTree(root)).toBe("62e27c13de01ec035463d06ba40958d43b95919fcc7927dedab721b91998100b");
  });

  it("copies the verified active release and records the exact packaged-byte digest", () => {
    const fixture = createFixture();
    const result = preparePackagedFrontend({
      ...fixture,
      ensureBuild: () => ({ ok: true, release: fixture.release, buildKey: fixture.buildKey })
    });

    expect(result.frontendTreeHash).toBe("b".repeat(40));
    expect(result.frontendSourceCommit).toBe("c".repeat(40));
    expect(result.frontendBuildKey).toBe(fixture.buildKey);
    expect(result.frontendContentSha256).toMatch(/^[0-9a-f]{64}$/);
    expect(sha256DirectoryTree(result.path)).toBe(result.frontendContentSha256);
    expect(readFileSync(join(result.path, "index.html"), "utf8")).toBe("<main>launcher</main>\n");

    const repeated = preparePackagedFrontend({
      ...fixture,
      packageInputRoot: resolve(fixture.workspaceRoot, "build/session-2/package-web-dist"),
      ensureBuild: () => ({ ok: true, release: fixture.release, buildKey: fixture.buildKey })
    });
    expect(repeated.path).not.toBe(result.path);
    expect(sha256DirectoryTree(repeated.path)).toBe(result.frontendContentSha256);
    expect(existsSync(resolve(fixture.electronRoot, "node_modules/.cache/vibelution-package-web-dist"))).toBe(false);
  });

  it("refuses a release that changed after the frontend freshness check", () => {
    const fixture = createFixture();
    expect(() => preparePackagedFrontend({
      ...fixture,
      ensureBuild: () => ({ ok: true, release: fixture.release, buildKey: "d".repeat(64) })
    })).toThrow("Frontend active release changed while preparing the desktop package.");
  });

  it("refuses a package input path under shared electron node_modules", () => {
    const fixture = createFixture();
    const target = resolve(fixture.electronRoot, "node_modules/.cache/vibelution-package-web-dist");

    expect(() => preparePackagedFrontend({
      ...fixture,
      packageInputRoot: target,
      ensureBuild: () => ({ ok: true, release: fixture.release, buildKey: fixture.buildKey })
    })).toThrow("Desktop package frontend input cannot be written below shared electron/node_modules.");
    expect(existsSync(target)).toBe(false);
  });

  it("binds the digest to relative paths as well as file contents", () => {
    const first = createFixture();
    const firstHash = sha256DirectoryTree(first.release);
    writeFileSync(join(first.release, "assets", "launcher.js"), "export const launcher = false;\n", "utf8");
    expect(sha256DirectoryTree(first.release)).not.toBe(firstHash);
  });
});
