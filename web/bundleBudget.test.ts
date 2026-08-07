import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { checkBundleBudget } from "./scripts/checkBundleBudget.mjs";

let tempRoot = "";

function writeAsset(name: string, bytes: number) {
  writeFileSync(join(tempRoot, name), Buffer.alloc(bytes, 1));
}

beforeEach(() => {
  tempRoot = join(tmpdir(), `vibelution-bundle-budget-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  mkdirSync(tempRoot, { recursive: true });
});

afterEach(() => {
  if (tempRoot) {
    rmSync(tempRoot, { force: true, recursive: true });
    tempRoot = "";
  }
});

describe("bundle budget", () => {
  it("allows the known lazy three graph chunk without treating it as a generic route chunk", () => {
    writeAsset("three.module-BuxUrWDk.js", 720 * 1024);
    writeAsset("index-BrPQ1lZ_.js", 430 * 1024);

    const result = checkBundleBudget(tempRoot, { expectElkWorker: false });

    expect(result.failures).toEqual([]);
    expect(result.entries.find((entry) => entry.name.startsWith("three.module-"))?.budgetName)
      .toBe("known lazy three graph chunk");
  });

  it("classifies framework vendor chunks separately from route feature chunks", () => {
    writeAsset("vendor-react-dom-Ab12CdEf.js", 200 * 1024);
    writeAsset("vendor-react-router-Gh34IjKl.js", 120 * 1024);
    writeAsset("index-BrPQ1lZ_.js", 200 * 1024);

    const result = checkBundleBudget(tempRoot, { expectElkWorker: false });

    expect(result.failures).toEqual([]);
    expect(result.entries.find((entry) => entry.name.startsWith("vendor-react-dom-"))?.budgetName)
      .toBe("known vendor framework chunks");
    expect(result.entries.find((entry) => entry.name.startsWith("vendor-react-router-"))?.budgetName)
      .toBe("known vendor framework chunks");
  });

  it("classifies TeamsRoute under the known residual budget, not the generic route budget", () => {
    writeAsset("TeamsRoute-CcYah-sm.js", 120 * 1024);

    const result = checkBundleBudget(tempRoot, { expectElkWorker: false });

    expect(result.failures).toEqual([]);
    expect(result.entries.find((entry) => entry.name.startsWith("TeamsRoute-"))?.budgetName)
      .toBe("known Teams route residual");
  });

  it("fails when TeamsRoute grows beyond its residual budget", () => {
    writeAsset("TeamsRoute-CcYah-sm.js", 170 * 1024);

    const result = checkBundleBudget(tempRoot, { expectElkWorker: false });

    expect(result.failures).toHaveLength(1);
    expect(result.failures[0]).toMatchObject({
      name: "TeamsRoute-CcYah-sm.js",
      budgetName: "known Teams route residual",
    });
  });

  it("classifies TeamsWorkbenchWithScPhase under its residual budget", () => {
    writeAsset("TeamsWorkbenchWithScPhase-Ab12CdEf.js", 280 * 1024);

    const result = checkBundleBudget(tempRoot, { expectElkWorker: false });

    expect(result.failures).toEqual([]);
    expect(result.entries.find((entry) => entry.name.startsWith("TeamsWorkbenchWithScPhase-"))?.budgetName)
      .toBe("known Teams SC phase residual");
  });

  it("fails when an ordinary feature chunk grows beyond its budget", () => {
    writeAsset("ChatCodingRoute-CcYah-sm.js", 420 * 1024);

    const result = checkBundleBudget(tempRoot, { expectElkWorker: false });

    expect(result.failures).toHaveLength(1);
    expect(result.failures[0]).toMatchObject({
      name: "ChatCodingRoute-CcYah-sm.js",
      budgetName: "route or feature chunks",
    });
  });

  it("classifies the real ELK worker asset name under its dedicated budget, before the generic route rule", () => {
    // The real Vite build emits `elk-worker.min-<hash>.js` (from
    // `elkjs/lib/elk-worker.min.js?worker`); the pattern must classify it
    // with the dedicated rule and never fall into the generic route rule.
    writeAsset("elk-worker.min-Ab12CdEf.js", 1700 * 1024);
    writeAsset("ChatCodingRoute-CcYah-sm.js", 120 * 1024);

    const result = checkBundleBudget(tempRoot, { expectElkWorker: true });

    expect(result.failures).toEqual([]);
    expect(result.elkWorker).toMatchObject({ present: true });
    expect(result.entries.find((entry) => entry.name.startsWith("elk-worker.min-"))?.budgetName)
      .toBe("known ELK worker chunk");
    expect(result.entries.find((entry) => entry.name.startsWith("ChatCodingRoute-"))?.budgetName)
      .toBe("route or feature chunks");
  });

  it("fails when the expected ELK worker asset is missing from the build output", () => {
    writeAsset("index-BrPQ1lZ_.js", 200 * 1024);

    const result = checkBundleBudget(tempRoot, { expectElkWorker: true });

    expect(result.elkWorker).toMatchObject({ present: false });
    expect(result.failures).toHaveLength(1);
    expect(result.failures[0].budgetName).toBe("known ELK worker chunk");
    expect(result.failures[0].name).toContain("missing");
  });

  it("fails when the ELK worker asset exceeds its dedicated budget", () => {
    writeAsset("elk-worker.min-Ab12CdEf.js", 1900 * 1024);

    const result = checkBundleBudget(tempRoot, { expectElkWorker: true });

    expect(result.failures).toHaveLength(1);
    expect(result.failures[0]).toMatchObject({
      budgetName: "known ELK worker chunk",
    });
  });

  it("fails when more than one ELK worker asset appears in the build output", () => {
    writeAsset("elk-worker.min-Ab12CdEf.js", 1700 * 1024);
    writeAsset("elk-worker.min-9zY8xWvQ.js", 1600 * 1024);

    const result = checkBundleBudget(tempRoot, { expectElkWorker: true });

    expect(result.elkWorker).toMatchObject({ present: false });
    expect(result.failures.some((failure) => failure.name.includes("duplicate"))).toBe(true);
  });

  it("ignores non JavaScript and CSS assets", () => {
    writeAsset("hero-background.webp", 900 * 1024);

    const result = checkBundleBudget(tempRoot, { expectElkWorker: false });

    expect(result.entries).toEqual([]);
    expect(result.failures).toEqual([]);
  });
});
