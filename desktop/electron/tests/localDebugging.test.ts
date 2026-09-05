import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it } from "vitest";
import { configureLocalDebugging, identifyDebugWindow, publishLocalDebugging } from "../src/debugging/localDebugging.js";

const roots: string[] = [];
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "desktop-debug-test-"));
  roots.push(root);
  const switches = new Map<string, string>();
  const app = { isPackaged: false, getPath: () => root, commandLine: {
    appendSwitch: (key: string, value: string) => switches.set(key, value),
    removeSwitch: (key: string) => switches.delete(key)
  } };
  return { root, app, switches };
}
afterEach(() => roots.splice(0).forEach(root => rmSync(root, { recursive: true, force: true })));

it("identifies launcher, main and branch through the existing window owner", () => {
  const windows = { launcher: { rendererProcessId: 1 }, workbench: { rendererProcessId: 2 } };
  const instances = [{ rendererProcessId: 3, instanceId: "branch-a" }];
  expect(identifyDebugWindow(1, windows, instances)).toEqual({ role: "launcher" });
  expect(identifyDebugWindow(2, windows, instances)).toEqual({ role: "main-workbench" });
  expect(identifyDebugWindow(3, windows, instances)).toEqual({ role: "branch-workbench", instanceId: "branch-a" });
  expect(identifyDebugWindow(4, windows, instances)).toEqual({ role: "unknown" });
});

it("enables native loopback ephemeral CDP for local launches without opening DevTools", () => {
  const { app, switches } = fixture();
  expect(configureLocalDebugging(app, [], true)).toBe(true);
  expect(Object.fromEntries(switches)).toEqual({ "remote-debugging-address": "127.0.0.1", "remote-debugging-port": "0" });
});

it("disables distribution defaults and enables an explicitly local packaged launch", () => {
  const { app, switches } = fixture();
  app.isPackaged = true;
  switches.set("remote-debugging-port", "9222");
  expect(configureLocalDebugging(app, [], true)).toBe(false);
  expect(switches.size).toBe(0);
  expect(configureLocalDebugging(app, ["--local-debugging"], true)).toBe(true);
});

it("secondary launches leave primary discovery untouched", () => {
  const { app, root, switches } = fixture();
  writeFileSync(join(root, "DevToolsActivePort"), "primary");
  expect(configureLocalDebugging(app, [], false)).toBe(false);
  expect(readFileSync(join(root, "DevToolsActivePort"), "utf8")).toBe("primary");
  expect(switches.size).toBe(0);
});

it("publishes only the native endpoint belonging to the current startup and cleans its record", async () => {
  const { app, root } = fixture();
  writeFileSync(join(root, "DevToolsActivePort"), "1234\n/devtools/browser/stale");
  configureLocalDebugging(app, [], true);
  writeFileSync(join(root, "DevToolsActivePort"), "4567\n/devtools/browser/current\n");
  const recordPath = join(root, "desktop_debug.json");
  const identity = { pid: process.pid, createTime: 123, executable: process.execPath };
  const dispose = await publishLocalDebugging(root, root, identity, recordPath);
  expect(JSON.parse(readFileSync(recordPath, "utf8"))).toMatchObject({
    ...identity, workspaceRoot: root, httpEndpoint: "http://127.0.0.1:4567",
    webSocketDebuggerUrl: "ws://127.0.0.1:4567/devtools/browser/current"
  });
  dispose();
  expect(() => readFileSync(recordPath)).toThrow();
});
