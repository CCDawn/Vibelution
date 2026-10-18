import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { IPC_CHANNELS } from "../src/ipc.js";
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

describe("human attention shell contract wiring", () => {
  it("registers the contract channels verbatim", () => {
    expect(IPC_CHANNELS.notifyHumanAttention).toBe("launcher:notify-human-attention");
    expect(IPC_CHANNELS.humanAttentionOpened).toBe("launcher:human-attention-opened");
  });

  it("handles the notify channel behind the trusted-sender guard in main", () => {
    const handleIndex = mainSource.indexOf("ipcMain.handle(IPC_CHANNELS.notifyHumanAttention");
    expect(handleIndex).toBeGreaterThanOrEqual(0);
    const segment = mainSource.slice(handleIndex, handleIndex + 400);
    expect(segment).toContain("assertTrustedIpcSender(event, trustedIpcOrigins())");
    expect(segment).not.toContain("throw new Error");
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
  private url: string;
  private destroyed = false;
  private focused = false;

  constructor(id: number, url: string) {
    this.id = id;
    this.url = url;
    this.webContents = {
      getOSProcessId: () => 9000 + id,
      getURL: () => this.url,
      on: () => this.webContents,
      send: (channel: string, payload: unknown) => {
        this.sentIpc.push({ channel, payload });
      }
    };
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
