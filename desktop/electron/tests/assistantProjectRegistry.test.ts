import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { AssistantProjectRegistry, MAX_ASSISTANT_PROJECTS, type AssistantProjectRegistryOptions } from "../src/assistant/projectRegistry.js";
import { writeLauncherStateFile } from "../src/process/workbenchBackend.js";

const roots: string[] = [];
function fixture(options: Partial<AssistantProjectRegistryOptions> = {}) {
  const root = mkdtempSync(join(tmpdir(), "assistant-project-registry-"));
  roots.push(root);
  const filePath = join(root, "grants.json");
  const directory = (name: string) => { const path = join(root, name); mkdirSync(path); return path; };
  return { root, filePath, directory, registry: new AssistantProjectRegistry({ filePath, ...options }) };
}
const candidate = (projectId: string, root: string, checkedOut = true) => ({ projectId, root, checkedOut });
const read = (filePath: string) => JSON.parse(readFileSync(filePath, "utf8"));

afterEach(() => {
  for (const root of roots.splice(0)) {
    try { rmSync(root, { recursive: true, force: true }); }
    catch { console.warn("Owned project registry fixture retained after cleanup failure."); }
  }
});

describe("main-owned project registration", () => {
  it("persists UUID grants, keeps no-op revisions, and never resurrects removed IDs", async () => {
    const { registry, root, directory, filePath } = fixture();
    const project = directory("project");
    const first = await registry.reconcile(root, [candidate("base", project)]);
    const id = Object.keys(first.projects)[0];
    expect(id).toMatch(/^base:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(first.revision).toBe(1);
    expect(await registry.reconcile(root, [candidate("base", project)])).toEqual(first);
    expect(new AssistantProjectRegistry({ filePath }).snapshot()).toEqual(first);
    const removed = await registry.reconcile(root, []);
    expect(removed).toEqual({ schemaVersion: 1, revision: 2, projects: {} });
    const added = await new AssistantProjectRegistry({ filePath }).reconcile(root, [candidate("base", project)]);
    expect(added.revision).toBe(3);
    expect(Object.keys(added.projects)[0]).not.toBe(id);
    const rows = read(filePath).registrations;
    expect(rows).toHaveLength(2);
    expect(rows.map((row: { active: boolean }) => row.active)).toEqual([false, true]);
    expect(`base:${rows[0].registrationUuid}`).toBe(id);
  });

  it("retains other integration groups and atomically rebinds one base to a new root", async () => {
    const { registry, directory, filePath } = fixture();
    const a = directory("a"), b = directory("b"), replacement = directory("replacement");
    const first = await registry.reconcile(a, [candidate("base-a", a)]);
    const combined = await registry.reconcile(b, [candidate("base-b", b)]);
    const bId = Object.keys(combined.projects).find(id => id.startsWith("base-b:"))!;
    const result = await registry.reconcile(a, [candidate("base-a", replacement)]);
    expect(Object.values(result.projects)).toHaveLength(2);
    expect(Object.keys(result.projects)).not.toContain(Object.keys(first.projects)[0]);
    expect(read(filePath).registrations).toHaveLength(3);
    expect((await registry.reconcile(a, [])).projects).toEqual({ [bId]: combined.projects[bId] });
  });

  it("normalizes Windows casing and namespace aliases without renewing permission", async () => {
    const { registry, filePath } = fixture({ platform: "win32", isDirectory: () => true, realPath: path => path });
    const first = await registry.reconcile("C:\\Repo", [candidate("base", "C:\\Repo\\branch")]);
    expect(Object.values(first.projects)).toEqual(["c:\\repo\\branch"]);
    expect(await registry.reconcile("c:\\repo\\", [candidate("base", "\\\\?\\C:\\REPO\\branch")])).toEqual(first);
    expect(read(filePath).registrations).toHaveLength(1);
  });

  it("accepts fully qualified UNC roots and normalizes namespace and host casing", async () => {
    const { registry } = fixture({ platform: "win32", isDirectory: () => true, realPath: path => path });
    const first = await registry.reconcile("\\\\server.example\\share\\integration", [candidate("base", "\\\\server.example\\share\\project")]);
    expect(await registry.reconcile("\\\\?\\UNC\\SERVER.EXAMPLE\\SHARE\\integration",
      [candidate("base", "\\\\?\\unc\\SERVER.EXAMPLE\\SHARE\\PROJECT")])).toEqual(first);
  });

  it("does not authorize unchecked branches and persists revocation of missing directories", async () => {
    const { registry, root, directory, filePath } = fixture();
    const project = directory("project");
    const first = await registry.reconcile(root, [candidate("base", project), candidate("not-open", "", false)]);
    rmSync(project, { recursive: true });
    expect(() => registry.snapshot()).toThrow("PROJECT_REGISTRY_RECONCILE_REQUIRED");
    await expect(new AssistantProjectRegistry({ filePath }).reconcile(root, [candidate("base", project)]))
      .resolves.toEqual({ schemaVersion: 1, revision: first.revision + 1, projects: {} });
  });

  it("fails closed if a physical directory changes beneath a registered alias", async () => {
    let destination = "C:\\TargetA";
    const { registry, filePath } = fixture({ platform: "win32", isDirectory: () => true,
      realPath: path => path.toLowerCase() === "c:\\alias" ? destination : path });
    const first = await registry.reconcile("C:\\Integration", [candidate("base", "C:\\alias")]);
    destination = "C:\\TargetB";
    // The persisted physical root is also no longer the same directory.
    const changed = new AssistantProjectRegistry({ filePath, platform: "win32", isDirectory: () => true,
      realPath: path => path.toLowerCase() === "c:\\targeta" ? destination : path });
    expect(() => changed.snapshot()).toThrow("PROJECT_REGISTRY_RECONCILE_REQUIRED");
    const rebound = await changed.reconcile("C:\\Integration", [candidate("base", destination)]);
    expect(Object.keys(rebound.projects)[0]).not.toBe(Object.keys(first.projects)[0]);
    expect(read(filePath).registrations).toHaveLength(2);
  });

  it("rejects duplicates and cross-group overlap without replacing the previous grants", async () => {
    const { registry, directory, filePath } = fixture();
    const a = directory("a"), b = directory("b");
    const first = await registry.reconcile(a, [candidate("base", a)]);
    const before = readFileSync(filePath, "utf8");
    for (const [integration, candidates] of [
      [a, [candidate("same", a), candidate("same", b)]],
      [a, [candidate("one", b), candidate("two", b)]],
      [a, [candidate("base", a), candidate("base", a)]],
      [b, [candidate("other", a)]],
      [b, [candidate("base", b)]],
    ] as const) {
      await expect(registry.reconcile(integration, [...candidates])).rejects.toThrow("PROJECT_REGISTRY_CONFLICT");
      expect(registry.snapshot()).toEqual(first);
      expect(readFileSync(filePath, "utf8")).toBe(before);
    }
  });

  it("allows distinct nested roots in distinct groups", async () => {
    const { registry, directory } = fixture();
    const parent = directory("parent"), child = join(parent, "child");
    mkdirSync(child);
    await registry.reconcile(parent, [candidate("parent", parent)]);
    expect(Object.keys((await registry.reconcile(child, [candidate("child", child)])).projects)).toHaveLength(2);
  });

  it("never publishes a same-revision subset or mutates an unrelated missing group", async () => {
    const { registry, directory, filePath } = fixture();
    const a = directory("a"), b = directory("b"), replacement = directory("replacement");
    const first = await registry.reconcile(a, [candidate("a", a)]);
    await registry.reconcile(b, [candidate("b", b)]);
    rmSync(b, { recursive: true });
    const before = readFileSync(filePath, "utf8");
    await expect(registry.reconcile(a, [candidate("a", replacement)])).rejects.toThrow("PROJECT_REGISTRY_RECONCILE_REQUIRED");
    expect(readFileSync(filePath, "utf8")).toBe(before);
    const revoked = await registry.reconcile(b, []);
    expect(revoked.revision).toBe(3);
    expect(revoked.projects).toEqual(first.projects);
  });

  it.each(["relative", "", "C:relative", "\\rooted", "C:\\bad\u0000path"])("rejects non-absolute or invalid roots: %s", async path => {
    const { registry } = fixture({ platform: "win32", isDirectory: () => true, realPath: value => value });
    await expect(registry.reconcile("C:\\integration", [candidate("base", path)])).rejects.toThrow("PROJECT_REGISTRY_INVALID");
    expect(registry.snapshot()).toEqual({ schemaVersion: 1, revision: 0, projects: {} });
  });

  it("bounds public IDs and rejects malformed authoritative candidates", async () => {
    const { registry, root, directory } = fixture();
    const project = directory("project");
    await expect(registry.reconcile(root, [candidate("b".repeat(124), project)])).rejects.toThrow("PROJECT_REGISTRY_INVALID");
    const result = await registry.reconcile(root, [candidate("b".repeat(123), project)]);
    expect(Object.keys(result.projects)[0]).toHaveLength(160);
    await expect(registry.reconcile("relative", [])).rejects.toThrow("PROJECT_REGISTRY_INVALID");
    await expect(registry.reconcile(root, [{ ...candidate("b", project), checkedOut: "yes" } as never])).rejects.toThrow("PROJECT_REGISTRY_INVALID");
  });

  it("allows 128 grants and rejects a 129th without committing a mixed revocation/addition", async () => {
    const options = { platform: "win32" as const, isDirectory: () => true, realPath: (path: string) => path };
    const { registry, filePath } = fixture(options);
    expect(MAX_ASSISTANT_PROJECTS).toBe(128);
    const candidates = Array.from({ length: 128 }, (_, index) => candidate(`p${index}`, `C:\\projects\\p${index}`));
    const first = await registry.reconcile("C:\\integration", candidates);
    expect(Object.keys(first.projects)).toHaveLength(128);
    const before = readFileSync(filePath, "utf8");
    for (const oversized of [
      [...candidates, candidate("extra", "C:\\projects\\extra")],
      [...candidates.slice(1), candidate("extra", "C:\\projects\\extra"), candidate("extra2", "C:\\projects\\extra2")],
    ]) {
      await expect(registry.reconcile("C:\\integration", oversized)).rejects.toThrow("PROJECT_REGISTRY_LIMIT_EXCEEDED");
      expect(readFileSync(filePath, "utf8")).toBe(before);
      expect(registry.snapshot()).toEqual(first);
    }
    const replaced = await registry.reconcile("C:\\integration", [...candidates.slice(1), candidate("extra", "C:\\projects\\extra")]);
    expect(replaced.revision).toBe(first.revision + 1);
    expect(Object.keys(replaced.projects)).toHaveLength(128);
    expect(read(filePath).registrations).toHaveLength(129); // Tombstones do not consume active capacity.
  });

  it("refuses to load 129 persisted active grants without overwriting permission data", async () => {
    const options = { platform: "win32" as const, isDirectory: () => true, realPath: (path: string) => path };
    const { registry, filePath } = fixture(options);
    await registry.reconcile("C:\\integration", Array.from({ length: 128 }, (_, index) => candidate(`p${index}`, `C:\\projects\\p${index}`)));
    const payload = read(filePath);
    payload.registrations.push({ ...payload.registrations[0], baseProjectId: "extra", root: "c:\\projects\\extra",
      registrationUuid: "00000000-0000-4000-8000-000000000001" });
    const before = JSON.stringify(payload);
    writeFileSync(filePath, before);
    expect(() => new AssistantProjectRegistry({ filePath, ...options })).toThrow("PROJECT_REGISTRY_LIMIT_EXCEEDED");
    expect(readFileSync(filePath, "utf8")).toBe(before);
  });

  it("preserves old bytes and memory when the existing atomic writer fails", async () => {
    const { registry, root, directory, filePath } = fixture();
    const first = await registry.reconcile(root, [candidate("base", directory("a"))]);
    const before = readFileSync(filePath, "utf8");
    let writes = 0;
    const failed = new AssistantProjectRegistry({ filePath, writeFile: async (path, payload) => {
      if (++writes === 1) throw new Error("private install path");
      await writeLauncherStateFile(path, payload);
    } });
    await expect(failed.reconcile(root, [])).rejects.toThrow("PROJECT_REGISTRY_WRITE_FAILED");
    expect(failed.snapshot()).toEqual(first);
    expect(readFileSync(filePath, "utf8")).toBe(before);
    expect(await failed.reconcile(root, [])).toEqual({ schemaVersion: 1, revision: first.revision + 1, projects: {} });
  });

  it("serializes queued reconciles and does not lose another group", async () => {
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    let writes = 0;
    const { registry, directory } = fixture({ writeFile: async (path, payload) => {
      if (++writes === 1) await gate;
      await writeLauncherStateFile(path, payload);
    } });
    const a = directory("a"), b = directory("b");
    const first = registry.reconcile(a, [candidate("a", a)]);
    const second = registry.reconcile(b, [candidate("b", b)]);
    release();
    expect((await first).revision).toBe(1);
    const result = await second;
    expect(result.revision).toBe(2);
    expect(Object.keys(result.projects)).toHaveLength(2);
    result.projects = {};
    expect(Object.keys(registry.snapshot().projects)).toHaveLength(2);
  });

  it("refuses unexpected on-disk edits, including valid grant changes, without overwriting", async () => {
    const { registry, root, directory, filePath } = fixture();
    const first = await registry.reconcile(root, [candidate("base", directory("project"))]);
    const original = readFileSync(filePath, "utf8");
    writeFileSync(filePath, "not json");
    expect(() => registry.snapshot()).toThrow("PROJECT_REGISTRY_CHANGED");
    await expect(registry.reconcile(root, [])).rejects.toThrow("PROJECT_REGISTRY_CHANGED");
    expect(readFileSync(filePath, "utf8")).toBe("not json");
    writeFileSync(filePath, original);
    expect(registry.snapshot()).toEqual(first);
    const changed = JSON.parse(original);
    changed.revision += 1;
    changed.registrations[0].active = false;
    writeFileSync(filePath, JSON.stringify(changed));
    expect(() => registry.snapshot()).toThrow("PROJECT_REGISTRY_CHANGED");
  });

  it.each(["schema", "revision", "uuid", "relative", "active", "unknown", "duplicateUuid", "duplicateRoot", "ambiguousBase"])(
    "refuses corrupt persisted permission data: %s", async kind => {
      const { registry, root, directory, filePath } = fixture();
      await registry.reconcile(root, [candidate("base", directory("project"))]);
      const payload = read(filePath);
      const row = payload.registrations[0];
      if (kind === "schema") payload.schemaVersion = 2;
      if (kind === "revision") payload.revision = -1;
      if (kind === "uuid") row.registrationUuid = "not-uuid";
      if (kind === "relative") row.root = "relative";
      if (kind === "active") row.active = "true";
      if (kind === "unknown") row.permissions = "extra";
      if (kind === "duplicateUuid") payload.registrations.push({ ...row, active: false });
      if (kind === "duplicateRoot") payload.registrations.push({ ...row, registrationUuid: "00000000-0000-4000-8000-000000000001", baseProjectId: "another" });
      if (kind === "ambiguousBase") payload.registrations.push({ ...row, registrationUuid: "00000000-0000-4000-8000-000000000001", root: `${row.root}-other` });
      const bytes = JSON.stringify(payload);
      writeFileSync(filePath, bytes);
      expect(() => new AssistantProjectRegistry({ filePath })).toThrow("PROJECT_REGISTRY_INVALID");
      expect(readFileSync(filePath, "utf8")).toBe(bytes);
    });
});
