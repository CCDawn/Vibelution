import type { AssistantHost, AssistantReminder, AssistantReminderChannel } from "./assistantHost.js";

type ReminderHost = Pick<AssistantHost, "snapshot" | "nextReminder" | "settleReminder" | "fallbackReminder">;
type ReminderNotice = Pick<AssistantReminder, "title" | "body">;

/** One main-process sender. Unknown outcomes pause it rather than replaying. */
export function startAssistantReminderPump(options: {
  host: ReminderHost;
  available(): boolean;
  notify(notice: ReminderNotice, recoveredFallback: boolean, onClick: () => void, onFailure: () => void, onFallback: (decision: Promise<boolean>) => void,
    onLateFallback: (show: () => Promise<boolean>) => void): Promise<AssistantReminderChannel>;
  openAssistant(): void;
  onError(reason: "notification" | "transport"): void;
  intervalMs?: number;
}): () => Promise<void> {
  let stopped = false;
  let retired = false;
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
      if (retired) return;
      failureReported = false;
      if (!event) { schedule(delay); return; }
      let clicked = false;
      let acknowledgement: Promise<void> | undefined;
      let channel: AssistantReminderChannel | undefined;
      let clickHandled = false;
      let lateFallbackHandled = false;
      const track = (recording: Promise<void>) => {
        pendingClicks.add(recording);
        void recording.finally(() => pendingClicks.delete(recording));
      };
      const recordClick = () => {
        if (!clicked || clickHandled || !acknowledgement || !channel) return;
        clickHandled = true;
        const confirmedChannel = channel;
        const recording = acknowledgement.then(() => options.host.settleReminder(event, confirmedChannel, true))
          .catch(() => options.onError("transport"));
        track(recording);
      };
      channel = await options.notify({ title: event.title, body: event.body }, event.recoveredFallback, () => {
        if (retired || lateFallbackHandled) return;
        clicked = true;
        options.openAssistant();
        recordClick();
      }, () => options.onError("notification"), decision => {
        pendingDialogs.add(decision);
        void decision.then(opened => {
          pendingDialogs.delete(decision);
          if (retired) return;
          clicked = true;
          if (opened) options.openAssistant();
          recordClick();
        }).catch(() => { pendingDialogs.delete(decision); options.onError("notification"); });
      }, show => {
        if (retired || lateFallbackHandled) return;
        lateFallbackHandled = true;
        // A previous toast can fail while a restarted host is answering the
        // next claim. Let that claim finish before publishing the fallback.
        const claimDone = claiming?.then(() => undefined, () => undefined) ?? Promise.resolve();
        const decision = claimDone.then(show);
        pendingDialogs.add(decision);
        let converted = false;
        const recording = claimDone.then(() => acknowledgement ?? Promise.resolve()).catch(() => undefined)
          .then(() => options.host.fallbackReminder(event))
          .then(() => { converted = true; })
          .catch(() => options.onError("transport"));
        track(recording);
        void decision.then(opened => {
          pendingDialogs.delete(decision);
          if (retired) return;
          if (opened) options.openAssistant();
          track(recording.then(() => converted ? options.host.settleReminder(event, "attention_fallback", true) : undefined)
            .catch(() => options.onError("transport")));
        }).catch(() => { pendingDialogs.delete(decision); options.onError("notification"); });
      });
      if (retired) return;
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
  return async () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    if (active) await active;
    if (pendingDialogs.size) {
      let timeout: ReturnType<typeof setTimeout> | undefined;
      await Promise.race([Promise.allSettled(pendingDialogs), new Promise<void>(resolve => { timeout = setTimeout(resolve, 2_000); })]);
      if (timeout) clearTimeout(timeout);
    }
    retired = true;
    await Promise.all(pendingClicks);
  };
}
