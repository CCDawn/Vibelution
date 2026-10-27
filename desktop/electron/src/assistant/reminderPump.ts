import type { AssistantHost, AssistantReminder, AssistantReminderChannel } from "./assistantHost.js";

type ReminderHost = Pick<AssistantHost, "snapshot" | "nextReminder" | "settleReminder">;
type ReminderNotice = Pick<AssistantReminder, "title" | "body">;

/** One main-process sender. Unknown outcomes pause it rather than replaying. */
export function startAssistantReminderPump(options: {
  host: ReminderHost;
  available(): boolean;
  notify(notice: ReminderNotice, onClick: () => void, onFailure: () => void, onFallback: () => void): Promise<AssistantReminderChannel>;
  openAssistant(): void;
  onError(reason: "notification" | "transport"): void;
  intervalMs?: number;
}): () => Promise<void> {
  let stopped = false;
  let retired = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let active: Promise<void> | undefined;
  let fallbackStarted: Promise<void> | undefined;
  let signalFallback: (() => void) | undefined;
  let notificationFinished: Promise<void> | undefined;
  let signalNotificationFinished: (() => void) | undefined;
  let notificationCompleted = false;
  const pendingClicks = new Set<Promise<void>>();
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
    fallbackStarted = new Promise(resolve => { signalFallback = resolve; });
    notificationFinished = new Promise(resolve => { signalNotificationFinished = resolve; });
    notificationCompleted = false;
    if (options.host.snapshot().state !== "ready") {
      schedule(delay);
      return;
    }
    if (!options.available()) {
      schedule(delay);
      return;
    }
    try {
      const event = await options.host.nextReminder();
      if (retired) return;
      failureReported = false;
      if (!event) { schedule(delay); return; }
      let clicked = false;
      let acknowledgement: Promise<void> | undefined;
      let channel: AssistantReminderChannel | undefined;
      let clickHandled = false;
      const recordClick = () => {
        if (!clicked || clickHandled || !acknowledgement || !channel) return;
        clickHandled = true;
        const confirmedChannel = channel;
        const recording = acknowledgement.then(() => options.host.settleReminder(event, confirmedChannel, true))
          .catch(() => options.onError("transport"));
        pendingClicks.add(recording);
        void recording.finally(() => pendingClicks.delete(recording));
      };
      channel = await options.notify({ title: event.title, body: event.body }, () => {
        if (retired) return;
        clicked = true;
        options.openAssistant();
        recordClick();
      }, () => options.onError("notification"), () => signalFallback?.());
      notificationCompleted = true;
      signalNotificationFinished?.();
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
    if (active) {
      const awaitingFallback = await Promise.race([active.then(() => false), fallbackStarted!.then(() => true)]);
      if (awaitingFallback) {
        let timeout: ReturnType<typeof setTimeout> | undefined;
        await Promise.race([active, notificationFinished!, new Promise<void>(resolve => { timeout = setTimeout(resolve, 2_000); })]);
        if (timeout) clearTimeout(timeout);
        if (notificationCompleted) await active;
      }
    }
    retired = true;
    await Promise.all(pendingClicks);
  };
}
