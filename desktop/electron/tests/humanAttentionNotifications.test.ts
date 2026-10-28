import { mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import type { IpcMainInvokeEvent } from "electron";
import { IPC_CHANNELS } from "../src/ipc.js";
import { handleHumanAttentionCapabilityIpc, handleHumanAttentionIpc } from "../src/notifications/humanAttentionIpc.js";
import { LegacyReminderSourceFence } from "../src/notifications/legacyReminderSourceFence.js";
import { LegacyReminderNegotiatedDocuments } from "../src/notifications/legacyReminderCoordinator.js";
import {
  createHumanAttentionNotificationService,
  type DesktopHumanAttentionNotification
} from "../src/notifications/humanAttentionNotifications.js";
import {
  ElectronWindowProvider,
  type ElectronWindowLike
} from "../src/windows/electronWindowProvider.js";
import type { DesktopPaths } from "../src/paths.js";

const OPENED_CHANNEL = "launcher:human-attention-opened";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
const preloadSource = readFileSync(fileURLToPath(new URL("../src/preload.ts", import.meta.url)), "utf8");
const webNotificationsSource = readFileSync(
  fileURLToPath(
    new URL("../../../web/src/routes/personalAssistant/humanAttentionNotifications.ts", import.meta.url)
  ),
  "utf8"
);

/** The web layer owns the kind whitelist; the shell must accept the same set. */
function webKindWhitelist(): string[] {
  const match = webNotificationsSource.match(
    /HUMAN_ATTENTION_KINDS = new Set<string>\(\[([^\]]*)\]\)/
  );
  expect(match).toBeTruthy();
  return (match?.[1] ?? "")
    .split(",")
    .map((entry) => entry.trim().replace(/^["']|["']$/g, ""))
    .filter(Boolean);
}

function attention(
  overrides: Partial<DesktopHumanAttentionNotification> = {}
): DesktopHumanAttentionNotification {
  return {
    id: "ha-1",
    kind: "knowledge_review",
    severity: "high",
    title: "知识评审需要处理",
    body: "有 3 条新评审意见等待确认。",
    targetUrl: "/knowledge?review=1",
    ...overrides
  };
}

function makeService(
  options: {
    assistantOpen?: boolean;
    /** Simulates a hidden/minimized surface that still accepts sends. */
    assistantVisible?: boolean;
    notificationSupported?: boolean;
    failNotificationCreation?: boolean;
    focusWorkbenchRejects?: boolean;
    dedupWindowMs?: number;
  } = {}
) {
  const notifications: Array<{ title: string; body: string; clicked: () => void; shown: boolean }> = [];
  const assistantMessages: Array<{ channel: string; payload: unknown }> = [];
  const workbenchMessages: Array<{ channel: string; payload: unknown }> = [];
  let assistantOpen = options.assistantOpen !== false;
  let currentMs = 10_000;
  const recordEvent = vi.fn(async () => undefined);
  const bridge = {
    sendToAssistantWindow: vi.fn((channel: string, payload: unknown) => {
      if (!assistantOpen) {
        return false;
      }
      assistantMessages.push({ channel, payload });
      return true;
    }),
    isAssistantWindowVisible: vi.fn(() => options.assistantVisible !== false),
    sendToWorkbench: vi.fn((channel: string, payload: unknown) => {
      workbenchMessages.push({ channel, payload });
      return true;
    }),
    focusWorkbench: vi.fn(() =>
      options.focusWorkbenchRejects
        ? Promise.reject(new Error("workbench focus failed"))
        : Promise.resolve({ role: "workbench", open: true })
    ),
    setWorkbenchAttention: vi.fn()
  };
  const service = createHumanAttentionNotificationService({
    windowBridge: bridge,
    notificationSupported: () => options.notificationSupported ?? true,
    createNotification: ({ title, body, onClick }) => {
      if (options.failNotificationCreation) {
        throw new Error("native toast unavailable");
      }
      const record = { title, body, clicked: onClick, shown: false };
      notifications.push(record);
      return {
        show: () => {
          record.shown = true;
        }
      };
    },
    openedChannel: OPENED_CHANNEL,
    recordEvent,
    now: () => currentMs,
    ...(options.dedupWindowMs !== undefined ? { dedupWindowMs: options.dedupWindowMs } : {})
  });
  return {
    service,
    bridge,
    notifications,
    assistantMessages,
    workbenchMessages,
    recordEvent,
    setAssistantOpen: (open: boolean) => {
      assistantOpen = open;
    },
    advance: (ms: number) => {
      currentMs += ms;
    }
  };
}

describe("human attention notification service", () => {
  it("delivers to the assistant window first without touching system channels", async () => {
    const harness = makeService();

    const result = await harness.service.notify(attention());

    expect(result).toEqual({ delivered: "assistant_window" });
    expect(harness.assistantMessages).toEqual([
      { channel: OPENED_CHANNEL, payload: attention() }
    ]);
    expect(harness.notifications).toHaveLength(0);
    expect(harness.bridge.sendToWorkbench).not.toHaveBeenCalled();
    expect(harness.bridge.setWorkbenchAttention).not.toHaveBeenCalled();
  });

  it("falls back to a system toast when the assistant window is absent", async () => {
    const harness = makeService({ assistantOpen: false });

    const result = await harness.service.notify(attention());

    expect(result).toEqual({ delivered: "system_notification" });
    expect(harness.notifications).toHaveLength(1);
    expect(harness.notifications[0]).toMatchObject({
      title: "知识评审需要处理",
      body: "有 3 条新评审意见等待确认。",
      shown: true
    });
    expect(harness.bridge.setWorkbenchAttention).not.toHaveBeenCalled();
    expect(harness.assistantMessages).toHaveLength(0);
  });

  it("uses the system toast when the assistant window is not on screen", async () => {
    const harness = makeService({ assistantVisible: false });

    const result = await harness.service.notify(attention({ id: "ha-hidden" }));

    expect(result).toEqual({ delivered: "system_notification" });
    expect(harness.assistantMessages).toHaveLength(0);
    expect(harness.notifications).toHaveLength(1);
    expect(harness.notifications[0]!.shown).toBe(true);
  });

  it("flashes the workbench when native notifications are unsupported", async () => {
    const harness = makeService({ assistantOpen: false, notificationSupported: false });

    const result = await harness.service.notify(attention({ id: "ha-flash" }));

    expect(result).toEqual({ delivered: "attention_fallback" });
    expect(harness.notifications).toHaveLength(0);
    expect(harness.bridge.setWorkbenchAttention).toHaveBeenCalledTimes(1);
    expect(harness.bridge.setWorkbenchAttention).toHaveBeenCalledWith({
      unreadCount: 1,
      flash: true,
      description: expect.any(String)
    });
  });

  it("flashes the workbench when native toast creation throws", async () => {
    const harness = makeService({ assistantOpen: false, failNotificationCreation: true });

    const result = await harness.service.notify(attention({ id: "ha-throw" }));

    expect(result).toEqual({ delivered: "attention_fallback" });
    expect(harness.bridge.setWorkbenchAttention).toHaveBeenCalledWith({
      unreadCount: 1,
      flash: true,
      description: expect.any(String)
    });
  });

  it("suppresses a repeated id within the dedup window and replays the first outcome", async () => {
    const harness = makeService();

    const first = await harness.service.notify(attention());
    harness.setAssistantOpen(false);
    const second = await harness.service.notify(attention());

    expect(first).toEqual({ delivered: "assistant_window" });
    expect(second).toEqual({ delivered: "assistant_window" });
    expect(harness.assistantMessages).toHaveLength(1);
    expect(harness.notifications).toHaveLength(0);
  });

  it("delivers a repeated id again after the dedup window expires", async () => {
    const harness = makeService({ dedupWindowMs: 60_000 });

    const first = await harness.service.notify(attention());
    harness.advance(60_000);
    const second = await harness.service.notify(attention());

    expect(first).toEqual({ delivered: "assistant_window" });
    expect(second).toEqual({ delivered: "assistant_window" });
    expect(harness.assistantMessages).toHaveLength(2);
  });

  it("delivers distinct ids independently", async () => {
    const harness = makeService();

    await harness.service.notify(attention({ id: "ha-a" }));
    await harness.service.notify(attention({ id: "ha-b", kind: "anomaly", severity: "critical" }));

    expect(harness.assistantMessages.map((message) => (message.payload as { id: string }).id)).toEqual([
      "ha-a",
      "ha-b"
    ]);
  });

  it.each([
    ["missing id", { ...attention(), id: "" }, "id"],
    ["non-string id", { ...attention(), id: 42 }, "id"],
    ["missing kind", { ...attention(), kind: undefined }, "kind"],
    ["unknown kind", { ...attention(), kind: "alert" }, "kind"],
    ["unknown severity", { ...attention(), severity: "low" }, "severity"],
    ["missing title", { ...attention(), title: "   " }, "title"],
    ["null payload", null, "object"],
    ["string payload", "ha-1", "object"]
  ])(
    "rejects a payload with a %s without delivering anything",
    async (_label, payload, expectedErrorFragment) => {
      const harness = makeService();

      const result = await harness.service.notify(payload);

      expect(result).toEqual({
        delivered: "invalid_payload",
        error: expect.stringContaining(expectedErrorFragment)
      });
      expect(harness.assistantMessages).toHaveLength(0);
      expect(harness.notifications).toHaveLength(0);
      expect(harness.bridge.setWorkbenchAttention).not.toHaveBeenCalled();
      expect(harness.bridge.sendToWorkbench).not.toHaveBeenCalled();
    }
  );

  it("focuses the workbench and broadcasts the opened payload when the toast is clicked", async () => {
    const harness = makeService({ assistantOpen: false });

    await harness.service.notify(attention());
    harness.notifications[0].clicked();

    expect(harness.bridge.focusWorkbench).toHaveBeenCalledTimes(1);
    expect(harness.workbenchMessages).toEqual([
      { channel: OPENED_CHANNEL, payload: { id: "ha-1", targetUrl: "/knowledge?review=1" } }
    ]);
  });

  it("broadcasts the opened payload without targetUrl when none was provided", async () => {
    const harness = makeService({ assistantOpen: false });

    await harness.service.notify(attention({ targetUrl: undefined }));
    harness.notifications[0].clicked();

    expect(harness.workbenchMessages).toEqual([
      { channel: OPENED_CHANNEL, payload: { id: "ha-1" } }
    ]);
  });

  it("also notifies a live assistant surface when the toast is clicked", async () => {
    const harness = makeService({ assistantOpen: false });

    await harness.service.notify(attention());
    harness.setAssistantOpen(true);
    harness.notifications[0].clicked();

    expect(harness.assistantMessages).toEqual([
      { channel: OPENED_CHANNEL, payload: { id: "ha-1", targetUrl: "/knowledge?review=1" } }
    ]);
  });

  it("never throws from a toast click whose focus fails", async () => {
    const harness = makeService({ assistantOpen: false, focusWorkbenchRejects: true });

    await harness.service.notify(attention());
    expect(() => harness.notifications[0].clicked()).not.toThrow();
    expect(harness.workbenchMessages).toHaveLength(1);
  });

  it("keeps telemetry fields free of title and body content", async () => {
    const harness = makeService();

    await harness.service.notify(attention({ title: "SECRET internal path C:\\Users\\secret" }));

    const event = harness.recordEvent.mock.calls[0]?.[0];
    expect(event.eventCode).toBe("electron.human_attention_notification.delivered");
    expect(event.fields).toEqual({
      id: "ha-1",
      kind: "knowledge_review",
      severity: "high",
      delivered: "assistant_window",
      duplicate: false,
      hasTargetUrl: true
    });
    expect(JSON.stringify(event.fields)).not.toContain("SECRET");
    expect(JSON.stringify(event.fields)).not.toContain("评审意见");
  });
});

describe("human attention kind whitelist parity with the web layer", () => {
  it("accepts exactly the web whitelist, including affair_reminder, human_gate and assistant_digest", async () => {
    const webKinds = [...new Set(webKindWhitelist())].sort();
    expect(webKinds).toEqual([
      "affair_reminder",
      "anomaly",
      "assistant_digest",
      "dispatch_receipt",
      "human_gate",
      "knowledge_review",
      "run_completed",
      "session_completed",
    ]);

    for (const kind of webKinds) {
      const harness = makeService();
      const result = await harness.service.notify(
        attention({ id: `ha-${kind}`, kind: kind as DesktopHumanAttentionNotification["kind"] })
      );
      expect(result).toEqual({ delivered: "assistant_window" });
      expect((harness.assistantMessages[0]?.payload as { kind?: string }).kind).toBe(kind);
    }
  });

  it("rejects a kind that is not on the shared whitelist", async () => {
    const harness = makeService();

    const result = await harness.service.notify(
      attention({ kind: "human-gate" as unknown as DesktopHumanAttentionNotification["kind"] })
    );

    expect(result.delivered).toBe("invalid_payload");
    expect(harness.assistantMessages).toHaveLength(0);
    expect(harness.notifications).toHaveLength(0);
  });
});

describe("human gate inline approval payload forwarding", () => {
  it("forwards sanitized human-gate actions and meta to the assistant window card", async () => {
    const harness = makeService();

    const result = await harness.service.notify(
      attention({
        id: "gate-1",
        kind: "human_gate",
        actions: [
          { label: "接受", decision: "accept" },
          { label: "驳回", decision: "reject" },
          { label: "   ", decision: "accept" },
          { label: "junk", decision: 7 as unknown as string }
        ],
        meta: {
          teamId: "team-1",
          runId: "run-7",
          nodeId: "node-gate",
          taskId: "task-9",
          decisions: ["accept", "reject", "revise"],
          junk: "dropped"
        } as unknown as DesktopHumanAttentionNotification["meta"]
      })
    );

    expect(result).toEqual({ delivered: "assistant_window" });
    expect(harness.assistantMessages[0]?.payload).toEqual({
      id: "gate-1",
      kind: "human_gate",
      severity: "high",
      title: "知识评审需要处理",
      body: "有 3 条新评审意见等待确认。",
      targetUrl: "/knowledge?review=1",
      actions: [
        { label: "接受", decision: "accept" },
        { label: "驳回", decision: "reject" }
      ],
      meta: {
        teamId: "team-1",
        runId: "run-7",
        nodeId: "node-gate",
        taskId: "task-9",
        decisions: ["accept", "reject", "revise"]
      }
    });
  });

  it("keeps the system toast navigation-only when the assistant window is closed", async () => {
    const harness = makeService({ assistantOpen: false });

    const result = await harness.service.notify(
      attention({
        id: "gate-toast",
        kind: "human_gate",
        actions: [{ label: "接受", decision: "accept" }]
      })
    );

    // The toast path receives only title/body/click — inline approval buttons
    // exist solely on the assistant-window card.
    expect(result).toEqual({ delivered: "system_notification" });
    expect(harness.notifications).toHaveLength(1);
    expect(harness.notifications[0]).toMatchObject({
      title: "知识评审需要处理",
      body: "有 3 条新评审意见等待确认。"
    });
    harness.notifications[0].clicked();
    expect(harness.workbenchMessages).toEqual([
      { channel: OPENED_CHANNEL, payload: { id: "gate-toast", targetUrl: "/knowledge?review=1" } }
    ]);
  });
});

describe("human attention shell contract wiring", () => {
  it("registers the contract channels verbatim", () => {
    expect(IPC_CHANNELS.notifyHumanAttention).toBe("launcher:notify-human-attention");
    expect(IPC_CHANNELS.humanAttentionOpened).toBe("launcher:human-attention-opened");
  });

  it("routes the registered notify channel through the tested sender boundary", () => {
    const handleIndex = mainSource.indexOf("ipcMain.handle(IPC_CHANNELS.notifyHumanAttention");
    expect(handleIndex).toBeGreaterThanOrEqual(0);
    const segment = mainSource.slice(handleIndex, handleIndex + 400);
    expect(segment).toContain("handleHumanAttentionIpc(event, payload, windowProvider, trustedIpcOrigins(event)");
    expect(segment).toContain("resolveHumanAttentionNotificationService().notify(acceptedPayload, source)");
  });

  it("routes through sendToPet and the opened channel in main", () => {
    expect(mainSource).toContain("windowProvider?.sendToPet(channel, payload) === true");
    expect(mainSource).toContain("openedChannel: IPC_CHANNELS.humanAttentionOpened");
    expect(mainSource).toContain("notificationSupported: () => Notification.isSupported()");
  });

  it("exposes notifyHumanAttention and an unsubscribing onHumanAttentionOpened in preload", () => {
    expect(preloadSource).toContain(
      "ipcRenderer.invoke(IPC_CHANNELS.notifyHumanAttention, payload)"
    );
    expect(preloadSource).toContain("ipcRenderer.on(IPC_CHANNELS.humanAttentionOpened, wrapped)");
    expect(preloadSource).toContain(
      "ipcRenderer.removeListener(IPC_CHANNELS.humanAttentionOpened, wrapped)"
    );
  });
});

class FakeElectronWindow implements ElectronWindowLike {
  readonly id: number;
  readonly webContents: ElectronWindowLike["webContents"];
  readonly sentIpc: Array<{ channel: string; payload: unknown }> = [];
  readonly loadedUrls: string[] = [];
  readonly flashes: boolean[] = [];
  private url: string;
  private destroyed = false;
  private focused = false;
  private readonly contentsHandlers = new Map<string, Array<(...args: unknown[]) => void>>();

  constructor(id: number, url: string) {
    this.id = id;
    this.url = url;
    this.webContents = {
      getOSProcessId: () => 9000 + id,
      getURL: () => this.url,
      on: (event, listener) => {
        this.contentsHandlers.set(event, [...(this.contentsHandlers.get(event) ?? []), listener]);
        return this.webContents;
      },
      send: (channel: string, payload: unknown) => {
        this.sentIpc.push({ channel, payload });
      }
    };
  }

  emitContents(event: string, ...args: unknown[]): void {
    for (const listener of this.contentsHandlers.get(event) ?? []) listener(...args);
  }

  focus(): void {
    this.focused = true;
  }

  show(): void {
    this.focused = true;
  }

  hide(): void {
    this.focused = false;
  }

  flashFrame(value: boolean): void { this.flashes.push(value); }

  close(): void {
    this.destroyed = true;
  }

  destroy(): void {
    this.destroyed = true;
  }

  loadURL(url: string): Promise<void> {
    this.loadedUrls.push(url);
    this.url = url;
    return Promise.resolve();
  }

  isDestroyed(): boolean {
    return this.destroyed;
  }

  isFocused(): boolean {
    return this.focused;
  }

  on(): this {
    return this;
  }
}

const fakeDesktopPaths: DesktopPaths = {
  schemaVersion: 1,
  desktopBundleRoot: "C:/Program Files/Vibelution/resources/app.asar/dist",
  resourcesRoot: "C:/Program Files/Vibelution/resources",
  workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
  userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution"
};

describe("human attention IPC sender boundary", () => {
  it("grants capability only to a verified document and never downgrades a granted document", async () => {
    const root = mkdtempSync(join(tmpdir(), "legacy-reminder-capability-"));
    try {
      const workbench = new FakeElectronWindow(1, "");
      const provider = new ElectronWindowProvider(fakeDesktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000/", {
        createWorkbenchWindow: () => workbench,
      });
      await provider.openOrFocusWorkbench();
      const frame = { url: "http://127.0.0.1:8000/" };
      const event = { sender: Object.assign(workbench.webContents, { mainFrame: frame }), senderFrame: frame } as unknown as IpcMainInvokeEvent;
      const info = statSync(root, { bigint: true });
      const binding = { projectId: "project", instanceId: "main", physicalRoot: root,
        physicalIdentity: { device: info.dev.toString(), inode: info.ino.toString() } };
      const docs = new LegacyReminderNegotiatedDocuments();
      const options = { documents: docs, resolveSource: vi.fn().mockResolvedValue(binding), authorize: vi.fn().mockResolvedValue(() => true) };
      expect(await handleHumanAttentionCapabilityIpc(event, provider, ["http://127.0.0.1:8000"])).toEqual({ schemaVersion: 1, legacyAffairReminder: "legacy" });
      expect(await handleHumanAttentionCapabilityIpc(event, provider, ["http://127.0.0.1:8000"], options)).toEqual({ schemaVersion: 1, legacyAffairReminder: "main_owned" });
      options.resolveSource.mockResolvedValue(null);
      expect(await handleHumanAttentionCapabilityIpc(event, provider, ["http://127.0.0.1:8000"], options)).toEqual({ schemaVersion: 1, legacyAffairReminder: "main_owned" });
      const child = { ...event, senderFrame: { url: frame.url } } as unknown as IpcMainInvokeEvent;
      await expect(handleHumanAttentionCapabilityIpc(child, provider, ["http://127.0.0.1:8000"], options)).rejects.toThrow();
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it("keeps a capability grant fail-closed when binding commit throws or its reply is lost", async () => {
    const root = mkdtempSync(join(tmpdir(), "legacy-reminder-capability-failed-"));
    try {
      const workbench = new FakeElectronWindow(1, "");
      const provider = new ElectronWindowProvider(fakeDesktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000/", {
        createWorkbenchWindow: () => workbench,
      });
      await provider.openOrFocusWorkbench();
      const frame = { url: "http://127.0.0.1:8000/" };
      const event = { sender: Object.assign(workbench.webContents, { mainFrame: frame }), senderFrame: frame } as unknown as IpcMainInvokeEvent;
      const info = statSync(root, { bigint: true });
      const binding = { projectId: "project", instanceId: "main", physicalRoot: root,
        physicalIdentity: { device: info.dev.toString(), inode: info.ino.toString() } };
      const documents = new LegacyReminderNegotiatedDocuments();
      const resolveSource = vi.fn().mockResolvedValue(binding);
      const options = { documents, resolveSource, authorize: vi.fn().mockResolvedValue(() => { throw new Error("binding lost"); }) };
      await expect(handleHumanAttentionCapabilityIpc(event, provider, ["http://127.0.0.1:8000"], options)).rejects.toThrow();
      resolveSource.mockResolvedValue(null);
      await expect(handleHumanAttentionCapabilityIpc(event, provider, ["http://127.0.0.1:8000"], options)).rejects.toThrow();
      const notify = vi.fn(async () => ({ delivered: "system_notification" as const }));
      const coordinated = { documents,
        dispatch: vi.fn(async () => ({ delivered: "attempt_pending" as const })) };
      const result = await handleHumanAttentionIpc(event, attention({ kind: "affair_reminder" }), provider, ["http://127.0.0.1:8000"], notify,
        { fence: new LegacyReminderSourceFence(join(root, "fence")), resolveSource, coordinated });
      expect(result).toEqual({ delivered: "attempt_pending" });
      expect(notify).not.toHaveBeenCalled();
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it("does not return legacy from a delayed capability lookup after another lookup commits", async () => {
    const root = mkdtempSync(join(tmpdir(), "legacy-reminder-capability-race-"));
    try {
      const workbench = new FakeElectronWindow(1, "");
      const provider = new ElectronWindowProvider(fakeDesktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000/", {
        createWorkbenchWindow: () => workbench,
      });
      await provider.openOrFocusWorkbench();
      const frame = { url: "http://127.0.0.1:8000/" };
      const event = { sender: Object.assign(workbench.webContents, { mainFrame: frame }), senderFrame: frame } as unknown as IpcMainInvokeEvent;
      const info = statSync(root, { bigint: true });
      const binding = { projectId: "project", instanceId: "main", physicalRoot: root,
        physicalIdentity: { device: info.dev.toString(), inode: info.ino.toString() } };
      let finish!: (value: typeof binding | null) => void;
      const resolveSource = vi.fn().mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
        .mockResolvedValue(binding);
      const options = { documents: new LegacyReminderNegotiatedDocuments(), resolveSource, authorize: async () => () => true };
      const slow = handleHumanAttentionCapabilityIpc(event, provider, ["http://127.0.0.1:8000"], options);
      expect(await handleHumanAttentionCapabilityIpc(event, provider, ["http://127.0.0.1:8000"], options))
        .toEqual({ schemaVersion: 1, legacyAffairReminder: "main_owned" });
      finish(null);
      expect(await slow).toEqual({ schemaVersion: 1, legacyAffairReminder: "main_owned" });
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it("keeps negotiated reminders fail-closed if source binding disappears and validates before coordination", async () => {
    const root = mkdtempSync(join(tmpdir(), "legacy-reminder-negotiated-"));
    try {
      const workbench = new FakeElectronWindow(1, "");
      const provider = new ElectronWindowProvider(fakeDesktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000/", {
        createWorkbenchWindow: () => workbench,
      });
      await provider.openOrFocusWorkbench();
      const frame = { url: "http://127.0.0.1:8000/" };
      const event = { sender: Object.assign(workbench.webContents, { mainFrame: frame }), senderFrame: frame } as unknown as IpcMainInvokeEvent;
      const fence = new LegacyReminderSourceFence(join(root, "fence"));
      const info = statSync(root, { bigint: true });
      const binding = { projectId: "project", instanceId: "main", physicalRoot: root,
        physicalIdentity: { device: info.dev.toString(), inode: info.ino.toString() } };
      const notify = vi.fn(async () => ({ delivered: "system_notification" as const }));
      const dispatch = vi.fn(async () => ({ delivered: "attempt_pending" as const }));
      const documents = new LegacyReminderNegotiatedDocuments();
      const documentToken = provider.notificationTargetForSender(event.sender, frame.url)!.documentToken;
      documents.begin(documentToken);
      documents.commit(documentToken);
      const coordinated = { documents, dispatch };
      const invoke = (payload: unknown, resolveSource: () => Promise<typeof binding | null>) => handleHumanAttentionIpc(event, payload, provider,
        ["http://127.0.0.1:8000"], notify, { fence, resolveSource, coordinated });
      expect(await invoke(attention({ kind: "affair_reminder" }), async () => null)).toEqual({ delivered: "attempt_pending" });
      expect(await invoke(attention({ kind: "affair_reminder", id: "" }), async () => binding)).toMatchObject({ delivered: "invalid_payload" });
      expect(dispatch).not.toHaveBeenCalled();
      expect(notify).not.toHaveBeenCalled();
      expect(await invoke(attention({ kind: "affair_reminder" }), async () => binding)).toEqual({ delivered: "attempt_pending" });
      expect(dispatch).toHaveBeenCalledOnce();
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it("waits for an already received legacy reminder to finish sending before granting capability", async () => {
    const root = mkdtempSync(join(tmpdir(), "legacy-reminder-grant-drain-"));
    try {
      const workbench = new FakeElectronWindow(1, "");
      const provider = new ElectronWindowProvider(fakeDesktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000/", {
        createWorkbenchWindow: () => workbench,
      });
      await provider.openOrFocusWorkbench();
      const frame = { url: "http://127.0.0.1:8000/" };
      const event = { sender: Object.assign(workbench.webContents, { mainFrame: frame }), senderFrame: frame } as unknown as IpcMainInvokeEvent;
      const info = statSync(root, { bigint: true });
      const binding = { projectId: "project", instanceId: "main", physicalRoot: root,
        physicalIdentity: { device: info.dev.toString(), inode: info.ino.toString() } };
      const documents = new LegacyReminderNegotiatedDocuments();
      const fence = new LegacyReminderSourceFence(join(root, "fence"));
      let releaseFence!: () => void;
      const fenceGate = new Promise<void>(resolve => { releaseFence = resolve; });
      const originalSubmit = fence.submit.bind(fence);
      vi.spyOn(fence, "submit").mockImplementation(async (source, send) => {
        await fenceGate;
        return originalSubmit(source, send);
      });
      let releaseSend!: () => void;
      const notify = vi.fn(() => new Promise<{ delivered: "system_notification" }>(resolve => {
        releaseSend = () => resolve({ delivered: "system_notification" });
      }));
      const dispatch = vi.fn(async () => ({ delivered: "attempt_pending" as const }));
      const resolveSource = async () => binding;
      const coordinated = { documents, dispatch };
      const invoke = () => handleHumanAttentionIpc(event, attention({ kind: "affair_reminder" }), provider,
        ["http://127.0.0.1:8000"], notify, { fence, resolveSource, coordinated });
      const old = invoke();
      await vi.waitFor(() => expect(fence.submit).toHaveBeenCalledOnce());
      const commit = vi.fn(() => true);
      let granted = false;
      const grant = handleHumanAttentionCapabilityIpc(event, provider, ["http://127.0.0.1:8000"],
        { documents, resolveSource, authorize: async () => commit }).then(result => { granted = true; return result; });
      await vi.waitFor(() => expect(documents.has(provider.notificationTargetForSender(event.sender, frame.url)!.documentToken)).toBe(true));
      expect(await invoke()).toEqual({ delivered: "attempt_pending" });
      expect(commit).not.toHaveBeenCalled();
      releaseFence();
      await vi.waitFor(() => expect(notify).toHaveBeenCalledOnce());
      expect(granted).toBe(false);
      releaseSend();
      expect(await old).toEqual({ delivered: "system_notification" });
      expect(await grant).toEqual({ schemaVersion: 1, legacyAffairReminder: "main_owned" });
      expect(await invoke()).toEqual({ delivered: "attempt_pending" });
      expect(dispatch).toHaveBeenCalledOnce();
      expect(notify).toHaveBeenCalledOnce();
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it.each(["unbound", "bound"])("waits for a pre-fence %s source lookup and any admitted send", async mode => {
    const root = mkdtempSync(join(tmpdir(), "legacy-reminder-barrier-"));
    try {
      const workbench = new FakeElectronWindow(1, "");
      const provider = new ElectronWindowProvider(fakeDesktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000/", {
        createWorkbenchWindow: () => workbench,
      });
      await provider.openOrFocusWorkbench();
      const frame = { url: "http://127.0.0.1:8000/" };
      const event = { sender: Object.assign(workbench.webContents, { mainFrame: frame }), senderFrame: frame } as unknown as IpcMainInvokeEvent;
      const fence = new LegacyReminderSourceFence(join(root, "fence"));
      const info = statSync(root, { bigint: true });
      const binding = { projectId: "project", instanceId: "main", physicalRoot: root,
        physicalIdentity: { device: info.dev.toString(), inode: info.ino.toString() } };
      let finishLookup!: (value: typeof binding | null) => void;
      let finishSend!: () => void;
      const lookup = new Promise<typeof binding | null>(resolve => { finishLookup = resolve; });
      const notify = vi.fn(() => new Promise<{ delivered: "system_notification" }>(resolve => {
        finishSend = () => resolve({ delivered: "system_notification" });
      }));
      const request = handleHumanAttentionIpc(event, attention({ kind: "affair_reminder" }), provider,
        ["http://127.0.0.1:8000"], notify, { fence, resolveSource: async () => lookup });
      let stopped = false;
      const stopping = fence.stop(binding).then(value => { stopped = true; return value; });
      await Promise.resolve();
      expect(stopped).toBe(false);
      finishLookup(mode === "bound" ? binding : null);
      if (mode === "unbound") {
        await vi.waitFor(() => expect(notify).toHaveBeenCalledOnce());
        expect(stopped).toBe(false);
        finishSend();
        expect(await request).toEqual({ delivered: "system_notification" });
      } else {
        expect(await request).toEqual({ delivered: "source_retired" });
        expect(notify).not.toHaveBeenCalled();
      }
      expect(await stopping).toEqual({ boundCallsDrained: true, preFenceIngressDrained: true, ingressDrainedAtReturn: true,
        unboundSourcesMayStillSend: true, readyForCutover: false });
    } finally { rmSync(root, { recursive: true, force: true }); }
  });

  it("applies a real persisted source stop to affair reminders through the IPC handler", async () => {
    const root = mkdtempSync(join(tmpdir(), "legacy-reminder-ipc-"));
    try {
      const workbench = new FakeElectronWindow(1, "");
      const provider = new ElectronWindowProvider(fakeDesktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000/", {
        createWorkbenchWindow: () => workbench,
      });
      await provider.openOrFocusWorkbench();
      const frame = { url: "http://127.0.0.1:8000/" };
      const event = { sender: Object.assign(workbench.webContents, { mainFrame: frame }), senderFrame: frame } as unknown as IpcMainInvokeEvent;
      const fence = new LegacyReminderSourceFence(join(root, "fence"));
      const info = statSync(root, { bigint: true });
      const binding = { projectId: "project", instanceId: "main", physicalRoot: root,
        physicalIdentity: { device: info.dev.toString(), inode: info.ino.toString() } };
      const notify = vi.fn(async () => ({ delivered: "system_notification" as const }));
      const controls = { fence, resolveSource: async () => binding };
      const invoke = (payload: unknown, options = controls) => handleHumanAttentionIpc(event, payload, provider,
        ["http://127.0.0.1:8000"], notify, options);
      expect(await invoke(attention({ kind: "affair_reminder" }))).toEqual({ delivered: "system_notification" });
      await fence.stop(binding);
      expect(await invoke(attention({ kind: "affair_reminder" }))).toEqual({ delivered: "source_retired" });
      expect(await invoke(attention({ kind: "anomaly" }))).toEqual({ delivered: "system_notification" });
      expect(await invoke(attention({ kind: "affair_reminder" }), { fence, resolveSource: async () => null }))
        .toEqual({ delivered: "system_notification" });
      expect(notify).toHaveBeenCalledTimes(3);
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
  it("admits only registered top-level workbenches and forwards their distinct instance", async () => {
    const main = new FakeElectronWindow(1, "");
    const branch = new FakeElectronWindow(2, "");
    const foreign = new FakeElectronWindow(3, "http://127.0.0.1:8000/");
    let next = 0;
    const provider = new ElectronWindowProvider(fakeDesktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000/", {
      createWorkbenchWindow: () => next++ === 0 ? main : branch,
    });
    await provider.openOrFocusWorkbench();
    await provider.openOrFocusInstanceWorkbench({ instanceId: "branch", url: "http://127.0.0.1:8001/" });
    const eventFor = (window: FakeElectronWindow) => {
      const frame = { url: `${new URL(window.webContents.getURL()).origin}/chat` };
      const sender = Object.assign(window.webContents, { mainFrame: frame });
      return { sender, senderFrame: frame } as unknown as IpcMainInvokeEvent;
    };
    const mainEvent = eventFor(main);
    const branchEvent = eventFor(branch);
    const foreignEvent = eventFor(foreign);
    const payload = attention();
    const origins = ["http://127.0.0.1:8000", "http://127.0.0.1:8001"];
    const notify = vi.fn(async (_payload: unknown, _source: unknown) => ({ delivered: "assistant_window" as const }));
    expect(await handleHumanAttentionIpc(mainEvent, payload, provider, origins, notify)).toEqual({ delivered: "assistant_window" });
    expect(await handleHumanAttentionIpc(branchEvent, payload, provider, origins, notify)).toEqual({ delivered: "assistant_window" });
    expect(notify.mock.calls).toEqual([
      [payload, expect.objectContaining({ instanceId: "main", allowAssistantWindow: expect.any(Function) })],
      [payload, expect.objectContaining({ instanceId: "branch", allowAssistantWindow: expect.any(Function) })],
    ]);

    const subframe = { ...mainEvent, senderFrame: { url: "http://127.0.0.1:8000/chat" } } as IpcMainInvokeEvent;
    await expect(handleHumanAttentionIpc(subframe, payload, provider, origins, notify)).rejects.toThrow("blocked human attention sender");
    await expect(handleHumanAttentionIpc(foreignEvent, payload, provider, origins, notify)).rejects.toThrow("blocked human attention sender");
    await expect(handleHumanAttentionIpc(mainEvent, payload, null, origins, notify)).rejects.toThrow("blocked human attention sender");
    await expect(handleHumanAttentionIpc(mainEvent, payload, provider, ["http://127.0.0.1:8001"], notify)).rejects.toThrow("blocked ipc sender origin");
    await branch.loadURL("http://127.0.0.1:9999/");
    await expect(handleHumanAttentionIpc(branchEvent, payload, provider, origins, notify)).rejects.toThrow("blocked human attention sender");
    await provider.closeInstanceWorkbench("branch");
    await expect(handleHumanAttentionIpc(branchEvent, payload, provider, origins, notify)).rejects.toThrow("blocked human attention sender");
    expect(notify).toHaveBeenCalledTimes(2);
  });

  it("routes real service dedup and toast clicks to the originating workbench", async () => {
    const main = new FakeElectronWindow(1, "");
    const branch = new FakeElectronWindow(2, "");
    const replacement = new FakeElectronWindow(3, "");
    let next = 0;
    const provider = new ElectronWindowProvider(fakeDesktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000/", {
      createWorkbenchWindow: () => [main, branch, replacement][next++]!,
    });
    await provider.openOrFocusWorkbench();
    await provider.openOrFocusInstanceWorkbench({ instanceId: "branch", url: "http://127.0.0.1:8000/" });
    const eventFor = (window: FakeElectronWindow) => {
      const frame = { url: "http://127.0.0.1:8000/" };
      return { sender: Object.assign(window.webContents, { mainFrame: frame }), senderFrame: frame } as unknown as IpcMainInvokeEvent;
    };
    const mainEvent = eventFor(main), branchEvent = eventFor(branch);
    const clicks: Array<() => void> = [];
    const sendToAssistantWindow = vi.fn(() => false);
    const service = createHumanAttentionNotificationService({
      windowBridge: {
        sendToAssistantWindow, isAssistantWindowVisible: () => false,
        sendToWorkbench: () => false, focusWorkbench: async () => undefined, setWorkbenchAttention: () => undefined,
      },
      notificationSupported: () => true,
      createNotification: ({ onClick }) => { clicks.push(onClick); return { show: () => undefined }; },
      openedChannel: OPENED_CHANNEL,
    });
    const invoke = (event: IpcMainInvokeEvent, payload = attention()) => handleHumanAttentionIpc(
      event, payload, provider, ["http://127.0.0.1:8000"], (input, source) => service.notify(input, source),
    );
    await invoke(mainEvent);
    await invoke(branchEvent);
    await invoke(branchEvent);
    expect(clicks).toHaveLength(2);
    clicks[1]();
    expect(branch.sentIpc).toEqual([{ channel: OPENED_CHANNEL, payload: { id: "ha-1", targetUrl: "/knowledge?review=1" } }]);
    expect(main.sentIpc).toEqual([]);
    clicks[0]();
    expect(main.sentIpc).toEqual([{ channel: OPENED_CHANNEL, payload: { id: "ha-1", targetUrl: "/knowledge?review=1" } }]);
    await provider.closeInstanceWorkbench("branch");
    await provider.openOrFocusInstanceWorkbench({ instanceId: "branch", url: "http://127.0.0.1:8000/" });
    await invoke(eventFor(replacement));
    expect(clicks).toHaveLength(3);
    clicks[1]();
    expect(main.sentIpc).toHaveLength(1);
    expect(branch.sentIpc).toHaveLength(1);
    expect(replacement.sentIpc).toEqual([]);
    clicks[2]();
    expect(replacement.sentIpc).toHaveLength(1);
    expect(sendToAssistantWindow).not.toHaveBeenCalled();
  });

  it("keeps a branch card and its fallback attention away from the main pet and workbench", async () => {
    const main = new FakeElectronWindow(1, ""), branch = new FakeElectronWindow(2, ""), pet = new FakeElectronWindow(3, "");
    let next = 0;
    const provider = new ElectronWindowProvider(fakeDesktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000/", {
      createWorkbenchWindow: () => next++ === 0 ? main : branch, createPetWindow: () => pet,
    });
    await provider.openOrFocusWorkbench();
    await provider.openOrFocusInstanceWorkbench({ instanceId: "branch", url: "http://127.0.0.1:8001/" });
    await provider.openPet();
    const eventFor = (window: FakeElectronWindow) => {
      const frame = { url: window.webContents.getURL() };
      return { sender: Object.assign(window.webContents, { mainFrame: frame }), senderFrame: frame } as unknown as IpcMainInvokeEvent;
    };
    const sendToAssistantWindow = vi.fn(() => true);
    const service = createHumanAttentionNotificationService({
      windowBridge: {
        sendToAssistantWindow, isAssistantWindowVisible: () => true,
        sendToWorkbench: () => false, focusWorkbench: async () => undefined, setWorkbenchAttention: () => undefined,
      },
      notificationSupported: () => false,
      createNotification: () => { throw new Error("unsupported"); },
      openedChannel: OPENED_CHANNEL,
    });
    const invoke = (window: FakeElectronWindow) => handleHumanAttentionIpc(
      eventFor(window), attention(), provider, ["http://127.0.0.1:8000", "http://127.0.0.1:8001"],
      (input, source) => service.notify(input, source),
    );
    expect(await invoke(branch)).toEqual({ delivered: "attention_fallback" });
    expect(branch.flashes).toEqual([true]);
    expect(main.flashes).toEqual([]);
    expect(sendToAssistantWindow).not.toHaveBeenCalled();
    expect(await invoke(main)).toEqual({ delivered: "assistant_window" });
    expect(sendToAssistantWindow).toHaveBeenCalledTimes(1);
  });

  it("does not reuse an old origin's dedup entry or click target after main navigation", async () => {
    const main = new FakeElectronWindow(1, "");
    const provider = new ElectronWindowProvider(fakeDesktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000/", {
      createWorkbenchWindow: () => main,
    });
    await provider.openOrFocusWorkbench();
    const clicks: Array<() => void> = [];
    const service = createHumanAttentionNotificationService({
      windowBridge: {
        sendToAssistantWindow: () => false, isAssistantWindowVisible: () => false,
        sendToWorkbench: () => false, focusWorkbench: async () => undefined, setWorkbenchAttention: () => undefined,
      },
      notificationSupported: () => true,
      createNotification: ({ onClick }) => { clicks.push(onClick); return { show: () => undefined }; },
      openedChannel: OPENED_CHANNEL,
    });
    const invoke = async () => {
      const frame = { url: main.webContents.getURL() };
      const event = { sender: Object.assign(main.webContents, { mainFrame: frame }), senderFrame: frame } as unknown as IpcMainInvokeEvent;
      return handleHumanAttentionIpc(event, attention(), provider, [new URL(frame.url).origin],
        (input, source) => service.notify(input, source));
    };
    await invoke();
    await provider.openOrFocusWorkbench("http://127.0.0.1:8002/");
    await invoke();
    await provider.openOrFocusWorkbench("http://127.0.0.1:8000/");
    await invoke();
    expect(clicks).toHaveLength(3);
    clicks[0]();
    clicks[1]();
    expect(main.sentIpc).toEqual([]);
    main.emitContents("did-start-navigation", { isMainFrame: true, isSameDocument: false });
    main.emitContents("did-navigate", {});
    await invoke();
    expect(clicks).toHaveLength(4);
    clicks[2]();
    expect(main.sentIpc).toEqual([]);
    clicks[3]();
    expect(main.sentIpc).toHaveLength(1);
  });
});

describe("window provider sendToPet", () => {
  it("delivers only to a ready pet window and stops once it is gone", async () => {
    const petWindow = new FakeElectronWindow(7, "");
    const provider = new ElectronWindowProvider(
      fakeDesktopPaths,
      "http://127.0.0.1:8765/launcher",
      "http://127.0.0.1:8000",
      { createPetWindow: () => petWindow }
    );

    expect(provider.sendToPet(OPENED_CHANNEL, { id: "ha-1" })).toBe(false);

    await provider.openPet();
    expect(provider.sendToPet(OPENED_CHANNEL, { id: "ha-1" })).toBe(true);
    expect(petWindow.sentIpc).toEqual([{ channel: OPENED_CHANNEL, payload: { id: "ha-1" } }]);
    expect(petWindow.loadedUrls).toEqual(["http://127.0.0.1:8000/desktop-assistant"]);

    petWindow.destroy();
    expect(provider.sendToPet(OPENED_CHANNEL, { id: "ha-1" })).toBe(false);
  });
});
