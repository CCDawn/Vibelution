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

    const result = checkBundleBudget(tempRoot);

    expect(result.failures).toEqual([]);
    expect(result.entries.find((entry) => entry.name.startsWith("three.module-"))?.budgetName)
      .toBe("known lazy three graph chunk");
  });

  it("fails when an ordinary feature chunk grows beyond its budget", () => {
    writeAsset("TeamsRoute-CcYah-sm.js", 420 * 1024);

    const result = checkBundleBudget(tempRoot);

    expect(result.failures).toHaveLength(1);
    expect(result.failures[0]).toMatchObject({
      name: "TeamsRoute-CcYah-sm.js",
      budgetName: "route or feature chunks",
    });
  });

  it("ignores non JavaScript and CSS assets", () => {
    writeAsset("hero-background.webp", 900 * 1024);

    const result = checkBundleBudget(tempRoot);

    expect(result.entries).toEqual([]);
    expect(result.failures).toEqual([]);
  });
});
