import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  handleLauncherAppProtocolRequest,
  isLauncherAppUrl,
  lastLauncherDistResolution,
  launcherAppOriginFor,
  LAUNCHER_APP_ORIGIN,
  LAUNCHER_APP_PROTOCOL,
  registerLauncherAppProtocolHandle,
  resetLauncherDistResolutionStateForTests,
  resolveLauncherAppUrl,
  resolveLauncherDistResolution,
  resolveLauncherDistRoot,
  type LauncherDistResolutionEvent,
} from "../src/protocol/launcherAppProtocol.js";
import {
  resolveLauncherWindowUrl,
  resolveWorkbenchUrl,
} from "../src/windows/windowUrlResolver.js";

const FAKE_DIST = "C:/fake/web/dist";
const fakeFiles: Record<string, string> = {
  "index.html": "<!doctype html><div id='root'></div>",
  "assets/app.js": "console.log('app');",
  "assets/app.css": "body { color: #000; }",
};

function handlerFor(requestUrl: string, distRoot = FAKE_DIST): Response {
  return handleLauncherAppProtocolRequest({
    distRoot,
    requestUrl,
    exists: (path) => Object.keys(fakeFiles).some((f) => path === resolve(distRoot, f)),
    readFile: (path) => {
      const key = Object.keys(fakeFiles).find((f) => path === resolve(distRoot, f)) ?? "";
      return Buffer.from(fakeFiles[key] ?? "", "utf8");
    },
  });
}

/**
 * Writes a release that satisfies the same completeness contract as
 * core/launcher/frontend_build.py: non-empty index.html, every referenced
 * /assets/* present, schema 2 provenance carrying the buildKey.
 */
function writeCompleteRelease(
  releasesRoot: string,
  release: string,
  options: { buildKey?: string; body?: string; schemaVersion?: number; provenance?: boolean; assets?: boolean } = {}
): string {
  const buildKey = options.buildKey ?? `key-${release}`;
  const root = join(releasesRoot, release);
  mkdirSync(join(root, "assets"), { recursive: true });
  writeFileSync(
    join(root, "index.html"),
    `<!doctype html><script src="/assets/app.js"></script>${options.body ?? release}`,
    "utf8"
  );
  if (options.assets !== false) {
    writeFileSync(join(root, "assets", "app.js"), "console.log('app');", "utf8");
  }
  if (options.provenance !== false) {
    writeFileSync(
      join(root, ".vibelution-build.json"),
      JSON.stringify({ schemaVersion: options.schemaVersion ?? 2, buildKey }),
      "utf8"
    );
  }
  return buildKey;
}

function activate(releasesRoot: string, release: string, buildKey?: string): void {
  mkdirSync(releasesRoot, { recursive: true });
  writeFileSync(
    join(releasesRoot, "active.json"),
    JSON.stringify({ schemaVersion: 2, release, ...(buildKey === undefined ? {} : { buildKey }) }),
    "utf8"
  );
}

beforeEach(() => {
  resetLauncherDistResolutionStateForTests();
});

describe("launcher app protocol URLs", () => {
  it("resolves the launcher window to the packaged app protocol origin", () => {
    expect(resolveLauncherAppUrl()).toBe(`${LAUNCHER_APP_ORIGIN}/launcher`);
    expect(isLauncherAppUrl(resolveLauncherAppUrl())).toBe(true);
    expect(isLauncherAppUrl("http://127.0.0.1:8765/launcher")).toBe(false);
  });

  it("keeps an explicit development launcher URL override", () => {
    expect(
      resolveLauncherWindowUrl({ VIBELUTION_LAUNCHER_URL: "http://127.0.0.1:9000/launcher" } as NodeJS.ProcessEnv)
    ).toBe("http://127.0.0.1:9000/launcher");
  });

  it("defaults the launcher window to the app protocol instead of a production port", () => {
    expect(resolveLauncherWindowUrl({ NODE_ENV: "production" } as NodeJS.ProcessEnv)).toBe(
      `${LAUNCHER_APP_ORIGIN}/launcher/assistant`
    );
  });

  it("keeps the workbench resolver on local HTTP for the workbench window", () => {
    expect(
      resolveWorkbenchUrl({ NODE_ENV: "production" } as NodeJS.ProcessEnv, "http://127.0.0.1:8000/")
    ).toBe("http://127.0.0.1:8000/");
    expect(() => resolveWorkbenchUrl({ NODE_ENV: "production" } as NodeJS.ProcessEnv)).toThrow(
      "Workbench URL is not resolved"
    );
  });

  it("normalizes custom scheme origins for main-process window matching", () => {
    expect(launcherAppOriginFor(`${LAUNCHER_APP_ORIGIN}/launcher`)).toBe(LAUNCHER_APP_ORIGIN);
    expect(launcherAppOriginFor("http://127.0.0.1:8000/chat")).toBe("http://127.0.0.1:8000");
  });
});

describe("launcher app protocol file serving", () => {
  it("serves a packaged assistant with no configured project", () => {
    expect(resolveLauncherDistRoot({ resourcesRoot: "C:/app/resources", workspaceRoot: "", packaged: true, env: {} }))
      .toBe(resolve("C:/app/resources/web-dist"));
  });
  it("serves the SPA fallback index.html for the /launcher route", async () => {
    const response = handlerFor(`${LAUNCHER_APP_ORIGIN}/launcher`);
    expect(response.status).toBe(200);
    expect(await response.text()).toContain("<div id='root'>");
  });

  it("serves concrete assets with their content types", async () => {
    const js = handlerFor(`${LAUNCHER_APP_ORIGIN}/assets/app.js`);
    expect(js.status).toBe(200);
    expect(js.headers.get("content-type")).toBe("text/javascript; charset=utf-8");
    expect(await js.text()).toBe("console.log('app');");

    const css = handlerFor(`${LAUNCHER_APP_ORIGIN}/assets/app.css`);
    expect(css.headers.get("content-type")).toBe("text/css; charset=utf-8");
  });

  it("rejects foreign hosts and paths that escape the dist root", async () => {
    expect(handlerFor("http://evil.example/launcher").status).toBe(403);
    expect(handlerFor(`${LAUNCHER_APP_ORIGIN}/..%2Fsecret.txt`).status).toBe(403);
    expect(handlerFor(`${LAUNCHER_APP_ORIGIN}/..\\secret.txt`).status).toBe(403);
  });

  it("returns 404 for missing concrete assets instead of serving the SPA shell", async () => {
    expect(handlerFor(`${LAUNCHER_APP_ORIGIN}/assets/missing.js`).status).toBe(404);
  });

  it("resolves the dist root to packaged resources or the workspace dev build", () => {
    const workspaceRoot = mkdtempSync(join(tmpdir(), "vibelution-dist-root-"));
    try {
      expect(
        resolveLauncherDistRoot({
          resourcesRoot: "C:/app/resources",
          workspaceRoot,
          packaged: true,
          env: {},
        })
      ).toBe(resolve("C:/app/resources/web-dist"));
      expect(
        resolveLauncherDistRoot({
          resourcesRoot: "C:/app/resources",
          workspaceRoot,
          packaged: false,
          env: {},
        })
      ).toBe(resolve(workspaceRoot, "web", "dist"));
    } finally {
      rmSync(workspaceRoot, { recursive: true, force: true });
    }
  });

  it("resolves an unpackaged workspace through its atomically active release", () => {
    const workspaceRoot = mkdtempSync(join(tmpdir(), "vibelution-release-"));
    const releasesRoot = join(workspaceRoot, "web", ".vibelution-builds");
    const release = "release-current";
    try {
      const buildKey = writeCompleteRelease(releasesRoot, release);
      activate(releasesRoot, release, buildKey);

      expect(
        resolveLauncherDistRoot({
          resourcesRoot: "C:/app/resources",
          workspaceRoot,
          packaged: false,
          env: {},
        })
      ).toBe(resolve(releasesRoot, release));
    } finally {
      rmSync(workspaceRoot, { recursive: true, force: true });
    }
  });

  it("resolves a packaged launcher to the workspace active release so web changes skip a rebuild", () => {
    const workspaceRoot = mkdtempSync(join(tmpdir(), "vibelution-packaged-release-"));
    const releasesRoot = join(workspaceRoot, "web", ".vibelution-builds");
    const release = "release-live";
    try {
      const buildKey = writeCompleteRelease(releasesRoot, release);
      activate(releasesRoot, release, buildKey);

      expect(
        resolveLauncherDistRoot({
          resourcesRoot: "C:/app/resources",
          workspaceRoot,
          packaged: true,
          env: {},
        })
      ).toBe(resolve(releasesRoot, release));
    } finally {
      rmSync(workspaceRoot, { recursive: true, force: true });
    }
  });

  it("falls back to the packaged snapshot when the workspace has no active release", () => {
    const workspaceRoot = mkdtempSync(join(tmpdir(), "vibelution-packaged-empty-"));
    try {
      expect(
        resolveLauncherDistRoot({
          resourcesRoot: "C:/app/resources",
          workspaceRoot,
          packaged: true,
          env: {},
        })
      ).toBe(resolve("C:/app/resources/web-dist"));
    } finally {
      rmSync(workspaceRoot, { recursive: true, force: true });
    }
  });

  it("falls back to the packaged snapshot when the active release is invalid", () => {
    const expectPackagedFallback = (
      release: unknown,
      setup: (releasesRoot: string) => void,
      expectedReason: string
    ): void => {
      const workspaceRoot = mkdtempSync(join(tmpdir(), "vibelution-packaged-invalid-"));
      const releasesRoot = join(workspaceRoot, "web", ".vibelution-builds");
      try {
        mkdirSync(releasesRoot, { recursive: true });
        setup(releasesRoot);
        writeFileSync(join(releasesRoot, "active.json"), JSON.stringify({ release }), "utf8");

        const input = { resourcesRoot: "C:/app/resources", workspaceRoot, packaged: true, env: {} };
        expect(resolveLauncherDistRoot(input)).toBe(resolve("C:/app/resources/web-dist"));
        const resolution = resolveLauncherDistResolution(input);
        expect(resolution.source).toBe("packaged-snapshot");
        expect(resolution.rejectedActiveRelease?.reason).toBe(expectedReason);
        expect(resolution.warnings.join("\n")).toContain(expectedReason);
      } finally {
        rmSync(workspaceRoot, { recursive: true, force: true });
      }
    };
    // Path escape attempt.
    expectPackagedFallback("../evil", () => undefined, "invalid_pointer_release");
    // Baseline name mismatch inside the releases root.
    expectPackagedFallback("release-evil/inner", (releasesRoot) => {
      writeCompleteRelease(releasesRoot, join("release-evil", "inner"));
    }, "invalid_pointer_release");
    // Release directory without an index.html entrypoint.
    expectPackagedFallback("release-blank", (releasesRoot) => {
      mkdirSync(join(releasesRoot, "release-blank"), { recursive: true });
    }, "missing_index");
  });

  it("keeps the explicit dist root override above the workspace active release", () => {
    const workspaceRoot = mkdtempSync(join(tmpdir(), "vibelution-packaged-override-"));
    const releasesRoot = join(workspaceRoot, "web", ".vibelution-builds");
    try {
      const buildKey = writeCompleteRelease(releasesRoot, "release-live");
      activate(releasesRoot, "release-live", buildKey);

      expect(
        resolveLauncherDistRoot({
          resourcesRoot: "C:/app/resources",
          workspaceRoot,
          packaged: true,
          env: { VIBELUTION_LAUNCHER_DIST_ROOT: "C:/override/dist" },
        })
      ).toBe(resolve("C:/override/dist"));
    } finally {
      rmSync(workspaceRoot, { recursive: true, force: true });
    }
  });

  it("registers the scheme handler through the Electron protocol module", () => {
    const handle = vi.fn();
    registerLauncherAppProtocolHandle({ resolveDistRoot: () => FAKE_DIST, handle });
    expect(handle).toHaveBeenCalledTimes(1);
    expect(handle.mock.calls[0][0]).toBe(LAUNCHER_APP_PROTOCOL);
    expect(typeof handle.mock.calls[0][1]).toBe("function");
  });

  it("re-resolves the dist root per request so an active release switch is served immediately", async () => {
    const workspaceRoot = mkdtempSync(join(tmpdir(), "vibelution-switch-"));
    const releasesRoot = join(workspaceRoot, "web", ".vibelution-builds");
    const distRootInput = {
      resourcesRoot: "C:/app/resources",
      workspaceRoot,
      packaged: false,
      env: {}
    };
    try {
      const keyA = writeCompleteRelease(releasesRoot, "release-a");
      const keyB = writeCompleteRelease(releasesRoot, "release-b");
      activate(releasesRoot, "release-a", keyA);

      const handle = vi.fn();
      registerLauncherAppProtocolHandle({
        resolveDistRoot: () => resolveLauncherDistRoot(distRootInput),
        handle
      });
      const handler = handle.mock.calls[0][1] as (request: Request) => Response;

      const first = handler(new Request(`${LAUNCHER_APP_ORIGIN}/launcher`));
      expect(first.status).toBe(200);

      activate(releasesRoot, "release-b", keyB);

      const second = handler(new Request(`${LAUNCHER_APP_ORIGIN}/launcher`));
      expect(second.status).toBe(200);

      expect(await first.text()).toContain("release-a");
      expect(await second.text()).toContain("release-b");
    } finally {
      rmSync(workspaceRoot, { recursive: true, force: true });
    }
  });

  it("serves the launcher shell with no-store caching headers", async () => {
    const shell = handlerFor(`${LAUNCHER_APP_ORIGIN}/launcher`);
    expect(shell.headers.get("cache-control")).toBe("no-store, no-cache, must-revalidate, max-age=0");
    expect(shell.headers.get("pragma")).toBe("no-cache");
    expect(shell.headers.get("expires")).toBe("0");

    const asset = handlerFor(`${LAUNCHER_APP_ORIGIN}/assets/app.js`);
    expect(asset.headers.get("cache-control")).toBeNull();
  });
});

describe("launcher dist resolution contract", () => {
  function withWorkspace<T>(prefix: string, run: (workspaceRoot: string, releasesRoot: string) => T): T {
    const workspaceRoot = mkdtempSync(join(tmpdir(), prefix));
    try {
      return run(workspaceRoot, join(workspaceRoot, "web", ".vibelution-builds"));
    } finally {
      rmSync(workspaceRoot, { recursive: true, force: true });
    }
  }

  it("accepts only a release that satisfies the Python completeness contract", () => {
    withWorkspace("vibelution-contract-", (workspaceRoot, releasesRoot) => {
      const buildKey = writeCompleteRelease(releasesRoot, "release-ok");
      activate(releasesRoot, "release-ok", buildKey);
      const resolution = resolveLauncherDistResolution({ resourcesRoot: "C:/app/resources", workspaceRoot, packaged: true, env: {} });
      expect(resolution).toEqual({
        distRoot: resolve(releasesRoot, "release-ok"),
        source: "active-release",
        release: "release-ok",
        buildKey,
        warnings: []
      });
    });
  });

  it.each([
    ["missing_provenance", { provenance: false }],
    ["provenance_schema:1", { schemaVersion: 1 }],
    ["missing_asset:app.js", { assets: false }],
  ] as const)("rejects an active release with %s instead of serving it", (reason, options) => {
    withWorkspace("vibelution-reject-", (workspaceRoot, releasesRoot) => {
      const buildKey = writeCompleteRelease(releasesRoot, "release-bad", options);
      activate(releasesRoot, "release-bad", buildKey);
      const resolution = resolveLauncherDistResolution({ resourcesRoot: "C:/app/resources", workspaceRoot, packaged: true, env: {} });
      expect(resolution.source).toBe("packaged-snapshot");
      expect(resolution.distRoot).toBe(resolve("C:/app/resources/web-dist"));
      expect(resolution.rejectedActiveRelease).toEqual({ release: "release-bad", reason });
      expect(resolution.warnings).toHaveLength(1);
    });
  });

  it("rejects an empty index.html like the Python validator", () => {
    withWorkspace("vibelution-empty-index-", (workspaceRoot, releasesRoot) => {
      const buildKey = writeCompleteRelease(releasesRoot, "release-empty");
      writeFileSync(join(releasesRoot, "release-empty", "index.html"), "", "utf8");
      activate(releasesRoot, "release-empty", buildKey);
      const resolution = resolveLauncherDistResolution({ resourcesRoot: "C:/app/resources", workspaceRoot, packaged: true, env: {} });
      expect(resolution.rejectedActiveRelease?.reason).toBe("empty_index");
    });
  });

  it("rejects a release whose provenance buildKey disagrees with the pointer", () => {
    withWorkspace("vibelution-key-mismatch-", (workspaceRoot, releasesRoot) => {
      writeCompleteRelease(releasesRoot, "release-drift", { buildKey: "provenance-key" });
      activate(releasesRoot, "release-drift", "pointer-key");
      const resolution = resolveLauncherDistResolution({ resourcesRoot: "C:/app/resources", workspaceRoot, packaged: true, env: {} });
      expect(resolution.source).toBe("packaged-snapshot");
      expect(resolution.rejectedActiveRelease).toEqual({ release: "release-drift", reason: "build_key_mismatch" });
    });
  });

  it("rejects a release whose provenance carries no buildKey", () => {
    withWorkspace("vibelution-no-prov-key-", (workspaceRoot, releasesRoot) => {
      writeCompleteRelease(releasesRoot, "release-keyless");
      writeFileSync(join(releasesRoot, "release-keyless", ".vibelution-build.json"), JSON.stringify({ schemaVersion: 2 }), "utf8");
      activate(releasesRoot, "release-keyless", "any");
      const resolution = resolveLauncherDistResolution({ resourcesRoot: "C:/app/resources", workspaceRoot, packaged: true, env: {} });
      expect(resolution.rejectedActiveRelease?.reason).toBe("provenance_missing_build_key");
    });
  });

  it("serves a complete release behind a pointer without buildKey, but says so", () => {
    withWorkspace("vibelution-pointer-no-key-", (workspaceRoot, releasesRoot) => {
      const buildKey = writeCompleteRelease(releasesRoot, "release-legacy-pointer");
      activate(releasesRoot, "release-legacy-pointer");
      const resolution = resolveLauncherDistResolution({ resourcesRoot: "C:/app/resources", workspaceRoot, packaged: true, env: {} });
      expect(resolution.source).toBe("active-release");
      expect(resolution.buildKey).toBe(buildKey);
      expect(resolution.warnings).toEqual([
        "active release pointer carries no buildKey; verified through provenance only"
      ]);
    });
  });

  it("reports the legacy web/dist fallback instead of serving it silently", () => {
    withWorkspace("vibelution-legacy-", (workspaceRoot) => {
      mkdirSync(join(workspaceRoot, "web", "dist"), { recursive: true });
      writeFileSync(join(workspaceRoot, "web", "dist", "index.html"), "<!doctype html>", "utf8");
      const events: LauncherDistResolutionEvent[] = [];
      const input = { resourcesRoot: "C:/app/resources", workspaceRoot, packaged: false, env: {}, onEvent: (event: LauncherDistResolutionEvent) => events.push(event) };

      expect(resolveLauncherDistRoot(input)).toBe(resolve(workspaceRoot, "web", "dist"));
      expect(events).toHaveLength(1);
      expect(events[0].level).toBe("warning");
      expect(events[0].kind).toBe("launcher_dist_resolution");
      expect(events[0].message).toContain("legacy web/dist served without provenance/buildKey");
      expect(events[0].resolution.source).toBe("legacy-dist");
      expect(events[0].resolution.legacyProvenance).toBe("missing");
      // The usage fact is recorded for anyone who asks later.
      expect(lastLauncherDistResolution()).toEqual(events[0].resolution);

      // Legacy dist carrying provenance is still legacy, but it is verifiable.
      writeFileSync(
        join(workspaceRoot, "web", "dist", ".vibelution-build.json"),
        JSON.stringify({ schemaVersion: 2, buildKey: "legacy-key" }),
        "utf8"
      );
      resolveLauncherDistRoot(input);
      expect(events).toHaveLength(2);
      expect(events[1].level).toBe("info");
      expect(events[1].resolution.legacyProvenance).toBe("present");
      expect(events[1].resolution.buildKey).toBe("legacy-key");
      expect(events[1].resolution.warnings).toEqual([]);
    });
  });

  it("carries the rejection reason into the legacy fallback for an unpackaged shell", () => {
    withWorkspace("vibelution-legacy-reject-", (workspaceRoot, releasesRoot) => {
      writeCompleteRelease(releasesRoot, "release-bad", { provenance: false });
      activate(releasesRoot, "release-bad", "key");
      const resolution = resolveLauncherDistResolution({ resourcesRoot: "C:/app/resources", workspaceRoot, packaged: false, env: {} });
      expect(resolution.source).toBe("legacy-dist");
      expect(resolution.rejectedActiveRelease).toEqual({ release: "release-bad", reason: "missing_provenance" });
      expect(resolution.legacyProvenance).toBe("missing");
      expect(resolution.warnings).toHaveLength(2);
    });
  });

  it("emits one event per distinct outcome across per-request resolutions", () => {
    withWorkspace("vibelution-dedupe-", (workspaceRoot, releasesRoot) => {
      const keyA = writeCompleteRelease(releasesRoot, "release-a");
      const keyB = writeCompleteRelease(releasesRoot, "release-b");
      activate(releasesRoot, "release-a", keyA);
      const events: LauncherDistResolutionEvent[] = [];
      const input = { resourcesRoot: "C:/app/resources", workspaceRoot, packaged: true, env: {}, onEvent: (event: LauncherDistResolutionEvent) => events.push(event) };

      resolveLauncherDistRoot(input);
      resolveLauncherDistRoot(input);
      resolveLauncherDistRoot(input);
      expect(events).toHaveLength(1);
      expect(events[0].level).toBe("info");
      expect(events[0].resolution.release).toBe("release-a");

      activate(releasesRoot, "release-b", keyB);
      resolveLauncherDistRoot(input);
      resolveLauncherDistRoot(input);
      expect(events).toHaveLength(2);
      expect(events[1].resolution.release).toBe("release-b");

      // A pointer that stops validating is a new outcome, reported once.
      activate(releasesRoot, "release-b", "drifted");
      resolveLauncherDistRoot(input);
      resolveLauncherDistRoot(input);
      expect(events).toHaveLength(3);
      expect(events[2].level).toBe("warning");
      expect(events[2].resolution.rejectedActiveRelease?.reason).toBe("build_key_mismatch");
    });
  });

  it("falls back to console.warn for warnings when no event sink is wired", () => {
    withWorkspace("vibelution-console-", (workspaceRoot) => {
      const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
      try {
        resolveLauncherDistRoot({ resourcesRoot: "C:/app/resources", workspaceRoot, packaged: false, env: {} });
        resolveLauncherDistRoot({ resourcesRoot: "C:/app/resources", workspaceRoot, packaged: false, env: {} });
        expect(warn).toHaveBeenCalledTimes(1);
        expect(String(warn.mock.calls[0][0])).toContain("legacy web/dist served without provenance/buildKey");
      } finally {
        warn.mockRestore();
      }
    });
  });
});
