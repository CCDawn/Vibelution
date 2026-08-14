import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

import {
  handleLauncherAppProtocolRequest,
  isLauncherAppUrl,
  launcherAppOriginFor,
  LAUNCHER_APP_ORIGIN,
  LAUNCHER_APP_PROTOCOL,
  registerLauncherAppProtocolHandle,
  resolveLauncherAppUrl,
  resolveLauncherDistRoot,
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
      `${LAUNCHER_APP_ORIGIN}/launcher`
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
    expect(
      resolveLauncherDistRoot({
        resourcesRoot: "C:/app/resources",
        workspaceRoot: "C:/repo",
        packaged: true,
        env: {},
      })
    ).toBe(resolve("C:/app/resources/web-dist"));
    expect(
      resolveLauncherDistRoot({
        resourcesRoot: "C:/app/resources",
        workspaceRoot: "C:/repo",
        packaged: false,
        env: {},
      })
    ).toBe(resolve("C:/repo/web/dist"));
  });

  it("registers the scheme handler through the Electron protocol module", () => {
    const handle = vi.fn();
    registerLauncherAppProtocolHandle({ distRoot: FAKE_DIST, handle });
    expect(handle).toHaveBeenCalledTimes(1);
    expect(handle.mock.calls[0][0]).toBe(LAUNCHER_APP_PROTOCOL);
    expect(typeof handle.mock.calls[0][1]).toBe("function");
  });
});
