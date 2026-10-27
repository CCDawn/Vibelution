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
    const notify = vi.fn(async (_notice, callback: () => void) => { click = callback; return "system_notification" as const; });
    const openAssistant = vi.fn();
    const onError = vi.fn();
    const stop = startAssistantReminderPump({ host, available: () => true, notify, openAssistant, onError });
    await vi.advanceTimersByTimeAsync(1);
    expect(notify).toHaveBeenCalledWith({ title: event.title, body: event.body }, expect.any(Function), expect.any(Function), expect.any(Function));
    expect(host.settleReminder).toHaveBeenCalledWith(event, "system_notification", false);
    click?.();
    await Promise.resolve();
    expect(openAssistant).toHaveBeenCalledOnce();
    expect(host.settleReminder).toHaveBeenCalledWith(event, "system_notification", true);
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
    const notify = vi.fn().mockResolvedValue("attention_fallback");
    const stop = startAssistantReminderPump({ host, available: () => true, notify,
      openAssistant: vi.fn(), onError: vi.fn() });
    vi.advanceTimersByTime(0);
    const stopping = stop();
    finishClaim(event);
    await stopping;
    expect(notify).toHaveBeenCalledOnce();
    expect(host.settleReminder).toHaveBeenCalledWith(event, "attention_fallback", false);
  });

  it("does not block exit or mark an unanswered fallback as sent", async () => {
    vi.useFakeTimers();
    const event: AssistantReminder = {
      id: `reminder:20261027:${"a".repeat(64)}`, kind: "affair_reminder", severity: "medium",
      title: "事务提醒：准备材料", body: "已到期", targetUrl: "", attemptToken: "b".repeat(64),
    };
    const host = {
      snapshot: () => ({ state: "ready" as const, errorCode: null }),
      nextReminder: vi.fn().mockResolvedValue(event),
      settleReminder: vi.fn().mockResolvedValue(undefined),
    };
    let dismiss!: (channel: "attention_fallback") => void;
    const notify = vi.fn((_notice, _click, _failure, onFallback: () => void) => {
      onFallback();
      return new Promise<"attention_fallback">(resolve => { dismiss = resolve; });
    });
    const stop = startAssistantReminderPump({ host, available: () => true, notify,
      openAssistant: vi.fn(), onError: vi.fn() });
    await vi.advanceTimersByTimeAsync(1);
    const stopping = stop();
    await vi.advanceTimersByTimeAsync(2_000);
    await stopping;
    dismiss("attention_fallback");
    await Promise.resolve();
    expect(host.nextReminder).toHaveBeenCalledOnce();
    expect(host.settleReminder).not.toHaveBeenCalled();
  });

  it("waits for the receipt once the fallback has been answered", async () => {
    vi.useFakeTimers();
    const event: AssistantReminder = {
      id: `reminder:20261027:${"a".repeat(64)}`, kind: "affair_reminder", severity: "medium",
      title: "事务提醒：准备材料", body: "已到期", targetUrl: "", attemptToken: "b".repeat(64),
    };
    let finishReceipt!: () => void;
    const host = {
      snapshot: () => ({ state: "ready" as const, errorCode: null }),
      nextReminder: vi.fn().mockResolvedValue(event),
      settleReminder: vi.fn(() => new Promise<void>(resolve => { finishReceipt = resolve; })),
    };
    let dismiss!: (channel: "attention_fallback") => void;
    const notify = vi.fn((_notice, _click, _failure, onFallback: () => void) => {
      onFallback();
      return new Promise<"attention_fallback">(resolve => { dismiss = resolve; });
    });
    const stop = startAssistantReminderPump({ host, available: () => true, notify,
      openAssistant: vi.fn(), onError: vi.fn() });
    await vi.advanceTimersByTimeAsync(1);
    let finished = false;
    const stopping = stop().then(() => { finished = true; });
    dismiss("attention_fallback");
    await vi.advanceTimersByTimeAsync(3_000);
    expect(finished).toBe(false);
    finishReceipt();
    await stopping;
    expect(host.settleReminder).toHaveBeenCalledWith(event, "attention_fallback", false);
  });
});
