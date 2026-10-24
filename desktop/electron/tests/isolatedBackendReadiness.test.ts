import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { expect, it } from "vitest";
import { waitForBackendHealthy } from "../src/process/workbenchBackendHealth.js";

it("admits an isolated shell before its renderer requests deferred feature routes", async () => {
  const source = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
  const start = source.indexOf("await waitForBackendHealthy({");
  const end = source.indexOf("\n        });", start);
  expect(start).toBeGreaterThan(0);
  expect(end).toBeGreaterThan(start);
  const wait = runInNewContext(`(async () => { ${source.slice(start, end + 12)} })`, {
    port: 8123, input: {}, spawned: { spawnError: () => null, child: { exitCode: null, killed: false } },
    waitForBackendHealthy: (input: Parameters<typeof waitForBackendHealthy>[0]) => waitForBackendHealthy({
      ...input, timeoutMs: 20, pollIntervalMs: 0, connect: async () => true,
      fetchHealth: async () => ({ status: 200, json: async () => ({ status: "ok", shellReady: true, routesReady: false }) })
    })
  });
  await expect(wait()).resolves.toBeUndefined();
});
