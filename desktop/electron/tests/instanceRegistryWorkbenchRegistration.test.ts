import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  readRegistry,
  registerWorkbenchInstance,
  sweepOrphanRegistryTemps
} from "../src/lifecycle/instanceRegistryStore.js";

const roots: string[] = [];

function makeRegistryPath(): string {
  const root = mkdtempSync(join(tmpdir(), "instance-registry-registration-"));
  roots.push(root);
  return join(root, "Vibelution", "instances.json");
}

afterEach(() => {
  while (roots.length) {
    const root = roots.pop();
    if (!root) continue;
    try {
      rmSync(root, { recursive: true, force: true });
    } catch {
      // A locked temp directory is left for the next run.
    }
  }
});

describe("registerWorkbenchInstance", () => {
  it("records the open workbench so a launcher restart can find it", async () => {
    const registryPath = makeRegistryPath();

    await registerWorkbenchInstance(registryPath, {
      projectRoot: "D:/work/project",
      port: 8123,
      controlPort: 8124,
      ownerPid: 4242
    });

    const registry = await readRegistry(registryPath);
    const entry = registry.instances.main;
    expect(entry).toBeTruthy();
    expect(entry.projectRoot).toBe("D:/work/project");
    expect(entry.host).toBe("127.0.0.1");
    expect(entry.port).toBe(8123);
    expect(entry.controlPort).toBe(8124);
    expect(entry.url).toBe("http://127.0.0.1:8123");
    expect(entry.status).toBe("open");
    expect(entry.phase).toBe("ready");
    expect(entry.ownerPid).toBe(4242);
    expect(entry.ownerId).toBe("pid:4242");
  });

  it("updates the same row on reopen instead of adding a second instance", async () => {
    const registryPath = makeRegistryPath();

    await registerWorkbenchInstance(registryPath, { projectRoot: "D:/work/project", port: 8123 });
    await registerWorkbenchInstance(registryPath, { projectRoot: "D:/work/project", port: 9123 });

    const registry = await readRegistry(registryPath);
    expect(Object.keys(registry.instances)).toEqual(["main"]);
    expect(registry.instances.main.port).toBe(9123);
  });

  it("omits controlPort when the caller does not know it", async () => {
    const registryPath = makeRegistryPath();

    await registerWorkbenchInstance(registryPath, { projectRoot: "D:/work/project", port: 8123 });

    const raw = JSON.parse(readFileSync(registryPath, "utf8")) as {
      instances: Record<string, { controlPort?: number }>;
    };
    expect(raw.instances.main.controlPort).toBeUndefined();
  });
});

describe("sweepOrphanRegistryTemps", () => {
  it("removes temp siblings that never replaced the registry", async () => {
    const registryPath = makeRegistryPath();
    mkdirSync(join(registryPath, ".."), { recursive: true });
    writeFileSync(registryPath, "{\"schemaVersion\":1,\"instances\":{}}\n", "utf8");
    const orphan = join(registryPath, "..", ".0e929a1d449f.instances.json");
    writeFileSync(orphan, "{}", "utf8");

    const removed = await sweepOrphanRegistryTemps(registryPath);

    expect(removed).toEqual([".0e929a1d449f.instances.json"]);
  });

  it("keeps the live registry and unrelated files", async () => {
    const registryPath = makeRegistryPath();
    mkdirSync(join(registryPath, ".."), { recursive: true });
    writeFileSync(registryPath, "{\"schemaVersion\":1,\"instances\":{}}\n", "utf8");
    const unrelated = join(registryPath, "..", "notes.txt");
    writeFileSync(unrelated, "keep", "utf8");

    const removed = await sweepOrphanRegistryTemps(registryPath);

    expect(removed).toEqual([]);
    expect(readFileSync(registryPath, "utf8")).toContain("schemaVersion");
    expect(readFileSync(unrelated, "utf8")).toBe("keep");
  });

  it("returns empty when the registry directory does not exist yet", async () => {
    const registryPath = makeRegistryPath();
    expect(await sweepOrphanRegistryTemps(registryPath)).toEqual([]);
  });
});
