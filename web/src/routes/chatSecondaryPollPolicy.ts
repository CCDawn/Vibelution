/**
 * Secondary Chat chrome polls (runtime / pet / teams / project bus).
 * Not owned by session/group SSE — keep intervals long and intent-gated (R1).
 */
import { resolvePollingInterval, type PollingInterval } from "../app/pollingPolicy";

export const CHAT_SECONDARY_RUNTIME_POLL_MS = 20_000;
export const CHAT_SECONDARY_PET_POLL_MS = 30_000;
export const CHAT_SECONDARY_TEAMS_POLL_MS = 15_000;
export const CHAT_SECONDARY_PROJECT_BUS_POLL_MS = 8_000;

export type ChatSecondaryPollPolicyInput = {
  chatPollingVisible: boolean;
  chatStartupWarmupActive: boolean;
  secondaryChatDataEnabled: boolean;
  /** True while the user is in the direct-session surface (not group/bus primary). */
  directSessionPanelActive: boolean;
  /** Group create composer or standard group room needs team picker freshness. */
  teamsPickerNeeded: boolean;
  projectBusActive: boolean;
};

export type ChatSecondaryPollPolicy = {
  runtimeRefetchInterval: PollingInterval;
  petRefetchInterval: PollingInterval;
  teamsRefetchInterval: PollingInterval;
  projectBusRefetchInterval: PollingInterval;
  secondaryRefetchIntervalInBackground: boolean;
};

export function resolveChatSecondaryPollPolicy(input: ChatSecondaryPollPolicyInput): ChatSecondaryPollPolicy {
  const secondaryEnabled = input.secondaryChatDataEnabled;
  const background = input.chatStartupWarmupActive;

  return {
    runtimeRefetchInterval: secondaryEnabled
      ? resolvePollingInterval(input.chatPollingVisible, CHAT_SECONDARY_RUNTIME_POLL_MS)
      : false,
    petRefetchInterval: secondaryEnabled
      ? resolvePollingInterval(input.chatPollingVisible, CHAT_SECONDARY_PET_POLL_MS)
      : false,
    // Teams list is only needed for group composer / team surfaces — not continuous direct chat.
    teamsRefetchInterval: secondaryEnabled && input.teamsPickerNeeded
      ? resolvePollingInterval(input.chatPollingVisible, CHAT_SECONDARY_TEAMS_POLL_MS)
      : false,
    projectBusRefetchInterval: input.projectBusActive
      ? resolvePollingInterval(input.chatPollingVisible, CHAT_SECONDARY_PROJECT_BUS_POLL_MS)
      : false,
    secondaryRefetchIntervalInBackground: background,
  };
}
