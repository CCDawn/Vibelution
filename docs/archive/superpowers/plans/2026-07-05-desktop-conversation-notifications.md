# Desktop Conversation Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Codex-like native desktop reminders when a Vibelution conversation turn completes in the background.

**Architecture:** The existing session stream remains the canonical source for turn completion. The React chat route detects completed turns and sends a narrow IPC payload through the preload bridge. Electron main owns native notification display, taskbar attention, duplicate suppression, and workbench focusing.

**Tech Stack:** React 19, TypeScript, Vitest, Electron 42, Electron `Notification`, Electron `BrowserWindow`, existing browser telemetry and runtime-scene telemetry.

## Global Constraints

- Scope: direct Chat/Coding conversations and Agent-backed session turns that flow through the existing session stream.
- Foreground policy: when the workbench window is focused, do not show an OS notification; clear pending desktop attention for the active workbench.
- Background policy: when the workbench window is not focused, show a native desktop notification, increment an unread desktop attention count, apply a Windows taskbar overlay badge where available, and flash the workbench taskbar entry when appropriate.
- Click behavior: clicking a notification focuses the workbench window and must not silently submit messages, switch workflows, restart Launcher, or mutate session data.
- Dedupe: a single completed turn must notify at most once even if the session SSE reconnects, sends a final snapshot after an assistant delta, or the frontend cache re-applies the same settled detail.
- Non-goals: no remote push notification service, no new runtime task queue, no notification preference page in the first slice, no backend-owned Windows notification code, no Teams workflow state rewrite, and no Launcher restart as part of implementation.
- Privacy: notification text and telemetry must not include assistant answer content, tool output, local file paths, prompts, secrets, or attachments.
- Dependency rule: do not add external notification dependencies; use Electron built-ins.
- Browser-only development must degrade to a no-op without errors.
- Use TDD: every production change starts with a failing test and a verified RED result.
- Work in `C:\Users\17533\Desktop\Vibelution-worktrees\desktop-conversation-notifications` on branch `codex/desktop-conversation-notifications`.

---

## File Structure

Create or modify these files only:

- `desktop/electron/src/windows/electronWindowProvider.ts`: expose workbench focus and attention helpers without leaking raw `BrowserWindow`.
- `desktop/electron/tests/windowProvider.test.ts`: extend fake window coverage for overlay, flash, focus, and focus-event clearing.
- `desktop/electron/src/notifications/conversationNotifications.ts`: own payload validation, duplicate suppression, unread count, native notification actions, taskbar attention, and click-to-focus.
- `desktop/electron/tests/conversationNotifications.test.ts`: focused unit tests for the notification service.
- `desktop/electron/src/ipc.ts`: add one IPC channel name.
- `desktop/electron/src/preload.ts`: expose one narrow bridge method.
- `desktop/electron/src/main.ts`: wire the IPC handler to the notification service and runtime-scene telemetry.
- `desktop/electron/tests/windowProvider.test.ts`: update the existing IPC channel width assertion.
- `web/src/routes/chatDesktopNotifications.ts`: pure frontend completion notification helper.
- `web/src/routes/chatDesktopNotifications.test.ts`: pure Vitest coverage for dedupe, no-op browser fallback, and completion event classification.
- `web/src/routes/ChatCodingRoute.tsx`: call the helper from existing final `assistant_delta` and `session_detail` paths.

Avoid these files unless a RED test proves the current stream lacks a stable identifier:

- `core/web/services/session_service.py`
- `web/src/api/types.ts`
- `web/src/i18n/dictionary.ts`
- `.docs/project-memory/**`
- `PROJECT_MEMORY.html`

## Task 1: Workbench Window Attention Surface

**Files:**
- Modify: `desktop/electron/src/windows/electronWindowProvider.ts`
- Modify: `desktop/electron/tests/windowProvider.test.ts`

**Interfaces:**
- Produces: `ElectronWindowProvider.isWorkbenchFocused(): boolean`
- Produces: `ElectronWindowProvider.setWorkbenchAttention(options: WorkbenchAttentionOptions): void`
- Produces type: `WorkbenchAttentionOptions = { unreadCount: number; overlayIcon?: unknown; description?: string; flash?: boolean }`
- Consumes: existing `ElectronWindowProvider.focusWorkbench()`

- [ ] **Step 1: Write the failing window provider tests**

Add the optional Electron window APIs to `FakeWindow` in `desktop/electron/tests/windowProvider.test.ts`:

```ts
  overlayCalls: Array<{ icon: unknown; description: string }> = [];
  flashCalls: boolean[] = [];

  setOverlayIcon(icon: unknown, description: string): void {
    this.overlayCalls.push({ icon, description });
  }

  flashFrame(flag: boolean): void {
    this.flashCalls.push(flag);
  }

  blur(): void {
    this.focused = false;
    this.emit("blur");
  }
```

Add these tests inside `describe("Electron window provider state", () => { ... })`:

```ts
  it("reports workbench focus without exposing the raw BrowserWindow", async () => {
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow,
    });

    expect(provider.isWorkbenchFocused()).toBe(false);

    await provider.openOrFocusWorkbench();

    expect(provider.isWorkbenchFocused()).toBe(true);

    workbenchWindow.blur();

    expect(provider.isWorkbenchFocused()).toBe(false);
  });

  it("applies and clears workbench taskbar attention", async () => {
    const workbenchWindow = new FakeWindow(42, "http://127.0.0.1:8000/", 4242);
    const provider = new ElectronWindowProvider(desktopPaths, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: (url) => new FakeWindow(7, url, 7070),
      createWorkbenchWindow: () => workbenchWindow,
    });
    await provider.openOrFocusWorkbench();

    const overlayIcon = { marker: "badge-1" };
    provider.setWorkbenchAttention({ unreadCount: 1, overlayIcon, description: "1 completed conversation", flash: true });

    expect(workbenchWindow.overlayCalls).toEqual([{ icon: overlayIcon, description: "1 completed conversation" }]);
    expect(workbenchWindow.flashCalls).toEqual([true]);

    provider.setWorkbenchAttention({ unreadCount: 0 });

    expect(workbenchWindow.overlayCalls.at(-1)).toEqual({ icon: null, description: "" });
    expect(workbenchWindow.flashCalls.at(-1)).toBe(false);
  });
```

- [ ] **Step 2: Run the Electron tests to verify RED**

Run:

```powershell
npm --prefix desktop/electron run test -- windowProvider.test.ts
```

Expected: FAIL because `isWorkbenchFocused` and `setWorkbenchAttention` do not exist on `ElectronWindowProvider`.

- [ ] **Step 3: Implement the minimal provider methods**

Update `desktop/electron/src/windows/electronWindowProvider.ts`:

```ts
export type WorkbenchAttentionOptions = {
  unreadCount: number;
  overlayIcon?: unknown;
  description?: string;
  flash?: boolean;
};

export type ElectronWindowLike = {
  id: number;
  focus(): void;
  close(): void;
  isDestroyed(): boolean;
  isFocused(): boolean;
  on(event: string, listener: ElectronWindowEventListener): unknown;
  setOverlayIcon?(icon: unknown, description: string): void;
  flashFrame?(flag: boolean): void;
  webContents: {
    getOSProcessId(): number;
    getURL(): string;
    on(event: string, listener: ElectronWindowEventListener): unknown;
  };
};
```

Add methods inside `ElectronWindowProvider`:

```ts
  isWorkbenchFocused(): boolean {
    return Boolean(this.workbenchWindow && !this.workbenchWindow.isDestroyed() && this.workbenchWindow.isFocused());
  }

  setWorkbenchAttention(options: WorkbenchAttentionOptions): void {
    if (!this.workbenchWindow || this.workbenchWindow.isDestroyed()) {
      return;
    }
    const unreadCount = Math.max(0, Number.isFinite(options.unreadCount) ? Math.round(options.unreadCount) : 0);
    const description = unreadCount > 0 ? String(options.description || `${unreadCount} completed conversation${unreadCount === 1 ? "" : "s"}`) : "";
    if (typeof this.workbenchWindow.setOverlayIcon === "function") {
      this.workbenchWindow.setOverlayIcon(unreadCount > 0 ? options.overlayIcon ?? null : null, description);
    }
    if (typeof this.workbenchWindow.flashFrame === "function") {
      this.workbenchWindow.flashFrame(Boolean(options.flash && unreadCount > 0));
    }
  }
```

In `attachWindowEvents`, clear attention when workbench gains focus:

```ts
    window.on("focus", () => {
      if (role === "workbench") {
        this.setWorkbenchAttention({ unreadCount: 0 });
      }
      void this.reportState(this.stateFor(role));
    });
```

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```powershell
npm --prefix desktop/electron run test -- windowProvider.test.ts
```

Expected: PASS for `windowProvider.test.ts`.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add -- desktop/electron/src/windows/electronWindowProvider.ts desktop/electron/tests/windowProvider.test.ts
git commit -m "feat(desktop): expose workbench attention controls"
```

Expected: commit succeeds with only the two listed files staged.

## Task 2: Electron Conversation Notification Service

**Files:**
- Create: `desktop/electron/src/notifications/conversationNotifications.ts`
- Create: `desktop/electron/tests/conversationNotifications.test.ts`

**Interfaces:**
- Consumes: `ElectronWindowProvider.isWorkbenchFocused()`
- Consumes: `ElectronWindowProvider.focusWorkbench()`
- Consumes: `ElectronWindowProvider.setWorkbenchAttention(options)`
- Produces: `createConversationNotificationService(options): ConversationNotificationService`
- Produces: `ConversationNotificationService.notify(payload): Promise<DesktopConversationNotificationResult>`
- Produces: `ConversationNotificationService.clearAttention(): void`

- [ ] **Step 1: Write the failing notification service tests**

Create `desktop/electron/tests/conversationNotifications.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import { createConversationNotificationService, type DesktopConversationCompletionNotification } from "../src/notifications/conversationNotifications.js";

function completion(overrides: Partial<DesktopConversationCompletionNotification> = {}): DesktopConversationCompletionNotification {
  return {
    schemaVersion: 1,
    notificationKey: "session-1:turn-1:completed",
    sessionId: "session-1",
    turnId: "turn-1",
    title: "对话已完成",
    body: "测试 Agent 已完成一轮回复。",
    completedAt: "2026-07-05T07:00:00Z",
    terminalStatus: "completed",
    ...overrides,
  };
}

function makeService(options: { focused?: boolean; notificationSupported?: boolean } = {}) {
  const notifications: Array<{ title: string; body: string; clicked: () => void; shown: boolean }> = [];
  const provider = {
    isWorkbenchFocused: vi.fn(() => Boolean(options.focused)),
    focusWorkbench: vi.fn(async () => ({ role: "workbench", provider: "electron", open: true, focused: true, windowId: 1, rendererProcessId: 2, url: "http://127.0.0.1:8000/" })),
    setWorkbenchAttention: vi.fn(),
  };
  const service = createConversationNotificationService({
    windowProvider: provider,
    notificationSupported: () => options.notificationSupported ?? true,
    createNotification: ({ title, body, onClick }) => {
      const record = { title, body, clicked: onClick, shown: false };
      notifications.push(record);
      return {
        show: () => {
          record.shown = true;
        },
      };
    },
    createBadgeIcon: (count) => ({ badgeCount: count }),
    recordEvent: vi.fn(async () => undefined),
  });
  return { service, provider, notifications };
}

describe("conversation notification service", () => {
  it("suppresses native notifications and clears attention when the workbench is focused", async () => {
    const { service, provider, notifications } = makeService({ focused: true });

    const result = await service.notify(completion());

    expect(result.status).toBe("suppressed_focused");
    expect(result.unreadCount).toBe(0);
    expect(notifications).toHaveLength(0);
    expect(provider.setWorkbenchAttention).toHaveBeenCalledWith({ unreadCount: 0 });
  });

  it("shows a native notification and taskbar attention when the workbench is unfocused", async () => {
    const { service, provider, notifications } = makeService({ focused: false });

    const result = await service.notify(completion());

    expect(result.status).toBe("notified");
    expect(result.unreadCount).toBe(1);
    expect(notifications).toHaveLength(1);
    expect(notifications[0]).toMatchObject({ title: "对话已完成", body: "测试 Agent 已完成一轮回复。", shown: true });
    expect(provider.setWorkbenchAttention).toHaveBeenCalledWith({
      unreadCount: 1,
      overlayIcon: { badgeCount: 1 },
      description: "1 completed conversation",
      flash: true,
    });
  });

  it("dedupes repeated completion keys", async () => {
    const { service, provider, notifications } = makeService({ focused: false });

    const first = await service.notify(completion());
    const second = await service.notify(completion());

    expect(first.status).toBe("notified");
    expect(second.status).toBe("duplicate");
    expect(second.unreadCount).toBe(1);
    expect(notifications).toHaveLength(1);
    expect(provider.setWorkbenchAttention).toHaveBeenCalledTimes(1);
  });

  it("focuses the workbench when the notification is clicked", async () => {
    const { service, provider, notifications } = makeService({ focused: false });

    await service.notify(completion());
    notifications[0].clicked();

    expect(provider.focusWorkbench).toHaveBeenCalledTimes(1);
  });

  it("applies taskbar attention even when native notifications are unavailable", async () => {
    const { service, provider, notifications } = makeService({ focused: false, notificationSupported: false });

    const result = await service.notify(completion());

    expect(result.status).toBe("notification_unavailable_attention_applied");
    expect(result.unreadCount).toBe(1);
    expect(notifications).toHaveLength(0);
    expect(provider.setWorkbenchAttention).toHaveBeenCalledWith({
      unreadCount: 1,
      overlayIcon: { badgeCount: 1 },
      description: "1 completed conversation",
      flash: true,
    });
  });
});
```

- [ ] **Step 2: Run the notification tests to verify RED**

Run:

```powershell
npm --prefix desktop/electron run test -- conversationNotifications.test.ts
```

Expected: FAIL because `desktop/electron/src/notifications/conversationNotifications.ts` does not exist.

- [ ] **Step 3: Implement the notification service**

Create `desktop/electron/src/notifications/conversationNotifications.ts`:

```ts
export type DesktopConversationCompletionNotification = {
  schemaVersion: 1;
  notificationKey: string;
  sessionId: string;
  turnId?: string;
  title: string;
  body: string;
  completedAt?: string;
  terminalStatus?: string;
};

export type DesktopConversationNotificationStatus =
  | "notified"
  | "suppressed_focused"
  | "duplicate"
  | "invalid_payload"
  | "notification_unavailable_attention_applied"
  | "failed";

export type DesktopConversationNotificationResult = {
  schemaVersion: 1;
  status: DesktopConversationNotificationStatus;
  notificationKey: string;
  unreadCount: number;
  focused: boolean;
};

type NotificationLike = {
  show(): void;
};

type NotificationFactoryInput = {
  title: string;
  body: string;
  onClick: () => void;
};

type WindowProviderLike = {
  isWorkbenchFocused(): boolean;
  focusWorkbench(): Promise<unknown>;
  setWorkbenchAttention(options: {
    unreadCount: number;
    overlayIcon?: unknown;
    description?: string;
    flash?: boolean;
  }): void;
};

export type ConversationNotificationServiceOptions = {
  windowProvider: WindowProviderLike;
  notificationSupported: () => boolean;
  createNotification: (input: NotificationFactoryInput) => NotificationLike;
  createBadgeIcon: (count: number) => unknown;
  recordEvent?: (event: {
    eventCode: string;
    message: string;
    fields: Record<string, unknown>;
  }) => void | Promise<void>;
  maxSeenKeys?: number;
};

export type ConversationNotificationService = {
  notify(payload: DesktopConversationCompletionNotification): Promise<DesktopConversationNotificationResult>;
  clearAttention(): void;
};

export function createConversationNotificationService(
  options: ConversationNotificationServiceOptions,
): ConversationNotificationService {
  const seenKeys: string[] = [];
  const seenKeySet = new Set<string>();
  const maxSeenKeys = Math.max(1, Math.round(options.maxSeenKeys ?? 200));
  let unreadCount = 0;

  function rememberKey(key: string): boolean {
    if (seenKeySet.has(key)) {
      return false;
    }
    seenKeySet.add(key);
    seenKeys.push(key);
    while (seenKeys.length > maxSeenKeys) {
      const removed = seenKeys.shift();
      if (removed) {
        seenKeySet.delete(removed);
      }
    }
    return true;
  }

  function result(
    status: DesktopConversationNotificationStatus,
    payload: DesktopConversationCompletionNotification,
    focused: boolean,
  ): DesktopConversationNotificationResult {
    return {
      schemaVersion: 1,
      status,
      notificationKey: String(payload.notificationKey || ""),
      unreadCount,
      focused,
    };
  }

  function record(
    eventCode: string,
    message: string,
    payload: DesktopConversationCompletionNotification,
    focused: boolean,
    status: DesktopConversationNotificationStatus,
  ): void {
    void options.recordEvent?.({
      eventCode,
      message,
      fields: {
        sessionId: payload.sessionId,
        turnId: payload.turnId ?? "",
        notificationKey: payload.notificationKey,
        terminalStatus: payload.terminalStatus ?? "",
        focused,
        unreadCount,
        status,
      },
    });
  }

  function applyAttention(): void {
    const boundedCount = Math.min(unreadCount, 9);
    options.windowProvider.setWorkbenchAttention({
      unreadCount,
      overlayIcon: options.createBadgeIcon(boundedCount),
      description: `${unreadCount} completed conversation${unreadCount === 1 ? "" : "s"}`,
      flash: true,
    });
  }

  return {
    async notify(payload) {
      const notificationKey = String(payload?.notificationKey || "").trim();
      const sessionId = String(payload?.sessionId || "").trim();
      if (payload?.schemaVersion !== 1 || !notificationKey || !sessionId) {
        const focused = options.windowProvider.isWorkbenchFocused();
        unreadCount = Math.max(0, unreadCount);
        record("electron.conversation_notification.failed", "Conversation completion notification payload was invalid.", {
          ...payload,
          notificationKey,
          sessionId,
          schemaVersion: 1,
        }, focused, "invalid_payload");
        return result("invalid_payload", { ...payload, notificationKey, sessionId, schemaVersion: 1 }, focused);
      }
      const normalizedPayload: DesktopConversationCompletionNotification = {
        schemaVersion: 1,
        notificationKey,
        sessionId,
        turnId: String(payload.turnId || "").trim() || undefined,
        title: String(payload.title || "对话已完成").trim() || "对话已完成",
        body: String(payload.body || "Vibelution 已完成一轮回复。").trim() || "Vibelution 已完成一轮回复。",
        completedAt: String(payload.completedAt || "").trim() || undefined,
        terminalStatus: String(payload.terminalStatus || "").trim() || undefined,
      };
      const focused = options.windowProvider.isWorkbenchFocused();
      if (!rememberKey(notificationKey)) {
        record("electron.conversation_notification.suppressed", "Duplicate conversation completion notification was suppressed.", normalizedPayload, focused, "duplicate");
        return result("duplicate", normalizedPayload, focused);
      }
      if (focused) {
        unreadCount = 0;
        options.windowProvider.setWorkbenchAttention({ unreadCount: 0 });
        record("electron.conversation_notification.suppressed", "Conversation completion notification was suppressed because workbench is focused.", normalizedPayload, focused, "suppressed_focused");
        return result("suppressed_focused", normalizedPayload, focused);
      }
      unreadCount += 1;
      applyAttention();
      if (!options.notificationSupported()) {
        record("electron.conversation_notification.failed", "Native notification was unavailable; taskbar attention was applied.", normalizedPayload, focused, "notification_unavailable_attention_applied");
        return result("notification_unavailable_attention_applied", normalizedPayload, focused);
      }
      try {
        const notification = options.createNotification({
          title: normalizedPayload.title,
          body: normalizedPayload.body,
          onClick: () => {
            void options.windowProvider.focusWorkbench();
          },
        });
        notification.show();
        record("electron.conversation_notification.notified", "Conversation completion notification was shown.", normalizedPayload, focused, "notified");
        return result("notified", normalizedPayload, focused);
      } catch {
        record("electron.conversation_notification.failed", "Native notification failed; taskbar attention was applied.", normalizedPayload, focused, "failed");
        return result("failed", normalizedPayload, focused);
      }
    },
    clearAttention() {
      unreadCount = 0;
      options.windowProvider.setWorkbenchAttention({ unreadCount: 0 });
    },
  };
}
```

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```powershell
npm --prefix desktop/electron run test -- conversationNotifications.test.ts
```

Expected: PASS for `conversationNotifications.test.ts`.

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add -- desktop/electron/src/notifications/conversationNotifications.ts desktop/electron/tests/conversationNotifications.test.ts
git commit -m "feat(desktop): add conversation notification service"
```

Expected: commit succeeds with only the listed notification service files staged.

## Task 3: Electron IPC And Preload Bridge

**Files:**
- Modify: `desktop/electron/src/ipc.ts`
- Modify: `desktop/electron/src/preload.ts`
- Modify: `desktop/electron/src/main.ts`
- Modify: `desktop/electron/tests/windowProvider.test.ts`

**Interfaces:**
- Consumes: `createConversationNotificationService`
- Produces IPC channel: `launcher:notify-conversation-completed`
- Produces preload method: `window.vibelutionLauncher.notifyConversationCompleted(payload)`

- [ ] **Step 1: Write the failing IPC width test**

Update `desktop/electron/tests/windowProvider.test.ts` in `it("keeps the bridge narrow", () => { ... })`:

```ts
    expect(Object.keys(IPC_CHANNELS).sort()).toEqual([
      "focusWorkbenchWindow",
      "getDesktopShellSummary",
      "getVersion",
      "notifyConversationCompleted",
      "requestDesktopShellExit",
    ]);
```

- [ ] **Step 2: Run the IPC test to verify RED**

Run:

```powershell
npm --prefix desktop/electron run test -- windowProvider.test.ts
```

Expected: FAIL because `notifyConversationCompleted` is not present in `IPC_CHANNELS`.

- [ ] **Step 3: Add the IPC channel and preload method**

Update `desktop/electron/src/ipc.ts`:

```ts
export const IPC_CHANNELS = {
  getVersion: "launcher:get-version",
  getDesktopShellSummary: "launcher:get-desktop-shell-summary",
  focusWorkbenchWindow: "launcher:focus-workbench-window",
  requestDesktopShellExit: "launcher:request-desktop-shell-exit",
  notifyConversationCompleted: "launcher:notify-conversation-completed",
} as const;
```

Update `desktop/electron/src/preload.ts`:

```ts
contextBridge.exposeInMainWorld("vibelutionLauncher", {
  getVersion: () => ipcRenderer.invoke(IPC_CHANNELS.getVersion),
  getDesktopShellSummary: () => ipcRenderer.invoke(IPC_CHANNELS.getDesktopShellSummary),
  focusWorkbenchWindow: () => ipcRenderer.invoke(IPC_CHANNELS.focusWorkbenchWindow),
  requestDesktopShellExit: () => ipcRenderer.invoke(IPC_CHANNELS.requestDesktopShellExit),
  notifyConversationCompleted: (payload: unknown) => ipcRenderer.invoke(IPC_CHANNELS.notifyConversationCompleted, payload),
});
```

- [ ] **Step 4: Wire `main.ts` to the notification service**

Update imports in `desktop/electron/src/main.ts`:

```ts
import { Notification, app, ipcMain, nativeImage, nativeTheme } from "electron";
import {
  createConversationNotificationService,
  type ConversationNotificationService,
  type DesktopConversationCompletionNotification,
} from "./notifications/conversationNotifications.js";
```

Add a module-level service variable:

```ts
let conversationNotificationService: ConversationNotificationService | null = null;
```

Add helper functions near `createWindowProvider`:

```ts
function createConversationBadgeIcon(count: number) {
  const safeCount = Math.max(1, Math.min(9, Math.round(count)));
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
    <circle cx="16" cy="16" r="15" fill="#1f2937"/>
    <text x="16" y="21" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="18" font-weight="700" fill="#ffffff">${safeCount}</text>
  </svg>`;
  return nativeImage.createFromDataURL(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);
}

function resolveConversationNotificationService(): ConversationNotificationService | null {
  if (conversationNotificationService !== null) {
    return conversationNotificationService;
  }
  if (windowProvider === null) {
    return null;
  }
  conversationNotificationService = createConversationNotificationService({
    windowProvider,
    notificationSupported: () => Notification.isSupported(),
    createNotification: ({ title, body, onClick }) => {
      const notification = new Notification({ title, body, silent: false });
      notification.on("click", onClick);
      return notification;
    },
    createBadgeIcon: createConversationBadgeIcon,
    recordEvent: async (event) => {
      await recordElectronSupervisorEvent(launcherBootstrap, event);
    },
  });
  return conversationNotificationService;
}
```

Add IPC handler near the existing IPC handlers:

```ts
ipcMain.handle(IPC_CHANNELS.notifyConversationCompleted, async (event, payload: DesktopConversationCompletionNotification) => {
  assertTrustedIpcSender(event, trustedIpcOrigins());
  const service = resolveConversationNotificationService();
  if (service === null) {
    return {
      schemaVersion: 1,
      status: "failed",
      notificationKey: String(payload?.notificationKey || ""),
      unreadCount: 0,
      focused: false,
    };
  }
  return await service.notify(payload);
});
```

Inside `createWindowProvider`, reset the cached service when the provider changes:

```ts
  conversationNotificationService = null;
```

Place that assignment before `return new ElectronWindowProvider(...)`.

- [ ] **Step 5: Run Electron tests and build**

Run:

```powershell
npm --prefix desktop/electron run test -- windowProvider.test.ts conversationNotifications.test.ts
npm --prefix desktop/electron run build
```

Expected: both commands exit `0`.

- [ ] **Step 6: Commit Task 3**

Run:

```powershell
git add -- desktop/electron/src/ipc.ts desktop/electron/src/preload.ts desktop/electron/src/main.ts desktop/electron/tests/windowProvider.test.ts
git commit -m "feat(desktop): expose conversation completion IPC"
```

Expected: commit succeeds with only the listed Electron bridge files staged.

## Task 4: Frontend Completion Notification Helper

**Files:**
- Create: `web/src/routes/chatDesktopNotifications.ts`
- Create: `web/src/routes/chatDesktopNotifications.test.ts`

**Interfaces:**
- Consumes: `SessionAssistantDeltaStreamEvent`, `SessionDetail`, `SessionStreamEvent`
- Produces: `createDesktopConversationNotifier(options): DesktopConversationNotifier`
- Produces: `DesktopConversationNotifier.handleAssistantDelta(payload, context): void`
- Produces: `DesktopConversationNotifier.handleSessionDetail(detail, context): void`

- [ ] **Step 1: Write the failing frontend helper tests**

Create `web/src/routes/chatDesktopNotifications.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import type { SessionDetail, SessionStreamEvent } from "../api/types";
import { createDesktopConversationNotifier } from "./chatDesktopNotifications";

function assistantDelta(
  patch: Partial<Extract<SessionStreamEvent, { type: "assistant_delta" }> = {},
): Extract<SessionStreamEvent, { type: "assistant_delta" }> {
  return {
    type: "assistant_delta",
    sessionId: "session-1",
    turnId: "turn-1",
    ledgerSeq: 3,
    stage: "responding",
    content: "final answer",
    thought: "",
    updatedAt: "2026-07-05T07:00:00Z",
    done: true,
    ...patch,
  };
}

function detail(patch: Partial<SessionDetail> = {}): SessionDetail {
  return {
    id: "session-1",
    title: "测试会话",
    status: "ready",
    currentPhase: "ready",
    messages: [
      {
        id: "assistant-final",
        role: "assistant",
        content: "final answer",
        timestamp: "2026-07-05T07:00:00Z",
        metadata: { turnId: "turn-1" },
      },
    ],
    defaultFileContext: "",
    previewTabs: [],
    activePreviewPath: "",
    changedFiles: [],
    readFiles: [],
    stopRequested: false,
    stopRequestedAt: "",
    stopReason: "",
    ...patch,
  } as SessionDetail;
}

describe("desktop conversation notifier", () => {
  it("emits once for a completed assistant delta", () => {
    const notify = vi.fn(async () => ({ schemaVersion: 1, status: "notified", notificationKey: "session-1:turn-1:completed", unreadCount: 1, focused: false }));
    const telemetry = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: telemetry,
    });

    notifier.handleAssistantDelta(assistantDelta(), { sessionTitle: "测试会话" });
    notifier.handleAssistantDelta(assistantDelta(), { sessionTitle: "测试会话" });

    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({
      schemaVersion: 1,
      notificationKey: "session-1:turn-1:completed",
      sessionId: "session-1",
      turnId: "turn-1",
      title: "对话已完成",
      body: "测试会话 已完成一轮回复。",
      terminalStatus: "completed",
    }));
    expect(telemetry).toHaveBeenCalledWith(expect.objectContaining({
      eventCode: "browser.desktop_notification.conversation_completed_emitted",
    }));
  });

  it("does not emit for a non-final assistant delta", () => {
    const notify = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: vi.fn(),
    });

    notifier.handleAssistantDelta(assistantDelta({ done: false }), { sessionTitle: "测试会话" });

    expect(notify).not.toHaveBeenCalled();
  });

  it("emits once for a detail transition from busy to ready", () => {
    const notify = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: vi.fn(),
    });

    notifier.handleSessionDetail(detail({ currentPhase: "running", status: "running" }), { sessionTitle: "测试会话" });
    notifier.handleSessionDetail(detail({ currentPhase: "ready", status: "ready" }), { sessionTitle: "测试会话" });
    notifier.handleSessionDetail(detail({ currentPhase: "ready", status: "ready" }), { sessionTitle: "测试会话" });

    expect(notify).toHaveBeenCalledTimes(1);
  });

  it("degrades to telemetry-only when the Electron bridge is missing", () => {
    const telemetry = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: undefined,
      postTelemetry: telemetry,
    });

    notifier.handleAssistantDelta(assistantDelta(), { sessionTitle: "测试会话" });

    expect(telemetry).toHaveBeenCalledWith(expect.objectContaining({
      eventCode: "browser.desktop_notification.conversation_completed_skipped",
    }));
  });
});
```

- [ ] **Step 2: Run the helper tests to verify RED**

Run:

```powershell
npm --prefix web run test -- chatDesktopNotifications.test.ts
```

Expected: FAIL because `web/src/routes/chatDesktopNotifications.ts` does not exist.

- [ ] **Step 3: Implement the helper**

Create `web/src/routes/chatDesktopNotifications.ts`:

```ts
import type { BrowserTelemetryEventInput } from "../app/browserTelemetry";
import type { ConversationMessage, SessionDetail, SessionStreamEvent } from "../api/types";

type DesktopConversationCompletionNotification = {
  schemaVersion: 1;
  notificationKey: string;
  sessionId: string;
  turnId?: string;
  title: string;
  body: string;
  completedAt?: string;
  terminalStatus?: string;
};

type DesktopBridge = {
  notifyConversationCompleted?: (payload: DesktopConversationCompletionNotification) => Promise<unknown>;
};

type DesktopConversationNotifierOptions = {
  bridge?: DesktopBridge;
  postTelemetry: (event: BrowserTelemetryEventInput) => void;
  maxSeenKeys?: number;
};

type NotificationContext = {
  sessionTitle?: string;
};

export type DesktopConversationNotifier = {
  handleAssistantDelta(payload: Extract<SessionStreamEvent, { type: "assistant_delta" }>, context?: NotificationContext): void;
  handleSessionDetail(detail: SessionDetail, context?: NotificationContext): void;
};

const BUSY_PHASES = new Set(["queued", "running", "thinking", "tooling", "answering", "planning", "reading", "editing", "verifying", "stopping", "paused"]);

function normalizeText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function isBusyPhase(value: unknown): boolean {
  return BUSY_PHASES.has(normalizeText(value).toLowerCase());
}

function latestAssistantTurnMessage(detail: SessionDetail): ConversationMessage | undefined {
  return [...(detail.messages ?? [])].reverse().find((message) =>
    message.role === "assistant"
    && String(message.metadata?.kind ?? "") !== "session_active_turn_layer"
    && String(message.metadata?.kind ?? "") !== "session_live_overlay"
    && Boolean(normalizeText(message.content ?? message.thought ?? "")),
  );
}

function messageTurnId(message: ConversationMessage | undefined): string {
  const raw = normalizeText(message?.metadata?.turnId);
  return raw.startsWith("live:") ? raw.slice("live:".length) : raw;
}

function notificationBody(context?: NotificationContext): string {
  const subject = normalizeText(context?.sessionTitle) || "Vibelution";
  return `${subject} 已完成一轮回复。`;
}

export function browserDesktopNotificationBridge(globalLike: unknown = globalThis): DesktopBridge | undefined {
  const bridge = (globalLike as { vibelutionLauncher?: unknown })?.vibelutionLauncher;
  if (typeof bridge !== "object" || bridge === null) {
    return undefined;
  }
  const candidate = bridge as DesktopBridge;
  return typeof candidate.notifyConversationCompleted === "function" ? candidate : undefined;
}

export function createDesktopConversationNotifier(
  options: DesktopConversationNotifierOptions,
): DesktopConversationNotifier {
  const seenKeys: string[] = [];
  const seenKeySet = new Set<string>();
  const maxSeenKeys = Math.max(1, Math.round(options.maxSeenKeys ?? 200));
  const lastBusyBySession = new Map<string, boolean>();

  function remember(key: string): boolean {
    if (seenKeySet.has(key)) {
      return false;
    }
    seenKeySet.add(key);
    seenKeys.push(key);
    while (seenKeys.length > maxSeenKeys) {
      const removed = seenKeys.shift();
      if (removed) {
        seenKeySet.delete(removed);
      }
    }
    return true;
  }

  function emit(payload: DesktopConversationCompletionNotification): void {
    if (!remember(payload.notificationKey)) {
      return;
    }
    const bridge = options.bridge;
    if (!bridge?.notifyConversationCompleted) {
      options.postTelemetry({
        phase: "desktop_notification",
        eventCode: "browser.desktop_notification.conversation_completed_skipped",
        message: "Conversation completion desktop notification bridge was unavailable.",
        level: "info",
        fields: {
          sessionId: payload.sessionId,
          turnId: payload.turnId ?? "",
          notificationKey: payload.notificationKey,
          terminalStatus: payload.terminalStatus ?? "",
          reason: "bridge_unavailable",
        },
      });
      return;
    }
    void bridge.notifyConversationCompleted(payload);
    options.postTelemetry({
      phase: "desktop_notification",
      eventCode: "browser.desktop_notification.conversation_completed_emitted",
      message: "Conversation completion desktop notification was emitted to Electron.",
      level: "info",
      fields: {
        sessionId: payload.sessionId,
        turnId: payload.turnId ?? "",
        notificationKey: payload.notificationKey,
        terminalStatus: payload.terminalStatus ?? "",
      },
    });
  }

  return {
    handleAssistantDelta(payload, context) {
      if (!payload.done) {
        return;
      }
      const sessionId = normalizeText(payload.sessionId);
      const turnId = normalizeText(payload.turnId);
      if (!sessionId || !turnId) {
        return;
      }
      emit({
        schemaVersion: 1,
        notificationKey: `${sessionId}:${turnId}:completed`,
        sessionId,
        turnId,
        title: "对话已完成",
        body: notificationBody(context),
        completedAt: normalizeText(payload.updatedAt) || undefined,
        terminalStatus: "completed",
      });
    },
    handleSessionDetail(detail, context) {
      const sessionId = normalizeText(detail.id);
      if (!sessionId) {
        return;
      }
      const phase = normalizeText(detail.currentPhase || detail.status);
      const busy = isBusyPhase(phase);
      const wasBusy = lastBusyBySession.get(sessionId) ?? false;
      lastBusyBySession.set(sessionId, busy);
      if (busy || !wasBusy) {
        return;
      }
      const latest = latestAssistantTurnMessage(detail);
      const turnId = messageTurnId(latest) || normalizeText(latest?.id);
      if (!turnId) {
        return;
      }
      emit({
        schemaVersion: 1,
        notificationKey: `${sessionId}:${turnId}:completed`,
        sessionId,
        turnId,
        title: "对话已完成",
        body: notificationBody(context),
        completedAt: normalizeText(latest?.timestamp) || new Date().toISOString(),
        terminalStatus: "completed",
      });
    },
  };
}
```

- [ ] **Step 4: Run helper tests to verify GREEN**

Run:

```powershell
npm --prefix web run test -- chatDesktopNotifications.test.ts
```

Expected: PASS for `chatDesktopNotifications.test.ts`.

- [ ] **Step 5: Commit Task 4**

Run:

```powershell
git add -- web/src/routes/chatDesktopNotifications.ts web/src/routes/chatDesktopNotifications.test.ts
git commit -m "feat(web): add chat desktop notification helper"
```

Expected: commit succeeds with only the listed frontend helper files staged.

## Task 5: Chat Stream Integration

**Files:**
- Modify: `web/src/routes/ChatCodingRoute.tsx`
- Modify: `web/src/routes/chatDesktopNotifications.test.ts`

**Interfaces:**
- Consumes: `createDesktopConversationNotifier`
- Consumes: `browserDesktopNotificationBridge`
- Consumes: existing `postBrowserTelemetry`
- Produces: calls from `handleAssistantDelta` and `queueSessionDetail` final paths.

- [ ] **Step 1: Write a failing helper-level integration test for route-compatible usage**

Append this test to `web/src/routes/chatDesktopNotifications.test.ts`:

```ts
  it("supports the route pattern of assistant delta final followed by final detail without duplicate notification", () => {
    const notify = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: vi.fn(),
    });

    notifier.handleAssistantDelta(assistantDelta({ done: true }), { sessionTitle: "测试会话" });
    notifier.handleSessionDetail(detail({ currentPhase: "running", status: "running" }), { sessionTitle: "测试会话" });
    notifier.handleSessionDetail(detail({ currentPhase: "ready", status: "ready" }), { sessionTitle: "测试会话" });

    expect(notify).toHaveBeenCalledTimes(1);
  });
```

- [ ] **Step 2: Run the test to verify RED or current gap**

Run:

```powershell
npm --prefix web run test -- chatDesktopNotifications.test.ts
```

Expected before route integration: the helper may already PASS. If it passes, keep it as a route contract test and continue. The RED requirement for production route integration is satisfied by temporarily asserting `ChatCodingRoute.tsx` imports `createDesktopConversationNotifier` in the next step.

Add a source contract assertion to `web/src/routes/ChatCodingRoute.layout.test.ts`:

```ts
  it("wires completed session stream events into the desktop notification helper", () => {
    expect(routeSource).toContain("createDesktopConversationNotifier");
    expect(routeSource).toContain("handleAssistantDelta(payload");
    expect(routeSource).toContain("handleSessionDetail(detail");
  });
```

Run:

```powershell
npm --prefix web run test -- ChatCodingRoute.layout.test.ts
```

Expected: FAIL because the route has not imported or called the helper yet.

- [ ] **Step 3: Integrate the notifier into `ChatCodingRoute.tsx`**

Add imports near existing route helper imports:

```ts
import {
  browserDesktopNotificationBridge,
  createDesktopConversationNotifier,
} from "./chatDesktopNotifications";
```

Create the notifier after `activeTurnLayersBySessionRef` setup and before the session stream effect:

```ts
  const desktopConversationNotifierRef = useRef(createDesktopConversationNotifier({
    bridge: browserDesktopNotificationBridge(),
    postTelemetry: postBrowserTelemetry,
  }));
```

In `queueSessionDetail`, after `syncSessionDetail(detail);`, call:

```ts
      desktopConversationNotifierRef.current.handleSessionDetail(detail, {
        sessionTitle: detail.title || detail.agentDisplayName || detail.agentName || detail.id,
      });
```

In `handleAssistantDelta`, after `setSessionStreamConnected(true);` and before `queueAssistantDelta(payload, event.data.length);`, call:

```ts
      desktopConversationNotifierRef.current.handleAssistantDelta(payload, {
        sessionTitle: sessionDetailQuery.data?.title || directSessionActiveSummary?.title || streamSessionId,
      });
```

If TypeScript reports that `agentDisplayName` or `agentName` is not present on `SessionDetail`, use only stable fields already present on `SessionSummary`:

```ts
        sessionTitle: detail.title || detail.id,
```

Then update the source contract assertion to match the exact call text that exists after implementation.

- [ ] **Step 4: Run focused frontend tests**

Run:

```powershell
npm --prefix web run test -- chatDesktopNotifications.test.ts ChatCodingRoute.layout.test.ts
```

Expected: PASS for both tests.

- [ ] **Step 5: Commit Task 5**

Run:

```powershell
git add -- web/src/routes/ChatCodingRoute.tsx web/src/routes/ChatCodingRoute.layout.test.ts web/src/routes/chatDesktopNotifications.test.ts
git commit -m "feat(web): emit desktop notifications for completed chat turns"
```

Expected: commit succeeds with only the listed frontend integration files staged.

## Task 6: Full Verification And Handoff

**Files:**
- No production files unless verification reveals a specific failed task above.
- May update this plan checkbox status while executing.

**Interfaces:**
- Consumes all previous task outputs.
- Produces final validation evidence and handoff state.

- [ ] **Step 1: Run Electron tests**

Run:

```powershell
npm --prefix desktop/electron run test
```

Expected: exit `0`; no failed Vitest suites.

- [ ] **Step 2: Run frontend focused tests**

Run:

```powershell
npm --prefix web run test -- chatDesktopNotifications.test.ts ChatCodingRoute.layout.test.ts chatActiveTurnLayer.test.ts
```

Expected: exit `0`; no failed Vitest suites.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
npm --prefix web run build
```

Expected: exit `0`; existing chunk-size warnings are acceptable only if the command exits `0`.

- [ ] **Step 4: Run Electron build**

Run:

```powershell
npm --prefix desktop/electron run build
```

Expected: exit `0`.

- [ ] **Step 5: Run diff hygiene**

Run:

```powershell
git diff --check
git status --short --branch
```

Expected: `git diff --check` exits `0`; `git status` shows only intentional committed branch state or the current plan checkbox update if this file was edited during execution.

- [ ] **Step 6: Launcher refresh decision**

Do not restart Launcher automatically during implementation. Report:

```text
Launcher refresh: recommended before user testing; required before release/runtime verification because Electron preload/main and web build inputs changed.
```

If the user explicitly requests runtime verification after implementation, use the guarded Launcher path from `DEVELOPMENT_STANDARD.md` and respect active-work guards.

- [ ] **Step 7: Project memory decision**

Before updating `.docs/project-memory/**`, run:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" status
```

If no memory writer claim overlaps, sync a short `chat-coding-surface` update. If a memory writer claim is active, do not force. Report this exact proposal instead:

```text
Project memory proposal: add chat-coding-surface recent update noting Electron/Web desktop conversation completion notifications, tests run, Launcher refresh recommendation, and version impact.
```

- [ ] **Step 8: Version impact decision**

Report:

```text
Version impact: patch-level user-visible feature. Implementation branch should not edit VERSION or CHANGELOG unless the integration/release owner asks for version preparation.
```

- [ ] **Step 9: Final commit if plan checkboxes changed**

If execution updated this plan file's checkboxes, commit only this plan file:

```powershell
git add -- docs/superpowers/plans/2026-07-05-desktop-conversation-notifications.md
git commit -m "docs: update desktop notification implementation checklist"
```

Expected: commit succeeds only if the plan file changed during execution.

## Self-Review

Spec coverage:

- Background notification, foreground suppression, click-to-focus, duplicate suppression, browser no-op, privacy boundaries, and taskbar attention are covered by Tasks 1 to 5.
- Electron IPC sender validation and bridge width are covered by Task 3.
- Frontend helper dedupe and session stream integration are covered by Tasks 4 and 5.
- Verification, Launcher refresh decision, project memory decision, and version impact are covered by Task 6.

Placeholder scan:

- This plan intentionally contains only fully specified task steps and no unresolved placeholder instructions.

Type consistency:

- `DesktopConversationCompletionNotification` fields match the approved spec.
- `notifyConversationCompleted(payload)` is used consistently across preload, IPC, and frontend helper.
- `notificationKey`, `sessionId`, `turnId`, `terminalStatus`, `unreadCount`, and `focused` are used consistently in Electron result and telemetry.
