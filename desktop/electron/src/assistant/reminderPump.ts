import type { AssistantHost, AssistantReminder } from "./assistantHost.js";

type ReminderHost = Pick<AssistantHost, "snapshot" | "nextReminder" | "settleReminder">;
type ReminderNotice = Pick<AssistantReminder, "title" | "body">;

/** One main-process sender. Unknown outcomes pause it rather than replaying. */
export function startAssistantReminderPump(options: {
  host: ReminderHost;
  available(): boolean;
  notify(notice: ReminderNotice, onClick: () => void, onFailure: () => void): void;
  openAssistant(): void;
  onError(): void;
  intervalMs?: number;
}): () => Promise<void> {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let active: Promise<void> | undefined;
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
    try {
      const event = await options.host.nextReminder();
      failureReported = false;
      if (!event) { schedule(delay); return; }
      let clicked = false;
      let acknowledgement: Promise<void> | undefined;
      let clickHandled = false;
      const recordClick = () => {
        if (!clicked || clickHandled || !acknowledgement) return;
        clickHandled = true;
        void acknowledgement.then(() => options.host.settleReminder(event, true)).catch(() => options.onError());
      };
      options.notify({ title: event.title, body: event.body }, () => {
        clicked = true;
        options.openAssistant();
        recordClick();
      }, () => options.onError());
      acknowledgement = options.host.settleReminder(event, false);
      recordClick();
      await acknowledgement;
      schedule(0);
    } catch (error) {
      if (stopped) return;
      // The owner never returns an already reserved event. Continue scanning
      // later for other reminders, without replaying an uncertain submission.
      if (!failureReported) { options.onError(); failureReported = true; }
      if (error instanceof Error && error.message === "ASSISTANT_REMINDER_BLOCKED") stopped = true;
      else schedule(delay);
    }
  }
  schedule(0);
  return async () => { stopped = true; if (timer) clearTimeout(timer); await active; };
}
