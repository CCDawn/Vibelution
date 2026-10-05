import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { renameMock } = vi.hoisted(() => ({ renameMock: vi.fn() }));
vi.mock("node:fs/promises", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs/promises")>();
  return { ...actual, rename: renameMock.mockImplementation(actual.rename) };
});
import { holderFilePath, instanceLockdirPath, withInstanceLock } from "../src/lifecycle/instanceLock.js";

const roots: string[] = [];
beforeEach(async () => {
  const actual = await vi.importActual<typeof import("node:fs/promises")>("node:fs/promises");
  renameMock.mockReset().mockImplementation(actual.rename);
});
afterEach(async () => {
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});

async function setup() {
  const root = await mkdtemp(join(tmpdir(), "vibelution-lock-release-"));
  roots.push(root);
  const registry = join(root, "instances.json");
  return { root, registry, lockdir: instanceLockdirPath(registry) };
}

function filesystemError(code: string) {
  return Object.assign(new Error(`injected ${code}`), { code });
}

describe("owned instance lock release", () => {
  it.each(["EPERM", "EACCES", "EBUSY"])("retries transient %s and releases the lock", async (code) => {
    const { root, registry } = await setup();
    await withInstanceLock(registry, () => {
      renameMock.mockRejectedValueOnce(filesystemError(code));
    });
    expect(await readdir(root)).toEqual([]);
  });

  it("stops retrying if a different holder appears", async () => {
    const { registry, lockdir } = await setup();
    const replacement = { pid: process.pid + 1, startedAt: new Date(0).toISOString() };
    await withInstanceLock(registry, () => {
      renameMock.mockImplementationOnce(async () => {
        await writeFile(holderFilePath(lockdir), JSON.stringify(replacement));
        throw filesystemError("EPERM");
      });
    });
    expect(JSON.parse(await readFile(holderFilePath(lockdir), "utf8"))).toEqual(replacement);
  });

  it("bounds persistent contention and leaves the owned lock intact", async () => {
    const { registry, lockdir } = await setup();
    const before = renameMock.mock.calls.length;
    await expect(withInstanceLock(registry, () => {
      for (let attempt = 0; attempt < 8; attempt += 1) {
        renameMock.mockRejectedValueOnce(filesystemError("EPERM"));
      }
    })).rejects.toMatchObject({ code: "EPERM" });
    // One holder publication plus the bounded release attempts.
    expect(renameMock.mock.calls.length - before).toBe(9);
    expect(JSON.parse(await readFile(holderFilePath(lockdir), "utf8"))).toMatchObject({ pid: process.pid });
  });

  it("reports non-transient filesystem errors immediately", async () => {
    const { registry } = await setup();
    const before = renameMock.mock.calls.length;
    await expect(withInstanceLock(registry, () => {
      renameMock.mockRejectedValueOnce(filesystemError("EIO"));
    })).rejects.toMatchObject({ code: "EIO" });
    expect(renameMock.mock.calls.length - before).toBe(2);
  });
});
