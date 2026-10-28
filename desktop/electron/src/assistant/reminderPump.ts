import type { AssistantHost, AssistantReminder, AssistantReminderChannel } from "./assistantHost.js";

type ReminderHost = Pick<AssistantHost, "snapshot" | "nextReminder" | "settleReminder" | "fallbackReminder">;
type ReminderNotice = Pick<AssistantReminder, "title" | "body">;
export type AssistantReminderPump = (() => Promise<void>) & {
  /** Stop admission and wait without a deadline for all admitted callbacks. */
  drainForMigration(): Promise<void>;
  /** Resume only after the previous drain completed. */
  resumeAfterMigration(): void;
};

/** One main-process sender. Unknown outcomes pause it rather than replaying. */
export function startAssistantReminderPump(options: {
  host: ReminderHost;
  available(): boolean;
  notify(notice: ReminderNotice, recoveredFallback: boolean, onClick: () => void, onFailure: () => void, onFallback: (decision: Promise<boolean>) => void,
    onLateFallback: (show: () => Promise<boolean>) => void): Promise<AssistantReminderChannel>;
  openAssistant(): void;
  onError(reason: "notification" | "transport"): void;
  intervalMs?: number;
}): AssistantReminderPump {
  let stopped = false;
  let retired = false;
  let permanentStop = false;
  let epoch = 0;
  let migrationDrain: Promise<void> | undefined;
  let migrationDrained = false;
  const deferredCallbacks: Array<() => void> = [];
  // A lost settlement is not authority to resend. Keep its original private
  // attempt token for this process lifetime while the durable receipt remains.
  const unconfirmed = new Map<string, AssistantReminder>();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let active: Promise<void> | undefined;
  let claiming: Promise<AssistantReminder | null> | undefined;
  const pendingClicks = new Set<Promise<void>>();
  const pendingDialogs = new Set<Promise<boolean>>();
  let failureReported = false;
  const delay = options.intervalMs ?? 30_000;
  const schedule = (ms: number) => {
    if (!stopped) timer = setTimeout(() => {
      active = tick();
      void active.finally(() => { active = undefined; });
    }, ms);
  };
  async function tick(): Promise<void> {
    if (stopped) return;
    const tickEpoch = epoch;
    const current = () => !retired && tickEpoch === epoch;
    if (options.host.snapshot().state !== "ready") {
      schedule(delay);
      return;
    }
    if (!options.available()) {
      schedule(delay);
      return;
    }
    if (pendingDialogs.size || pendingClicks.size) { schedule(delay); return; }
    try {
      claiming = options.host.nextReminder();
      let event: AssistantReminder | null;
      try { event = await claiming; }
      finally { claiming = undefined; }
      if (!current()) return;
      failureReported = false;
      if (!event) { schedule(delay); return; }
      let clicked = false;
      let acknowledgement: Promise<void> | undefined;
      let channel: AssistantReminderChannel | undefined;
      let clickHandled = false;
      let lateFallbackHandled = false;
      let deferredClick = false;
      let deferredLate = false;
      const track = (recording: Promise<void>) => {
        pendingClicks.add(recording);
        void recording.finally(() => pendingClicks.delete(recording));
      };
      const recordClick = () => {
        if (!clicked || clickHandled || !acknowledgement || !channel) return;
        clickHandled = true;
        const confirmedChannel = channel;
        const recording = acknowledgement.then(() => options.host.settleReminder(event, confirmedChannel, true))
          .then(() => { unconfirmed.delete(event.id); })
          .catch(() => { unconfirmed.set(event.id, event); options.onError("transport"); });
        track(recording);
      };
      const clickedNow = () => {
        if (!current() || lateFallbackHandled) return;
        clicked = true;
        options.openAssistant();
        recordClick();
      };
      const lateNow = (show: () => Promise<boolean>) => {
        if (!current() || lateFallbackHandled) return;
        lateFallbackHandled = true;
        const claimDone = claiming?.then(() => undefined, () => undefined) ?? Promise.resolve();
        const decision = claimDone.then(show);
        pendingDialogs.add(decision);
        let converted = false;
        const recording = claimDone.then(() => acknowledgement ?? Promise.resolve()).catch(() => undefined)
          .then(() => options.host.fallbackReminder(event))
          .then(() => { converted = true; })
          .catch(() => { unconfirmed.set(event.id, event); options.onError("transport"); });
        track(recording);
        void decision.then(opened => {
          pendingDialogs.delete(decision);
          if (!current()) return;
          if (opened) options.openAssistant();
          track(recording.then(() => converted ? options.host.settleReminder(event, "attention_fallback", true) : undefined)
            .catch(() => { unconfirmed.set(event.id, event); options.onError("transport"); }));
        }).catch(() => { pendingDialogs.delete(decision); if (current()) options.onError("notification"); });
      };
      channel = await options.notify({ title: event.title, body: event.body }, event.recoveredFallback, () => {
        if (permanentStop) return;
        if (migrationDrained) {
          if (!deferredClick) { deferredClick = true; deferredCallbacks.push(() => { deferredClick = false; clickedNow(); }); }
        } else clickedNow();
      }, () => { if (current()) options.onError("notification"); }, decision => {
        if (!current()) return;
        pendingDialogs.add(decision);
        void decision.then(opened => {
          pendingDialogs.delete(decision);
          if (!current()) return;
          clicked = true;
          if (opened) options.openAssistant();
          recordClick();
        }).catch(() => { pendingDialogs.delete(decision); if (current()) options.onError("notification"); });
      }, show => {
        if (permanentStop) return;
        if (migrationDrained) {
          if (!deferredLate) { deferredLate = true; deferredCallbacks.push(() => { deferredLate = false; lateNow(show); }); }
        } else lateNow(show);
      });
      if (!current()) return;
      acknowledgement = options.host.settleReminder(event, channel, false);
      recordClick();
      await acknowledgement;
      schedule(0);
    } catch (error) {
      if (stopped) return;
      // The owner never returns an already reserved event. Continue scanning
      // later for other reminders, without replaying an uncertain submission.
      if (!failureReported) {
        const notificationFailure = error instanceof Error && error.message.startsWith("ASSISTANT_REMINDER_NOTIFICATION_");
        options.onError(notificationFailure ? "notification" : "transport");
        failureReported = true;
      }
      if (error instanceof Error && error.message === "ASSISTANT_REMINDER_BLOCKED") stopped = true;
      else schedule(delay);
    }
  }
  schedule(0);
  const stop = async () => {
    permanentStop = true;
    stopped = true;
    if (timer) clearTimeout(timer);
    if (active) await active;
    if (pendingDialogs.size) {
      let timeout: ReturnType<typeof setTimeout> | undefined;
      await Promise.race([Promise.allSettled(pendingDialogs), new Promise<void>(resolve => { timeout = setTimeout(resolve, 2_000); })]);
      if (timeout) clearTimeout(timeout);
    }
    retired = true;
    epoch += 1;
    await Promise.all(pendingClicks);
  };
  const drainForMigration = (): Promise<void> => {
    if (migrationDrain) return migrationDrain;
    stopped = true;
    if (timer) clearTimeout(timer);
    migrationDrained = false;
    migrationDrain = (async () => {
      if (active) await active;
      // Future toast callbacks are held in memory until the same host owner
      // reopens. They must not write through a retired generation.
      while (pendingDialogs.size || pendingClicks.size)
        await Promise.allSettled([...pendingDialogs, ...pendingClicks]);
      retired = true;
      migrationDrained = true;
    })();
    return migrationDrain;
  };
  const resumeAfterMigration = () => {
    if (permanentStop || !migrationDrained) throw new Error("ASSISTANT_REMINDER_DRAIN_PENDING");
    migrationDrain = undefined;
    migrationDrained = false;
    retired = false;
    stopped = false;
    for (const callback of deferredCallbacks.splice(0)) callback();
    schedule(0);
  };
  return Object.assign(stop, { drainForMigration, resumeAfterMigration });
}
