import { afterEach, describe, expect, it, vi } from "vitest";
import { startAssistantReminderPump } from "../src/assistant/reminderPump.js";
import type { AssistantReminder } from "../src/assistant/assistantHost.js";

afterEach(() => vi.useRealTimers());

function fixture(recoveredFallback = false) {
  const event: AssistantReminder = {
    id: `reminder:20261027:${"a".repeat(64)}`, kind: "affair_reminder", severity: "medium",
    title: "事务提醒：准备材料", body: "已到期", targetUrl: "", attemptToken: "b".repeat(64), recoveredFallback,
  };
  const host = {
    snapshot: () => ({ state: "ready" as const, errorCode: null }),
    nextReminder: vi.fn().mockResolvedValueOnce(event).mockResolvedValue(null),
    settleReminder: vi.fn().mockResolvedValue(undefined),
    fallbackReminder: vi.fn().mockResolvedValue(undefined),
  };
  return { event, host };
}

describe("Launcher assistant reminders", () => {
  it("delivers a due system reminder and records a real click", async () => {
    vi.useFakeTimers();
    const { event, host } = fixture();
    let click!: () => void;
    const notify = vi.fn(async (_notice, _recovered, callback: () => void) => { click = callback; return "system_notification" as const; });
    const openAssistant = vi.fn();
    const stop = startAssistantReminderPump({ host, available: () => true, notify, openAssistant, onError: vi.fn() });
    await vi.advanceTimersByTimeAsync(1);
    expect(host.settleReminder).toHaveBeenCalledWith(event, "system_notification", false);
    click();
    await Promise.resolve();
    expect(host.settleReminder).toHaveBeenCalledWith(event, "system_notification", true);
    expect(openAssistant).toHaveBeenCalledOnce();
    await stop();
  });

  it("queues an unanswered fallback for recovery without blocking exit", async () => {
    vi.useFakeTimers();
    const { event, host } = fixture();
    const notify = vi.fn(async (_notice, _recovered, _click, _failure, fallback: (decision: Promise<boolean>) => void) => {
      fallback(new Promise<boolean>(() => {}));
      return "attention_fallback" as const;
    });
    const stop = startAssistantReminderPump({ host, available: () => true, notify, openAssistant: vi.fn(), onError: vi.fn() });
    await vi.advanceTimersByTimeAsync(1);
    expect(host.settleReminder).toHaveBeenCalledWith(event, "attention_fallback", false);
    const stopping = stop();
    await vi.advanceTimersByTimeAsync(2_000);
    await stopping;
    expect(host.settleReminder).not.toHaveBeenCalledWith(event, "attention_fallback", true);
  });

  it("records a late system failure and the fallback interaction", async () => {
    vi.useFakeTimers();
    const { event, host } = fixture();
    let late!: (show: () => Promise<boolean>) => void;
    const notify = vi.fn(async (_notice, _recovered, _click, _failure, _fallback, callback: (show: () => Promise<boolean>) => void) => {
      late = callback;
      return "system_notification" as const;
    });
    const openAssistant = vi.fn();
    const stop = startAssistantReminderPump({ host, available: () => true, notify, openAssistant, onError: vi.fn() });
    await vi.advanceTimersByTimeAsync(1);
    late(() => Promise.resolve(false));
    await vi.advanceTimersByTimeAsync(0);
    expect(host.fallbackReminder).toHaveBeenCalledWith(event);
    expect(host.settleReminder).toHaveBeenCalledWith(event, "attention_fallback", true);
    expect(openAssistant).not.toHaveBeenCalled();
    await stop();
  });

  it("shows a recovered fallback without repeating the system notification", async () => {
    vi.useFakeTimers();
    const { event, host } = fixture(true);
    const notify = vi.fn(async (_notice, recovered: boolean) => {
      expect(recovered).toBe(true);
      return "attention_fallback" as const;
    });
    const stop = startAssistantReminderPump({ host, available: () => true, notify, openAssistant: vi.fn(), onError: vi.fn() });
    await vi.advanceTimersByTimeAsync(1);
    expect(host.settleReminder).toHaveBeenCalledWith(event, "attention_fallback", false);
    await stop();
  });
});
