import type { IpcMainInvokeEvent } from "electron";
import type { ElectronWindowProvider } from "../windows/electronWindowProvider.js";
import { assertTrustedIpcSender } from "../security/ipcSenderValidation.js";
import type { DesktopHumanAttentionNotifyResult, HumanAttentionSource } from "./humanAttentionNotifications.js";
import type { LegacyReminderSourceBinding, LegacyReminderSourceFence } from "./legacyReminderSourceFence.js";
import { validateHumanAttentionPayload, type DesktopHumanAttentionNotification } from "./humanAttentionNotifications.js";
import type { LegacyReminderNegotiatedDocuments } from "./legacyReminderCoordinator.js";

type TrustedHumanAttentionSource = HumanAttentionSource & { target: HumanAttentionSource["target"] & { isLive(): boolean } };

/** Shared trusted top-level Workbench and current-document validation. */
function humanAttentionSource(
  event: IpcMainInvokeEvent,
  provider: ElectronWindowProvider | null,
  allowedOrigins: string[],
): TrustedHumanAttentionSource {
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
  return { instanceId, origin, documentToken: target.documentToken, target, allowAssistantWindow };
}

export type LegacyReminderCapabilityOptions = {
  documents: LegacyReminderNegotiatedDocuments;
  resolveSource: (event: IpcMainInvokeEvent, source: HumanAttentionSource) => Promise<LegacyReminderSourceBinding | null>;
  /** Resolve trusted PA identity asynchronously; the returned synchronous commit must recheck authority. */
  authorize: (event: IpcMainInvokeEvent, source: HumanAttentionSource, binding: LegacyReminderSourceBinding) => Promise<(() => boolean) | null>;
};

/** Trusted main-only registration. A committed grant never downgrades within a document. */
export async function handleHumanAttentionCapabilityIpc(
  event: IpcMainInvokeEvent, provider: ElectronWindowProvider | null, allowedOrigins: string[],
  options?: LegacyReminderCapabilityOptions,
): Promise<{ schemaVersion: 1; legacyAffairReminder: "legacy" | "main_owned" }> {
  const source = humanAttentionSource(event, provider, allowedOrigins);
  const legacy = { schemaVersion: 1, legacyAffairReminder: "legacy" } as const;
  const owned = { schemaVersion: 1, legacyAffairReminder: "main_owned" } as const;
  if (!options) return legacy;
  const prior = () => {
    if (options.documents.isCommitted(source.documentToken)) return owned;
    if (options.documents.has(source.documentToken)) throw new Error("legacy reminder capability unavailable");
    return legacy;
  };
  if (options.documents.has(source.documentToken)) return prior();
  const binding = await options.resolveSource(event, source);
  if (!source.target.isLive()) throw new Error("blocked human attention sender");
  if (!binding) return prior();
  if (binding.instanceId !== source.instanceId) throw new Error("LEGACY_REMINDER_SOURCE_INVALID");
  const commit = await options.authorize(event, source, binding);
  if (!source.target.isLive()) throw new Error("blocked human attention sender");
  if (!commit) return prior();
  const confirmed = await options.resolveSource(event, source);
  if (!source.target.isLive()) throw new Error("blocked human attention sender");
  if (!confirmed || confirmed.projectId !== binding.projectId || confirmed.instanceId !== binding.instanceId
      || confirmed.physicalRoot !== binding.physicalRoot
      || confirmed.physicalIdentity.device !== binding.physicalIdentity.device
      || confirmed.physicalIdentity.inode !== binding.physicalIdentity.inode) return prior();
  // Grant first: an exception or lost reply must never restore the legacy path.
  if (!options.documents.begin(source.documentToken)) {
    if (options.documents.isCommitted(source.documentToken)) return owned;
    throw new Error("legacy reminder capability unavailable");
  }
  await options.documents.drainLegacy(source.documentToken);
  if (!source.target.isLive()) throw new Error("blocked human attention sender");
  if (!commit()) throw new Error("legacy reminder capability unavailable");
  options.documents.commit(source.documentToken);
  return owned;
}

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
    /** Main retains negotiation for this document even if its authority is revoked. */
    coordinated?: {
      /** The exact same document registry passed to capability registration. */
      documents: LegacyReminderNegotiatedDocuments;
      dispatch: (event: IpcMainInvokeEvent, source: HumanAttentionSource, binding: LegacyReminderSourceBinding,
        payload: DesktopHumanAttentionNotification, send: () => Promise<DesktopHumanAttentionNotifyResult>) => Promise<DesktopHumanAttentionNotifyResult>;
    };
  },
): Promise<DesktopHumanAttentionNotifyResult> {
  const source = humanAttentionSource(event, provider, allowedOrigins);
  const { instanceId, target } = source;
  if (legacyReminders && payload !== null && typeof payload === "object"
      && (payload as { kind?: unknown }).kind === "affair_reminder") {
    const coordinated = legacyReminders.coordinated;
    const documents = coordinated?.documents;
    const releaseLegacy = documents?.enterLegacy(source.documentToken);
    const negotiated = documents ? releaseLegacy === null : false;
    if (negotiated && !documents!.isCommitted(source.documentToken)) return { delivered: "attempt_pending" };
    try { return await legacyReminders.fence.trackIngress(async () => {
      const binding = await legacyReminders.resolveSource(event, source);
      if (!target.isLive()) throw new Error("blocked human attention sender");
      if (binding && binding.instanceId !== instanceId) throw new Error("LEGACY_REMINDER_SOURCE_INVALID");
      if (negotiated && !binding) return { delivered: "attempt_pending" };
      return await legacyReminders.fence.submit(binding, () => {
        if (!target.isLive()) throw new Error("blocked human attention sender");
        if (negotiated && binding && coordinated) {
          const validated = validateHumanAttentionPayload(payload);
          if (!validated.ok) return Promise.resolve({ delivered: "invalid_payload", error: validated.error });
          return coordinated.dispatch(event, source, binding, validated.value, () => {
            if (!target.isLive()) throw new Error("blocked human attention sender");
            return notify(validated.value, source);
          });
        }
        return notify(payload, source);
      });
    }); } finally { releaseLegacy?.(); }
  }
  return await notify(payload, source);
}
