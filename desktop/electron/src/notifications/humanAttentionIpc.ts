import type { IpcMainInvokeEvent } from "electron";
import type { ElectronWindowProvider } from "../windows/electronWindowProvider.js";
import { assertTrustedIpcSender } from "../security/ipcSenderValidation.js";
import type { DesktopHumanAttentionNotifyResult, HumanAttentionSource } from "./humanAttentionNotifications.js";
import type { LegacyReminderSourceBinding, LegacyReminderSourceFence } from "./legacyReminderSourceFence.js";

/** The instance belongs to this managed window; it is not a project or Agent identity. */
export async function handleHumanAttentionIpc(
  event: IpcMainInvokeEvent,
  payload: unknown,
  provider: ElectronWindowProvider | null,
  allowedOrigins: string[],
  notify: (payload: unknown, source: HumanAttentionSource) => Promise<DesktopHumanAttentionNotifyResult>,
  legacyReminders?: {
    fence: LegacyReminderSourceFence;
    resolveSource: (event: IpcMainInvokeEvent, source: HumanAttentionSource) => Promise<LegacyReminderSourceBinding | null>;
  },
): Promise<DesktopHumanAttentionNotifyResult> {
  assertTrustedIpcSender(event, allowedOrigins);
  const frame = event.senderFrame;
  if (!frame || frame !== event.sender.mainFrame) throw new Error("blocked human attention sender");
  const instanceId = provider?.trustedWorkbenchInstanceForSender(event.sender, frame.url);
  if (!instanceId) throw new Error("blocked human attention sender");
  const target = provider?.notificationTargetForSender(event.sender, frame.url);
  if (!target) throw new Error("blocked human attention sender");
  const origin = new URL(frame.url).origin;
  const allowAssistantWindow = () => {
    try {
      const pet = provider?.snapshot().pet;
      return instanceId === "main" && Boolean(pet?.open)
        && target.isLive()
        && provider?.trustedWorkbenchInstanceForSender(event.sender, frame.url) === instanceId
        && new URL(pet!.url).origin === origin;
    } catch { return false; }
  };
  const source = { instanceId, origin, documentToken: target.documentToken, target, allowAssistantWindow };
  if (legacyReminders && payload !== null && typeof payload === "object"
      && (payload as { kind?: unknown }).kind === "affair_reminder") {
    return await legacyReminders.fence.trackIngress(async () => {
      const binding = await legacyReminders.resolveSource(event, source);
      if (!target.isLive()) throw new Error("blocked human attention sender");
      if (binding && binding.instanceId !== instanceId) throw new Error("LEGACY_REMINDER_SOURCE_INVALID");
      return await legacyReminders.fence.submit(binding, () => {
        if (!target.isLive()) throw new Error("blocked human attention sender");
        return notify(payload, source);
      });
    });
  }
  return await notify(payload, source);
}
