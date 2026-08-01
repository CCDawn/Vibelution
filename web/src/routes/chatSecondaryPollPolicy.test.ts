import { describe, expect, it } from "vitest";

import {
  CHAT_SECONDARY_PET_POLL_MS,
  CHAT_SECONDARY_PROJECT_BUS_POLL_MS,
  CHAT_SECONDARY_RUNTIME_POLL_MS,
  CHAT_SECONDARY_TEAMS_POLL_MS,
  resolveChatSecondaryPollPolicy,
} from "./chatSecondaryPollPolicy";

const base = {
  chatPollingVisible: true,
  chatStartupWarmupActive: false,
  secondaryChatDataEnabled: true,
  directSessionPanelActive: true,
  teamsPickerNeeded: false,
  projectBusActive: false,
};

describe("resolveChatSecondaryPollPolicy", () => {
  it("uses long intervals for runtime/pet when secondary data is enabled", () => {
    const policy = resolveChatSecondaryPollPolicy(base);
    expect(policy.runtimeRefetchInterval).toBe(CHAT_SECONDARY_RUNTIME_POLL_MS);
    expect(policy.petRefetchInterval).toBe(CHAT_SECONDARY_PET_POLL_MS);
    // Directory needs teams even without group picker; use the slower cadence.
    expect(policy.teamsRefetchInterval).toBe(CHAT_SECONDARY_TEAMS_POLL_MS * 2);
    expect(policy.projectBusRefetchInterval).toBe(false);
  });

  it("polls teams faster when the group picker surface needs fresher membership", () => {
    const policy = resolveChatSecondaryPollPolicy({ ...base, teamsPickerNeeded: true });
    expect(policy.teamsRefetchInterval).toBe(CHAT_SECONDARY_TEAMS_POLL_MS);
  });

  it("polls project bus slower than the old 3s tick when active", () => {
    const policy = resolveChatSecondaryPollPolicy({ ...base, projectBusActive: true });
    expect(policy.projectBusRefetchInterval).toBe(CHAT_SECONDARY_PROJECT_BUS_POLL_MS);
  });

  it("disables secondary polls when secondary data is not enabled", () => {
    const policy = resolveChatSecondaryPollPolicy({ ...base, secondaryChatDataEnabled: false });
    expect(policy.runtimeRefetchInterval).toBe(false);
    expect(policy.petRefetchInterval).toBe(false);
    expect(policy.teamsRefetchInterval).toBe(false);
  });
});
