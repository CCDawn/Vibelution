import { mkdtempSync, mkdirSync, realpathSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { IpcMainInvokeEvent } from "electron";
import { afterEach, describe, expect, it } from "vitest";
import { createLegacyReminderSourceResolver } from "../src/notifications/resolveLegacyReminderSource.js";
import { ElectronWindowProvider, type ElectronWindowLike } from "../src/windows/electronWindowProvider.js";
import type { HumanAttentionSource } from "../src/notifications/humanAttentionNotifications.js";
import { readRegistry, type RegistryPayload } from "../src/lifecycle/instanceRegistryStore.js";
import { AssistantProjectRegistry } from "../src/assistant/projectRegistry.js";

class Window implements ElectronWindowLike {
  id = 1;
  private url = "";
  private events = new Map<string, Array<(...args: unknown[]) => void>>();
  readonly webContents: ElectronWindowLike["webContents"] = {
    getOSProcessId: () => 1, getURL: () => this.url,
    on: (name, callback) => { this.events.set(name, [...(this.events.get(name) ?? []), callback]); },
    send: () => undefined,
  };
  focus() {} show() {} hide() {} close() {} destroy() {} isDestroyed() { return false; } isFocused() { return false; }
  on() { return this; }
  async loadURL(url: string) { this.url = url; }
  navigateDocument() { for (const fn of this.events.get("did-start-navigation") ?? []) fn({ isMainFrame: true, isSameDocument: false }); }
}

const paths = { schemaVersion: 1 as const, desktopBundleRoot: "C:/bundle", resourcesRoot: "C:/res", workspaceRoot: "C:/repo", userDataRoot: "C:/user" };
const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

async function fixture(instanceId = "branch") {
  const root = mkdtempSync(join(tmpdir(), "legacy-reminder-binding-")); roots.push(root);
  const project = join(root, "project"); mkdirSync(project);
  const window = new Window();
  const provider = new ElectronWindowProvider(paths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8001/", {
    createWorkbenchWindow: () => window,
  });
  if (instanceId === "main") await provider.openOrFocusWorkbench();
  else await provider.openOrFocusInstanceWorkbench({ instanceId, url: "http://127.0.0.1:8001/" });
  const frame = { url: "http://127.0.0.1:8001/chat" };
  const event = { sender: Object.assign(window.webContents, { mainFrame: frame }), senderFrame: frame } as unknown as IpcMainInvokeEvent;
  const target = provider.notificationTargetForSender(event.sender, frame.url)!;
  const source: HumanAttentionSource = { instanceId, origin: "http://127.0.0.1:8001", documentToken: target.documentToken,
    target, allowAssistantWindow: () => false };
  const registry: RegistryPayload = { schemaVersion: 3, instances: {
    branch: { status: "steady", phase: "steady", desiredState: "open", generation: 3,
      port: 8001, url: "http://127.0.0.1:8001/", projectRoot: project, portLeaseStatus: "held" },
  } };
  const snapshot = { schemaVersion: 1 as const, revision: 5, projects: { "project:uuid": project } as Record<string, string> };
  const connection = { snapshot: () => structuredClone(snapshot) };
  let reads = 0;
  let beforeRead: (count: number) => void = () => undefined;
  const resolver = createLegacyReminderSourceResolver({ windowProvider: () => provider, projectConnection: () => connection,
    readInstances: async () => { beforeRead(++reads); return structuredClone(registry); } });
  return { root, project, window, provider, frame, event, source, registry, snapshot, resolver,
    beforeRead: (fn: (count: number) => void) => { beforeRead = fn; } };
}

describe("legacy reminder source resolution", () => {
  it.each(["branch", "main"])("binds a %s window only through its unique registry origin and physical project", async instanceId => {
    const f = await fixture(instanceId);
    const info = statSync(f.project, { bigint: true });
    expect(await f.resolver(f.event, f.source)).toEqual({ projectId: "project:uuid", instanceId,
      physicalRoot: process.platform === "win32" ? realpathSync.native(f.project).toLowerCase() : realpathSync.native(f.project),
      physicalIdentity: { device: info.dev.toString(), inode: info.ino.toString() } });
  });

  it("rejects wrong branch identity, duplicate origin and duplicate physical project mapping", async () => {
    const f = await fixture();
    f.registry.instances.other = f.registry.instances.branch; delete f.registry.instances.branch;
    expect(await f.resolver(f.event, f.source)).toBeNull();
    f.registry.instances.branch = f.registry.instances.other;
    expect(await f.resolver(f.event, f.source)).toBeNull();
    delete f.registry.instances.other;
    f.snapshot.projects["project:other"] = f.project;
    expect(await f.resolver(f.event, f.source)).toBeNull();
  });

  it("rejects inactive, missing, invalid, mismatched and ambiguous source records", async () => {
    for (const patch of [{ status: "stopping" }, { desiredState: "closed" }, { phase: "starting" }, { generation: 0 },
      { port: 8002 }, { url: "http://127.0.0.1:8002/" }, { projectRoot: "missing" }, { cleanupInProgress: true },
      { portLeaseStatus: "reclaimable" }, { portLeaseStatus: undefined }]) {
      const f = await fixture(); Object.assign(f.registry.instances.branch, patch);
      expect(await f.resolver(f.event, f.source)).toBeNull();
    }
    const main = await fixture("main");
    main.registry.instances.unknown = { status: "starting" };
    expect(await main.resolver(main.event, main.source)).toBeNull();
  });

  it("uses the real instance reader and project registration rather than renderer-provided identity", async () => {
    const f = await fixture();
    const instanceFile = join(f.root, "instances.json");
    writeFileSync(instanceFile, JSON.stringify(f.registry));
    const connection = new AssistantProjectRegistry({ filePath: join(f.root, "projects.json") });
    const snapshot = await connection.reconcile(f.root, [{ projectId: "project", root: f.project, checkedOut: true }]);
    const projectId = Object.keys(snapshot.projects)[0];
    const resolver = createLegacyReminderSourceResolver({ windowProvider: () => f.provider,
      projectConnection: () => connection, readInstances: () => readRegistry(instanceFile) });
    expect(await resolver(f.event, f.source)).toMatchObject({ projectId, instanceId: "branch" });
  });

  it.each(["revision", "project", "instance", "document", "subframe"])("rejects a %s change during the asynchronous read", async change => {
    const f = await fixture();
    f.beforeRead(count => {
      if (count !== 2) return;
      if (change === "revision") f.snapshot.revision++;
      if (change === "project") f.snapshot.projects["other"] = f.project;
      if (change === "instance") f.registry.instances.branch.generation = 4;
      if (change === "document") f.window.navigateDocument();
      if (change === "subframe") Object.assign(f.event, { senderFrame: { url: f.frame.url } });
    });
    expect(await f.resolver(f.event, f.source)).toBeNull();
  });

  it("treats a failed registry read as unbound", async () => {
    const f = await fixture(); f.beforeRead(() => { throw new Error("registry unavailable"); });
    expect(await f.resolver(f.event, f.source)).toBeNull();
  });

  it("rejects replacement of the physical project directory during the read", async () => {
    const f = await fixture();
    f.beforeRead(count => {
      if (count !== 2) return;
      renameSync(f.project, join(f.root, "previous"));
      mkdirSync(f.project);
    });
    expect(await f.resolver(f.event, f.source)).toBeNull();
  });
});
