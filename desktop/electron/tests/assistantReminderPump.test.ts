import { afterEach, describe, expect, it, vi } from "vitest";
import { startAssistantReminderPump } from "../src/assistant/reminderPump.js";
import type { AssistantReminder } from "../src/assistant/assistantHost.js";

afterEach(() => vi.useRealTimers());

describe("Launcher assistant reminders", () => {
  it("delivers a due reminder and records a real click", async () => {
    vi.useFakeTimers();
    const event: AssistantReminder = {
      id: `reminder:20261027:${"a".repeat(64)}`, kind: "affair_reminder", severity: "medium",
      title: "事务提醒：准备材料", body: "已到期", targetUrl: "", attemptToken: "b".repeat(64),
    };
    const host = {
      snapshot: () => ({ state: "ready" as const, errorCode: null }),
      nextReminder: vi.fn().mockResolvedValueOnce(event).mockResolvedValue(null),
      settleReminder: vi.fn().mockResolvedValue(undefined),
    };
    let click: (() => void) | undefined;
    const notify = vi.fn((_notice, callback: () => void) => { click = callback; });
    const openAssistant = vi.fn();
    const onError = vi.fn();
    const stop = startAssistantReminderPump({ host, available: () => true, notify, openAssistant, onError });
    await vi.advanceTimersByTimeAsync(1);
    expect(notify).toHaveBeenCalledWith({ title: event.title, body: event.body }, expect.any(Function), expect.any(Function));
    expect(host.settleReminder).toHaveBeenCalledWith(event, false);
    click?.();
    await Promise.resolve();
    expect(openAssistant).toHaveBeenCalledOnce();
    expect(host.settleReminder).toHaveBeenCalledWith(event, true);
    expect(onError).not.toHaveBeenCalled();
    await stop();
  });

  it("finishes a reminder already claimed when the assistant exits", async () => {
    vi.useFakeTimers();
    const event: AssistantReminder = {
      id: `reminder:20261027:${"a".repeat(64)}`, kind: "affair_reminder", severity: "medium",
      title: "事务提醒：准备材料", body: "已到期", targetUrl: "", attemptToken: "b".repeat(64),
    };
    let finishClaim!: (event: AssistantReminder) => void;
    const host = {
      snapshot: () => ({ state: "ready" as const, errorCode: null }),
      nextReminder: vi.fn(() => new Promise<AssistantReminder>(resolve => { finishClaim = resolve; })),
      settleReminder: vi.fn().mockResolvedValue(undefined),
    };
    const notify = vi.fn();
    const stop = startAssistantReminderPump({ host, available: () => true, notify,
      openAssistant: vi.fn(), onError: vi.fn() });
    vi.advanceTimersByTime(0);
    const stopping = stop();
    finishClaim(event);
    await stopping;
    expect(notify).toHaveBeenCalledOnce();
    expect(host.settleReminder).toHaveBeenCalledWith(event, false);
  });
});
